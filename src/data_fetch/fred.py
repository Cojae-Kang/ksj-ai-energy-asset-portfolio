"""FRED(St. Louis Fed): DGS10(미 국채 10년), DEXKOUS(원/달러 현물환율, KRW per USD)."""
from __future__ import annotations

import logging
from typing import Mapping

import pandas as pd

from .base import (FetchError, FetchResult, Progress, STATUS_FAILED, STATUS_PARTIAL, STATUS_SUCCESS,
                   build_url, get_secret, make_client, mask_secrets, resolve_path, save_processed,
                   save_raw, to_number)

logger = logging.getLogger("data_fetch.fred")

SOURCE = "fred"
SOURCE_LABEL = "FRED, Federal Reserve Bank of St. Louis"


def parse_observations(payload: Mapping) -> pd.Series:
    """observations[{date, value}] → Series. 결측 '.'은 NaN."""
    if "observations" not in payload:
        raise FetchError(f"FRED 응답 오류: {payload.get('error_message', str(payload)[:200])}")
    obs = payload["observations"]
    return pd.Series([to_number(o.get("value")) for o in obs],
                     index=pd.to_datetime([o["date"] for o in obs]), dtype=float).sort_index()


class FredClient:
    def __init__(self, cfg: Mapping, as_of: str, *, http=None, use_cache: bool = True):
        self.fcfg = cfg["data_fetch"]["fred"]
        self.key = get_secret(self.fcfg["env_key"])
        self.as_of = as_of
        self.http = http or make_client(SOURCE, cfg, self.fcfg, use_cache=use_cache)
        self.raw_dir = resolve_path(cfg["paths"]["raw"]) / "fred"

    def fetch_series(self, series_id: str, unit: str | None = None) -> pd.Series:
        url = build_url(self.fcfg["base_url"], self.fcfg["endpoints"]["observations"])
        params = {"series_id": series_id, "file_type": "json",
                  "observation_start": self.fcfg["start_date"], "observation_end": self.as_of}
        resp = self.http.get(url, params={**params, "api_key": self.key})
        payload = resp.json()
        s = parse_observations(payload)
        save_raw(self.raw_dir / f"{series_id}.json", payload, source=SOURCE_LABEL, endpoint=url, params=params,
                 as_of=self.as_of, license_note=self.fcfg["license_note"], fetched_at=resp.fetched_at,
                 extra={"unit": unit})
        return s


def run(cfg: Mapping, as_of: str, *, use_cache: bool = True, client: FredClient | None = None) -> FetchResult:
    c = client or FredClient(cfg, as_of, use_cache=use_cache)
    specs = cfg["data_fetch"]["fred"]["series"]
    data, notes, outputs = {}, [], []
    prog = Progress(SOURCE, "시계열", len(specs))
    for spec in specs:
        try:
            with prog.step(spec["id"]) as st:
                data[spec["id"]] = c.fetch_series(spec["id"], spec.get("unit"))
                st["note"] = f"({data[spec['id']].notna().sum()}건)"
            outputs.append(str(c.raw_dir / f"{spec['id']}.json"))
        except FetchError as e:  # 타임아웃 포함: 해당 시리즈만 건너뜀
            notes.append(mask_secrets(f"{spec['id']} 실패: {e}"))
    if data:
        df = pd.DataFrame(data).rename_axis("date").reset_index()
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")
        path = resolve_path(cfg["paths"]["processed"]) / "fred_series.csv"
        save_processed(path, df, sources=[SOURCE_LABEL], as_of=as_of,
                       note="DGS10: % p.a. / DEXKOUS: KRW per USD (Noon buying rates in NY)")
        outputs.append(str(path))
    status = STATUS_SUCCESS if len(data) == len(specs) else (STATUS_PARTIAL if data else STATUS_FAILED)
    return FetchResult(SOURCE, status, n_items=len(data), outputs=outputs, message="; ".join(notes))
