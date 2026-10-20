"""데이터 수집 파이프라인 단위테스트 — 네트워크 없이 실행 (모든 응답은 mock)."""
from __future__ import annotations

import copy
import io
import json
import logging
import sys
import types
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import requests

from src.data_fetch import (base, consolidate, dart, ecos, eia, fetch_all, fred, krx, market_global, sec,
                            validate_peers)
from src.data_fetch.base import FetchError, HttpClient, SkipSource


# ---------------------------------------------------------------------------
# 공통 fixture / fake
# ---------------------------------------------------------------------------
class FakeResp:
    def __init__(self, status=200, body=b"", url="https://example.test"):
        self.status_code = status
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.content = body
        self.text = body.decode("utf-8", errors="replace")
        self.headers = {"Content-Type": "application/json"}
        self.url = url


class FakeSession:
    """handler(url, params, headers) → FakeResp 또는 Exception."""

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[dict] = []
        self.headers: dict = {}

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers or {}, "timeout": timeout})
        out = self.handler(url, params, headers or {})
        if isinstance(out, Exception):
            raise out
        return out


def make_http(handler, source="test", **kw):
    sleeps: list[float] = []
    sess = FakeSession(handler)
    client = HttpClient(source, {"timeout_sec": 7, "max_retries": 3, "backoff_base_sec": 1.0,
                                 "cache_ttl_hours": 0}, session=sess, sleep=sleeps.append, **kw)
    return client, sess, sleeps


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    """로컬 .env가 테스트에 섞이지 않도록 dotenv 로드를 막고 키를 비운다."""
    monkeypatch.setattr(base, "_DOTENV_LOADED", True)
    for k in ["DART_API_KEY", "KRX_API_KEY", "ECOS_API_KEY", "FRED_API_KEY", "EIA_API_KEY", "SEC_USER_AGENT"]:
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def cfg(tmp_path):
    c = copy.deepcopy(base.load_config())
    for k in ["raw", "processed", "manual", "reports"]:
        c["paths"][k] = str(tmp_path / k)
    out = c["data_fetch"]["output"]
    out["raw_large"] = str(tmp_path / "raw" / "large")
    out["cache"] = str(tmp_path / "cache")
    out["processed_peers"] = str(tmp_path / "processed" / "peers_financials.csv")
    for k in ["summary_report", "peer_validation_report", "crosscheck_report_krx", "crosscheck_report_global"]:
        out[k] = str(tmp_path / "reports" / Path(out[k]).name)
    c["data_fetch"]["manual_overseas_financials"] = str(tmp_path / "manual" / "overseas.csv")
    return c


# ---------------------------------------------------------------------------
# base: 마스킹·meta·재시도·캐시·지연·키 로드
# ---------------------------------------------------------------------------
def test_mask_secrets_query_path_and_registered(monkeypatch):
    monkeypatch.setenv("ECOS_API_KEY", "SECRETECOS123")
    key = base.get_secret("ECOS_API_KEY")
    url = f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/10/731Y001/D/20230101/20261020/0000001"
    assert key not in base.mask_secrets(url)
    assert "/StatisticSearch/***/json" in base.mask_secrets(url)
    assert base.mask_secrets("x?crtfc_key=abcd1234&corp_code=1") == "x?crtfc_key=***&corp_code=1"
    assert base.mask_secrets("api_key=zzz9&series_id=DGS10") == "api_key=***&series_id=DGS10"


def test_logging_filter_masks_keys(monkeypatch, caplog):
    monkeypatch.setenv("DART_API_KEY", "DARTKEY_ABCDEF")
    key = base.get_secret("DART_API_KEY")
    lg = logging.getLogger("data_fetch.test_mask")
    caplog.handler.addFilter(base.SecretMaskingFilter())
    with caplog.at_level(logging.INFO):
        lg.info("calling %s?crtfc_key=%s", "https://opendart", key)
    assert key not in caplog.text and "***" in caplog.text


def test_get_secret_missing_raises_skip():
    with pytest.raises(SkipSource, match="DART_API_KEY"):
        base.get_secret("DART_API_KEY")


def test_save_raw_writes_meta_without_key(tmp_path):
    p = base.save_raw(tmp_path / "x" / "data.json", {"a": 1}, source="SRC", endpoint="https://h/api",
                      params={"crtfc_key": "KEY123456", "bsns_year": "2025"}, as_of="2026-10-20",
                      license_note="LN", fetched_at="2026-10-20T00:00:00+00:00")
    meta = json.loads((tmp_path / "x" / "data.meta.json").read_text(encoding="utf-8"))
    assert p.exists()
    assert set(base.META_FIELDS) <= set(meta)
    assert meta["params"] == {"bsns_year": "2025"}
    assert "KEY123456" not in json.dumps(meta)


def test_sanitize_params_list_of_tuples():
    out = base.sanitize_params([("api_key", "k"), ("facets[sectorid][]", "RES"), ("facets[sectorid][]", "COM")])
    assert out == {"facets[sectorid][]": ["RES", "COM"]}


def test_retry_exponential_backoff_then_success():
    seq = [FakeResp(503), requests.ConnectionError("boom"), FakeResp(200, {"ok": 1})]
    client, sess, sleeps = make_http(lambda *a: seq.pop(0))
    r = client.get("https://h/x", params={"a": 1})
    assert r.json() == {"ok": 1}
    assert sleeps == [1.0, 2.0]                       # 지수 백오프
    assert all(c["timeout"] == 7 for c in sess.calls)  # 타임아웃 전달


def test_retry_gives_up_after_three_retries():
    client, sess, sleeps = make_http(lambda *a: FakeResp(500))
    with pytest.raises(FetchError, match="3회 재시도"):
        client.get("https://h/x?api_key=SHOULDMASK")
    assert len(sess.calls) == 4 and sleeps == [1.0, 2.0, 4.0]


def test_http_4xx_raises_masked_without_retry():
    client, sess, _ = make_http(lambda *a: FakeResp(401, "bad key"))
    with pytest.raises(FetchError) as ei:
        client.get("https://h/x?crtfc_key=TOPSECRET99")
    assert "TOPSECRET99" not in str(ei.value) and len(sess.calls) == 1


def test_request_delay_between_calls():
    t = {"now": 0.0}
    sleeps: list[float] = []
    client = HttpClient("t", {"cache_ttl_hours": 0}, request_delay_sec=0.5,
                        session=FakeSession(lambda *a: FakeResp(200, {})), sleep=sleeps.append,
                        clock=lambda: t["now"])
    client.get("https://h/1")
    t["now"] = 0.1
    client.get("https://h/2")
    assert sleeps == [pytest.approx(0.4)]


def test_cache_hit_skips_network(tmp_path):
    sess = FakeSession(lambda *a: FakeResp(200, {"v": 1}))
    client = HttpClient("t", {"cache_ttl_hours": 1}, cache_dir=tmp_path, session=sess, sleep=lambda s: None)
    r1 = client.get("https://h/x", params={"api_key": "K1", "q": 1})
    r2 = client.get("https://h/x", params={"api_key": "K1", "q": 1})
    assert len(sess.calls) == 1 and r2.from_cache and r2.json() == r1.json()
    assert not any("K1" in p.read_text(errors="ignore") for p in tmp_path.rglob("*.hdr.json"))


def test_build_url_with_path_params():
    assert base.build_url("https://data.sec.gov/", "api/xbrl/companyfacts/CIK{cik10}.json",
                          cik10="0001234567") == "https://data.sec.gov/api/xbrl/companyfacts/CIK0001234567.json"


# ---------------------------------------------------------------------------
# DART
# ---------------------------------------------------------------------------
def _corp_zip() -> bytes:
    xml = """<?xml version="1.0" encoding="UTF-8"?><result>
      <list><corp_code>00000001</corp_code><corp_name>HD현대일렉트릭</corp_name><stock_code>267260</stock_code><modify_date>20250101</modify_date></list>
      <list><corp_code>00000002</corp_code><corp_name>비상장사</corp_name><stock_code> </stock_code><modify_date>20250101</modify_date></list>
    </result>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CORPCODE.xml", xml)
    return buf.getvalue()


def _fn_rows():
    return [
        {"rcept_no": "R1", "sj_div": "BS", "account_id": "ifrs-full_CashAndCashEquivalents", "account_nm": "현금및현금성자산", "account_detail": "-", "thstrm_amount": "50000000000"},
        {"rcept_no": "R1", "sj_div": "BS", "account_id": "ifrs-full_ShortTermBorrowings", "account_nm": "단기차입금", "account_detail": "-", "thstrm_amount": "10000000000"},
        {"rcept_no": "R1", "sj_div": "BS", "account_id": "x", "account_nm": "사채", "account_detail": "-", "thstrm_amount": "20000000000"},
        {"rcept_no": "R1", "sj_div": "BS", "account_id": "x", "account_nm": "사채할인발행차금", "account_detail": "-", "thstrm_amount": "-100000000"},
        {"rcept_no": "R1", "sj_div": "BS", "account_id": "x", "account_nm": "리스부채", "account_detail": "-", "thstrm_amount": "999000000000"},
        {"rcept_no": "R1", "sj_div": "BS", "account_id": "x", "account_nm": "장기차입금", "account_detail": "세부", "thstrm_amount": "777000000000"},
        {"rcept_no": "R1", "sj_div": "IS", "account_id": "ifrs-full_Revenue", "account_nm": "매출액", "account_detail": "-", "thstrm_amount": "3,000,000,000,000"},
        {"rcept_no": "R1", "sj_div": "IS", "account_id": "dart_OperatingIncomeLoss", "account_nm": "영업이익", "account_detail": "-", "thstrm_amount": "300000000000"},
        {"rcept_no": "R1", "sj_div": "IS", "account_id": "ifrs-full_ProfitLoss", "account_nm": "당기순이익", "account_detail": "-", "thstrm_amount": "200000000000"},
        {"rcept_no": "R1", "sj_div": "IS", "account_id": "ifrs-full_ProfitLossAttributableToOwnersOfParent", "account_nm": "지배기업의 소유주에게 귀속되는 당기순이익", "account_detail": "-", "thstrm_amount": "190000000000"},
    ]


def test_parse_corp_code_zip():
    df = dart.parse_corp_code_zip(_corp_zip())
    assert len(df) == 2
    assert df.loc[df.stock_code == "267260", "corp_code"].item() == "00000001"


def test_parse_corp_code_error_payload():
    with pytest.raises(dart.DartAPIError) as ei:
        dart.parse_corp_code_zip(b'{"status":"010","message":"unregistered key"}')
    assert ei.value.status == "010"


def test_extract_dart_metrics_units_and_debt(cfg):
    m, debt, flags = dart.extract_dart_metrics(_fn_rows(), cfg["data_fetch"]["dart"])
    assert m["revenue"] == pytest.approx(30000.0)          # 3조원 = 30,000억원
    assert m["operating_income"] == pytest.approx(3000.0)
    assert m["net_income"] == pytest.approx(1900.0)        # 지배주주 귀속 우선
    assert m["cash"] == pytest.approx(500.0)
    assert m["total_debt"] == pytest.approx(300.0)         # 단기차입금 100 + 사채 200 (할인차금·리스·세부행 제외)
    assert {d["account_nm"] for d in debt} == {"단기차입금", "사채"}
    assert flags == []


def test_extract_dart_net_income_fallback_flag(cfg):
    rows = [r for r in _fn_rows() if "Owners" not in r["account_id"]]
    m, _, flags = dart.extract_dart_metrics(rows, cfg["data_fetch"]["dart"])
    assert m["net_income"] == pytest.approx(2000.0)
    assert any(f.startswith("net_income:fallback") for f in flags)


def test_dart_financials_cfs_then_ofs(cfg, monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "DKEY_0001")

    def handler(url, params, headers):
        if params["fs_div"] == "CFS":
            return FakeResp(200, {"status": "013", "message": "조회된 데이타가 없습니다."})
        return FakeResp(200, {"status": "000", "message": "정상", "list": _fn_rows()})

    http, sess, _ = make_http(handler)
    c = dart.DartClient(cfg, "2026-10-20", http=http)
    rows, fs_div = c.fetch_financials("00000001", 2025, "267260")
    assert fs_div == "OFS" and len(rows) == len(_fn_rows())
    assert [call["params"]["fs_div"] for call in sess.calls] == ["CFS", "OFS"]
    assert sess.calls[0]["params"]["reprt_code"] == "11011"
    meta = json.loads((Path(cfg["paths"]["raw"]) / "dart" / "fnltt_267260_2025_OFS.meta.json").read_text(encoding="utf-8"))
    assert "crtfc_key" not in meta["params"] and meta["as_of"] == "2026-10-20"


def test_dart_api_error_raises(cfg, monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "DKEY_0001")
    http, _, _ = make_http(lambda *a: FakeResp(200, {"status": "020", "message": "요청 제한 초과"}))
    c = dart.DartClient(cfg, "2026-10-20", http=http)
    with pytest.raises(dart.DartAPIError, match="020"):
        c.fetch_financials("00000001", 2025)


def test_date_windows_max_90_days():
    w = dart.date_windows(date(2025, 1, 1), date(2025, 12, 31), 90)
    assert w[0] == (date(2025, 1, 1), date(2025, 3, 31))
    assert w[-1][1] == date(2025, 12, 31)
    assert all((e - s).days < 90 for s, e in w)


def test_dart_search_filings_pagination_and_filter(cfg, monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "DKEY_0001")

    def handler(url, params, headers):
        assert params["pblntf_ty"] == "C"
        page = params["page_no"]
        rows = [{"rcept_no": f"{params['bgn_de']}-{page}", "report_nm": "증권신고서(지분증권)", "corp_name": "A"},
                {"rcept_no": f"{params['bgn_de']}-{page}x", "report_nm": "투자설명서", "corp_name": "B"}]
        return FakeResp(200, {"status": "000", "total_page": 2, "page_no": page, "list": rows})

    http, sess, _ = make_http(handler)
    c = dart.DartClient(cfg, "2026-10-20", http=http)
    df = c.search_filings("20250101", "20250331")             # 90일 → 1구간, 2페이지
    assert len(sess.calls) == 2
    assert list(df["report_nm"].unique()) == ["증권신고서(지분증권)"] and len(df) == 2


def test_dart_document_zip_and_error(cfg, monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "DKEY_0001")
    ok_zip = _corp_zip()
    http, _, _ = make_http(lambda u, p, h: FakeResp(200, ok_zip if p["rcept_no"] == "1" else
                                                    b"<result><status>014</status><message>file none</message></result>"))
    c = dart.DartClient(cfg, "2026-10-20", http=http)
    path = c.download_document("1")
    assert path.exists() and path.with_name("1.meta.json").exists()
    with pytest.raises(dart.DartAPIError, match="014"):
        c.download_document("2")


def test_dart_run_end_to_end(cfg, monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "DKEY_0001")
    cfg["peers"]["domestic"] = cfg["peers"]["domestic"][:1]
    cfg["data_fetch"]["fiscal_years"] = [2025]
    cfg["data_fetch"]["dart"]["ipo_search"]["bgn_de"] = "20261001"

    def handler(url, params, headers):
        if url.endswith("corpCode.xml"):
            return FakeResp(200, _corp_zip())
        if url.endswith("fnlttSinglAcntAll.json"):
            return FakeResp(200, {"status": "000", "list": _fn_rows()})
        if url.endswith("list.json"):
            return FakeResp(200, {"status": "013", "message": "no data"})
        raise AssertionError(url)

    http, _, _ = make_http(handler)
    res = dart.run(cfg, "2026-10-20", client=dart.DartClient(cfg, "2026-10-20", http=http))
    assert res.status == base.STATUS_SUCCESS and res.n_items == 1
    df = pd.read_csv(Path(cfg["paths"]["processed"]) / "dart_financials.csv", dtype={"ticker": str})
    assert df.loc[0, "ticker"] == "267260" and df.loc[0, "fiscal_year"] == "FY2025A"
    assert df.loc[0, "unit"] == "억원" and df.loc[0, "revenue"] == pytest.approx(30000.0)


# ---------------------------------------------------------------------------
# KRX
# ---------------------------------------------------------------------------
TRADE = [{"BAS_DD": "20261020", "ISU_CD": "267260", "ISU_NM": "HD현대일렉트릭", "TDD_CLSPRC": "400,000",
          "MKTCAP": "14418000000000", "LIST_SHRS": "36045000"},
         {"BAS_DD": "20261020", "ISU_CD": "005930", "ISU_NM": "삼성전자", "TDD_CLSPRC": "1", "MKTCAP": "1",
          "LIST_SHRS": "1"}]
BASE_INFO = [{"ISU_CD": "KR7267260008", "ISU_SRT_CD": "267260", "ISU_ABBRV": "HD현대일렉트릭", "LIST_SHRS": "36045000"}]


def test_short_code_variants():
    assert krx.short_code("KR7267260008") == "267260"
    assert krx.short_code("A267260") == "267260"
    assert krx.short_code("10120") == "010120"


def test_select_peer_rows():
    out = krx.select_peer_rows(TRADE, BASE_INFO, ["267260"])
    assert set(out) == {"267260"}
    assert out["267260"]["close_krw"] == 400000 and out["267260"]["listed_shares"] == 36045000


def test_krx_auth_header_and_holiday_lookback(cfg, monkeypatch):
    monkeypatch.setenv("KRX_API_KEY", "KRXKEY_777")

    def handler(url, params, headers):
        assert headers.get("AUTH_KEY") == "KRXKEY_777"   # ASSUMPTION(verify) 헤더 방식
        if params["basDd"] == "20261020":
            return FakeResp(200, {"OutBlock_1": []})       # 휴장일 가정
        return FakeResp(200, {"OutBlock_1": TRADE if url.endswith("stk_bydd_trd") else BASE_INFO})

    http, _, _ = make_http(handler)
    c = krx.KrxOpenApiClient(cfg, "2026-10-20", http=http)
    bas_dd, trade, base_rows = c.fetch_latest(5)
    assert bas_dd == "20261019" and len(trade) == 2 and len(base_rows) == 1
    meta = json.loads((Path(cfg["paths"]["raw"]) / "krx" / "daily_trade_20261019.meta.json").read_text(encoding="utf-8"))
    assert "KRXKEY_777" not in json.dumps(meta)


def test_merge_provider_values_priority_and_compute():
    chain = [("KRX Open API", {}), ("FinanceDataReader", {"267260": {"close_krw": 100.0}}),
             ("pykrx", {"267260": {"close_krw": 999.0, "listed_shares": 10.0}})]
    m = krx.merge_provider_values(chain, ["267260"])["267260"]
    assert m["close_krw"] == 100.0 and m["source_close_krw"] == "FinanceDataReader"
    assert m["listed_shares"] == 10.0 and m["source_listed_shares"] == "pykrx"
    assert m["market_cap_krw"] == 1000.0 and m["source_market_cap_krw"].startswith("computed")


def test_krx_run_without_key_uses_fallbacks(cfg):
    tickers = [str(p["ticker"]).zfill(6) for p in cfg["peers"]["domestic"]]
    providers = {
        "fdr": lambda t, a, lb: {x: {"close_krw": 1000.0} for x in t},
        "pykrx": lambda t, a, lb: {x: {"close_krw": 1001.0, "market_cap_krw": 5e11, "listed_shares": 5e8} for x in t},
    }
    res = krx.run(cfg, "2026-10-20", providers=providers)          # KRX_API_KEY 없음
    assert res.status == base.STATUS_PARTIAL and "건너뜀" in res.message
    df = pd.read_csv(Path(cfg["paths"]["processed"]) / "krx_peers_market.csv", dtype={"ticker": str})
    assert list(df["ticker"]) == tickers
    assert (df["source_close_krw"] == "FinanceDataReader").all() and (df["source_listed_shares"] == "pykrx").all()
    assert df["cross_check_required"].all()
    assert df["market_cap_krw_100m"].iloc[0] == pytest.approx(5000.0)


def test_krx_run_fallback_failure_does_not_crash(cfg):
    def boom(*a):
        raise ImportError("no module")
    res = krx.run(cfg, "2026-10-20", providers={"fdr": boom, "pykrx": boom})
    assert res.status == base.STATUS_FAILED and "FinanceDataReader 실패" in res.message


def test_krx_run_success_with_crosscheck(cfg, monkeypatch):
    monkeypatch.setenv("KRX_API_KEY", "KRXKEY_777")
    peers = cfg["peers"]["domestic"]
    trade = [{"ISU_CD": str(p["ticker"]).zfill(6), "TDD_CLSPRC": "1000", "MKTCAP": "100000000000",
              "LIST_SHRS": "100000000"} for p in peers]
    http, _, _ = make_http(lambda u, p, h: FakeResp(200, {"OutBlock_1": trade if u.endswith("trd") else []}))
    client = krx.KrxOpenApiClient(cfg, "2026-10-20", http=http)
    res = krx.run(cfg, "2026-10-20", client=client,
                  providers={"fdr": lambda t, a, lb: {x: {"close_krw": 1020.0} for x in t}})
    assert res.status == base.STATUS_SUCCESS and res.n_items == len(peers)
    report = Path(cfg["data_fetch"]["output"]["crosscheck_report_krx"]).read_text(encoding="utf-8")
    assert "CHECK" in report                      # 2% 차이 > 허용오차 0.5%


# ---------------------------------------------------------------------------
# ECOS
# ---------------------------------------------------------------------------
def _ecos_payload(item_name, values):
    rows = [{"ITEM_NAME1": item_name, "TIME": t, "DATA_VALUE": v} for t, v in values]
    return {"StatisticSearch": {"list_total_count": len(rows), "row": rows}}


def test_ecos_parse_and_no_data():
    assert ecos.parse_ecos_rows({"RESULT": {"CODE": "INFO-200", "MESSAGE": "없음"}}) == []
    with pytest.raises(FetchError):
        ecos.parse_ecos_rows({"RESULT": {"CODE": "INFO-100", "MESSAGE": "인증키 오류"}})


def test_ecos_verify_item_name():
    rows = _ecos_payload("국고채(3년)", [("20250102", "2.6")])["StatisticSearch"]["row"]
    assert ecos.verify_item_name(rows, "3년") is None
    assert "불일치" in ecos.verify_item_name(rows, "10년")


def test_annual_fx_summary():
    s = ecos.rows_to_series([{"TIME": "20241230", "DATA_VALUE": "1470.0"}, {"TIME": "20250102", "DATA_VALUE": "1400"},
                             {"TIME": "20250103", "DATA_VALUE": "1,500"}, {"TIME": "20251230", "DATA_VALUE": "1450"}])
    a = ecos.annual_fx_summary(s).set_index("year")
    assert a.loc[2025, "usdkrw_avg"] == pytest.approx(1450.0)
    assert a.loc[2025, "usdkrw_year_end"] == 1450.0 and a.loc[2025, "year_end_date"] == "2025-12-30"
    assert a.loc[2024, "n_obs"] == 1


def test_ecos_run_key_in_path_masked(cfg, monkeypatch):
    monkeypatch.setenv("ECOS_API_KEY", "ECOSKEY_999")
    names = {"0000001": "원/미국달러(매매기준율)", "010200000": "국고채(3년)", "010210000": "국고채(10년)"}

    def handler(url, params, headers):
        assert "/StatisticSearch/ECOSKEY_999/json/kr/1/10000/" in url
        item = url.rsplit("/", 1)[-1]
        return FakeResp(200, _ecos_payload(names[item], [("20251230", "1450"), ("20261020", "1400")]))

    http, _, _ = make_http(handler)
    res = ecos.run(cfg, "2026-10-20", client=ecos.EcosClient(cfg, "2026-10-20", http=http))
    assert res.status == base.STATUS_SUCCESS, res.message
    raw = Path(cfg["paths"]["raw"]) / "ecos"
    for f in raw.glob("*.json"):
        assert "ECOSKEY_999" not in f.read_text(encoding="utf-8")
    meta = json.loads((raw / "usdkrw_daily.meta.json").read_text(encoding="utf-8"))
    assert "/StatisticSearch/***/json/" in meta["endpoint"]   # 키 자리 마스킹
    ktb = pd.read_csv(Path(cfg["paths"]["processed"]) / "ecos_ktb_daily.csv")
    assert list(ktb.columns) == ["date", "ktb_3y", "ktb_10y"]


# ---------------------------------------------------------------------------
# SEC
# ---------------------------------------------------------------------------
def _fact(val, end, start=None, form="10-K", filed="2026-02-15", accn="A1"):
    e = {"val": val, "end": end, "form": form, "filed": filed, "accn": accn, "fy": 2025, "fp": "FY"}
    if start:
        e["start"] = start
    return e


FACTS = {"entityName": "Vertiv Holdings Co", "facts": {
    "us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            _fact(8_000_000_000, "2024-12-31", "2024-01-01", filed="2025-02-20"),
            _fact(8_010_000_000, "2024-12-31", "2024-01-01", filed="2026-02-15"),   # 재작성(최신 filed)
            _fact(2_000_000_000, "2025-03-31", "2025-01-01", form="10-Q"),           # 분기 제외
            _fact(6_000_000_000, "2025-09-30", "2025-01-01", form="10-K"),           # 9개월 누적 제외
            _fact(10_000_000_000, "2025-12-31", "2025-01-01"),
        ]}},
        "OperatingIncomeLoss": {"units": {"USD": [_fact(1_500_000_000, "2025-12-31", "2025-01-01")]}},
        "NetIncomeLoss": {"units": {"USD": [_fact(1_000_000_000, "2025-12-31", "2025-01-01")]}},
        "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [_fact(900_000_000, "2025-12-31")]}},
        "LongTermDebtNoncurrent": {"units": {"USD": [_fact(2_900_000_000, "2025-12-31")]}},
        "LongTermDebtCurrent": {"units": {"USD": [_fact(100_000_000, "2025-12-31")]}},
        "CommercialPaper": {"units": {"USD": [_fact(50_000_000, "2025-12-31")]}},
    },
    "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"val": 380_000_000, "end": "2025-10-20", "filed": "2025-10-25", "accn": "Q3"},
        {"val": 381_000_000, "end": "2026-01-31", "filed": "2026-02-15", "accn": "K"}]}}},
}}


def test_parse_company_tickers():
    df = sec.parse_company_tickers({"0": {"cik_str": 1674101, "ticker": "vrt", "title": "Vertiv Holdings Co"}})
    assert df.loc[0, "ticker"] == "VRT" and sec.cik10(df.loc[0, "cik"]) == "0001674101"


def test_sec_annual_values_dedupe_and_duration(cfg):
    scfg = cfg["data_fetch"]["sec"]
    v = sec.annual_values(FACTS, "RevenueFromContractWithCustomerExcludingAssessedTax", kind="flow",
                          forms=scfg["forms"], duration_days=(350, 380), cutoff_month=6)
    assert set(v) == {2024, 2025}
    assert v[2024]["val"] == 8_010_000_000 and v[2025]["val"] == 10_000_000_000


def test_sec_extract_financials_usd_mn_and_debt(cfg):
    rows, detail = sec.extract_company_financials(FACTS, cfg["data_fetch"]["sec"], [2024, 2025])
    r25 = next(r for r in rows if r["fiscal_year"] == "FY2025A")
    assert r25["revenue"] == pytest.approx(10_000.0) and r25["operating_income"] == pytest.approx(1_500.0)
    assert r25["net_income"] == pytest.approx(1_000.0) and r25["cash"] == pytest.approx(900.0)
    assert r25["total_debt"] == pytest.approx(3_050.0)   # 2,900 + 100 + CP 50
    assert {d["tag"] for d in detail} == {"LongTermDebtNoncurrent", "LongTermDebtCurrent", "CommercialPaper"}
    r24 = next(r for r in rows if r["fiscal_year"] == "FY2024A")
    assert "operating_income:missing" in r24["flags"] and "total_debt:missing" in r24["flags"]


def test_fiscal_year_label_cutoff():
    assert sec.fiscal_year_label("2025-12-31") == 2025
    assert sec.fiscal_year_label("2025-01-31") == 2024


def test_sec_latest_shares():
    assert sec.latest_shares_outstanding(FACTS)["shares"] == 381_000_000


def test_sec_skip_without_user_agent(cfg):
    with pytest.raises(SkipSource, match="SEC_USER_AGENT"):
        sec.SecClient(cfg, "2026-10-20")


def test_sec_run_sends_user_agent_and_skips_schneider(cfg, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    tickers = {str(i): {"cik_str": 1000 + i, "ticker": p["ticker"], "title": p["name"]}
               for i, p in enumerate(cfg["peers"]["overseas"]) if p["ticker"] != "SU.PA"}

    def handler(url, params, headers):
        assert headers["User-Agent"] == "Test User test@example.com"
        return FakeResp(200, tickers if url.endswith("company_tickers.json") else FACTS)

    http, sess, _ = make_http(handler)
    res = sec.run(cfg, "2026-10-20", client=sec.SecClient(cfg, "2026-10-20", http=http))
    assert res.status == base.STATUS_SUCCESS and res.n_items == 5
    assert "SEC 공시 대상 아님" in res.message
    assert not any("SU.PA" in c["url"] for c in sess.calls)


# ---------------------------------------------------------------------------
# FRED / EIA
# ---------------------------------------------------------------------------
def test_fred_parse_missing_dot():
    s = fred.parse_observations({"observations": [{"date": "2026-10-19", "value": "4.1"},
                                                  {"date": "2026-10-20", "value": "."}]})
    assert s.iloc[0] == 4.1 and pd.isna(s.iloc[1])


def test_fred_run(cfg, monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "FREDKEY_1234")

    def handler(url, params, headers):
        assert params["api_key"] == "FREDKEY_1234" and params["observation_end"] == "2026-10-20"
        return FakeResp(200, {"observations": [{"date": "2026-10-20", "value": "1"}]})

    http, _, _ = make_http(handler)
    res = fred.run(cfg, "2026-10-20", client=fred.FredClient(cfg, "2026-10-20", http=http))
    assert res.status == base.STATUS_SUCCESS
    df = pd.read_csv(Path(cfg["paths"]["processed"]) / "fred_series.csv")
    assert list(df.columns) == ["date", "DGS10", "DEXKOUS"]
    meta = (Path(cfg["paths"]["raw"]) / "fred" / "DGS10.meta.json").read_text(encoding="utf-8")
    assert "FREDKEY_1234" not in meta


def test_eia_params_and_pagination(cfg, monkeypatch):
    monkeypatch.setenv("EIA_API_KEY", "EIAKEY_5678")
    cfg["data_fetch"]["eia"]["page_length"] = 2
    data = [{"period": "2024", "sectorid": s, "sales": "100", "price": "12.5", "sales-units": "million kilowatt hours"}
            for s in ["ALL", "RES", "COM"]]

    def handler(url, params, headers):
        p = dict(params)
        assert ("facets[sectorid][]", "RES") in params and p["frequency"] == "annual"
        off = int(p["offset"])
        return FakeResp(200, {"response": {"total": "3", "data": data[off:off + 2]}})

    http, sess, _ = make_http(handler)
    res = eia.run(cfg, "2026-10-20", client=eia.EiaClient(cfg, "2026-10-20", http=http))
    assert len(sess.calls) == 2 and res.n_items == 3
    df = pd.read_csv(Path(cfg["paths"]["processed"]) / "eia_retail_sales_annual.csv")
    assert (df["source"] == "U.S. Energy Information Administration (EIA)").all()
    assert df["price"].dtype.kind == "f"


# ---------------------------------------------------------------------------
# market_global (yfinance mock)
# ---------------------------------------------------------------------------
class FakeTicker:
    def __init__(self, symbol):
        idx = pd.to_datetime(["2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21"]).tz_localize("America/New_York")
        self._hist = pd.DataFrame({"Close": [10.0, 11.0, 12.0, 99.0]}, index=idx)
        self.fast_info = {"shares": 100_000_000, "currency": "EUR" if symbol == "SU.PA" else "USD",
                          "market_cap": 1.3e9}

    def history(self, start, end, auto_adjust=False):
        return self._hist


def test_fetch_quote_uses_close_on_or_before_asof():
    q = market_global.fetch_quote("VRT", "2026-10-20", 10, FakeTicker)
    assert q["close"] == 12.0 and q["price_date"] == "2026-10-20"
    assert q["market_cap_asof"] == pytest.approx(1.2e9)


def test_global_run_flags_and_crosscheck(cfg):
    proc = Path(cfg["paths"]["processed"])
    proc.mkdir(parents=True)
    pd.DataFrame([{"ticker": "VRT", "shares": 100_500_000, "end": "2026-01-31"},
                  {"ticker": "ETN", "shares": 150_000_000, "end": "2026-01-31"}]).to_csv(
        proc / "sec_shares_outstanding.csv", index=False)
    res = market_global.run(cfg, "2026-10-20", ticker_factory=FakeTicker)
    assert res.status == base.STATUS_SUCCESS
    df = pd.read_csv(proc / "global_peers_market.csv")
    assert df["cross_check_required"].all() and (df["source_priority"] == 3).all()
    report = Path(cfg["data_fetch"]["output"]["crosscheck_report_global"]).read_text(encoding="utf-8")
    assert "| Vertiv | VRT |" in report and "OK" in report and "CHECK" in report


# ---------------------------------------------------------------------------
# validate_peers
# ---------------------------------------------------------------------------
def test_names_match():
    assert validate_peers.names_match("Vertiv", "Vertiv Holdings Co")
    assert validate_peers.names_match("GE Vernova", "GE Vernova Inc.")
    assert validate_peers.names_match("HD현대일렉트릭", "(주)HD현대일렉트릭")
    assert not validate_peers.names_match("Eaton", "Vistra Corp.")


def test_validate_peers_report(cfg):
    raw = Path(cfg["paths"]["raw"])
    (raw / "dart").mkdir(parents=True)
    (raw / "sec").mkdir(parents=True)
    corp = pd.DataFrame([
        {"corp_code": "00000001", "corp_name": "HD현대일렉트릭", "corp_eng_name": "", "stock_code": "267260", "modify_date": "1"},
        {"corp_code": "00000002", "corp_name": "엘에스일렉트릭", "corp_eng_name": "LS ELECTRIC Co., Ltd.", "stock_code": "010120", "modify_date": "1"},
        {"corp_code": "00000003", "corp_name": "다른회사", "corp_eng_name": "", "stock_code": "298040", "modify_date": "1"},
    ])
    corp.to_csv(raw / "dart" / "corp_codes_listed.csv", index=False)
    (raw / "sec" / "company_tickers.json").write_text(json.dumps({
        "0": {"cik_str": 1674101, "ticker": "VRT", "title": "Vertiv Holdings Co"},
        "1": {"cik_str": 1551182, "ticker": "ETN", "title": "Eaton Corp plc"},
    }), encoding="utf-8")
    res = validate_peers.run(cfg, "2026-10-20")
    text = Path(res.outputs[0]).read_text(encoding="utf-8")
    assert res.status == base.STATUS_PARTIAL
    assert "corp_code 00000001" in text and "CIK 0001674101" in text
    assert "LS ELECTRIC" in text and "| 국내 | LS ELECTRIC | 010120 | KOSPI | corp_code 00000002 | 엘에스일렉트릭 | OK |" in text
    assert "| 국내 | 효성중공업 | 298040 | KOSPI | corp_code 00000003 | 다른회사 | WARN |" in text
    assert "034020" in text and "FAIL" in text                 # DART 매핑 없음
    assert "N/A (SEC 비대상)" in text and "Schneider Electric" in text


# ---------------------------------------------------------------------------
# consolidate
# ---------------------------------------------------------------------------
def test_fx_conversion_helpers():
    assert consolidate.usd_mn_to_krw_100m(1.0, 1400.0) == pytest.approx(14.0)     # 1 USD mn = 14억원
    assert consolidate.krw_100m_to_usd_mn(14.0, 1400.0) == pytest.approx(1.0)


def test_consolidate_normalizes_units_and_fx():
    dart_df = pd.DataFrame([{"company": "K", "ticker": "267260", "fiscal_year": "FY2025A", "fs_div": "CFS",
                             "currency": "KRW", "unit": "억원", "revenue": 14000.0, "operating_income": 1400.0,
                             "net_income": 700.0, "total_debt": 1450.0, "cash": 290.0, "flags": ""}])
    sec_df = pd.DataFrame([{"company": "U", "ticker": "VRT", "fiscal_year": "FY2025A", "basis": "US GAAP",
                            "fiscal_year_end": "2025-12-31", "currency": "USD", "unit": "mn", "revenue": 10.0,
                            "operating_income": 1.0, "net_income": 1.0, "total_debt": 2.0, "cash": 1.0, "flags": ""}])
    manual = pd.DataFrame([{"company": "S", "ticker": "SU.PA", "region": "EU", "basis": "IFRS", "fiscal_year": "FY2025A",
                            "currency": "EUR", "unit": "mn", "revenue": None, "operating_income": None,
                            "net_income": None, "total_debt": None, "cash": None, "source": "URD"}])
    fx = pd.DataFrame([{"fiscal_year": "FY2025", "usdkrw_avg": 1400.0, "usdkrw_year_end": 1450.0}])
    out = consolidate.consolidate(dart_df, sec_df, manual, fx)
    assert list(out.columns) == consolidate.COLUMNS
    df = out.set_index("ticker")
    assert df.loc["267260", "revenue_usd_mn"] == pytest.approx(1000.0)        # 14,000억원 / 1,400
    assert df.loc["267260", "total_debt_usd_mn"] == pytest.approx(100.0)      # 연말 환율 1,450 적용
    assert df.loc["267260", "net_debt"] == pytest.approx(1160.0)
    assert df.loc["VRT", "revenue_krw_100m"] == pytest.approx(140.0)          # 10 USD mn × 1,400 / 100
    assert df.loc["VRT", "cash_krw_100m"] == pytest.approx(14.5)
    assert "TODO(data)" in df.loc["SU.PA", "flags"] and pd.isna(df.loc["SU.PA", "revenue_usd_mn"])


# ---------------------------------------------------------------------------
# fetch_all
# ---------------------------------------------------------------------------
def test_parse_args_multiple_sources():
    a = fetch_all.parse_args(["--source", "dart", "sec", "--asof", "2026-10-20"])
    assert a.source == ["dart", "sec"] and a.asof == "2026-10-20"
    with pytest.raises(SystemExit):
        fetch_all.parse_args(["--source", "bloomberg"])
    with pytest.raises(ValueError):
        fetch_all.parse_args(["--asof", "2026/10/20"])


def test_fetch_all_skips_missing_keys_and_continues(cfg, monkeypatch, capsys):
    monkeypatch.setattr(fetch_all, "load_config", lambda path=None: cfg)
    monkeypatch.setitem(fetch_all.SOURCES, "global", lambda c, a, **kw: base.FetchResult("global", "SUCCESS", 3))
    monkeypatch.setitem(fetch_all.SOURCES, "krx", lambda c, a, **kw: base.FetchResult("krx", "PARTIAL", 4))
    rc = fetch_all.main(["--source", "all", "--asof", "2026-10-20"])
    out = capsys.readouterr().out
    for s in ["dart", "ecos", "sec", "fred", "eia"]:
        assert any(line.startswith(s) and "SKIPPED" in line for line in out.splitlines()), s
    assert "validate" in out and "consolidate" in out
    summary = Path(cfg["data_fetch"]["output"]["summary_report"]).read_text(encoding="utf-8")
    assert "| dart | SKIPPED |" in summary
    assert rc == 1   # validate/consolidate는 입력 파일이 없어 FAILED → 종료코드 1


def test_run_one_masks_exception_message(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "LEAKYKEY_42")
    base.get_secret("FRED_API_KEY")

    def bad(cfg, as_of, **kw):
        raise RuntimeError("failed url ...?api_key=LEAKYKEY_42")

    res = fetch_all.run_one("fred", bad, {}, "2026-10-20", True)
    assert res.status == base.STATUS_FAILED and "LEAKYKEY_42" not in res.message


def test_modules_do_not_import_optional_libs_at_import_time():
    for mod in ("FinanceDataReader", "pykrx", "yfinance"):
        assert mod not in sys.modules or isinstance(sys.modules[mod], types.ModuleType)
