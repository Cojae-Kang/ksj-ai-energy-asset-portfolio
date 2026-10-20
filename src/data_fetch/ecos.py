"""ECOS(한국은행 경제통계시스템): 원/달러 환율(일별 → 연평균·연말), 국고채 3년·10년(일별).

ECOS는 인증키가 URL 경로에 들어간다. 로그·meta에서는 base.mask_secrets로 마스킹한다.
통계코드·항목코드는 config.yaml(data_fetch.ecos.series)에서 관리하고, 응답의 ITEM_NAME1로 검증한다.
"""
from __future__ import annotations

import logging
from typing import Mapping

import pandas as pd

from .base import (FetchError, FetchResult, Progress, STATUS_FAILED, STATUS_PARTIAL, STATUS_SUCCESS,
                   get_secret, make_client, mask_secrets, resolve_path, save_processed, save_raw,
                   to_number)

logger = logging.getLogger("data_fetch.ecos")

SOURCE = "ecos"
SOURCE_LABEL = "한국은행 경제통계시스템(ECOS)"
INFO_NO_DATA = "INFO-200"


def build_ecos_url(base_url: str, service: str, key: str, start_row: int, end_row: int, stat_code: str,
                   cycle: str, start: str, end: str, item_code: str) -> str:
    parts = [service, key, "json", "kr", str(start_row), str(end_row), stat_code, cycle, start, end, item_code]
    return base_url.rstrip("/") + "/" + "/".join(parts)


def parse_ecos_rows(payload: Mapping, service: str = "StatisticSearch") -> list[dict]:
    """ECOS JSON → row 리스트. 데이터 없음(INFO-200)은 빈 리스트, 그 외 RESULT 오류는 예외."""
    if service in payload:
        return payload[service].get("row", []) or []
    result = payload.get("RESULT", {})
    if result.get("CODE") == INFO_NO_DATA:
        return []
    raise FetchError(f"ECOS 오류 {result.get('CODE')}: {result.get('MESSAGE')}")


def verify_item_name(rows: list[dict], expect: str | None) -> str | None:
    """응답 ITEM_NAME1이 기대 키워드를 포함하지 않으면 경고 문자열 반환 (코드 오기입 방지)."""
    if not rows or not expect:
        return None
    names = {str(r.get("ITEM_NAME1", "")) for r in rows}
    if not any(expect in n for n in names):
        return f"항목명 불일치: 기대 '{expect}' / 응답 {sorted(names)} → config의 item_code 확인 필요"
    return None


def rows_to_series(rows: list[dict], cycle: str = "D") -> pd.Series:
    fmt = {"D": "%Y%m%d", "M": "%Y%m", "A": "%Y"}.get(cycle, "%Y%m%d")
    idx = pd.to_datetime([r["TIME"] for r in rows], format=fmt)
    return pd.Series([to_number(r.get("DATA_VALUE")) for r in rows], index=idx).sort_index()


def annual_fx_summary(daily: pd.Series) -> pd.DataFrame:
    """일별 환율 → 연도별 단순평균(영업일)·연말(마지막 영업일)·관측치 수."""
    s = daily.dropna()
    g = s.groupby(s.index.year)
    out = pd.DataFrame({
        "year": g.mean().index.astype(int),
        "usdkrw_avg": g.mean().values,
        "usdkrw_year_end": g.last().values,
        "year_end_date": [d.strftime("%Y-%m-%d") for d in g.apply(lambda x: x.index.max())],
        "n_obs": g.size().values,
    })
    out["fiscal_year"] = "FY" + out["year"].astype(str)
    return out


class EcosClient:
    def __init__(self, cfg: Mapping, as_of: str, *, http=None, use_cache: bool = True):
        self.cfg = cfg
        self.ecfg = cfg["data_fetch"]["ecos"]
        self.key = get_secret(self.ecfg["env_key"])  # 없으면 SkipSource
        self.as_of = as_of
        self.http = http or make_client(SOURCE, cfg, self.ecfg, use_cache=use_cache)
        self.raw_dir = resolve_path(cfg["paths"]["raw"]) / "ecos"

    def fetch_series(self, spec: Mapping, start: str, end: str) -> tuple[list[dict], str | None]:
        page, rows, fetched_at = int(self.ecfg["page_size"]), [], None
        start_row = 1
        while True:
            url = build_ecos_url(self.ecfg["base_url"], self.ecfg["service"], self.key, start_row,
                                 start_row + page - 1, spec["stat_code"], spec["cycle"], start, end,
                                 spec["item_code"])
            resp = self.http.get(url)
            fetched_at = resp.fetched_at
            payload = resp.json()
            chunk = parse_ecos_rows(payload, self.ecfg["service"])
            rows += chunk
            total = int(payload.get(self.ecfg["service"], {}).get("list_total_count", len(rows)) or 0)
            if not chunk or len(rows) >= total:
                break
            start_row += page
        # endpoint는 키 자리를 {KEY}로 표기
        endpoint = build_ecos_url(self.ecfg["base_url"], self.ecfg["service"], "{KEY}", 1, len(rows) or page,
                                  spec["stat_code"], spec["cycle"], start, end, spec["item_code"])
        save_raw(self.raw_dir / f"{spec['id']}.json", {"row": rows}, source=SOURCE_LABEL, endpoint=endpoint,
                 params={"stat_code": spec["stat_code"], "cycle": spec["cycle"], "item_code": spec["item_code"],
                         "start": start, "end": end},
                 as_of=self.as_of, license_note=self.ecfg["license_note"], fetched_at=fetched_at,
                 extra={"unit": spec.get("unit")})
        return rows, fetched_at


def run(cfg: Mapping, as_of: str, *, use_cache: bool = True, client: EcosClient | None = None) -> FetchResult:
    c = client or EcosClient(cfg, as_of, use_cache=use_cache)
    ecfg = cfg["data_fetch"]["ecos"]
    start, end = ecfg["start_date"], as_of.replace("-", "")
    processed = resolve_path(cfg["paths"]["processed"])
    series: dict[str, pd.Series] = {}
    notes, outputs = [], []

    prog = Progress(SOURCE, "시계열", len(ecfg["series"]))
    for spec in ecfg["series"]:
        try:
            with prog.step(f"{spec['id']} {spec['stat_code']}/{spec['item_code']}") as st:
                rows, _ = c.fetch_series(spec, start, end)
                st["note"] = f"({len(rows)}건)"
        except FetchError as e:  # 타임아웃 포함: 해당 시리즈만 건너뜀
            notes.append(mask_secrets(f"{spec['id']} 실패: {e}"))
            continue
        warn = verify_item_name(rows, spec.get("expect_item_name"))
        if warn:
            notes.append(f"{spec['id']}: {warn}")
            logger.warning("ECOS %s %s", spec["id"], warn)
        if not rows:
            notes.append(f"{spec['id']}: 데이터 없음")
            continue
        series[spec["id"]] = rows_to_series(rows, spec["cycle"])
        outputs.append(str(c.raw_dir / f"{spec['id']}.json"))

    if "usdkrw_daily" in series:
        fx = series["usdkrw_daily"].rename("usdkrw").rename_axis("date").reset_index()
        fx["date"] = fx["date"].dt.strftime("%Y-%m-%d")
        save_processed(processed / "ecos_fx_daily.csv", fx, sources=[SOURCE_LABEL], as_of=as_of,
                       note="원/달러 매매기준율, KRW per USD")
        annual = annual_fx_summary(series["usdkrw_daily"])
        off = ecfg.get("official_annual_fx") or {}
        if off.get("stat_code") and off.get("item_code"):  # 공식 연평균 시리즈 → 직접 계산값과 비교용 열
            spec = {"id": "usdkrw_annual_official", **off}
            try:
                rows, _ = c.fetch_series(spec, start[:4], end[:4])
                official = rows_to_series(rows, "A")
                annual["usdkrw_avg_official"] = annual["year"].map(dict(zip(official.index.year, official.values)))
            except FetchError as e:
                notes.append(mask_secrets(f"공식 연평균 환율 실패: {e}"))
        save_processed(processed / "ecos_fx_annual.csv", annual,
                       sources=[SOURCE_LABEL], as_of=as_of,
                       note="연평균 = 일별 영업일 단순평균(직접 계산), 연말 = 해당 연도 마지막 영업일. "
                            "기준일이 속한 연도는 연초~기준일 평균(YTD).")
        outputs += [str(processed / "ecos_fx_daily.csv"), str(processed / "ecos_fx_annual.csv")]

    ktb = {k: v for k, v in series.items() if k.startswith("ktb")}
    if ktb:
        df = pd.DataFrame(ktb).rename_axis("date").reset_index()
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")
        save_processed(processed / "ecos_ktb_daily.csv", df, sources=[SOURCE_LABEL], as_of=as_of,
                       note="국고채 수익률, % p.a.")
        outputs.append(str(processed / "ecos_ktb_daily.csv"))

    n = len(series)
    status = STATUS_SUCCESS if n == len(ecfg["series"]) and not notes else (STATUS_PARTIAL if n else STATUS_FAILED)
    return FetchResult(SOURCE, status, n_items=n, outputs=outputs, message="; ".join(notes))
