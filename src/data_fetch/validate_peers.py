"""config.yaml peers 티커 검증: 국내 → DART corp_code, 해외 → SEC CIK.

결과는 reports/peer_validation.md에 기록한다.
입력: data/raw/dart/corp_codes_listed.csv, data/raw/sec/company_tickers.json (fetch_all 실행 후 생성)

실행: python -m src.data_fetch.validate_peers
"""
from __future__ import annotations

import json
import logging
import re
import sys
from typing import Mapping

import pandas as pd

from .base import (FetchResult, STATUS_FAILED, STATUS_PARTIAL, STATUS_SUCCESS, load_config,
                   markdown_table, resolve_path, utc_now_iso)
from .sec import cik10, parse_company_tickers

logger = logging.getLogger("data_fetch.validate")

OK, WARN, FAIL, NA = "OK", "WARN", "FAIL", "N/A (SEC 비대상)"

_CORP_SUFFIXES = r"(주식회사|주|㈜|inc\.?|corp\.?|corporation|co\.?|company|plc|holdings?|ltd\.?|limited|s\.?a\.?|se)$"


def normalize_name(name: str) -> str:
    s = str(name or "").lower().strip()
    s = re.sub(r"[\s,.\-&'()]", " ", s)
    tokens = [t for t in s.split() if not re.fullmatch(_CORP_SUFFIXES, t)]
    return "".join(tokens)


def names_match(expected: str, actual: str) -> bool:
    a, b = normalize_name(expected), normalize_name(actual)
    return bool(a) and bool(b) and (a in b or b in a)


def validate_domestic(peers: list[Mapping], corp_df: pd.DataFrame | None) -> list[dict]:
    rows = []
    for p in peers:
        ticker = str(p["ticker"]).zfill(6)
        base = {"구분": "국내", "회사(config)": p["name"], "ticker": ticker, "시장": p.get("market")}
        if corp_df is None:
            rows.append({**base, "식별자": None, "공시상 회사명": None, "결과": FAIL,
                         "비고": "DART 고유번호 파일 없음 → --source dart 먼저 실행"})
            continue
        hit = corp_df[corp_df["stock_code"].astype(str).str.zfill(6) == ticker]
        if hit.empty:
            rows.append({**base, "식별자": None, "공시상 회사명": None, "결과": FAIL,
                         "비고": "DART corpCode에 해당 종목코드 없음 (티커 오기입 또는 상장폐지)"})
            continue
        if len(hit) > 1:
            hit = hit.sort_values("modify_date", ascending=False)
        r = hit.iloc[0]
        ok = names_match(p["name"], r["corp_name"]) or names_match(p["name"], r.get("corp_eng_name", ""))
        rows.append({**base, "식별자": f"corp_code {r['corp_code']}", "공시상 회사명": r["corp_name"],
                     "결과": OK if ok else WARN, "비고": "" if ok else "회사명 불일치 → 수동 확인"})
    return rows


def validate_overseas(peers: list[Mapping], sec_df: pd.DataFrame | None, not_sec: set[str]) -> list[dict]:
    rows = []
    for p in peers:
        t = p["ticker"].upper()
        base = {"구분": "해외", "회사(config)": p["name"], "ticker": t, "시장": p.get("market")}
        if t in not_sec:
            rows.append({**base, "식별자": None, "공시상 회사명": None, "결과": NA,
                         "비고": "SEC 등록 공시기업 아님(Euronext Paris 상장). 재무는 연차보고서(URD) 기반 "
                                 "data/manual 수기 입력. TODO(data)"})
            continue
        if sec_df is None:
            rows.append({**base, "식별자": None, "공시상 회사명": None, "결과": FAIL,
                         "비고": "SEC company_tickers 파일 없음 → --source sec 먼저 실행"})
            continue
        hit = sec_df[sec_df["ticker"] == t]
        if hit.empty:
            rows.append({**base, "식별자": None, "공시상 회사명": None, "결과": FAIL,
                         "비고": "SEC company_tickers.json에 티커 없음"})
            continue
        r = hit.iloc[0]
        ok = names_match(p["name"], r["title"])
        rows.append({**base, "식별자": f"CIK {cik10(r['cik'])}", "공시상 회사명": r["title"],
                     "결과": OK if ok else WARN, "비고": "" if ok else "회사명 불일치 → 수동 확인"})
    return rows


def load_mappings(cfg: Mapping) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    raw = resolve_path(cfg["paths"]["raw"])
    corp_path, sec_path = raw / "dart" / "corp_codes_listed.csv", raw / "sec" / "company_tickers.json"
    corp_df = pd.read_csv(corp_path, dtype=str, keep_default_na=False) if corp_path.exists() else None
    sec_df = parse_company_tickers(json.loads(sec_path.read_text(encoding="utf-8"))) if sec_path.exists() else None
    return corp_df, sec_df


def render_report(rows: list[dict], as_of: str) -> str:
    counts = pd.Series([r["결과"] for r in rows]).value_counts().to_dict()
    issues = [r for r in rows if r["결과"] in (WARN, FAIL)]
    lines = [
        "# Peers 식별자 검증 (DART corp_code / SEC CIK)", "",
        f"- 기준일: {as_of} · 생성: {utc_now_iso()}",
        "- 출처: Open DART corpCode.xml(금융감독원), SEC EDGAR company_tickers.json",
        "- 판정: OK = 티커·회사명 일치 / WARN = 티커는 있으나 회사명 불일치 / FAIL = 티커 없음 / N/A = SEC 비대상", "",
        "## 핵심 결론", "",
        f"1. 검증 {len(rows)}개 중 " + ", ".join(f"{k} {v}개" for k, v in counts.items()),
        f"2. 불일치(WARN/FAIL): {len(issues)}개" + (" — 아래 표의 비고 확인" if issues else " — config 티커 그대로 사용 가능"),
        "3. Schneider Electric(SU.PA)은 SEC 비대상 → 재무 수치는 회사 연차보고서로 수기 입력(data/manual)", "",
        "## 상세", "", markdown_table(rows, ["구분", "회사(config)", "ticker", "시장", "식별자", "공시상 회사명", "결과", "비고"]),
        "## 한계", "",
        "- 회사명 비교는 공백·법인격 표기를 제거한 부분일치 기준이라, 동명이사(同名異社)는 수동 확인 필요",
        "- company_tickers.json은 SEC가 수시 갱신하는 매핑으로, 티커 변경 직후에는 반영이 늦을 수 있음", "",
    ]
    return "\n".join(lines)


def run(cfg: Mapping, as_of: str, **_) -> FetchResult:
    corp_df, sec_df = load_mappings(cfg)
    not_sec = {t.upper() for t in cfg["data_fetch"]["sec"].get("not_sec_registrants", [])}
    rows = validate_domestic(cfg["peers"]["domestic"], corp_df) + validate_overseas(cfg["peers"]["overseas"], sec_df, not_sec)
    path = resolve_path(cfg["data_fetch"]["output"]["peer_validation_report"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(rows, as_of), encoding="utf-8")
    n_fail = sum(r["결과"] == FAIL for r in rows)
    n_warn = sum(r["결과"] == WARN for r in rows)
    n_checkable = sum(r["결과"] != NA for r in rows)
    status = STATUS_SUCCESS if not (n_fail or n_warn) else (STATUS_FAILED if n_fail == n_checkable else STATUS_PARTIAL)
    return FetchResult("validate", status, n_items=len(rows), outputs=[str(path)],
                       message=f"FAIL {n_fail}, WARN {n_warn}")


if __name__ == "__main__":  # pragma: no cover
    _cfg = load_config()
    res = run(_cfg, _cfg["data_fetch"]["as_of_default"])
    print(f"{res.status}: {res.message} → {res.outputs[0]}")
    sys.exit(0 if res.status != STATUS_FAILED else 1)
