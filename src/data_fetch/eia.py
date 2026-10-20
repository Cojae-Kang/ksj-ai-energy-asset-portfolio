"""EIA Open Data v2: 미국 전력 소매판매량·가격 (부문별, 연간).

출처 표기: "U.S. Energy Information Administration (EIA)"
route: electricity/retail-sales (sales: million kWh, price: cents/kWh — 응답의 *-units 열로 확인)
"""
from __future__ import annotations

import logging
from typing import Mapping

import pandas as pd

from .base import (FetchError, FetchResult, STATUS_FAILED, STATUS_SUCCESS, build_url, get_secret,
                   make_client, resolve_path, save_processed, save_raw, to_number)

logger = logging.getLogger("data_fetch.eia")

SOURCE = "eia"


def build_params(ecfg: Mapping, offset: int = 0) -> list[tuple[str, str]]:
    """EIA v2 파라미터 (data[]/facets[] 반복 키 때문에 튜플 리스트)."""
    p: list[tuple[str, str]] = [("frequency", ecfg["frequency"])]
    p += [(f"data[{i}]", f) for i, f in enumerate(ecfg["data_fields"])]
    p.append(("facets[stateid][]", ecfg["state"]))
    p += [("facets[sectorid][]", s) for s in ecfg["sectors"]]
    if ecfg.get("start"):
        p.append(("start", str(ecfg["start"])))
    if ecfg.get("end"):
        p.append(("end", str(ecfg["end"])))
    p += [("sort[0][column]", "period"), ("sort[0][direction]", "asc"),
          ("sort[1][column]", "sectorid"), ("sort[1][direction]", "asc"),
          ("offset", str(offset)), ("length", str(ecfg["page_length"]))]
    return p


def parse_response(payload: Mapping) -> tuple[list[dict], int]:
    if "response" not in payload:
        raise FetchError(f"EIA 응답 오류: {str(payload.get('error', payload))[:200]}")
    r = payload["response"]
    return r.get("data", []) or [], int(r.get("total", 0) or 0)


def tidy(rows: list[dict], fields: list[str], source_label: str) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for f in fields:
        if f in df:
            df[f] = df[f].map(to_number)
    df["source"] = source_label
    return df.sort_values(["period", "sectorid"]).reset_index(drop=True)


class EiaClient:
    def __init__(self, cfg: Mapping, as_of: str, *, http=None, use_cache: bool = True):
        self.ecfg = cfg["data_fetch"]["eia"]
        self.key = get_secret(self.ecfg["env_key"])
        self.as_of = as_of
        self.http = http or make_client(SOURCE, cfg, self.ecfg, use_cache=use_cache)
        self.raw_dir = resolve_path(cfg["paths"]["raw"]) / "eia"

    def fetch_retail_sales(self) -> tuple[list[dict], str]:
        url = build_url(self.ecfg["base_url"], self.ecfg["endpoints"]["retail_sales"])
        rows, offset, fetched_at, pages = [], 0, None, []
        while True:
            params = build_params(self.ecfg, offset)
            resp = self.http.get(url, params=[("api_key", self.key)] + params)
            fetched_at = resp.fetched_at
            payload = resp.json()
            chunk, total = parse_response(payload)
            rows += chunk
            pages.append({k: v for k, v in payload.get("response", {}).items() if k != "data"})
            offset += len(chunk)
            if not chunk or offset >= total:
                break
        save_raw(self.raw_dir / "retail_sales_annual.json", {"data": rows, "pages": pages},
                 source=self.ecfg["source_label"], endpoint=url, params=build_params(self.ecfg),
                 as_of=self.as_of, license_note=self.ecfg["license_note"], fetched_at=fetched_at)
        return rows, fetched_at


def run(cfg: Mapping, as_of: str, *, use_cache: bool = True, client: EiaClient | None = None) -> FetchResult:
    c = client or EiaClient(cfg, as_of, use_cache=use_cache)
    ecfg = cfg["data_fetch"]["eia"]
    rows, _ = c.fetch_retail_sales()
    df = tidy(rows, ecfg["data_fields"], ecfg["source_label"])
    if df.empty:
        return FetchResult(SOURCE, STATUS_FAILED, message="EIA retail-sales 데이터 없음")
    path = resolve_path(cfg["paths"]["processed"]) / "eia_retail_sales_annual.csv"
    save_processed(path, df, sources=[ecfg["source_label"]], as_of=as_of,
                   note="단위는 *-units 열 참조 (sales: million kWh, price: cents/kWh)")
    return FetchResult(SOURCE, STATUS_SUCCESS, n_items=len(df),
                       outputs=[str(c.raw_dir / "retail_sales_annual.json"), str(path)])
