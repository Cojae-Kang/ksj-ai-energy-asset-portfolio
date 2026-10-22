"""config.yaml peers 티커 검증: 국내 → DART corp_code, 해외 → SEC CIK.

결과는 docs/qa/peer_validation.md에 기록한다.
입력: data/raw/dart/corp_codes_listed.csv, data/raw/sec/company_tickers.json (fetch_all 실행 후 생성),
      data/processed/sec_entity_check.csv (시총 주체 = 상장사, 재무 주체 = companyfacts 법인 검사 결과)
해외 피어(SEC) 데이터 노트는 research/vol03/data_notes.md에 갱신한다 (Vol.3에서 사용).

실행: python -m src.data_fetch.validate_peers
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Mapping

import pandas as pd

from .base import (FetchResult, STATUS_FAILED, STATUS_PARTIAL, STATUS_SKIPPED, STATUS_SUCCESS, load_config,
                   markdown_table, names_match, normalize_name, resolve_path, utc_now_iso)  # noqa: F401 (re-export)
from .sec import apply_entity_override, cik10, parse_company_tickers

logger = logging.getLogger("data_fetch.validate")

OK, WARN, FAIL, NA = "OK", "WARN", "FAIL", "N/A (SEC 비대상)"
SEC_UNAVAILABLE = "SKIPPED(sec unavailable)"   # SEC 매핑 수집 실패 → 검증 보류 (티커 오류와 구분)


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


def validate_overseas(peers: list[Mapping], sec_df: pd.DataFrame | None, not_sec: set[str],
                      entity: Mapping[str, Mapping] | None = None) -> list[dict]:
    """entity: ticker → sec_entity_check 행. 티커는 맞아도 재무 주체가 상장사와 다르면 WARN + 사유."""
    entity = entity or {}
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
            rows.append({**base, "식별자": None, "공시상 회사명": None, "결과": SEC_UNAVAILABLE,
                         "비고": "SEC company_tickers.json 수집 실패/없음 → 티커 검증 보류. "
                                 "python -m src.data_fetch.sec --diagnose 후 --source sec 재실행"})
            continue
        hit = sec_df[sec_df["ticker"] == t]
        if hit.empty:
            rows.append({**base, "식별자": None, "공시상 회사명": None, "결과": FAIL,
                         "비고": "SEC company_tickers.json에 티커 없음"})
            continue
        r = hit.iloc[0]
        ok = names_match(p["name"], r["title"])
        note = "" if ok else "회사명 불일치 → 수동 확인"
        ent = entity.get(t)
        if ent is not None and str(ent.get("verdict")) != OK:
            ok = False
            note = "; ".join(x for x in (note, f"재무 주체 확인 필요: {ent.get('reason')}") if x)
        elif ent is not None and ent.get("manual_check"):
            note = "; ".join(x for x in (note, f"OK({ent['manual_check'].split(' — ')[0]})") if x)
        rows.append({**base, "식별자": f"CIK {cik10(r['cik'])}", "공시상 회사명": r["title"],
                     "결과": OK if ok else WARN, "비고": note})
    return rows


def load_entity_checks(cfg: Mapping) -> pd.DataFrame | None:
    """sec_entity_check.csv + 수동 확인 override(config entity_check.manual_overrides) 적용."""
    ec = cfg["data_fetch"]["sec"].get("entity_check") or {}
    path = resolve_path(cfg["paths"]["processed"]) / ec.get("output", "sec_entity_check.csv")
    if not path.exists():
        return None
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    rows = [apply_entity_override(r, ec.get("manual_overrides")) for r in df.to_dict("records")]
    return pd.DataFrame(rows).fillna("")


def load_mappings(cfg: Mapping) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    raw = resolve_path(cfg["paths"]["raw"])
    corp_path, sec_path = raw / "dart" / "corp_codes_listed.csv", raw / "sec" / "company_tickers.json"
    corp_df = pd.read_csv(corp_path, dtype=str, keep_default_na=False) if corp_path.exists() else None
    sec_df = parse_company_tickers(json.loads(sec_path.read_text(encoding="utf-8"))) if sec_path.exists() else None
    return corp_df, sec_df


ENTITY_COLS = ["company", "ticker", "listed_cik", "listed_title", "entity_cik", "entity_name", "same_consolidated",
               "verdict", "reason"]


def manual_section(ent: pd.DataFrame | None) -> list[str]:
    """수동 확인 override 기록 (근거 URL·확인일)."""
    if ent is None or "manual_check" not in ent or not (ent["manual_check"] != "").any():
        return []
    m = ent[ent["manual_check"] != ""]
    rows = [{"ticker": r["ticker"], "자동 판정": f"{r.get('auto_verdict', '')} ({r.get('auto_same', '')})",
             "수동 판정": f"{r['verdict']}({r['manual_check'].split(' — ')[0]})", "내용": r["manual_check"].split(" — ")[-1],
             "근거 URL": r.get("manual_url", ""), "확인일": r.get("verified_on", "")} for r in m.to_dict("records")]
    return ["**수동 확인 (자동 판정 override)**", "", markdown_table(rows)]


def entity_section(ent: pd.DataFrame | None) -> list[str]:
    lines = ["## 시총(상장사) vs 재무(법인) 주체 검사", ""]
    if ent is None or ent.empty:
        return lines + ["- SEC companyfacts 미수집 → 검사 보류 (fetch_all --source sec [--sec-offline])", ""]
    lines += ["- 상장사 = company_tickers.json의 티커·CIK(시가총액 주체), 재무 = companyfacts의 cik·entityName",
              "- same_consolidated: yes 같은 법인 / likely 같은 CIK·보통주·EPS(법인명 표기만 다름) / no 다른 법인 / "
              "unknown 보통주·EPS 미보고 / yes (manual) 수동 확인", "",
              markdown_table(ent[ENTITY_COLS].to_dict("records"))] + manual_section(ent)
    return lines


def render_report(rows: list[dict], as_of: str, ent: pd.DataFrame | None = None) -> str:
    counts = pd.Series([r["결과"] for r in rows]).value_counts().to_dict()
    issues = [r for r in rows if r["결과"] in (WARN, FAIL)]
    lines = [
        "# Peers 식별자 검증 (DART corp_code / SEC CIK)", "",
        f"- 기준일: {as_of} · 생성: {utc_now_iso()}",
        "- 출처: Open DART corpCode.xml(금융감독원), SEC EDGAR company_tickers.json",
        "- 판정: OK = 티커·회사명 일치 / WARN = 티커는 있으나 회사명 불일치 또는 재무 주체(법인)가 상장사와 다를 수 있음 / "
        "FAIL = 티커 없음 / N/A = SEC 비대상 / "
        f"{SEC_UNAVAILABLE} = SEC 매핑 수집 실패로 검증 보류(티커 오류 아님)", "",
        "## 핵심 결론", "",
        f"1. 검증 {len(rows)}개 중 " + ", ".join(f"{k} {v}개" for k, v in counts.items()),
        f"2. 불일치(WARN/FAIL): {len(issues)}개" + (" — 아래 표의 비고 확인" if issues else " — config 티커 그대로 사용 가능"),
        "3. Schneider Electric(SU.PA)은 SEC 비대상 → 재무 수치는 회사 연차보고서로 수기 입력(data/manual)"
        + (f" · SEC 매핑 미수집으로 {sum(r['결과'] == SEC_UNAVAILABLE for r in rows)}개 검증 보류"
           if any(r["결과"] == SEC_UNAVAILABLE for r in rows) else ""), "",
        "## 상세", "", markdown_table(rows, ["구분", "회사(config)", "ticker", "시장", "식별자", "공시상 회사명", "결과", "비고"]),
        *entity_section(ent),
        "## 한계", "",
        "- 회사명 비교는 공백·법인격 표기를 제거한 부분일치 기준이라, 동명이사(同名異社)는 수동 확인 필요",
        "- company_tickers.json은 SEC가 수시 갱신하는 매핑으로, 티커 변경 직후에는 반영이 늦을 수 있음", "",
    ]
    return "\n".join(lines)


def render_vol03_notes(ent: pd.DataFrame | None, watchlist: Mapping[str, str], as_of: str) -> str:
    """Vol.3(IPO·해외 피어) 데이터 노트: 핵심 결론 3줄 → 근거 → 한계."""
    warn = [] if ent is None else [r for r in ent.to_dict("records") if r["verdict"] != OK]
    pending = {t: v for t, v in watchlist.items() if ent is None or t not in set(ent["ticker"])}
    n = 0 if ent is None else len(ent)
    lines = ["# Vol.3 데이터 노트 — 해외 피어(SEC EDGAR)", "",
             f"- 기준일: {as_of} · 갱신: {utc_now_iso()} · 생성: `python -m src.data_fetch.validate_peers`",
             "- 출처: SEC EDGAR company_tickers.json(상장사 티커·CIK), XBRL companyfacts(연간 재무). "
             "403 환경에서는 브라우저 다운로드 파일(SEC EDGAR (manual browser download))", "",
             "## 핵심 결론", "",
             (f"1. 재무 주체 검사 {n}개사 중 WARN {len(warn)}개" if n else "1. 재무 주체 검사 보류 — SEC companyfacts 미수집(TODO(data))"),
             "2. 시총은 상장사(company_tickers 티커), 재무는 companyfacts 법인 기준 — 둘이 다르면 배수 계산에서 제외",
             "3. " + ("; ".join(f"{r['ticker']}: {r['reason']}" for r in warn) if warn else
                      ("; ".join(f"{t}: {v} (검사 대기)" for t, v in pending.items()) if pending else
                       "주체 불일치 없음" + "".join(f" — {r['ticker']}: {r['manual_check'].split(' — ')[0]} (확인일 {r.get('verified_on', '')})"
                                                  for r in ([] if ent is None or 'manual_check' not in ent else ent.to_dict('records'))
                                                  if r.get('manual_check')))),
             "", "## 근거", ""]
    if ent is not None and not ent.empty:
        lines += [markdown_table(ent[ENTITY_COLS].to_dict("records"))] + manual_section(ent)
    else:
        lines += ["- TODO(data): SEC companyfacts 수집 후 자동 작성 — `python -m src.data_fetch.fetch_all --source sec --sec-offline`", ""]
    if pending:
        lines += ["**검사 대기 중인 관찰 기록**", ""] + [f"- {t}: {v}" for t, v in pending.items()] + [""]
    lines += ["## 한계", "",
              "- 법인 일치 판정은 CIK·법인명·보통주 발행주식수·EPS 보고 여부로 한 자동 판정이다. 최종 확인은 10-K 표지(registrant)와 연결범위 주석",
              "- 오프라인 모드 수치의 기준 시각은 브라우저 다운로드 파일의 수정 시각(.meta.json fetched_at)",
              "- 수동 확인 override는 config(data_fetch.sec.entity_check.manual_overrides)에 근거 URL·확인일과 함께 기록하며, 자동 판정은 auto_verdict로 보존",
              ""]
    return "\n".join(lines)


def run(cfg: Mapping, as_of: str, **_) -> FetchResult:
    corp_df, sec_df = load_mappings(cfg)
    ent = load_entity_checks(cfg)
    ent_map = {} if ent is None else {r["ticker"]: r for r in ent.to_dict("records")}
    not_sec = {t.upper() for t in cfg["data_fetch"]["sec"].get("not_sec_registrants", [])}
    rows = (validate_domestic(cfg["peers"]["domestic"], corp_df)
            + validate_overseas(cfg["peers"]["overseas"], sec_df, not_sec, ent_map))
    path = resolve_path(cfg["data_fetch"]["output"]["peer_validation_report"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(rows, as_of, ent), encoding="utf-8")
    notes_out = cfg["data_fetch"]["output"].get("vol03_data_notes")
    if notes_out:
        np_ = resolve_path(notes_out)
        np_.parent.mkdir(parents=True, exist_ok=True)
        watch = (cfg["data_fetch"]["sec"].get("entity_check") or {}).get("watchlist") or {}
        np_.write_text(render_vol03_notes(ent, watch, as_of), encoding="utf-8")
    n_fail = sum(r["결과"] == FAIL for r in rows)
    n_warn = sum(r["결과"] == WARN for r in rows)
    n_skip = sum(r["결과"] == SEC_UNAVAILABLE for r in rows)
    n_checkable = sum(r["결과"] not in (NA, SEC_UNAVAILABLE) for r in rows)
    if n_checkable == 0:
        status = STATUS_SKIPPED
    elif n_fail == n_checkable:
        status = STATUS_FAILED
    elif n_fail or n_warn or n_skip:
        status = STATUS_PARTIAL
    else:
        status = STATUS_SUCCESS
    n_ent = 0 if ent is None else int((ent["verdict"] != OK).sum())
    msg = (f"FAIL {n_fail}, WARN {n_warn}" + (f", {SEC_UNAVAILABLE} {n_skip}" if n_skip else "")
           + (f", 재무 주체 WARN {n_ent}" if n_ent else ""))
    outputs = [str(path)] + ([str(resolve_path(notes_out))] if notes_out else [])
    return FetchResult("validate", status, n_items=len(rows), outputs=outputs, message=msg)


if __name__ == "__main__":  # pragma: no cover
    _cfg = load_config()
    res = run(_cfg, _cfg["data_fetch"]["as_of_default"])
    print(f"{res.status}: {res.message} → {res.outputs[0]}")
    sys.exit(0 if res.status != STATUS_FAILED else 1)
