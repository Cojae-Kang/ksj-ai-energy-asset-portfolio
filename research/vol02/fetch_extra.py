"""Vol.2 추가 수집 (로컬 실행 전용). Vol.1과 같은 src/data_fetch 인프라를 쓴다.

    python -m research.vol02.fetch_extra --asof 2026-10-20

B-1) EIA: 버지니아(VA)·미국(US) 상업용(COM) 전력 소매판매량·평균 가격, 연간 2015~최신
     → data/processed/vol02_eia_va_com.csv (+ .meta.json), raw: data/raw/eia/vol02_retail_sales_com_va_price.json
     케이스 B의 전력비 민감도 단가(버지니아 상업용 평균 요금). 수집 전에는 미국 상업용 평균을 대용치로 쓴다.
키가 없으면 SKIPPED. 원자료(data/raw)는 커밋하지 않는다.
"""
from __future__ import annotations

import argparse
import copy
import logging
import sys
from typing import Mapping

from src.data_fetch import eia
from src.data_fetch.base import (FetchResult, SkipSource, STATUS_FAILED, STATUS_SKIPPED, STATUS_SUCCESS, load_config,
                                 mask_secrets, resolve_path, save_processed, setup_logging)

logger = logging.getLogger("research.vol02.fetch_extra")

EIA_RAW = "vol02_retail_sales_com_va_price.json"


def eia_va_config(cfg: Mapping) -> dict:
    """기존 data_fetch.eia 설정을 복사해 VA·US 상업용 판매량·가격 범위로 덮어쓴 cfg."""
    c = copy.deepcopy(dict(cfg))
    c["data_fetch"]["eia"].update(state=["VA", "US"], sectors=["COM"], data_fields=["sales", "price"], start="2015", end=None)
    return c


def fetch_eia_va_price(cfg: Mapping, as_of: str, *, use_cache: bool = True, client=None) -> FetchResult:
    c2 = eia_va_config(cfg)
    client = client or eia.EiaClient(c2, as_of, use_cache=use_cache)   # 키 없으면 SkipSource
    rows, _ = client.fetch_retail_sales(raw_name=EIA_RAW)
    df = eia.tidy(rows, ["sales", "price"], c2["data_fetch"]["eia"]["source_label"])
    if df.empty or "VA" not in set(df["stateid"]):
        return FetchResult("eia_va_price", STATUS_FAILED, message="EIA 응답에 버지니아 상업용 데이터 없음")
    df = df[df["stateid"].isin(["VA", "US"]) & (df["sectorid"] == "COM")].copy()
    df["period"] = df["period"].astype(int)
    out = resolve_path(cfg["research"]["vol02"]["inputs"]["eia_va_price"])
    save_processed(out, df.sort_values(["stateid", "period"]).reset_index(drop=True),
                   sources=[c2["data_fetch"]["eia"]["source_label"]], as_of=as_of,
                   note="electricity/retail-sales, VA·US, COM, annual 2015~최신. sales: million kWh, price: cents/kWh")
    return FetchResult("eia_va_price", STATUS_SUCCESS, n_items=len(df), outputs=[str(out)],
                       message=f"{df['period'].min()}~{df['period'].max()}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="KSJ Research Vol.2 추가 수집 (로컬 실행)")
    p.add_argument("--asof", default=None)
    p.add_argument("--config", default=None)
    p.add_argument("--no-cache", action="store_true")
    args = p.parse_args(argv)
    setup_logging()
    cfg = load_config(args.config)
    as_of = args.asof or cfg["research"]["vol02"]["as_of"]
    try:
        r = fetch_eia_va_price(cfg, as_of, use_cache=not args.no_cache)
    except SkipSource as e:
        r = FetchResult("eia_va_price", STATUS_SKIPPED, message=str(e))
    except Exception as e:  # noqa: BLE001
        r = FetchResult("eia_va_price", STATUS_FAILED, message=mask_secrets(f"{type(e).__name__}: {e}"))
    print(f"\n=== Vol.2 추가 수집 ===\n{r.source:<13} {r.status:<8} {r.n_items:>4}  {r.message}")
    return 1 if r.status == STATUS_FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
