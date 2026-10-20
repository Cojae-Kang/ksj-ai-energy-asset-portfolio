"""SEC EDGAR: company_tickers.json(CIK 매핑) + XBRL companyfacts(연간 재무).

추출 지표: Revenue, OperatingIncome, NetIncome, 총차입금, 현금 (USD → USD mn).
SEC fair access: User-Agent 헤더(이름 + 이메일) 필수, 초당 10건 이하.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Mapping

import pandas as pd

from .base import (FetchError, FetchResult, STATUS_FAILED, STATUS_PARTIAL, STATUS_SUCCESS,
                   build_url, get_secret, make_client, mask_secrets, resolve_path, save_processed,
                   save_raw)

logger = logging.getLogger("data_fetch.sec")

SOURCE = "sec"
SOURCE_LABEL = "SEC EDGAR (U.S. Securities and Exchange Commission)"
USD_PER_MN = 1e6


# ---------------------------------------------------------------------------
# 순수 함수
# ---------------------------------------------------------------------------
def parse_company_tickers(payload: Mapping) -> pd.DataFrame:
    """{"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...} → DataFrame."""
    rows = [{"ticker": str(v["ticker"]).upper(), "cik": int(v["cik_str"]), "title": v["title"]}
            for v in payload.values()]
    return pd.DataFrame(rows)


def cik10(cik: int | str) -> str:
    return str(int(cik)).zfill(10)


def fiscal_year_label(end: str, cutoff_month: int = 6) -> int:
    """회계연도 종료일 → 회계연도 (ASSUMPTION: 종료월 < cutoff_month이면 전년도)."""
    d = datetime.strptime(end, "%Y-%m-%d")
    return d.year if d.month >= cutoff_month else d.year - 1


def _entries(facts: Mapping, taxonomy: str, tag: str, unit: str) -> list[dict]:
    try:
        return facts["facts"][taxonomy][tag]["units"][unit]
    except KeyError:
        return []


def annual_values(facts: Mapping, tag: str, *, kind: str, forms: list[str], duration_days: tuple[int, int],
                  cutoff_month: int, taxonomy: str = "us-gaap", unit: str = "USD") -> dict[int, dict]:
    """연간 값 추출 → {fiscal_year: {val, end, accn, filed, form}}.

    kind="flow": start~end가 duration_days 범위(약 1년)인 항목만 (분기 누적값 제외)
    kind="instant": start가 없는 시점 값
    동일 종료일이 여러 공시에 나오면 가장 최근 filed(재작성 반영) 채택.
    """
    best: dict[str, dict] = {}
    for e in _entries(facts, taxonomy, tag, unit):
        if e.get("form") not in forms or "end" not in e or e.get("val") is None:
            continue
        if kind == "flow":
            if "start" not in e:
                continue
            days = (datetime.strptime(e["end"], "%Y-%m-%d") - datetime.strptime(e["start"], "%Y-%m-%d")).days
            if not (duration_days[0] <= days <= duration_days[1]):
                continue
        elif "start" in e:
            continue
        prev = best.get(e["end"])
        if prev is None or e.get("filed", "") > prev.get("filed", ""):
            best[e["end"]] = e
    out: dict[int, dict] = {}
    for end, e in best.items():
        fy = fiscal_year_label(end, cutoff_month)
        if fy not in out or end > out[fy]["end"]:
            out[fy] = {"val": float(e["val"]), "end": end, "accn": e.get("accn"),
                       "filed": e.get("filed"), "form": e.get("form"), "tag": tag}
    return out


def first_available(facts: Mapping, tags: list[str], fy: int, **kw) -> dict | None:
    for tag in tags:
        v = annual_values(facts, tag, **kw).get(fy)
        if v is not None:
            return v
    return None


def total_debt(facts: Mapping, components: list[Mapping], fy: int, fy_end: str | None,
               **kw) -> tuple[float, list[dict], list[str]]:
    """총차입금 = 구성요소별 첫 번째 사용 가능한 대안의 합 (ASSUMPTION: config sec.total_debt_components).

    대안의 첫 태그가 있어야 채택. 나머지 태그가 없으면 0으로 보고 플래그.
    fy_end가 주어지면 같은 종료일의 값만 사용 (손익 기준일과 일치).
    """
    total, detail, flags, found_any = 0.0, [], [], False
    for comp in components:
        for alt in comp["alternatives"]:
            vals = {t: annual_values(facts, t, kind="instant", **kw).get(fy) for t in alt}
            head = vals[alt[0]]
            if head is None or (fy_end and head["end"] != fy_end):
                continue
            found_any = True
            for t, v in vals.items():
                if v is None or (fy_end and v["end"] != fy_end):
                    flags.append(f"total_debt:{comp['name']}:{t}=missing→0")
                    continue
                total += v["val"]
                detail.append({"component": comp["name"], "tag": t, "val_usd": v["val"], "end": v["end"],
                               "accn": v["accn"]})
            break
    if not found_any:
        return float("nan"), detail, flags + ["total_debt:missing"]
    return total, detail, flags


def extract_company_financials(facts: Mapping, scfg: Mapping, fiscal_years: list[int]) -> tuple[list[dict], list[dict]]:
    """companyfacts → 연도별 지표 행(USD mn) + 차입금 구성 상세."""
    kw = dict(forms=scfg["forms"], duration_days=tuple(scfg["flow_duration_days"]),
              cutoff_month=int(scfg["fy_label_cutoff_month"]))
    rows, debt_detail = [], []
    for fy in fiscal_years:
        rec: dict[str, Any] = {"fiscal_year": f"FY{fy}A"}
        flags = []
        rev = first_available(facts, scfg["metrics"]["revenue"], fy, kind="flow", **kw)
        fy_end = rev["end"] if rev else None
        for metric, tags in scfg["metrics"].items():
            kind = "instant" if metric == "cash" else "flow"
            v = rev if metric == "revenue" else first_available(facts, tags, fy, kind=kind, **kw)
            if v is not None and fy_end and v["end"] != fy_end:
                flags.append(f"{metric}:end_mismatch({v['end']})")
            if v is None:
                rec[metric] = float("nan")
                flags.append(f"{metric}:missing")
            else:
                rec[metric] = v["val"] / USD_PER_MN
                rec[f"{metric}_tag"] = v["tag"]
                if v["tag"] != tags[0]:
                    flags.append(f"{metric}:tag={v['tag']}")
        debt, detail, dflags = total_debt(facts, scfg["total_debt_components"], fy, fy_end, **kw)
        rec["total_debt"] = debt / USD_PER_MN if debt == debt else float("nan")
        rec["fiscal_year_end"] = fy_end
        rec["accn"] = rev["accn"] if rev else None
        rec["flags"] = ";".join(flags + dflags)
        rows.append(rec)
        debt_detail += [{"fiscal_year": f"FY{fy}A", **d, "val_usd_mn": d["val_usd"] / USD_PER_MN} for d in detail]
    return rows, debt_detail


def latest_shares_outstanding(facts: Mapping, taxonomy: str = "dei",
                              tag: str = "EntityCommonStockSharesOutstanding") -> dict | None:
    """표지(cover page) 발행주식수 중 가장 최근 값. 복수 클래스는 같은 end의 합."""
    entries = _entries(facts, taxonomy, tag, "shares")
    if not entries:
        return None
    last_end = max(e["end"] for e in entries)
    same = [e for e in entries if e["end"] == last_end]
    latest_filed = max(e.get("filed", "") for e in same)
    same = [e for e in same if e.get("filed", "") == latest_filed]
    # 동일 공시 내 클래스별 값(중복 제거 후 합)
    vals = {(e.get("accn"), e.get("frame"), e["val"]) for e in same}
    return {"shares": float(sum(v[2] for v in vals)), "end": last_end, "filed": latest_filed}


# ---------------------------------------------------------------------------
# 클라이언트
# ---------------------------------------------------------------------------
class SecClient:
    def __init__(self, cfg: Mapping, as_of: str, *, http=None, use_cache: bool = True):
        self.cfg = cfg
        self.scfg = cfg["data_fetch"]["sec"]
        self.user_agent = get_secret(self.scfg["env_key"])  # 없으면 SkipSource
        self.as_of = as_of
        self.http = http or make_client(SOURCE, cfg, self.scfg, use_cache=use_cache)
        self.headers = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}
        self.raw_dir = resolve_path(cfg["paths"]["raw"]) / "sec"
        self.large_dir = resolve_path(cfg["data_fetch"]["output"]["raw_large"]) / "sec"

    def _meta(self, endpoint: str, params: Mapping, fetched_at: str) -> dict:
        return dict(source=SOURCE_LABEL, endpoint=endpoint, params=params, as_of=self.as_of,
                    license_note=self.scfg["license_note"], fetched_at=fetched_at)

    def fetch_tickers(self) -> pd.DataFrame:
        url = self.scfg["tickers_url"]
        resp = self.http.get(url, headers=self.headers)
        payload = resp.json()
        save_raw(self.raw_dir / "company_tickers.json", payload, **self._meta(url, {}, resp.fetched_at))
        return parse_company_tickers(payload)

    def fetch_companyfacts(self, cik: int) -> dict:
        url = build_url(self.scfg["base_url"], self.scfg["endpoints"]["companyfacts"], cik10=cik10(cik))
        resp = self.http.get(url, headers=self.headers)
        payload = resp.json()
        # companyfacts 원본은 수 MB → large/ (git 제외)
        save_raw(self.large_dir / f"companyfacts_CIK{cik10(cik)}.json", resp.content,
                 **self._meta(url, {"cik": cik10(cik)}, resp.fetched_at))
        return payload


def run(cfg: Mapping, as_of: str, *, use_cache: bool = True, client: SecClient | None = None) -> FetchResult:
    c = client or SecClient(cfg, as_of, use_cache=use_cache)
    scfg = cfg["data_fetch"]["sec"]
    years = cfg["data_fetch"]["fiscal_years"]
    skip = set(scfg.get("not_sec_registrants", []))
    tick = c.fetch_tickers()
    outputs = [str(c.raw_dir / "company_tickers.json")]
    notes, fin_rows, debt_rows, share_rows = [], [], [], []

    for peer in cfg["peers"]["overseas"]:
        t = peer["ticker"].upper()
        if t in skip:
            notes.append(f"{peer['name']}({t}): SEC 공시 대상 아님 → data/manual 수기 입력 대상")
            continue
        hit = tick[tick["ticker"] == t]
        if hit.empty:
            notes.append(f"{peer['name']}({t}): company_tickers.json에 없음")
            continue
        cik = int(hit.iloc[0]["cik"])
        try:
            facts = c.fetch_companyfacts(cik)
        except FetchError as e:
            notes.append(mask_secrets(f"{peer['name']} companyfacts 실패: {e}"))
            continue
        rows, detail = extract_company_financials(facts, scfg, years)
        base = {"company": peer["name"], "ticker": t, "cik": cik10(cik), "entity_name": facts.get("entityName")}
        fin_rows += [{**base, "basis": "US GAAP (consolidated)", "currency": "USD", "unit": "mn", **r}
                     for r in rows]
        debt_rows += [{**base, **d} for d in detail]
        tag = scfg.get("shares_tag", ["dei", "EntityCommonStockSharesOutstanding"])
        sh = latest_shares_outstanding(facts, tag[0], tag[1])
        if sh:
            share_rows.append({**base, **sh})

    processed = resolve_path(cfg["paths"]["processed"])
    if fin_rows:
        save_processed(processed / "sec_financials.csv", pd.DataFrame(fin_rows), sources=[SOURCE_LABEL],
                       as_of=as_of, note="USD mn, 10-K 연간값(최신 filed 기준). 총차입금 정의는 config ASSUMPTION 참조.")
        save_processed(processed / "sec_debt_components.csv", pd.DataFrame(debt_rows), sources=[SOURCE_LABEL],
                       as_of=as_of, note="총차입금 구성 태그 (검산용)")
        outputs += [str(processed / "sec_financials.csv"), str(processed / "sec_debt_components.csv")]
    if share_rows:
        save_processed(processed / "sec_shares_outstanding.csv", pd.DataFrame(share_rows),
                       sources=[SOURCE_LABEL], as_of=as_of, note="dei:EntityCommonStockSharesOutstanding (표지)")
        outputs.append(str(processed / "sec_shares_outstanding.csv"))

    n_target = len([p for p in cfg["peers"]["overseas"] if p["ticker"].upper() not in skip])
    n_done = len({r["ticker"] for r in fin_rows})
    errs = [n for n in notes if "SEC 공시 대상 아님" not in n]
    status = STATUS_SUCCESS if n_done == n_target and not errs else (STATUS_PARTIAL if n_done else STATUS_FAILED)
    return FetchResult(SOURCE, status, n_items=n_done, outputs=outputs, message="; ".join(notes))
