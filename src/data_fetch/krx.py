"""KRX 국내 peers 시장 데이터: 종가·시가총액·상장주식수.

1순위: KRX Open API (승인 서비스: 유가증권 일별매매정보, 유가증권 종목기본정보)
대체:  FinanceDataReader → pykrx (보조 소스, 교차검증 플래그 표시)

ASSUMPTION(verify): 인증키는 요청 헤더 AUTH_KEY로 전달, 기준일 파라미터는 basDd(YYYYMMDD),
응답은 {"OutBlock_1": [...]} 형식. KRX Open API 개발명세서로 재확인할 것.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Callable, Mapping

import pandas as pd

from .base import (FetchError, FetchResult, SkipSource, STATUS_FAILED, STATUS_PARTIAL,
                   STATUS_SUCCESS, build_url, get_secret, make_client, markdown_table, mask_secrets,
                   resolve_path, save_processed, save_raw, to_number, utc_now_iso)

logger = logging.getLogger("data_fetch.krx")

SOURCE = "krx"
FIELDS = ("close_krw", "market_cap_krw", "listed_shares")


# ---------------------------------------------------------------------------
# 순수 함수
# ---------------------------------------------------------------------------
def short_code(isu_cd: str) -> str:
    """표준코드(KR7267260008) 또는 단축코드(267260 / A267260) → 6자리 단축코드."""
    s = str(isu_cd or "").strip()
    if len(s) == 12 and s.startswith("KR"):
        return s[3:9]
    if len(s) == 7 and s[0].isalpha():
        return s[1:]
    return s.zfill(6)


def select_peer_rows(trade_rows: list[dict], base_rows: list[dict], tickers: list[str]) -> dict[str, dict]:
    """일별매매정보 + 종목기본정보에서 peers 행 추출 → {ticker: {close_krw, market_cap_krw, listed_shares}}."""
    want = {str(t).zfill(6) for t in tickers}
    out: dict[str, dict] = {}
    for r in trade_rows:
        code = short_code(r.get("ISU_SRT_CD") or r.get("ISU_CD"))
        if code in want:
            out[code] = {
                "close_krw": to_number(r.get("TDD_CLSPRC")),
                "market_cap_krw": to_number(r.get("MKTCAP")),
                "listed_shares": to_number(r.get("LIST_SHRS")),
                "isu_nm": r.get("ISU_NM"),
            }
    for r in base_rows:  # 상장주식수 보완 + 종목명 확인
        code = short_code(r.get("ISU_SRT_CD") or r.get("ISU_CD"))
        if code in want:
            d = out.setdefault(code, {"close_krw": float("nan"), "market_cap_krw": float("nan"),
                                      "listed_shares": float("nan")})
            if pd.isna(d.get("listed_shares")):
                d["listed_shares"] = to_number(r.get("LIST_SHRS"))
            d.setdefault("isu_nm", r.get("ISU_ABBRV") or r.get("ISU_NM"))
    return out


def merge_provider_values(chain: list[tuple[str, dict[str, dict]]], tickers: list[str]) -> dict[str, dict]:
    """소스 우선순위대로 필드별 값을 채운다. 필드마다 사용한 소스를 기록."""
    merged: dict[str, dict] = {}
    for t in tickers:
        rec: dict[str, Any] = {f: float("nan") for f in FIELDS}
        rec.update({f"source_{f}": None for f in FIELDS})
        for src, values in chain:
            v = values.get(t, {})
            for f in FIELDS:
                if pd.isna(rec[f]) and not pd.isna(v.get(f, float("nan"))):
                    rec[f], rec[f"source_{f}"] = float(v[f]), src
        if pd.isna(rec["market_cap_krw"]) and not pd.isna(rec["close_krw"]) and not pd.isna(rec["listed_shares"]):
            rec["market_cap_krw"] = rec["close_krw"] * rec["listed_shares"]
            rec["source_market_cap_krw"] = "computed(close×shares)"
        merged[t] = rec
    return merged


def _asof_date(as_of: str) -> date:
    return datetime.strptime(as_of, "%Y-%m-%d").date()


def _last_on_or_before(df: pd.DataFrame, as_of: str) -> pd.Series | None:
    if df is None or df.empty:
        return None
    idx = pd.to_datetime(df.index)
    df = df.loc[idx <= pd.Timestamp(as_of)]
    return None if df.empty else df.iloc[-1]


# ---------------------------------------------------------------------------
# KRX Open API
# ---------------------------------------------------------------------------
class KrxOpenApiClient:
    def __init__(self, cfg: Mapping, as_of: str, *, http=None, use_cache: bool = True):
        self.cfg = cfg
        self.kcfg = cfg["data_fetch"]["krx"]
        self.key = get_secret(self.kcfg["env_key"])  # 없으면 SkipSource
        self.as_of = as_of
        self.http = http or make_client(SOURCE, cfg, self.kcfg, use_cache=use_cache)
        self.raw_dir = resolve_path(cfg["paths"]["raw"]) / "krx"

    def _url(self, name: str) -> str:
        return build_url(self.kcfg["base_url"], self.kcfg["endpoints"][name])

    def fetch(self, name: str, bas_dd: str, save: bool = True) -> list[dict]:
        params = {"basDd": bas_dd}
        resp = self.http.get(self._url(name), params=params, headers={self.kcfg["auth_header"]: self.key})
        payload = resp.json()
        block = self.kcfg["response_block"]
        if block not in payload:
            raise FetchError(f"KRX {name} 응답에 {block} 없음: {mask_secrets(str(payload)[:200])}")
        rows = payload.get(block) or []
        if save and rows:
            save_raw(self.raw_dir / f"{name}_{bas_dd}.json", payload,
                     source="KRX Open API (한국거래소)", endpoint=self._url(name), params=params,
                     as_of=bas_dd, license_note=self.kcfg["license_note"], fetched_at=resp.fetched_at,
                     extra={"auth": f"header {self.kcfg['auth_header']} (ASSUMPTION(verify))"})
        return rows

    def fetch_latest(self, max_lookback: int) -> tuple[str, list[dict], list[dict]]:
        """기준일부터 거꾸로 거래일을 찾는다 (휴장일이면 빈 OutBlock)."""
        d = _asof_date(self.as_of)
        for i in range(max_lookback + 1):
            bas_dd = (d - timedelta(days=i)).strftime("%Y%m%d")
            trade = self.fetch("daily_trade", bas_dd)
            if trade:
                base = self.fetch("base_info", bas_dd)
                if i:
                    logger.info("KRX 기준일 %s 데이터 없음 → 직전 거래일 %s 사용", self.as_of, bas_dd)
                return bas_dd, trade, base
        raise FetchError(f"KRX {self.as_of}부터 {max_lookback}일 소급해도 데이터 없음")


# ---------------------------------------------------------------------------
# 보조 소스 (지연 import: 테스트·미설치 환경에서도 모듈 로드 가능)
# ---------------------------------------------------------------------------
def fdr_provider(tickers: list[str], as_of: str, lookback_days: int) -> dict[str, dict]:
    import FinanceDataReader as fdr  # noqa: N813

    start = (_asof_date(as_of) - timedelta(days=lookback_days)).isoformat()
    out = {}
    for t in tickers:
        row = _last_on_or_before(fdr.DataReader(t, start, as_of), as_of)
        if row is not None:
            out[t] = {"close_krw": to_number(row.get("Close")), "date": str(row.name)[:10]}
    return out


def pykrx_provider(tickers: list[str], as_of: str, lookback_days: int) -> dict[str, dict]:
    # ASSUMPTION(verify): 최신 pykrx는 KRX 로그인(KRX_ID/KRX_PW 환경변수)이 필요할 수 있다. 비어 있으면 실패 가능.
    from pykrx import stock

    end = as_of.replace("-", "")
    start = (_asof_date(as_of) - timedelta(days=lookback_days)).strftime("%Y%m%d")
    out = {}
    for t in tickers:
        row = _last_on_or_before(stock.get_market_cap(start, end, t), as_of)
        if row is not None:
            out[t] = {"close_krw": to_number(row.get("종가")), "market_cap_krw": to_number(row.get("시가총액")),
                      "listed_shares": to_number(row.get("상장주식수")), "date": str(row.name)[:10]}
    return out


PROVIDERS: dict[str, Callable[[list[str], str, int], dict[str, dict]]] = {
    "fdr": fdr_provider,
    "pykrx": pykrx_provider,
}
PROVIDER_LABELS = {"fdr": "FinanceDataReader", "pykrx": "pykrx"}


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
def run(cfg: Mapping, as_of: str, *, use_cache: bool = True, client: KrxOpenApiClient | None = None,
        providers: Mapping[str, Callable] | None = None) -> FetchResult:
    kcfg = cfg["data_fetch"]["krx"]
    providers = providers or PROVIDERS
    peers = cfg["peers"]["domestic"]
    tickers = [str(p["ticker"]).zfill(6) for p in peers]
    raw_dir = resolve_path(cfg["paths"]["raw"]) / "krx"
    notes, outputs = [], []
    chain: list[tuple[str, dict[str, dict]]] = []
    bas_dd = as_of.replace("-", "")
    krx_ok = False

    try:
        c = client or KrxOpenApiClient(cfg, as_of, use_cache=use_cache)
        bas_dd, trade, base = c.fetch_latest(int(kcfg["max_lookback_days"]))
        chain.append(("KRX Open API", select_peer_rows(trade, base, tickers)))
        outputs += [str(raw_dir / f"daily_trade_{bas_dd}.json"), str(raw_dir / f"base_info_{bas_dd}.json")]
        krx_ok = True
    except SkipSource as e:
        notes.append(f"KRX Open API 건너뜀: {e}")
    except FetchError as e:
        notes.append(mask_secrets(f"KRX Open API 실패: {e}"))
    except Exception as e:  # 응답 형식 오류 등
        notes.append(mask_secrets(f"KRX Open API 오류: {type(e).__name__}: {e}"))

    def missing(tick_chain) -> list[str]:
        merged = merge_provider_values(tick_chain, tickers)
        return [t for t in tickers if any(pd.isna(merged[t][f]) for f in FIELDS)]

    lookback = int(kcfg["max_lookback_days"])
    for name in kcfg.get("fallback_order", []):
        todo = missing(chain)
        if not todo:
            break
        try:
            vals = providers[name](todo, as_of, lookback)
        except Exception as e:  # ImportError, 로그인 필요, 네트워크 등
            notes.append(mask_secrets(f"{PROVIDER_LABELS.get(name, name)} 실패: {type(e).__name__}: {e}"))
            continue
        chain.append((PROVIDER_LABELS.get(name, name), vals))
        path = raw_dir / f"fallback_{name}_{as_of}.csv"
        save_raw(path, pd.DataFrame([{"ticker": t, **v} for t, v in vals.items()]),
                 source=PROVIDER_LABELS.get(name, name), endpoint=f"{name} library", params={"tickers": todo},
                 as_of=as_of, license_note="보조 라이브러리. 원 데이터는 KRX 약관 적용. 교차검증 필요.",
                 fetched_at=utc_now_iso())
        outputs.append(str(path))
        notes.append(f"{PROVIDER_LABELS.get(name, name)}로 {len(vals)}종목 보완 (교차검증 필요)")

    merged = merge_provider_values(chain, tickers)
    rows = []
    for p, t in zip(peers, tickers):
        m = merged[t]
        aux = any(m[f"source_{f}"] not in (None, "KRX Open API") for f in FIELDS)
        rows.append({
            "company": p["name"], "ticker": t, "as_of": as_of, "bas_dd": bas_dd if krx_ok else None,
            "close_krw": m["close_krw"],
            "market_cap_krw_100m": m["market_cap_krw"] / 1e8 if not pd.isna(m["market_cap_krw"]) else float("nan"),
            "listed_shares": m["listed_shares"],
            **{f"source_{f}": m[f"source_{f}"] for f in FIELDS},
            "cross_check_required": aux,
        })
    df = pd.DataFrame(rows)
    out_path = resolve_path(cfg["paths"]["processed"]) / "krx_peers_market.csv"
    save_processed(out_path, df, sources=[s for s, _ in chain] or ["(none)"], as_of=as_of,
                   note="종가 KRW, 시가총액 KRW 억원. source_* 열에 필드별 출처 기록.")
    outputs.append(str(out_path))

    # 교차검증: KRX 성공 시 FDR 종가와 비교
    if krx_ok and kcfg.get("crosscheck_with_fdr"):
        try:
            fdr_vals = providers["fdr"](tickers, as_of, lookback)
            write_krx_crosscheck(cfg, df, fdr_vals, float(kcfg["crosscheck_tolerance_pct"]), as_of)
        except Exception as e:
            notes.append(mask_secrets(f"FDR 교차검증 생략: {type(e).__name__}: {e}"))

    value_cols = ["close_krw", "market_cap_krw_100m", "listed_shares"]
    n_complete = int(df[value_cols].notna().all(axis=1).sum())
    if n_complete == len(tickers) and krx_ok and not df["cross_check_required"].any():
        status = STATUS_SUCCESS
    elif df[value_cols].notna().any().any():
        status = STATUS_PARTIAL
    else:
        status = STATUS_FAILED
    return FetchResult(SOURCE, status, n_items=n_complete, outputs=outputs, message="; ".join(notes))


def write_krx_crosscheck(cfg: Mapping, krx_df: pd.DataFrame, fdr_vals: dict[str, dict], tol_pct: float,
                         as_of: str) -> str:
    rows = []
    for _, r in krx_df.iterrows():
        alt = fdr_vals.get(r["ticker"], {}).get("close_krw", float("nan"))
        diff = (alt / r["close_krw"] - 1) * 100 if r["close_krw"] and not pd.isna(alt) else float("nan")
        rows.append({"company": r["company"], "ticker": r["ticker"], "KRX 종가(원)": r["close_krw"],
                     "FDR 종가(원)": alt, "차이(%)": None if pd.isna(diff) else round(diff, 3),
                     "판정": "N/A" if pd.isna(diff) else ("OK" if abs(diff) <= tol_pct else "CHECK")})
    path = resolve_path(cfg["data_fetch"]["output"]["crosscheck_report_krx"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# KRX 종가 교차검증 (KRX Open API vs FinanceDataReader)\n\n"
        f"- 기준일: {as_of} · 생성: {utc_now_iso()} · 허용오차: ±{tol_pct}%\n"
        f"- 1순위: KRX Open API(한국거래소) / 보조: FinanceDataReader\n\n"
        + markdown_table(rows), encoding="utf-8")
    return str(path)
