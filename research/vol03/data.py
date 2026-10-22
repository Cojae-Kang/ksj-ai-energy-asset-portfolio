"""Vol.3 데이터·가정 로드와 계산 (순수 함수). 보고서의 모든 숫자·서술 방향은 여기서 계산한다.

가정: config research.vol03.params (master) + data/manual/vol03_assumptions.csv (사용자 입력, 우선).
derive 항목(성장률·이익률·순차입금 비율·성장률 분포)은 국내 비교기업 DART 데이터에서 값과 범위를 계산한다.
데이터가 없으면 그 계산만 Unavailable(빠진 항목)로 두고 보고서는 회색 박스로 표시한다.
해외 피어: SEC EDGAR 재무(커밋됨) + 시총(market_points / global_peers_market / 수기 양식 — 없으면 '시총 수집 후').
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from research.vol02.data import (CSV_COLUMNS, Assumption, csv_to_value, norm_tag, read_csv_overrides,
                                 value_to_csv)
from src.analysis import ipo_model as im
from src.data_fetch.base import meta_path_for, resolve_path, to_number
from src.data_fetch.sec import apply_entity_override

CASES = ("target", "deal", "mc")
CMD_FETCH = "python -m research.vol03.fetch_extra --asof 2026-10-20"
CMD_GLOBAL = "python -m src.data_fetch.fetch_all --source global --asof 2026-10-20"

LABELS: dict[str, tuple[str, str]] = {
    "revenue": ("매출 FY2025A", "Revenue FY2025A"), "midsize_threshold": ("중견 기준 매출(참고)", "Mid-size revenue threshold (ref.)"),
    "revenue_growth": ("매출 성장률 (FY2026E)", "Revenue growth (FY2026E)"), "opm": ("영업이익률", "Operating margin"),
    "npm": ("지배순이익률", "Net margin (to parent)"), "net_debt_ratio": ("순차입금 ÷ 매출", "Net debt ÷ revenue"),
    "da_ratio": ("D&A ÷ 매출", "D&A ÷ revenue"), "shares_pre": ("상장 전 주식수", "Pre-IPO shares"),
    "offer_ratio": ("공모 비율 (공모 후 주식 대비)", "Offer size (% of post-IPO shares)"),
    "new_share_ratio": ("신주 비중 (나머지 구주매출)", "Primary share (rest secondary)"),
    "lockup_months": ("최대주주 의무보유", "Lock-up (major holders)"),
    "band_discount_low": ("밴드 할인율 하단", "Band discount (low)"), "band_discount_high": ("밴드 할인율 상단", "Band discount (high)"),
    "growth_mean": ("성장률 분포 평균 (로그)", "Growth mean (log)"), "growth_sd": ("성장률 분포 표준편차 (로그)", "Growth s.d. (log)"),
    "per_shape": ("1년 후 PER 분포", "1-yr-ahead P/E distribution"),
    "band_q_low": ("밴드 하단 분위", "Band low quantile"), "band_q_high": ("밴드 상단 분위", "Band high quantile"),
    "npm_low": ("1년 후 순이익률 최소", "1-yr net margin min"), "npm_mode": ("1년 후 순이익률 최빈", "1-yr net margin mode"),
    "npm_high": ("1년 후 순이익률 최대", "1-yr net margin max"), "npm_shape": ("1년 후 순이익률 분포", "1-yr net margin distribution"),
    "corr_growth_per": ("상관: 성장률·PER", "Corr.: growth–P/E"), "corr_growth_npm": ("상관: 성장률·순이익률", "Corr.: growth–margin"),
    "corr_npm_per": ("상관: 순이익률·PER", "Corr.: margin–P/E"),
    "inst_lockup_2025": ("기관 의무보유확약 비율 2025", "Institutional lock-up commitments 2025"),
    "inst_lockup_2024": ("기관 의무보유확약 비율 2024", "Institutional lock-up commitments 2024"),
    "inst_lockup_kospi_2025": ("기관 의무보유확약 비율 코스피 2025", "Institutional lock-up commitments, KOSPI 2025"),
    "ipo_in_band_2025": ("2025 IPO 공모가 밴드 안 결정 비율", "2025 IPOs priced within the range"),
    "top_of_band_h2_2025": ("2025 하반기 밴드 최상단 결정 비율", "2025 H2 IPOs priced at the top"),
}
REQUIRED_TARGET = ["revenue", "npm", "shares_pre"]
REQUIRED_DEAL = ["offer_ratio", "new_share_ratio"]
REQUIRED_MC = ["growth_mean", "growth_sd", "band_q_low", "band_q_high"]
REQUIRED_DP = ["npm_low", "npm_mode", "npm_high"]


@dataclass
class Unavailable:
    reason: str
    reason_en: str = ""
    missing: list[str] = field(default_factory=list)
    command: str = ""


def ok(x: Any) -> bool:
    return not isinstance(x, Unavailable)


finite = im.finite


def _fy(s: str | int) -> int:
    return int(str(s)[2:6]) if str(s).startswith("FY") else int(s)


def _read(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path, dtype={"ticker": str, "corp_code": str}, keep_default_na=False, encoding="utf-8-sig")
    return df if not df.empty else None


def _inp(cfg: Mapping, key: str) -> list[Path]:
    v = cfg["research"]["vol03"]["inputs"][key]
    return [resolve_path(p) for p in (v if isinstance(v, list) else [v])]


def meta_info(path: Path) -> dict:
    m = meta_path_for(path)
    return json.loads(m.read_text(encoding="utf-8")) if m.exists() else {}


def num(x: Any) -> float:
    v = to_number(x)
    return float(v) if v == v else float("nan")


# ---------------------------------------------------------------------------
# 가정 (config + CSV)
# ---------------------------------------------------------------------------
def config_assumptions(cfg: Mapping) -> dict[str, Assumption]:
    out: dict[str, Assumption] = {}
    for case, items in cfg["research"]["vol03"]["params"].items():
        for key, p in items.items():
            out[key] = Assumption(case, key, p.get("value"), p.get("unit", ""), p.get("tag"), p.get("source"),
                                  p.get("url"), p.get("published"), p.get("page"), p.get("todo"), p.get("low"), p.get("high"))
    return out


def derive_keys(cfg: Mapping) -> dict[str, str]:
    return {k: p["derive"] for items in cfg["research"]["vol03"]["params"].values() for k, p in items.items() if p.get("derive")}


def apply_csv(a: dict[str, Assumption], path: Path) -> None:
    """CSV 사용자 입력: value가 있으면 config·데이터 값보다 우선 (origin = csv)."""
    for r in read_csv_overrides(path):
        key = (r.get("item") or "").strip()
        if key not in a:
            continue
        cur = a[key]
        v = csv_to_value(r.get("value"), cur.unit)
        if v is not None:
            cur.value, cur.origin, cur.tag = v, "csv", "user"
        for bound in ("low", "high"):
            b = csv_to_value(r.get(bound), cur.unit)
            if b is not None:
                setattr(cur, bound, b)
        if norm_tag(r.get("tag")):
            cur.tag = norm_tag(r.get("tag"))
        for k_csv, k_attr in (("source_name", "source"), ("url", "url"), ("published", "published"), ("page", "page")):
            if (r.get(k_csv) or "").strip():
                setattr(cur, k_attr, r[k_csv].strip())


def write_template(cfg: Mapping, path: Path | None = None, facts: "Facts | None" = None) -> Path:
    """data/manual/vol03_assumptions.csv 양식 생성·갱신 (Vol.2와 같은 열). 사용자가 채운 칸은 보존."""
    path = path or resolve_path(cfg["research"]["vol03"]["assumptions_csv"])
    old = {(r["case"], r["item"]): r for r in read_csv_overrides(path)}
    eff = facts.assumptions if facts is not None else load_facts(cfg).assumptions
    rows = []
    for key, a in config_assumptions(cfg).items():
        prev = old.get((a.case, key), {})
        cur = eff[key]
        rows.append({"case": a.case, "item": key, "value": prev.get("value", ""), "low": prev.get("low", ""),
                     "high": prev.get("high", ""), "unit": a.unit, "tag": prev.get("tag", ""),
                     "source_name": prev.get("source_name", ""), "url": prev.get("url", ""),
                     "published": prev.get("published", ""), "page": prev.get("page", ""),
                     "current": value_to_csv(cur.value, a.unit) if cur.value is not None else "null",
                     "hint": " / ".join(x for x in (LABELS.get(key, (key,))[0], a.source or "", a.todo or "") if x)})
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return path


# ---------------------------------------------------------------------------
# 국내 비교기업 (DART + KRX)
# ---------------------------------------------------------------------------
@dataclass
class Domestic:
    fin: pd.DataFrame       # ticker, fy(int), revenue, operating_income, net_income, cash, total_debt (KRW 억원)
    mcap: pd.DataFrame      # ticker, company, company_en, mcap_t0, mcap_t1, close_t0, close_t1, shares_t0, shares_t1
    t0: str
    t1: str
    dart_as_of: str | None
    krx_as_of: str | None

    def val(self, ticker: str, fy: int, col: str) -> float:
        hit = self.fin[(self.fin["ticker"] == ticker) & (self.fin["fy"] == fy)]
        return float(hit.iloc[0][col]) if not hit.empty and finite(hit.iloc[0][col]) else float("nan")


def _ymd(s: str) -> str:
    s = str(s)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else s


def domestic(cfg: Mapping) -> Domestic | Unavailable:
    frames = [d for d in (_read(p) for p in _inp(cfg, "dart")) if d is not None]
    k = _read(_inp(cfg, "krx_points")[0])
    if not frames:
        return Unavailable("DART 재무 없음", "DART financials missing", ["dart_financials.csv"])
    if k is None:
        return Unavailable("KRX 시가총액 없음", "KRX market caps missing", ["vol01_krx_mcap_points.csv"])
    fin = pd.concat(frames, ignore_index=True)
    fin["ticker"] = fin["ticker"].astype(str).str.zfill(6)
    fin["fy"] = fin["fiscal_year"].map(_fy)
    for c in ("revenue", "operating_income", "net_income", "cash", "total_debt"):
        fin[c] = fin[c].map(num) if c in fin else float("nan")
    fin = fin.drop_duplicates(["ticker", "fy"], keep="first")
    k["ticker"] = k["ticker"].astype(str).str.zfill(6)
    for c in ("market_cap_krw_100m", "close_krw", "listed_shares"):
        k[c] = k[c].map(num)
    p0, p1 = k[k["point"] == "start_2023"].set_index("ticker"), k[k["point"] == "latest"].set_index("ticker")
    if p0.empty or p1.empty:
        return Unavailable("KRX 두 시점 중 하나 없음", "One of the two KRX dates is missing", ["vol01_krx_mcap_points.csv"])
    rows = []
    for p in cfg["peers"]["domestic"]:
        t = str(p["ticker"]).zfill(6)
        a = p0.loc[t] if t in p0.index else None
        b = p1.loc[t] if t in p1.index else None
        rows.append({"ticker": t, "company": p["name"], "company_en": p.get("name_en", p["name"]),
                     "mcap_t0": a["market_cap_krw_100m"] if a is not None else float("nan"),
                     "mcap_t1": b["market_cap_krw_100m"] if b is not None else float("nan"),
                     "close_t0": a["close_krw"] if a is not None else float("nan"),
                     "close_t1": b["close_krw"] if b is not None else float("nan"),
                     "shares_t0": a["listed_shares"] if a is not None else float("nan"),
                     "shares_t1": b["listed_shares"] if b is not None else float("nan")})
    dm = meta_info(_inp(cfg, "dart")[0])
    km = meta_info(_inp(cfg, "krx_points")[0])
    return Domestic(fin, pd.DataFrame(rows), _ymd(p0.iloc[0]["bas_dd"]), _ymd(p1.iloc[0]["bas_dd"]),
                    dm.get("as_of"), km.get("as_of"))


# ---------------------------------------------------------------------------
# 해외 비교기업 (SEC + 시총)
# ---------------------------------------------------------------------------
@dataclass
class Overseas:
    fin: pd.DataFrame       # ticker, fy, revenue, operating_income, net_income, cash, total_debt (USD mn)
    shares: pd.DataFrame    # ticker, shares, end, filed (SEC dei)
    entity: pd.DataFrame    # ticker, verdict, reason, auto_verdict, manual_check, same_consolidated, ...
    market: pd.DataFrame    # ticker, point(start_2023|latest), date, close, shares, shares_yf, mcap (USD mn), source
    extra: pd.DataFrame     # ticker, fy, metric, value (USD mn / KRW 억원), source
    sec_as_of: str | None
    sec_source: str
    market_source: str | None
    debt: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["ticker", "fiscal_year", "component"]))  # 총차입금 구성


def _market_frames(cfg: Mapping) -> tuple[pd.DataFrame, str | None]:
    """해외 시총 원천 우선순위: vol03 market_points(fetch_extra) > global_peers_market(기준일만) > 수기 양식."""
    out, label = [], None
    mp = _read(_inp(cfg, "market_points")[0])
    if mp is not None:
        mp = mp.assign(close=mp["close"].map(num), shares_sec=mp.get("shares_sec", pd.Series(dtype=str)).map(num),
                       shares_yf=mp.get("shares_yf", pd.Series(dtype=str)).map(num))
        out.append(mp[["ticker", "point", "date", "close", "shares_sec", "shares_yf"]].assign(source="yfinance (fetch_extra)"))
        label = "yfinance"
    gm = _read(_inp(cfg, "global_market")[0])
    if gm is not None:
        gm = gm.assign(point="latest", date=gm["price_date"], close=gm["close"].map(num), shares_sec=float("nan"),
                       shares_yf=gm["shares_current"].map(num))
        out.append(gm[["ticker", "point", "date", "close", "shares_sec", "shares_yf"]].assign(source="yfinance (global)"))
        label = label or "yfinance"
    mm = _read(_inp(cfg, "market_manual")[0])
    if mm is not None:
        mm = mm[mm["close"].map(num).notna()]
        if not mm.empty:
            mm = mm.assign(close=mm["close"].map(num), shares_sec=mm["shares"].map(num), shares_yf=float("nan"))
            out.append(mm[["ticker", "point", "date", "close", "shares_sec", "shares_yf"]].assign(source="manual"))
            label = label or "manual"
    if not out:
        return pd.DataFrame(columns=["ticker", "point", "date", "close", "shares_sec", "shares_yf", "source"]), None
    df = pd.concat(out, ignore_index=True)
    df["ticker"] = df["ticker"].astype(str).str.upper()
    return df.drop_duplicates(["ticker", "point"], keep="first").reset_index(drop=True), label


def _extra_frames(cfg: Mapping) -> pd.DataFrame:
    out = []
    for key in ("peer_extra", "peer_manual"):
        d = _read(_inp(cfg, key)[0])
        if d is not None:
            d = d[d["value"].map(num).notna()]
            if not d.empty:
                out.append(d.assign(value=d["value"].map(num), fy=d["fiscal_year"].map(_fy),
                                    ticker=d["ticker"].astype(str).str.upper().str.zfill(6).where(
                                        d["ticker"].astype(str).str.isdigit(), d["ticker"].astype(str).str.upper())))
    if not out:
        return pd.DataFrame(columns=["ticker", "fy", "metric", "value", "source"])
    return pd.concat(out, ignore_index=True).drop_duplicates(["ticker", "fy", "metric"], keep="first")


def overseas(cfg: Mapping) -> Overseas | Unavailable:
    f = _read(_inp(cfg, "sec_financials")[0])
    if f is None:
        return Unavailable("SEC 재무 없음", "SEC financials missing", ["sec_financials.csv"])
    f["ticker"] = f["ticker"].astype(str).str.upper()
    f["fy"] = f["fiscal_year"].map(_fy)
    for c in ("revenue", "operating_income", "net_income", "cash", "total_debt"):
        f[c] = f[c].map(num)
    sh = _read(_inp(cfg, "sec_shares")[0])
    sh = sh.assign(ticker=sh["ticker"].str.upper(), shares=sh["shares"].map(num)) if sh is not None else pd.DataFrame(columns=["ticker", "shares", "end"])
    ent = _read(_inp(cfg, "sec_entity")[0])
    ov = cfg["data_fetch"]["sec"].get("entity_check", {}).get("manual_overrides")
    ent = (pd.DataFrame([apply_entity_override(r, ov) for r in ent.to_dict("records")]) if ent is not None
           else pd.DataFrame(columns=["ticker", "verdict"]))
    if not ent.empty:
        ent["ticker"] = ent["ticker"].str.upper()
    mk, label = _market_frames(cfg)
    m = meta_info(_inp(cfg, "sec_financials")[0])
    dbt = _read(_inp(cfg, "sec_debt")[0]) if "sec_debt" in cfg["research"]["vol03"]["inputs"] else None
    dbt = dbt.assign(ticker=dbt["ticker"].str.upper()) if dbt is not None else pd.DataFrame(columns=["ticker", "fiscal_year", "component"])
    return Overseas(f, sh, ent, mk, _extra_frames(cfg), m.get("as_of"), m.get("source", "SEC EDGAR"), label, dbt)


def fx_on(cfg: Mapping, as_of: str) -> tuple[float | None, str | None]:
    d = _read(_inp(cfg, "fx")[0])
    if d is None or "usdkrw" not in d:
        return None, None
    d = d.assign(usdkrw=d["usdkrw"].map(num))
    d = d[(d["date"] <= as_of) & d["usdkrw"].notna()]
    return (float(d.iloc[-1]["usdkrw"]), str(d.iloc[-1]["date"])) if not d.empty else (None, None)


# ---------------------------------------------------------------------------
# 비교기업 표 (3단계 선정 + 배수 + 이상치)
# ---------------------------------------------------------------------------
GROUP_ORDER = ("domestic", "core", "reference", "excluded")


@dataclass
class Peers:
    table: pd.DataFrame     # 회사별 한 행 (아래 build_peers 참조)
    t1: str                 # 기준 시점 (국내 KRX 최근 거래일)
    t0: str                 # 2023년 첫 거래일
    fy1: int
    fy0: int
    ev_basis: str           # "EBITDA" | "EBIT" (D&A 미수집 시 대용)
    overseas_pending: bool  # 해외 핵심 비교군 시총 미수집
    market_source: str | None

    def rows(self, group: str) -> pd.DataFrame:
        return self.table[self.table["group"] == group]


def _status_text(step2: str, step3: str, group: str, pending: bool) -> str:
    if step2 not in ("pass", "pending"):
        return "excluded"
    if group == "excluded" or step3 == "low":
        return "excluded"
    if pending:
        return "pending"
    return "applied" if group in ("domestic", "core") else "reference"


def build_peers(cfg: Mapping, dom: Domestic | Unavailable, ovs: Overseas | Unavailable) -> Peers | Unavailable:
    v3 = cfg["research"]["vol03"]
    mcfg, out = v3["multiples"], v3["multiples"]["outlier"]
    fy1, fy0 = _fy(mcfg["basis_fy"]), _fy(mcfg["start_fy"])
    if not ok(dom):
        return Unavailable(dom.reason, dom.reason_en, dom.missing)
    rows = []
    scr = v3["screen"]
    # 국내
    for p in cfg["peers"]["domestic"]:
        t = str(p["ticker"]).zfill(6)
        s = (scr.get("domestic") or {}).get(t, {})
        m = dom.mcap.set_index("ticker").loc[t]
        ni1, ni0 = dom.val(t, fy1, "net_income"), dom.val(t, fy0, "net_income")
        debt, cash = dom.val(t, fy1, "total_debt"), dom.val(t, fy1, "cash")
        rows.append({"company": p["name"], "company_en": p.get("name_en", p["name"]), "ticker": t, "region": "KR",
                     "group": "domestic", "kind": "equipment", "segment": p.get("segment", ""), "similarity": s.get("similarity", "mid"),
                     "business_kr": s.get("business_kr", p.get("segment", "")), "business_en": s.get("business_en", ""),
                     "currency": "KRW", "unit": "억원", "fin_source": "DART",
                     "mcap1": m["mcap_t1"], "mcap0": m["mcap_t0"], "ni1": ni1, "ni0": ni0,
                     "rev1": dom.val(t, fy1, "revenue"), "rev0": dom.val(t, fy0, "revenue"), "oi1": dom.val(t, fy1, "operating_income"),
                     "net_debt1": debt - cash if finite(debt) and finite(cash) else float("nan"), "debt_missing": not finite(debt),
                     "entity_warn": False, "has_fin": finite(ni1), "listed0": finite(m["mcap_t0"]), "mcap_src": "KRX",
                     "shares_check": float("nan")})
    # 해외
    names = {p["ticker"].upper(): p for p in cfg["peers"]["overseas"]}
    o_scr = scr.get("overseas") or {}
    for tk, p in names.items():
        s = o_scr.get(tk, {})
        base = {"company": p["name"], "company_en": p["name"], "ticker": tk, "region": "EU" if tk == "SU.PA" else "US",
                "group": s.get("group", "reference"), "kind": s.get("kind", ""), "segment": p.get("segment", ""),
                "similarity": {"core": "high", "reference": "mid"}.get(s.get("group"), "mid"),
                "business_kr": s.get("business_kr", p.get("segment", "")), "business_en": s.get("business_en", ""),
                "reason_kr": s.get("reason_kr", ""), "reason_en": s.get("reason_en", ""),
                "currency": "EUR" if tk == "SU.PA" else "USD", "unit": "mn", "fin_source": "SEC"}
        if not ok(ovs) or tk not in set(ovs.fin["ticker"]):
            rows.append({**base, "mcap1": float("nan"), "mcap0": float("nan"), "ni1": float("nan"), "ni0": float("nan"),
                         "rev1": float("nan"), "rev0": float("nan"), "oi1": float("nan"), "net_debt1": float("nan"),
                         "debt_missing": True, "entity_warn": False, "has_fin": False, "listed0": False, "mcap_src": "",
                         "shares_check": float("nan"), "fin_source": "manual" if tk == "SU.PA" else "SEC"})
            continue
        fin = ovs.fin[ovs.fin["ticker"] == tk].set_index("fy")
        g = lambda fy, col: float(fin.loc[fy, col]) if fy in fin.index and finite(fin.loc[fy, col]) else float("nan")  # noqa: E731
        ex = ovs.extra[(ovs.extra["ticker"] == tk)]
        ni0 = g(fy0, "net_income")
        if not finite(ni0):
            hit = ex[(ex["fy"] == fy0) & (ex["metric"] == "net_income")]
            ni0 = float(hit.iloc[0]["value"]) if not hit.empty else float("nan")
        e = ovs.entity[ovs.entity["ticker"] == tk]
        warn = (not e.empty) and str(e.iloc[0].get("verdict", "")).upper() == "WARN"
        mk = ovs.market[ovs.market["ticker"] == tk].set_index("point")
        sec_sh = ovs.shares[ovs.shares["ticker"] == tk]
        sh1 = float(sec_sh.iloc[0]["shares"]) if not sec_sh.empty else float("nan")
        mcap1 = mcap0 = chk = float("nan")
        if "latest" in mk.index and finite(mk.loc["latest", "close"]):
            r = mk.loc["latest"]
            shares = sh1 if finite(sh1) else r["shares_sec"]
            mcap1 = r["close"] * shares / 1e6 if finite(shares) else float("nan")
            chk = (r["shares_yf"] / sh1 - 1) if finite(r["shares_yf"]) and finite(sh1) else float("nan")
        if "start_2023" in mk.index and finite(mk.loc["start_2023", "close"]) and finite(mk.loc["start_2023", "shares_sec"]):
            r = mk.loc["start_2023"]
            mcap0 = r["close"] * r["shares_sec"] / 1e6
        debt, cash = g(fy1, "total_debt"), g(fy1, "cash")
        dc = ovs.debt[(ovs.debt["ticker"] == tk) & (ovs.debt["fiscal_year"] == f"FY{fy1}A")] if not ovs.debt.empty else ovs.debt
        lt_tag = bool((dc["component"] == "long_term_debt_incl_current").any()) if not dc.empty else None
        rows.append({**base, "mcap1": mcap1, "mcap0": mcap0, "ni1": g(fy1, "net_income"), "ni0": ni0, "lt_debt_tag": lt_tag,
                     "rev1": g(fy1, "revenue"), "rev0": g(fy0, "revenue"), "oi1": g(fy1, "operating_income"),
                     "net_debt1": debt - cash if finite(debt) and finite(cash) else float("nan"), "debt_missing": not finite(debt),
                     "entity_warn": warn, "has_fin": finite(g(fy1, "net_income")), "listed0": finite(mcap0),
                     "mcap_src": str(mk.loc["latest", "source"]) if "latest" in mk.index else "", "shares_check": chk,
                     "entity_reason": str(e.iloc[0].get("reason", "")) if not e.empty else ""})
    t = pd.DataFrame(rows)
    # D&A (EBITDA) — 모든 적용 후보에 있을 때만 EBITDA, 아니면 EBIT 대용
    da = {}
    if ok(ovs):
        for _, r in ovs.extra[(ovs.extra["metric"] == "da") & (ovs.extra["fy"] == fy1)].iterrows():
            da[str(r["ticker"])] = float(r["value"])
    t["da1"] = t["ticker"].map(lambda k: da.get(k, float("nan")))
    # 배수
    t["per1"] = [im.multiple(a, b) for a, b in zip(t["mcap1"], t["ni1"])]
    t["per0"] = [im.multiple(a, b) for a, b in zip(t["mcap0"], t["ni0"])]
    for col, ni, per in (("s1", "ni1", "per1"), ("s0", "ni0", "per0")):
        t[col] = [im.screen_per(pe, n, per_max=float(out["per_max"]), entity_warn=w, exclude_nonpositive=out["exclude_nonpositive"],
                                exclude_entity_warn=out["exclude_entity_warn"]) for pe, n, w in zip(t[per], t[ni], t["entity_warn"])]
    cand = t["group"].isin(["domestic", "core"]) & t["has_fin"]
    ev_basis = "EBITDA" if cand.any() and t.loc[cand, "da1"].notna().all() else "EBIT"
    t["ev1"] = [im.enterprise_value(a, b) for a, b in zip(t["mcap1"], t["net_debt1"])]
    t["ebitda1"] = t["oi1"] + t["da1"] if ev_basis == "EBITDA" else t["oi1"]
    t["evm1"] = [im.multiple(a, b) for a, b in zip(t["ev1"], t["ebitda1"])]
    t["sev"] = [im.screen_ev(m, e, v, ev_max=float(out["ev_ebitda_max"])) for m, e, v in zip(t["evm1"], t["ebitda1"], t["ev1"])]
    # R6 수동 보류: 표에는 남기고 PER·EV 배수에서 제외 (근거 지표는 데이터로 계산해 함께 보관)
    hold = {k.upper(): v for k, v in (mcfg.get("hold_out") or {}).items()}
    t["held"] = t["ticker"].isin(hold)
    t["ni_to_oi"] = [a / b if finite(a) and finite(b) and b > 0 else float("nan") for a, b in zip(t["ni1"], t["oi1"])]
    for col in ("s1", "s0", "sev"):
        t[col] = [im.Screen(sc.value, False, "R6") if h else sc for sc, h in zip(t[col], t["held"])]
    # 3단계 선정
    pending_any = False
    st2, st3, status, why = [], [], [], []
    for _, r in t.iterrows():
        pend = r["group"] in ("core", "reference") and r["has_fin"] and not finite(r["mcap1"])
        pending_any |= bool(pend and r["group"] == "core")
        if not r["has_fin"]:
            s2 = "no_fin"
        elif r["held"] and not pend:
            s2 = "R6"
        elif r["s1"].rule in ("R1", "R2", "R3"):
            s2 = r["s1"].rule
        elif pend:
            s2 = "pending"
        else:
            s2 = "pass"
        s3 = r["similarity"] if r["group"] in ("domestic",) else ("low" if r["group"] == "excluded" else r["similarity"])
        st2.append(s2)
        st3.append(s3)
        status.append("held" if s2 == "R6" else _status_text(s2, s3, r["group"], pend))
        why.append(s2 if s2 not in ("pass", "pending") else ("step3" if status[-1] == "excluded" else ""))
    t["step2"], t["step3"], t["status"], t["why"] = st2, st3, status, why
    flags = im.flag_high({r["ticker"]: r["per1"] for _, r in t[t["status"] == "applied"].iterrows() if r["group"] == "domestic"},
                         float(out["flag_vs_median"]))
    flags |= im.flag_high({r["ticker"]: r["per1"] for _, r in t[t["status"] == "applied"].iterrows() if r["group"] == "core"},
                          float(out["flag_vs_median"]))
    t["high_flag"] = t["ticker"].isin(flags)
    pts = dom.t1, dom.t0
    return Peers(t, pts[0], pts[1], fy1, fy0, ev_basis, pending_any, ovs.market_source if ok(ovs) else None)


# ---------------------------------------------------------------------------
# 그룹 배수 · 시나리오
# ---------------------------------------------------------------------------
@dataclass
class Multiples:
    groups: dict[str, dict[str, im.GroupMultiple]]     # group → {"current", "start", "ev"}
    scen: dict[str, dict[str, float]]                  # domestic|core|combined → {current, normalized, conservative}
    method: str
    combine: str
    applied_group: str                                  # "combined" | "domestic" (해외 미수집 시)
    ev_applied: float
    norm: Mapping

    def applied(self, s: str) -> float:
        return self.scen[self.applied_group][s]


SCEN = ("current", "normalized", "conservative")


def multiples(cfg: Mapping, pe: Peers) -> Multiples | Unavailable:
    m = cfg["research"]["vol03"]["multiples"]
    method, comb, norm = m["aggregation"], m["combine"], m["normalization"]
    t = pe.table
    groups: dict[str, dict[str, im.GroupMultiple]] = {}
    for g in ("domestic", "core", "reference"):
        r = t[(t["group"] == g) & t["status"].isin(["applied", "reference"])]
        cur = im.group_multiple((x["ticker"], x["mcap1"], x["ni1"]) for _, x in r.iterrows() if x["s1"].included)
        st = im.group_multiple((x["ticker"], x["mcap0"], x["ni0"]) for _, x in r.iterrows() if x["s0"].included)
        ev = im.group_multiple((x["ticker"], x["ev1"], x["ebitda1"]) for _, x in r.iterrows() if x["sev"].included)
        groups[g] = {"current": cur, "start": st, "ev": ev}
    if groups["domestic"]["current"].n == 0:
        return Unavailable("국내 비교기업 배수 없음", "No domestic peer multiple", ["KRX·DART"])
    scen = {}
    for g in ("domestic", "core", "reference"):
        c, s = groups[g]["current"].pick(method), groups[g]["start"].pick(method)
        scen[g] = {"current": c, "conservative": s, "normalized": im.normalized_multiple(c, s, norm["weight"], norm["method"])}
    applied_core = groups["core"]["current"].n > 0 and groups["core"]["start"].n > 0
    scen["combined"] = {k: im.combine_groups([scen["domestic"][k]] + ([scen["core"][k]] if applied_core else []), comb) for k in SCEN}
    ev_applied = im.combine_groups([groups["domestic"]["ev"].pick(method)] + ([groups["core"]["ev"].pick(method)] if groups["core"]["ev"].n else []), comb)
    return Multiples(groups, scen, method, comb, "combined" if applied_core else "domestic", ev_applied, norm)


# ---------------------------------------------------------------------------
# 가정 파생 (국내 적용 피어 DART)
# ---------------------------------------------------------------------------
@dataclass
class Derived:
    values: dict[str, tuple[float, float, float]]   # key → (value, low, high)
    detail: pd.DataFrame                             # ticker, company, cagr, opm, npm, nd_ratio, da_ratio
    growth_obs: list[tuple[str, int, float]]         # (ticker, fy, yoy)
    members: list[str]
    hist: dict[int, dict[str, float]] = field(default_factory=dict)   # FY → 합산 opm·npm (사이클 비교)


def derive(cfg: Mapping, dom: Domestic, pe: Peers | Unavailable) -> Derived:
    fy1, fy0 = _fy(cfg["research"]["vol03"]["multiples"]["basis_fy"]), _fy(cfg["research"]["vol03"]["multiples"]["start_fy"])
    if ok(pe):
        members = list(pe.table[(pe.table["group"] == "domestic") & (pe.table["status"] == "applied")]["ticker"])
    else:
        members = [str(p["ticker"]).zfill(6) for p in cfg["peers"]["domestic"]]
    names = {str(p["ticker"]).zfill(6): p["name"] for p in cfg["peers"]["domestic"]}
    da = {}
    if ok(pe):
        da = dict(zip(pe.table["ticker"], pe.table["da1"]))
    rows, obs = [], []
    for t in members:
        r0, r1 = dom.val(t, fy0, "revenue"), dom.val(t, fy1, "revenue")
        debt, cash = dom.val(t, fy1, "total_debt"), dom.val(t, fy1, "cash")
        rows.append({"ticker": t, "company": names.get(t, t), "rev0": r0, "rev1": r1,
                     "oi1": dom.val(t, fy1, "operating_income"), "ni1": dom.val(t, fy1, "net_income"),
                     "nd1": debt - cash if finite(debt) and finite(cash) else float("nan"), "da1": da.get(t, float("nan")),
                     "cagr": (r1 / r0) ** (1 / (fy1 - fy0)) - 1 if finite(r0) and finite(r1) and r0 > 0 else float("nan")})
        for fy in range(fy0 + 1, fy1 + 1):
            a, b = dom.val(t, fy - 1, "revenue"), dom.val(t, fy, "revenue")
            if finite(a) and finite(b) and a > 0:
                obs.append((t, fy, b / a - 1))
    d = pd.DataFrame(rows)
    vals: dict[str, tuple[float, float, float]] = {}
    if not d.empty:
        d["opm"], d["npm"] = d["oi1"] / d["rev1"], d["ni1"] / d["rev1"]
        d["nd_ratio"], d["da_ratio"] = d["nd1"] / d["rev1"], d["da1"] / d["rev1"]
        agg = lambda num_, den_: float(d[num_].sum() / d[den_].sum())  # noqa: E731
        r0s, r1s = d["rev0"].sum(), d["rev1"].sum()
        vals["peer_revenue_cagr"] = ((r1s / r0s) ** (1 / (fy1 - fy0)) - 1, d["cagr"].min(), d["cagr"].max())
        vals["peer_opm"] = (agg("oi1", "rev1"), d["opm"].min(), d["opm"].max())
        vals["peer_npm"] = (agg("ni1", "rev1"), d["npm"].min(), d["npm"].max())
        nd = d[d["nd1"].notna()]
        if not nd.empty:
            vals["peer_net_debt_ratio"] = (float(nd["nd1"].sum() / nd["rev1"].sum()), nd["nd_ratio"].min(), nd["nd_ratio"].max())
        dd = d[d["da1"].notna()]
        if len(dd) == len(d) and len(d):
            vals["peer_da_ratio"] = (float(dd["da1"].sum() / dd["rev1"].sum()), dd["da_ratio"].min(), dd["da_ratio"].max())
    if len(obs) >= 2:
        mu, sd = im.log_growth_params([g for _, _, g in obs])
        lg = np.log1p([g for _, _, g in obs])
        vals["peer_log_growth_mean"] = (mu, float(lg.min()), float(lg.max()))
        vals["peer_log_growth_sd"] = (sd, float("nan"), float("nan"))
    hist = {}
    for fy in range(fy0, fy1 + 1):
        r = sum(dom.val(t, fy, "revenue") for t in members)
        if finite(r) and r > 0:
            hist[fy] = {"opm": sum(dom.val(t, fy, "operating_income") for t in members) / r,
                        "npm": sum(dom.val(t, fy, "net_income") for t in members) / r, "revenue": r}
    if fy0 in hist and fy1 in hist:
        vals["peer_npm_start"] = (hist[fy0]["npm"], float("nan"), float("nan"))
        ni_sum = sum(h["npm"] * h["revenue"] for h in hist.values())
        vals["peer_npm_cycle"] = (ni_sum / sum(h["revenue"] for h in hist.values()), float("nan"), float("nan"))
    return Derived(vals, d, obs, members, hist)


def load_assumptions(cfg: Mapping, der: Derived | None) -> dict[str, Assumption]:
    a = config_assumptions(cfg)
    for key, how in derive_keys(cfg).items():
        cur = a[key]
        if der is not None and how in der.values and cur.value is None:
            v, lo, hi = der.values[how]
            cur.value, cur.origin = v, "data"
            cur.low, cur.high = (lo, hi) if finite(lo) and finite(hi) else (None, None)
    apply_csv(a, resolve_path(cfg["research"]["vol03"]["assumptions_csv"]))
    return a


# ---------------------------------------------------------------------------
# 평가: 적정 시총 → 주식수 → 주당 평가가액 → 할인 → 밴드
# ---------------------------------------------------------------------------
@dataclass
class Valuation:
    rev: float
    ni: float
    oi: float
    net_debt: float | None
    ev_base: float          # EBITDA 또는 EBIT
    shares: im.Shares
    equity: dict[str, float]          # scenario → 적정 시총(억원)
    per_share: dict[str, float]       # scenario → 주당 평가가액(원)
    grid: pd.DataFrame                # discount → 주당 공모가(현재 배수)
    sens: pd.DataFrame                # PER × 할인율
    sens_rows: list[tuple[str, float]]  # (라벨 키, PER)
    ev_equity: float | None           # EV 배수 교차 확인 (억원)
    ev_per_share: float | None
    rev26: float
    ni26: float
    nn: dict | None = None            # 정상화 이익 × 정상화 배수: npm, per, ni, equity, per_share


def valuation(cfg: Mapping, a: Mapping[str, Assumption], mu: Multiples) -> Valuation | Unavailable:
    v3 = cfg["research"]["vol03"]
    miss = [k for k in REQUIRED_TARGET + REQUIRED_DEAL if a[k].value is None]
    if miss:
        return Unavailable("Target Co. 가정 미입력", "Target Co. inputs missing", miss)
    rev, npm = float(a["revenue"].value), float(a["npm"].value)
    opm = a["opm"].value
    ni, oi = rev * npm, rev * float(opm) if opm is not None else float("nan")
    nd = rev * float(a["net_debt_ratio"].value) if a["net_debt_ratio"].value is not None else None
    da = rev * float(a["da_ratio"].value) if a["da_ratio"].value is not None else 0.0
    sh = im.deal_shares(float(a["shares_pre"].value), float(a["offer_ratio"].value), float(a["new_share_ratio"].value))
    eq = {s: ni * mu.applied(s) for s in SCEN}
    ps = {s: im.per_share(eq[s], sh.post) for s in SCEN}
    grid = pd.DataFrame({"discount": v3["discount_grid"], "price": [ps["current"] * (1 - d) for d in v3["discount_grid"]]})
    rows = [(s, mu.applied(s)) for s in SCEN] + [(f"grid{p}", float(p)) for p in v3["per_grid"]]
    sens = im.sensitivity(ni, sh.post, [p for _, p in rows], v3["discount_grid"])
    sens.index = [k for k, _ in rows]
    ev_base = oi + (da if a["da_ratio"].value is not None else 0.0)
    ev_eq = mu.ev_applied * ev_base - nd if finite(mu.ev_applied) and finite(ev_base) and nd is not None else None
    g = a["revenue_growth"].value
    rev26 = rev * (1 + g) if g is not None else float("nan")
    nn = None
    if a["npm_mode"].value is not None:
        nm_npm, nm_per = float(a["npm_mode"].value), mu.applied("normalized")
        nn = {"npm": nm_npm, "per": nm_per, "ni": rev * nm_npm, "equity": rev * nm_npm * nm_per,
              "per_share": im.per_share(rev * nm_npm * nm_per, sh.post)}
    return Valuation(rev, ni, oi, nd, ev_base, sh, eq, ps, grid, sens, rows, ev_eq,
                     im.per_share(ev_eq, sh.post) if ev_eq is not None else None, rev26, rev26 * npm, nn)


@dataclass
class Band:
    low: float
    high: float
    d_low: float            # 상단 가격의 할인율 (작은 값)
    d_high: float           # 하단 가격의 할인율
    basis: str              # "evidence"(국내 IPO 할인율 분포) | "config"(사용자 입력) | "mc"(몬테카를로 분위)
    raw_low: float
    raw_high: float


def band_mc(cfg: Mapping, a: Mapping[str, Assumption], val: Valuation, mc: "MCFacts") -> Band:
    """몬테카를로 분위 밴드 (이중 고점 밴드에 사용)."""
    tick = float(cfg["research"]["vol03"].get("price_tick") or 0)
    v0 = val.per_share["current"]
    lo_p, hi_p = mc.result.q(float(a["band_q_low"].value)), mc.result.q(float(a["band_q_high"].value))
    lo_r, hi_r = im.round_price(lo_p, tick), im.round_price(hi_p, tick)
    return Band(lo_r, hi_r, im.implied_discount(v0, hi_r), im.implied_discount(v0, lo_r), "mc", lo_p, hi_p)


def band_from(cfg: Mapping, a: Mapping[str, Assumption], val: Valuation, mc: "MCFacts | Unavailable") -> Band | Unavailable:
    tick = float(cfg["research"]["vol03"].get("price_tick") or 0)
    v0 = val.per_share["current"]
    lo_d, hi_d = a["band_discount_low"].value, a["band_discount_high"].value
    if lo_d is not None and hi_d is not None:
        hi_p, lo_p = v0 * (1 - lo_d), v0 * (1 - hi_d)
        basis = "evidence" if a["band_discount_low"].origin == "evidence" else "config"
    elif ok(mc):
        lo_p, hi_p = mc.result.q(float(a["band_q_low"].value)), mc.result.q(float(a["band_q_high"].value))
        basis = "mc"
    else:
        return Unavailable("밴드 근거 없음 (할인율 사례·몬테카를로 입력)", "No basis for the band", ["band_discount_low", "band_discount_high"])
    lo_r, hi_r = im.round_price(lo_p, tick), im.round_price(hi_p, tick)
    return Band(lo_r, hi_r, im.implied_discount(v0, hi_r), im.implied_discount(v0, lo_r), basis, lo_p, hi_p)


# ---------------------------------------------------------------------------
# 몬테카를로
# ---------------------------------------------------------------------------
@dataclass
class MCFacts:
    result: im.MCResult
    per_tri: tuple[float, float, float]
    mu: float
    sd: float
    n: int
    seed: int
    required: dict[float, float]       # 분위 q → 필요 할인율 (= 1 − Pq ÷ 주당 평가가액)
    loss_grid: dict[float, float]      # 할인율 → 1년 후 손실 확률
    mode: str = "base"                 # base | dp | stress
    npm_tri: tuple | None = None
    corr: np.ndarray | None = None
    se_p50: float = float("nan")       # P50 배치 표준오차(10개 배치) ÷ P50 — 단계 비교와 별도의 오차 진단
    check_n: int = 0                   # 진단용 대규모 재실행 횟수 (같은 seed)
    check_p50: float = float("nan")    # 그 P50 (보고값 = n회 결과, 진단은 결론 불변 확인용)


def run_mc(cfg: Mapping, a: Mapping[str, Assumption], val: Valuation | Unavailable, mu: Multiples | Unavailable,
           mode: str = "base") -> MCFacts | Unavailable:
    """mode: base = 현재 기준(순이익률 고정) / dp = 이중 고점(순이익률 삼각분포, 상관 = config) / stress = 이중 고점 + 동조 상관."""
    if not ok(val):
        return Unavailable(val.reason, val.reason_en, val.missing)
    if not ok(mu):
        return Unavailable(mu.reason, mu.reason_en, mu.missing)
    miss = [k for k in REQUIRED_MC if a[k].value is None]
    if miss:
        return Unavailable("몬테카를로 입력 없음", "Monte Carlo inputs missing", miss)
    tri = (mu.applied("conservative"), mu.applied("normalized"), mu.applied("current"))
    if not all(finite(x) for x in tri):
        return Unavailable("배수 시나리오 없음", "Multiple scenarios missing", ["conservative"])
    mc_cfg = cfg["research"]["vol03"]["monte_carlo"]
    n, seed = int(cfg["monte_carlo"]["n_sims"]), int(cfg["monte_carlo"]["seed"])
    kw = {}
    npm_tri, corr = None, None
    if mode in ("dp", "stress"):
        miss = [k for k in REQUIRED_DP if a[k].value is None]
        if miss:
            return Unavailable("순이익률 분포 입력 없음", "Net-margin distribution inputs missing", miss)
        npm_tri = (float(a["npm_low"].value), float(a["npm_mode"].value), float(a["npm_high"].value))
        rs = float(mc_cfg.get("corr_stress", 0.5))
        rho = (rs, rs, rs) if mode == "stress" else tuple(float(a[k].value or 0.0) for k in ("corr_growth_per", "corr_growth_npm", "corr_npm_per"))
        corr = im.corr_matrix(*rho)
        kw = dict(npm_tri=npm_tri, npm_base=val.ni / val.rev, corr=corr)
    r = im.monte_carlo(val.ni, val.shares.post, float(a["growth_mean"].value), float(a["growth_sd"].value), tri, n, seed,
                       mc_cfg["convergence"], float(mc_cfg["tolerance"]), int(mc_cfg["horizon_years"]), **kw)
    v0 = val.per_share["current"]
    req = {q: im.implied_discount(v0, r.q(q)) for q in (0.10, 0.25, 0.50)}
    loss = {d: r.prob_below(v0 * (1 - d)) for d in cfg["research"]["vol03"]["discount_grid"]}
    nb = 10
    batches = r.values[: n - n % nb].reshape(nb, -1)
    se = float(np.std(np.median(batches, axis=1), ddof=1) / math.sqrt(nb) / r.q(0.5))
    cn = int(mc_cfg.get("check_multiple", 10)) * n
    big = im.monte_carlo(val.ni, val.shares.post, float(a["growth_mean"].value), float(a["growth_sd"].value), tri, cn, seed,
                         horizon_years=int(mc_cfg["horizon_years"]), **kw)
    return MCFacts(r, tri, float(a["growth_mean"].value), float(a["growth_sd"].value), n, seed, req, loss, mode, npm_tri,
                   corr if corr is not None else np.eye(2), se, cn, big.q(0.5))


# ---------------------------------------------------------------------------
# 국내 IPO 할인율 실증 (DART 증권신고서, research.vol03.ipo_discounts 결과)
# ---------------------------------------------------------------------------
@dataclass
class IPOEvidence:
    table: pd.DataFrame          # 사용 행 (신뢰도 기준 통과, 할인율 하단·상단 있음)
    n_all: int                   # 파일 전체 행
    n: int
    stats: dict[str, tuple[float, float, float]]   # low·high·mid → (Q1, 중앙값, Q3) 할인율
    used: bool                   # n ≥ min_n → 밴드 할인율을 분포 기반으로
    min_n: int
    period: tuple[str, str]
    as_of: str | None

    def rank(self, d: float, which: str = "mid") -> float:
        """할인율 d가 분포에서 차지하는 백분위 (0~1)."""
        col = {"low": "discount_low", "high": "discount_high", "mid": "discount_mid"}[which]
        x = self.table[col].to_numpy()
        return float(np.mean(x <= d)) if len(x) else float("nan")


def ipo_evidence(cfg: Mapping) -> IPOEvidence | Unavailable:
    v3 = cfg["research"]["vol03"]
    icfg = v3.get("ipo_discounts") or {}
    path = _inp(cfg, "ipo_discounts")[0] if "ipo_discounts" in v3["inputs"] else None
    df = _read(path) if path is not None else None
    if df is None:
        return Unavailable("국내 IPO 할인율 실증 미수집", "Korean IPO discount evidence not collected", ["vol03_ipo_discounts.csv"])
    for c in ("discount_low", "discount_high", "value_per_share", "band_low", "band_high"):
        df[c] = df[c].map(num) if c in df else float("nan")
    use = set(icfg.get("use_confidence", ["high", "medium"]))
    t = df[df["confidence"].isin(use) & df["discount_low"].notna() & df["discount_high"].notna()].copy()
    t["discount_mid"] = (t["discount_low"] + t["discount_high"]) / 2
    q = lambda col: tuple(float(np.quantile(t[col], x)) for x in (0.25, 0.5, 0.75)) if len(t) else (float("nan"),) * 3  # noqa: E731
    min_n = int(icfg.get("min_n", 10))
    m = meta_info(path)
    return IPOEvidence(t, len(df), len(t), {"low": q("discount_low"), "high": q("discount_high"), "mid": q("discount_mid")},
                       len(t) >= min_n, min_n, (str(icfg.get("bgn_de", "")), str(icfg.get("end_de", ""))), m.get("as_of"))


def apply_evidence(a: dict[str, Assumption], ev: IPOEvidence | Unavailable) -> None:
    """n ≥ min_n이고 사용자가 밴드 할인율을 직접 넣지 않았으면 분포 중앙값(하단·상단)을 근거 있는(sourced) 값으로."""
    if not ok(ev) or not ev.used:
        return
    for key, which in (("band_discount_low", "low"), ("band_discount_high", "high")):
        cur = a[key]
        if cur.value is None:
            q1, med, q3 = ev.stats[which]
            cur.value, cur.low, cur.high, cur.origin = med, q1, q3, "evidence"
            cur.tag = "ASSUMPTION(sourced)"
            cur.source = (f"DART 증권신고서(지분증권) 신규 상장 {ev.n}건 할인율 중앙값 (범위 = 사분위, {ev.period[0]}~{ev.period[1]})")
            cur.url = "https://dart.fss.or.kr"


# ---------------------------------------------------------------------------
# Vol.1·Vol.2 연결, 데이터 소스
# ---------------------------------------------------------------------------
@dataclass
class Links:
    per0: float | None      # Vol.1 3사 합산 PER (2023 초)
    per1: float | None      # 현재
    earn_share: float | None
    n_valid: int
    group: str
    opm0: float | None      # Vol.2 3사 합산 OPM FY2022A → FY2025A
    opm1: float | None
    implied: float | None
    implied_rng: tuple[float, float] | None
    pp_table: list[dict] = field(default_factory=list)   # 회사별 OPM FY2022A → FY2025A, 함의 가격 상승률


def links(cfg: Mapping, as_of: str) -> Links:
    out = dict(per0=None, per1=None, earn_share=None, n_valid=0, group="", opm0=None, opm1=None, implied=None, implied_rng=None)
    try:
        from research.vol01 import data as v1
        mk, fin = v1.market(cfg), v1.financials(cfg)
        dc = v1.decompose(cfg, mk, fin)
        if v1.ok(dc):
            out.update(per0=dc.agg["per0"], per1=dc.agg["per1"], earn_share=dc.agg["earn_share"], n_valid=dc.n_valid,
                       group=",".join(dc.valid_rows["ticker"]))
    except Exception:  # noqa: BLE001 — Vol.1 입력이 없으면 연결 문장만 생략
        pass
    try:
        from research.vol02 import data as v2
        pp = v2.peer_pricing(cfg)
        if v2.ok(pp):
            out.update(opm0=pp.agg_opm0, opm1=pp.agg_opm1, implied=pp.agg_implied, implied_rng=(pp.low, pp.high),
                       pp_table=pp.table.to_dict("records"))
    except Exception:  # noqa: BLE001
        pass
    return Links(**out)


SOURCES = [
    ("dart", "DART · 금융감독원", "DART · FSS", "사업보고서 연결 재무 FY2022A~FY2025A (국내 4사)", "Annual reports, consolidated, FY2022A–FY2025A (4 Korean names)", "dart"),
    ("krx", "KRX · 한국거래소", "KRX · Korea Exchange", "종가·시가총액·상장주식수 (2023-01-02 · 2026-10-19)", "Close, market cap, listed shares (2 Jan 2023 · 19 Oct 2026)", "krx_points"),
    ("sec", "SEC EDGAR", "SEC EDGAR", "10-K 연간 재무(XBRL) · 표지 발행주식수 · 재무 주체 검사", "10-K annual financials (XBRL), cover shares, entity check", "sec_financials"),
    ("yf", "yfinance (보조)", "yfinance (secondary)", "미국 피어 종가 (2023 첫 거래일 · 기준일)", "U.S. peers' closes (first 2023 trading day · as-of)", "market"),
    ("da", "DART·SEC (추가)", "DART·SEC (extra)", "D&A(EBITDA용) · SEC FY2022A 순이익", "D&A (for EBITDA) · SEC FY2022A NI", "peer_extra"),
    ("ecos", "ECOS · 한국은행", "ECOS · Bank of Korea", "원/달러 매매기준율 (표시용 환산)", "USD/KRW (display conversion)", "fx"),
    ("ipo", "DART 증권신고서", "DART prospectuses", "신규 상장 증권신고서 평가가액·희망공모가·할인율 (2025-01~2026-10)", "New-listing prospectuses: value, range, discount (Jan 2025–Oct 2026)", "ipo_discounts"),
]


def source_status(cfg: Mapping, ovs: Overseas | Unavailable) -> list[dict]:
    rows = []
    for sid, org_kr, org_en, ds_kr, ds_en, key in SOURCES:
        if key == "market":
            okk = ok(ovs) and not ovs.market.empty
            path = _inp(cfg, "market_points")[0]
        else:
            path = _inp(cfg, key)[0]
            okk = path.exists()
        m = meta_info(path) if path.exists() else {}
        rows.append({"id": sid, "org_kr": org_kr, "org_en": org_en, "ds_kr": ds_kr, "ds_en": ds_en, "ok": okk,
                     "as_of": m.get("as_of") if okk else None, "fetched_at": m.get("fetched_at") if okk else None})
    return rows


def entity_rows(ovs: Overseas | Unavailable) -> list[dict]:
    if not ok(ovs) or ovs.entity.empty:
        return []
    return ovs.entity.fillna("").astype(str).to_dict("records")


# ---------------------------------------------------------------------------
# 전체 묶음
# ---------------------------------------------------------------------------
@dataclass
class Facts:
    as_of: str
    assumptions: dict[str, Assumption]
    dom: Domestic | Unavailable
    ovs: Overseas | Unavailable
    peers: Peers | Unavailable
    der: Derived | None
    mult: Multiples | Unavailable
    val: Valuation | Unavailable
    mc: MCFacts | Unavailable
    band: Band | Unavailable
    links: Links
    fx: float | None
    fx_date: str | None
    sources: list[dict]
    entity: list[dict]
    mc_dp: MCFacts | Unavailable = None          # 이중 고점 (순이익률 확률변수, 기준 상관)
    mc_stress: MCFacts | Unavailable = None      # 이중 고점 + 동조 상관 (민감도)
    band_dp: Band | Unavailable = None
    ipo: IPOEvidence | Unavailable = None


def load_facts(cfg: Mapping, as_of: str | None = None) -> Facts:
    as_of = as_of or cfg["research"]["vol03"]["as_of"]
    dom, ovs = domestic(cfg), overseas(cfg)
    pe = build_peers(cfg, dom, ovs)
    der = derive(cfg, dom, pe) if ok(dom) else None
    a = load_assumptions(cfg, der)
    ev = ipo_evidence(cfg)
    apply_evidence(a, ev)
    mu = multiples(cfg, pe) if ok(pe) else Unavailable(pe.reason, pe.reason_en, pe.missing)
    val = valuation(cfg, a, mu) if ok(mu) else Unavailable(mu.reason, mu.reason_en, mu.missing)
    mc = run_mc(cfg, a, val, mu)
    mc_dp, mc_st = run_mc(cfg, a, val, mu, "dp"), run_mc(cfg, a, val, mu, "stress")
    band = band_from(cfg, a, val, mc) if ok(val) else Unavailable(val.reason, val.reason_en, val.missing)
    band_dp = band_mc(cfg, a, val, mc_dp) if ok(val) and ok(mc_dp) else Unavailable("이중 고점 몬테카를로 없음", "No double-peak run")
    fx, fd = fx_on(cfg, as_of)
    return Facts(as_of, a, dom, ovs, pe, der, mu, val, mc, band, links(cfg, as_of), fx, fd, source_status(cfg, ovs), entity_rows(ovs),
                 mc_dp, mc_st, band_dp, ev)


def table_keys(a: Mapping[str, Assumption]) -> list[str]:
    return list(a.keys())


def fmt_missing(keys: list[str], kr: bool = True) -> str:
    return ", ".join(LABELS.get(k, (k, k))[0 if kr else 1] for k in keys)
