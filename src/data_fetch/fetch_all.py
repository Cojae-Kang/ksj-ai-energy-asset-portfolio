"""데이터 수집 실행 진입점 (로컬 전용).

    python -m src.data_fetch.fetch_all --source all --asof 2026-10-20
    python -m src.data_fetch.fetch_all --source krx,ecos,sec --asof 2026-10-20
    python -m src.data_fetch.fetch_all --source dart --skip-filings --no-cache

키가 없는 소스는 SKIPPED로 건너뛰고 나머지는 계속 진행한다.
수집 후 peers 식별자 검증(validate)과 재무 통합(consolidate)을 자동 실행한다.
"""
from __future__ import annotations

import argparse
import copy
import logging
import sys
import time
from datetime import datetime
from typing import Callable, Mapping

from . import consolidate, dart, ecos, eia, fred, krx, market_global, sec, validate_peers
from .base import (FetchResult, SkipSource, STATUS_FAILED, STATUS_SKIPPED, load_config, markdown_table,
                   mask_secrets, resolve_path, setup_logging, utc_now_iso)

logger = logging.getLogger("data_fetch")

SOURCES: dict[str, Callable[..., FetchResult]] = {
    "dart": dart.run,
    "krx": krx.run,
    "ecos": ecos.run,
    "sec": sec.run,
    "fred": fred.run,
    "eia": eia.run,
    "global": market_global.run,
}
# 후처리 단계: (이름, 함수, 실행 조건이 되는 소스)
POST_STEPS: list[tuple[str, Callable[..., FetchResult], set[str]]] = [
    ("validate", validate_peers.run, {"dart", "sec"}),
    ("consolidate", consolidate.run, {"dart", "sec", "ecos"}),
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AI-DC 전력 밸류체인 데이터 수집 (로컬 실행)")
    p.add_argument("--source", nargs="+", default=["all"],
                   help=f"수집 소스. 쉼표 또는 공백으로 여러 개 (예: krx,ecos,sec). "
                        f"all = 전체. 선택지: {', '.join(SOURCES)}")
    p.add_argument("--asof", default=None, help="기준일 YYYY-MM-DD (기본: config data_fetch.as_of_default)")
    p.add_argument("--config", default=None, help="config.yaml 경로")
    p.add_argument("--no-cache", action="store_true", help="응답 캐시 무시하고 새로 요청")
    p.add_argument("--no-post", action="store_true", help="validate/consolidate 후처리 생략")
    p.add_argument("--skip-filings", action="store_true",
                   help="DART 발행공시 검색·원문 다운로드 생략 (config dart.filings.enabled보다 우선)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    args.source = split_sources(args.source, p)
    if args.asof:
        datetime.strptime(args.asof, "%Y-%m-%d")  # 형식 검증 (잘못되면 ValueError)
    return args


def split_sources(values: list[str], parser: argparse.ArgumentParser | None = None) -> list[str]:
    """["krx,ecos", "sec"] → ["krx", "ecos", "sec"]. 알 수 없는 소스는 argparse 오류(종료코드 2)."""
    out = [v.strip().lower() for raw in values for v in raw.split(",") if v.strip()]
    unknown = [v for v in out if v not in ("all", *SOURCES)]
    if unknown:
        msg = f"알 수 없는 소스: {', '.join(unknown)} (선택지: all, {', '.join(SOURCES)})"
        if parser:
            parser.error(msg)
        raise ValueError(msg)
    return out or ["all"]


def run_one(name: str, fn: Callable[..., FetchResult], cfg: Mapping, as_of: str, use_cache: bool) -> FetchResult:
    t0 = time.monotonic()
    try:
        res = fn(cfg, as_of, use_cache=use_cache)
    except SkipSource as e:
        res = FetchResult(name, STATUS_SKIPPED, message=str(e))
    except Exception as e:  # 한 소스 실패가 전체를 멈추지 않도록
        res = FetchResult(name, STATUS_FAILED, message=mask_secrets(f"{type(e).__name__}: {e}"))
    res.source = name
    res.message = mask_secrets(res.message)
    res.elapsed_sec = round(time.monotonic() - t0, 1)
    logger.info("[%s] %s (%d items) %s", name, res.status, res.n_items, res.message[:300])
    return res


def summary_rows(results: list[FetchResult]) -> list[dict]:
    return [{"source": r.source, "status": r.status, "items": r.n_items, "sec": r.elapsed_sec,
             "message": (r.message[:160] + "…") if len(r.message) > 160 else r.message} for r in results]


def print_summary(results: list[FetchResult]) -> str:
    rows = summary_rows(results)
    widths = {k: max(len(k), *(len(str(r[k])) for r in rows)) for k in ("source", "status", "items", "sec")}
    head = "  ".join(k.ljust(widths[k]) for k in widths) + "  message"
    lines = [head, "-" * len(head)]
    lines += ["  ".join(str(r[k]).ljust(widths[k]) for k in widths) + "  " + r["message"] for r in rows]
    text = "\n".join(lines)
    print("\n=== 데이터 수집 요약 ===\n" + text + "\n")
    return text


def write_summary_report(cfg: Mapping, results: list[FetchResult], as_of: str) -> str:
    path = resolve_path(cfg["data_fetch"]["output"]["summary_report"])
    path.parent.mkdir(parents=True, exist_ok=True)
    outputs = sorted({o for r in results for o in r.outputs})
    root = str(resolve_path("."))
    path.write_text(
        f"# 데이터 수집 요약\n\n- 기준일(as_of): {as_of}\n- 실행 시각(UTC): {utc_now_iso()}\n\n"
        + markdown_table(summary_rows(results))
        + "\n## 생성 파일\n\n" + "\n".join(f"- `{o.replace(root, '').lstrip('/').lstrip(chr(92))}`" for o in outputs)
        + "\n", encoding="utf-8")
    return str(path)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    cfg = load_config(args.config)
    if args.skip_filings:
        cfg = copy.deepcopy(cfg)
        cfg["data_fetch"]["dart"].setdefault("filings", {})["enabled"] = False
    as_of = args.asof or cfg["data_fetch"]["as_of_default"]
    selected = list(SOURCES) if "all" in args.source else [s for s in SOURCES if s in args.source]
    filings_on = cfg["data_fetch"]["dart"].get("filings", {}).get("enabled", False)
    logger.info("기준일 %s, 소스 %s, DART 공시검색 %s", as_of, ", ".join(selected), "ON" if filings_on else "OFF")

    results = [run_one(name, SOURCES[name], cfg, as_of, not args.no_cache) for name in selected]
    if not args.no_post:
        for name, fn, triggers in POST_STEPS:
            if triggers & set(selected):
                results.append(run_one(name, fn, cfg, as_of, not args.no_cache))

    print_summary(results)
    report = write_summary_report(cfg, results, as_of)
    print(f"요약 보고서: {report}")
    return 1 if any(r.status == STATUS_FAILED for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
