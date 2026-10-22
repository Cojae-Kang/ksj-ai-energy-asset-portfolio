"""데이터 수집 파이프라인 단위테스트 — 네트워크 없이 실행 (모든 응답은 mock)."""
from __future__ import annotations

import copy
import io
import json
import logging
import sys
import types
import warnings
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import requests

from src.data_fetch import (base, consolidate, dart, ecos, eia, fetch_all, fred, krx, market_global, sec,
                            validate_peers)
from src.data_fetch.base import FetchError, HttpClient, RequestTimeout, SkipSource


# ---------------------------------------------------------------------------
# 공통 fixture / fake
# ---------------------------------------------------------------------------
class FakeResp:
    """stream=True 응답 흉내. chunks/on_chunk로 '느리게 흘러오는 응답'을 재현할 수 있다."""

    def __init__(self, status=200, body=b"", url="https://example.test", chunks=None, on_chunk=None):
        self.status_code = status
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.content = body
        self.text = body.decode("utf-8", errors="replace")
        self.headers = {"Content-Type": "application/json"}
        self.url = url
        self._chunks = chunks if chunks is not None else [body]
        self._on_chunk = on_chunk
        self.closed = False

    def iter_content(self, chunk_size=1):
        for c in self._chunks:
            if self._on_chunk:
                self._on_chunk()
            yield c

    def close(self):
        self.closed = True


class FakeClock:
    """테스트용 시계: sleep하면 시간이 흐른다."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


class FakeSession:
    """handler(url, params, headers) → FakeResp 또는 Exception."""

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[dict] = []
        self.headers: dict = {}

    def get(self, url, params=None, headers=None, timeout=None, stream=False):
        merged = {**self.headers, **(headers or {})}   # requests처럼 세션 기본 헤더 + 요청 헤더
        self.calls.append({"url": url, "params": params, "headers": merged, "timeout": timeout,
                           "stream": stream})
        out = self.handler(url, params, merged)
        if isinstance(out, Exception):
            raise out
        return out


def make_http(handler, source="test", **kw):
    sleeps: list[float] = []
    sess = FakeSession(handler)
    client = HttpClient(source, {"connect_timeout_sec": 5, "read_timeout_sec": 20, "max_retries": 3,
                                 "backoff_base_sec": 1.0, "max_total_wait_sec": 60, "cache_ttl_hours": 0},
                        session=sess, sleep=sleeps.append, **kw)
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
    for k in ["summary_report", "peer_validation_report", "crosscheck_report_krx", "crosscheck_report_global",
              "vol03_data_notes"]:
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
    assert all(c["timeout"] == (5, 20) and c["stream"] for c in sess.calls)  # (연결, 응답) 타임아웃


def test_retry_gives_up_after_three_retries():
    client, sess, sleeps = make_http(lambda *a: FakeResp(500))
    with pytest.raises(FetchError, match="재시도 후 실패") as ei:
        client.get("https://h/x?api_key=SHOULDMASK")
    assert len(sess.calls) == 4 and sleeps == [1.0, 2.0, 4.0]


    assert not isinstance(ei.value, RequestTimeout)      # 5xx는 타임아웃이 아님


def test_config_http_timeouts_are_5_and_20():
    h = base.load_config()["data_fetch"]["http"]
    assert (h["connect_timeout_sec"], h["read_timeout_sec"]) == (5, 20)
    assert h["max_retries"] == 3 and h["max_total_wait_sec"] == 60
    client = base.make_client("t", base.load_config(), {}, session=FakeSession(lambda *a: FakeResp()))
    assert (client.connect_timeout, client.read_timeout, client.max_total_wait) == (5.0, 20.0, 60.0)


def test_slow_trickle_body_hits_wall_clock_deadline_and_total_cap():
    """서버가 조금씩 보내 소켓 read timeout이 안 걸리는 상황(이번 DART 무한대기) 재현."""
    clk = FakeClock()

    def tick():
        clk.now += 8.0                                     # 청크마다 8초 → 3청크 = 24초 > 20초

    sess = FakeSession(lambda *a: FakeResp(200, chunks=[b"{", b'"a"', b":1}"], on_chunk=tick))
    client = HttpClient("dart", {"connect_timeout_sec": 5, "read_timeout_sec": 20, "max_retries": 3,
                                 "backoff_base_sec": 1.0, "max_total_wait_sec": 60, "cache_ttl_hours": 0},
                        session=sess, sleep=clk.sleep, clock=clk)
    with pytest.raises(RequestTimeout, match="타임아웃") as ei:
        client.get("https://opendart.fss.or.kr/api/list.json", params={"crtfc_key": "SECRET_KEY_1"})
    assert "SECRET_KEY_1" not in str(ei.value)
    assert len(sess.calls) == 3                            # 4번째 시도 전에 총 60초 상한 도달
    assert sess.calls[0]["timeout"] == (5, 20)
    assert sess.calls[2]["timeout"] == (5, pytest.approx(9.0))   # 남은 예산만큼만 대기
    assert clk.now < 60 + 20                               # 무한대기 없음


def test_requests_timeout_is_retried_then_request_timeout():
    clk = FakeClock()
    sess = FakeSession(lambda *a: requests.ReadTimeout("Read timed out. (read timeout=20)"))
    client = HttpClient("t", {"max_retries": 3, "backoff_base_sec": 1.0, "max_total_wait_sec": 60,
                              "cache_ttl_hours": 0}, session=sess, sleep=clk.sleep, clock=clk)
    with pytest.raises(RequestTimeout):
        client.get("https://h/x")
    assert len(sess.calls) == 4 and clk.sleeps == [1.0, 2.0, 4.0]


def test_progress_log_line_format(caplog):
    clk = FakeClock()
    prog = base.Progress("dart", "재무제표", 12, clock=clk)
    prog.i = 2
    with caplog.at_level(logging.INFO, logger="data_fetch.progress"):
        with prog.step("HD현대일렉트릭 FY2025") as st:
            clk.now += 1.234
            st["note"] = "(CFS)"
        with pytest.raises(RequestTimeout):
            with prog.step("LS ELECTRIC FY2025"):
                raise RequestTimeout("timed out")
    lines = [r.getMessage() for r in caplog.records]
    assert lines[0] == "[dart] 재무제표 3/12 HD현대일렉트릭 FY2025 ... 완료(1.2초) (CFS)"
    assert lines[1].startswith("[dart] 재무제표 4/12 LS ELECTRIC FY2025 ... 타임아웃→건너뜀(0.0초)")


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


def test_month_windows_three_months():
    w = dart.month_windows(date(2025, 1, 1), date(2026, 10, 20), 3)
    assert w[:2] == [(date(2025, 1, 1), date(2025, 3, 31)), (date(2025, 4, 1), date(2025, 6, 30))]
    assert w[-1] == (date(2026, 10, 1), date(2026, 10, 20))
    assert len(w) == 8
    assert dart.month_windows(date(2025, 11, 30), date(2026, 3, 31), 3)[0] == (date(2025, 11, 30), date(2026, 2, 27))


def _filings_handler(total_page=2, timeout_bgn=None):
    def handler(url, params, headers):
        assert params["pblntf_ty"] == "C" and params["page_count"] == 100
        if params["bgn_de"] == timeout_bgn:
            return requests.ReadTimeout("Read timed out.")
        page = params["page_no"]
        rows = [{"rcept_no": f"{params['bgn_de']}-{page}", "report_nm": "증권신고서(지분증권)", "corp_name": "A"},
                {"rcept_no": f"{params['bgn_de']}-{page}x", "report_nm": "투자설명서", "corp_name": "B"}]
        return FakeResp(200, {"status": "000", "total_page": total_page, "page_no": page, "list": rows})
    return handler


def test_dart_search_filings_splits_3_months_and_caps_pages(cfg, monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "DKEY_0001")
    cfg["data_fetch"]["dart"]["filings"]["max_pages"] = 2
    http, sess, _ = make_http(_filings_handler(total_page=10))
    c = dart.DartClient(cfg, "2026-10-20", http=http)
    df, notes = c.search_filings("20250101", "20250630")     # corp_code 없음 → 3개월 × 2구간
    assert {(x["params"]["bgn_de"], x["params"]["end_de"]) for x in sess.calls} == {
        ("20250101", "20250331"), ("20250401", "20250630")}
    assert all("corp_code" not in x["params"] for x in sess.calls)
    assert len(sess.calls) == 4                                 # 구간당 max_pages=2
    assert sum("max_pages=2에서 중단" in n for n in notes) == 2
    assert list(df["report_nm"].unique()) == ["증권신고서(지분증권)"] and len(df) == 4


def test_dart_search_filings_timeout_skips_window_and_continues(cfg, monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "DKEY_0001")
    http, sess, _ = make_http(_filings_handler(total_page=1, timeout_bgn="20250101"))
    c = dart.DartClient(cfg, "2026-10-20", http=http)
    df, notes = c.search_filings("20250101", "20250630")
    assert len(notes) == 1 and "20250101~20250331" in notes[0] and "건너뜀" in notes[0]
    assert "DKEY_0001" not in notes[0]
    assert list(df["rcept_no"]) == ["20250401-1"]               # 다음 구간은 정상 수집


def test_dart_search_filings_with_corp_code_single_window(cfg, monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "DKEY_0001")
    http, sess, _ = make_http(_filings_handler(total_page=1))
    c = dart.DartClient(cfg, "2026-10-20", http=http)
    c.search_filings("20250101", "20261020", corp_code="00000001")
    assert len(sess.calls) == 1 and sess.calls[0]["params"]["corp_code"] == "00000001"
    assert (sess.calls[0]["params"]["bgn_de"], sess.calls[0]["params"]["end_de"]) == ("20250101", "20261020")


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


def _dart_run_handler(calls):
    def handler(url, params, headers):
        calls.append(url.rsplit("/", 1)[-1])
        if url.endswith("corpCode.xml"):
            return FakeResp(200, _corp_zip())
        if url.endswith("fnlttSinglAcntAll.json"):
            if params["bsns_year"] == "2024":
                return requests.ReadTimeout("Read timed out.")   # 이 연도만 타임아웃
            return FakeResp(200, {"status": "000", "list": _fn_rows()})
        if url.endswith("list.json"):
            return FakeResp(200, {"status": "013", "message": "no data"})
        raise AssertionError(url)
    return handler


def test_dart_run_filings_off_by_default_and_timeout_skips_year(cfg, monkeypatch, caplog):
    monkeypatch.setenv("DART_API_KEY", "DKEY_0001")
    assert base.load_config()["data_fetch"]["dart"]["filings"]["enabled"] is False   # 기본값 OFF
    cfg["peers"]["domestic"] = cfg["peers"]["domestic"][:1]
    cfg["data_fetch"]["fiscal_years"] = [2024, 2025]
    calls: list[str] = []
    http, _, _ = make_http(_dart_run_handler(calls))
    with caplog.at_level(logging.INFO, logger="data_fetch.progress"):
        res = dart.run(cfg, "2026-10-20", client=dart.DartClient(cfg, "2026-10-20", http=http))
    assert "list.json" not in calls                                # 공시 검색 안 함
    assert res.status == base.STATUS_PARTIAL and res.n_items == 1  # 2024 타임아웃 → 건너뛰고 2025 수집
    assert "FY2024" in res.message and "타임아웃" in res.message
    msgs = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("[dart] 재무제표 1/2 HD현대일렉트릭 FY2024 ... 타임아웃→건너뜀") for m in msgs)
    assert any(m.startswith("[dart] 재무제표 2/2 HD현대일렉트릭 FY2025 ... 완료(") for m in msgs)
    df = pd.read_csv(Path(cfg["paths"]["processed"]) / "dart_financials.csv", dtype={"ticker": str})
    assert df.loc[0, "ticker"] == "267260" and df.loc[0, "fiscal_year"] == "FY2025A"
    assert df.loc[0, "unit"] == "억원" and df.loc[0, "revenue"] == pytest.approx(30000.0)


def test_dart_run_filings_peers_mode(cfg, monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "DKEY_0001")
    cfg["peers"]["domestic"] = cfg["peers"]["domestic"][:1]
    cfg["data_fetch"]["fiscal_years"] = [2025]
    f = cfg["data_fetch"]["dart"]["filings"]
    f.update(enabled=True, mode="peers", bgn_de="20250101")
    calls: list[str] = []
    http, sess, _ = make_http(_dart_run_handler(calls))
    res = dart.run(cfg, "2026-10-20", client=dart.DartClient(cfg, "2026-10-20", http=http))
    list_calls = [x for x in sess.calls if x["url"].endswith("list.json")]
    assert len(list_calls) == 1 and list_calls[0]["params"]["corp_code"] == "00000001"
    assert res.status == base.STATUS_SUCCESS
    assert any("filings_peers_20250101_20261020.csv" in o for o in res.outputs)


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


SEC_403_HTML = (b"<html><head><title>SEC.gov | Request Rate Threshold Exceeded</title></head><body>"
                + b"<h1>Request Rate Threshold Exceeded</h1>" + b"x" * 5000 + b"</body></html>")


@pytest.mark.parametrize("raw, expected", [
    ('"Shinjae Kang a.b+c@example.com"', "Shinjae Kang a.b+c@example.com"),
    ("'Shinjae Kang a@example.com'", "Shinjae Kang a@example.com"),
    ("\ufeff  \u201cShinjae   Kang\ta@example.com\u201d \n", "Shinjae Kang a@example.com"),
    ('Shinjae "Kang" a@example.com', "Shinjae Kang a@example.com"),
])
def test_normalize_user_agent(raw, expected):
    assert sec.normalize_user_agent(raw) == expected
    assert sec.user_agent_problems(expected) == []


def test_user_agent_problems_and_masking():
    assert any("이메일" in p for p in sec.user_agent_problems("Shinjae Kang"))
    assert any("헤더에 쓸 수 없는" in p for p in sec.user_agent_problems("강신재 a@example.com"))
    assert sec.mask_user_agent("Shinjae Kang abc+x@users.noreply.github.com") == "S*** K*** ab***@users.noreply.github.com"


def test_sec_client_quoted_env_and_invalid_env(cfg, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", '  "Test User   test@example.com"  ')
    http, _, _ = make_http(lambda *a: FakeResp(200, {}))
    c = sec.SecClient(cfg, "2026-10-20", http=http)
    assert c.user_agent == "Test User test@example.com"
    monkeypatch.setenv("SEC_USER_AGENT", "no-email-here")
    with pytest.raises(SkipSource, match="형식 오류"):
        sec.SecClient(cfg, "2026-10-20", http=http)


def test_sec_session_headers_on_both_hosts_and_rate_limit(cfg, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    cfg["data_fetch"]["sec"]["request_delay_sec"] = 0          # config가 0이어도 초당 10건 미만 보장
    clk = FakeClock()
    sess = FakeSession(lambda *a: FakeResp(200, {"facts": {}}))
    http = HttpClient("sec", {"cache_ttl_hours": 0}, session=sess, sleep=clk.sleep, clock=clk)
    c = sec.SecClient(cfg, "2026-10-20", http=http)
    assert sess.headers["User-Agent"] == "Test User test@example.com"         # 세션 기본 헤더
    assert sess.headers["Accept-Encoding"] == "gzip, deflate"
    for cik in (1, 2, 3):
        c.fetch_companyfacts(cik)
    c.http.get(cfg["data_fetch"]["sec"]["tickers_url"])                        # 요청 헤더 없이 호출해도
    hosts = {x["url"].split("/")[2] for x in sess.calls}
    assert hosts == {"data.sec.gov", "www.sec.gov"}
    assert all(x["headers"]["User-Agent"] == "Test User test@example.com" and
               x["headers"]["Accept-Encoding"] == "gzip, deflate" for x in sess.calls)
    assert c.http.request_delay == pytest.approx(1 / 8)
    assert (len(sess.calls) - 1) / clk.now == pytest.approx(8.0)              # 요청 간격 기준 8건/초 (< 10)


def test_sec_403_one_line_summary_and_stop(cfg, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    cfg["data_fetch"]["sec"]["offline"]["auto_on_403"] = False                  # 자동 오프라인 전환 끔
    http, sess, _ = make_http(lambda *a: FakeResp(403, SEC_403_HTML))
    c = sec.SecClient(cfg, "2026-10-20", http=http)
    res = sec.run(cfg, "2026-10-20", client=c)
    assert res.status == base.STATUS_FAILED
    assert res.message.startswith("SEC 403: User-Agent 확인 필요 (https://www.sec.gov/files/company_tickers.json)")
    assert "<" not in res.message and "\n" not in res.message and len(res.message) < 250
    assert "요청 속도 초과" in res.message                                         # 차단 페이지 판별
    assert len(sess.calls) == 1                                                # 403은 재시도 안 함


def test_sec_companyfacts_403_stops_remaining_requests(cfg, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    cfg["data_fetch"]["sec"]["offline"]["auto_on_403"] = False
    tickers = {str(i): {"cik_str": 1000 + i, "ticker": p["ticker"], "title": p["name"]}
               for i, p in enumerate(cfg["peers"]["overseas"]) if p["ticker"] != "SU.PA"}
    http, sess, _ = make_http(lambda u, p, h: FakeResp(200, tickers) if u.endswith("company_tickers.json")
                              else FakeResp(403, b"<html><body>Undeclared Automated Tool</body></html>"))
    res = sec.run(cfg, "2026-10-20", client=sec.SecClient(cfg, "2026-10-20", http=http))
    assert res.status == base.STATUS_FAILED
    assert len([x for x in sess.calls if "companyfacts" in x["url"]]) == 1    # 첫 403 후 중단
    assert "User-Agent 미선언" in res.message and "이후 companyfacts 요청 중단" in res.message


def test_http_status_error_summarizes_html():
    client, _, _ = make_http(lambda *a: FakeResp(404, b"<html><title>Not Found</title>" + b"y" * 9000))
    with pytest.raises(base.HttpStatusError) as ei:
        client.get("https://h/x")
    assert ei.value.status_code == 404 and "HTML 응답" in str(ei.value) and "yyyy" not in str(ei.value)


def test_fetch_all_records_sec_403_as_one_line(cfg, monkeypatch, capsys):
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    monkeypatch.setattr(fetch_all, "load_config", lambda path=None: cfg)
    http, _, _ = make_http(lambda *a: FakeResp(403, SEC_403_HTML))
    monkeypatch.setitem(fetch_all.SOURCES, "sec",
                        lambda c, a, **kw: sec.run(c, a, client=sec.SecClient(c, a, http=http)))
    fetch_all.main(["--source", "sec"])
    out = capsys.readouterr().out
    assert "SEC 403: User-Agent 확인 필요" in out and "<html" not in out.lower()
    assert "SKIPPED(sec unavailable) 5" in out                                 # validate는 FAIL이 아님


def test_sec_diagnose_masks_and_shows_effective_headers(cfg, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", '"Shinjae Kang abc+x@users.noreply.github.com"')
    lines: list[str] = []
    rc = sec.diagnose(cfg, out=lines.append, session=FakeSession(lambda *a: FakeResp(200, {})))
    text = "\n".join(lines)
    assert rc == 0
    assert "S*** K*** ab***@users.noreply.github.com" in text and "abc+x@" not in text
    assert "정리한 항목: 따옴표" in text
    assert "Host: www.sec.gov" in text and "Host: data.sec.gov" in text
    assert "Accept-Encoding: gzip, deflate" in text and "User-Agent: S*** K***" in text
    assert "noreply" in text and "실제 요청은 하지 않음" in text


def test_sec_diagnose_probe_403(cfg, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    lines: list[str] = []
    sess = FakeSession(lambda *a: FakeResp(403, SEC_403_HTML))
    rc = sec.diagnose(cfg, probe=True, out=lines.append, session=sess)
    text = "\n".join(lines)
    assert rc == 1 and len(sess.calls) == 1
    assert "SEC 403: User-Agent 확인 필요" in text and "VPN" in text
    assert sess.calls[0]["headers"]["User-Agent"] == "Test User test@example.com"


def test_sec_diagnose_missing_env(cfg):
    lines: list[str] = []
    assert sec.diagnose(cfg, out=lines.append) == 1
    assert any("미설정" in x for x in lines)


def test_sec_cli_requires_diagnose_flag(capsys):
    assert sec.main([]) == 0
    assert "fetch_all --source sec" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# SEC 오프라인 모드 (브라우저 다운로드 파일) · CIK 정규화 · 주체 검사
# ---------------------------------------------------------------------------
LISTED = {"VRT": (1674101, "Vertiv Holdings Co"), "ETN": (1551182, "Eaton Corp plc"),
          "GEV": (1996810, "GE Vernova Inc."), "CEG": (1868275, "Constellation Energy Corp"),
          "VST": (1692819, "Vistra Corp.")}


def _facts_for(ticker, cik_value, name=None, shares=True, eps=True):
    f = copy.deepcopy(FACTS)
    f["cik"] = cik_value
    f["entityName"] = name or LISTED[ticker][1]
    if not shares:
        f["facts"].pop("dei")
    if eps:
        f["facts"]["us-gaap"]["EarningsPerShareBasic"] = {"units": {"USD/shares": [
            _fact(2.5, "2025-12-31", "2025-01-01")]}}
    return f


def _write_manual(cfg, facts_by_cik: dict, tickers: dict | None = None, mtime: float = 1_760_000_000):
    d = Path(cfg["paths"]["raw"]) / "sec_manual"
    d.mkdir(parents=True, exist_ok=True)
    tickers = tickers or {str(i): {"cik_str": c, "ticker": t, "title": n} for i, (t, (c, n)) in enumerate(LISTED.items())}
    (d / "company_tickers.json").write_text(json.dumps(tickers), encoding="utf-8")
    for cik, facts in facts_by_cik.items():
        (d / f"CIK{sec.cik10(cik)}.json").write_text(json.dumps(facts), encoding="utf-8")
    import os
    for f in d.glob("*.json"):
        os.utime(f, (mtime, mtime))
    return d


def _all_manual(cfg, **override):
    """5사 companyfacts. cik 표기는 숫자·0 채운 문자열을 섞는다 (실제 파일과 같은 상황)."""
    facts = {}
    for i, (t, (c, _)) in enumerate(LISTED.items()):
        facts[c] = override.get(t) or _facts_for(t, c if i % 2 == 0 else sec.cik10(c))
    return _write_manual(cfg, facts)


@pytest.mark.parametrize("v, expected", [
    (1551182, 1551182), ("0001868275", 1868275), ("1868275", 1868275), ("CIK0001868275", 1868275),
    (1868275.0, 1868275), (" 0001692819 ", 1692819), (None, None), ("abc", None), (True, None), (1.5, None),
])
def test_normalize_cik_mixed_formats(v, expected):
    assert sec.normalize_cik(v) == expected


def test_cik10_accepts_both_formats():
    assert sec.cik10(1551182) == sec.cik10("0001551182") == "0001551182"
    with pytest.raises(ValueError):
        sec.cik10("not-a-cik")


def test_sec_offline_mode_reads_manual_files_without_user_agent(cfg):
    d = _all_manual(cfg)
    lines: list[str] = []
    res = sec.run(cfg, "2026-10-20", offline=True, out=lines.append)          # SEC_USER_AGENT 없어도 동작
    assert res.status == base.STATUS_SUCCESS and res.n_items == 5, res.message
    assert "오프라인 모드" in res.message and not lines
    proc = Path(cfg["paths"]["processed"])
    fin = pd.read_csv(proc / "sec_financials.csv", dtype={"cik": str})
    assert set(fin["data_source"]) == {"manual browser download"}
    assert set(fin["cik"]) == {sec.cik10(c) for c, _ in LISTED.values()}       # 숫자·문자열 cik 모두 정규화
    ent = pd.read_csv(proc / "sec_entity_check.csv", dtype=str)
    assert set(ent["verdict"]) == {"OK"}
    # meta: 출처 라벨 + 파일 수정 시각
    m = json.loads((d / "CIK0001674101.meta.json").read_text(encoding="utf-8"))
    assert m["source"] == "SEC EDGAR (manual browser download)"
    assert m["fetched_at"] == "2025-10-09T08:53:20+00:00"                      # mtime 1,760,000,000
    assert m["endpoint"].endswith("CIK0001674101.json") and m["params"] == {"cik": "0001674101"}
    assert set(m) >= set(base.META_FIELDS) and len(m["sha256"]) == 64
    copied = Path(cfg["paths"]["raw"]) / "sec" / "company_tickers.json"      # validate 입력 위치로 복사
    assert copied.exists() and json.loads(base.meta_path_for(copied).read_text(encoding="utf-8"))["source"] \
        == "SEC EDGAR (manual browser download)"
    pmeta = json.loads((proc / "sec_financials.meta.json").read_text(encoding="utf-8"))
    assert "manual browser download" in pmeta["source"]


def test_sec_offline_missing_files_prints_ciks_and_urls_then_skipped(cfg):
    lines: list[str] = []
    res = sec.run(cfg, "2026-10-20", offline=True, out=lines.append)
    text = "\n".join(lines)
    assert res.status == base.STATUS_SKIPPED
    assert "https://www.sec.gov/files/company_tickers.json" in text
    for t, (c, _) in LISTED.items():
        assert f"CIK {sec.cik10(c)}" in text
        assert f"https://data.sec.gov/api/xbrl/companyfacts/CIK{sec.cik10(c)}.json" in text
    assert "[없음]" in text and "오프라인 파일 없음" in res.message


def test_sec_offline_partial_lists_only_missing(cfg):
    facts = {c: _facts_for(t, c) for t, (c, _) in LISTED.items() if t != "GEV"}
    _write_manual(cfg, facts)
    lines: list[str] = []
    res = sec.run(cfg, "2026-10-20", offline=True, out=lines.append)
    assert res.status == base.STATUS_PARTIAL and res.n_items == 4
    assert "CIK0001996810.json" in res.message
    assert "[없음] GEV CIK 0001996810" in "\n".join(lines)


def test_sec_offline_broken_json_is_reported(cfg):
    d = _all_manual(cfg)
    (d / "CIK0001551182.json").write_text("<html>blocked</html>", encoding="utf-8")
    res = sec.run(cfg, "2026-10-20", offline=True, out=lambda s: None)
    assert res.status == base.STATUS_PARTIAL and "JSON 해석 실패" in res.message


def test_sec_403_auto_switches_to_offline(cfg, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    _all_manual(cfg)
    http, sess, _ = make_http(lambda *a: FakeResp(403, SEC_403_HTML))
    res = sec.run(cfg, "2026-10-20", client=sec.SecClient(cfg, "2026-10-20", http=http), out=lambda s: None)
    assert res.status == base.STATUS_SUCCESS and res.n_items == 5, res.message
    assert res.message.startswith("SEC 403: User-Agent 확인 필요") and "오프라인 모드 자동 전환" in res.message
    assert len(sess.calls) == 1                                                # 403 이후 네트워크 요청 없음


def test_sec_companyfacts_403_switches_to_offline_midway(cfg, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    _all_manual(cfg)
    tickers = {str(i): {"cik_str": c, "ticker": t, "title": n} for i, (t, (c, n)) in enumerate(LISTED.items())}
    http, sess, _ = make_http(lambda u, p, h: FakeResp(200, tickers) if u.endswith("company_tickers.json")
                              else FakeResp(403, b"<html><body>Undeclared Automated Tool</body></html>"))
    res = sec.run(cfg, "2026-10-20", client=sec.SecClient(cfg, "2026-10-20", http=http), out=lambda s: None)
    assert res.status == base.STATUS_SUCCESS and res.n_items == 5, res.message
    assert len([x for x in sess.calls if "companyfacts" in x["url"]]) == 1
    fin = pd.read_csv(Path(cfg["paths"]["processed"]) / "sec_financials.csv")
    assert set(fin["data_source"]) == {"manual browser download"}


def test_sec_persistent_403_hint_after_one_day(cfg, monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone
    state = tmp_path / "state.json"
    t0 = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
    assert sec.record_403(state, t0) == 0
    assert sec.persistent_403_note(sec.record_403(state, t0 + timedelta(hours=5)), 24) == ""
    h = sec.record_403(state, t0 + timedelta(hours=25))
    note = sec.persistent_403_note(h, 24)
    assert h == pytest.approx(25) and "네트워크·클라이언트 차단 가능성 → 브라우저 다운로드 후 오프라인 모드" in note
    sec.clear_403(state)
    assert not state.exists()
    # run 경로: 하루 뒤 다시 403 → 메시지에 안내
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    cfg["data_fetch"]["sec"]["offline"]["auto_on_403"] = False
    http, _, _ = make_http(lambda *a: FakeResp(403, SEC_403_HTML))
    c = sec.SecClient(cfg, "2026-10-20", http=http)
    assert "차단 가능성" not in sec.run(cfg, "2026-10-20", client=c, now=t0).message
    msg = sec.run(cfg, "2026-10-20", client=c, now=t0 + timedelta(hours=30)).message
    assert "403이 30시간째 지속 — 네트워크·클라이언트 차단 가능성 → 브라우저 다운로드 후 오프라인 모드" in msg


def test_sec_online_success_clears_403_state(cfg, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    state = Path(cfg["paths"]["raw"]) / "sec" / "_403_state.json"
    sec.record_403(state)
    tickers = {str(i): {"cik_str": c, "ticker": t, "title": n} for i, (t, (c, n)) in enumerate(LISTED.items())}
    http, _, _ = make_http(lambda u, p, h: FakeResp(200, tickers if u.endswith("company_tickers.json") else FACTS))
    sec.run(cfg, "2026-10-20", client=sec.SecClient(cfg, "2026-10-20", http=http))
    assert not state.exists()


def test_check_entity_same_likely_unknown_and_mismatch():
    c, title = LISTED["VST"]
    ok_ = sec.check_entity("VST", c, title, _facts_for("VST", "0001692819", "Vistra Corp."))
    assert ok_["verdict"] == "OK" and ok_["same_consolidated"] == "yes"
    likely = sec.check_entity("VST", c, title, _facts_for("VST", c, "Vistra Energy Corp."))
    assert likely["verdict"] == "WARN" and likely["same_consolidated"] == "likely"
    sub = sec.check_entity("VST", c, title, _facts_for("VST", "0001692819", "Vistra Operations Company LLC",
                                                       shares=False, eps=False))
    assert sub["verdict"] == "WARN" and sub["same_consolidated"] == "unknown"
    assert "Vistra Operations Company LLC" in sub["reason"] and "보통주 발행주식수(dei) 미보고" in sub["reason"]
    other = sec.check_entity("VST", c, title, _facts_for("VST", 1999999, "Vistra Operations Company LLC"))
    assert other["same_consolidated"] == "no" and "주체 불일치" in other["reason"]
    assert other["entity_cik"] == "0001999999" and other["listed_cik"] == "0001692819"


def test_offline_uses_user_file_when_tickers_cik_differs_and_flags_it(cfg):
    """company_tickers의 VST CIK가 사용자가 받은 파일(CIK0001692819)과 다르면 그 파일로 처리하고 주체 불일치 WARN."""
    tickers = {str(i): {"cik_str": (1999999 if t == "VST" else c), "ticker": t, "title": n}
               for i, (t, (c, n)) in enumerate(LISTED.items())}
    facts = {c: _facts_for(t, c, "Vistra Operations Company LLC" if t == "VST" else None, shares=t != "VST",
                           eps=t != "VST") for t, (c, _) in LISTED.items()}
    _write_manual(cfg, facts, tickers)
    res = sec.run(cfg, "2026-10-20", offline=True, out=lambda s: None)
    assert res.n_items == 5
    assert "expected_ciks 0001692819 ≠ company_tickers 0001999999" in res.message
    assert "Vistra: 주체 검사 WARN" in res.message
    ent = pd.read_csv(Path(cfg["paths"]["processed"]) / "sec_entity_check.csv", dtype=str).set_index("ticker")
    assert ent.loc["VST", "same_consolidated"] == "no" and ent.loc["VRT", "verdict"] == "OK"


def test_validate_marks_entity_warn_and_writes_vol03_notes(cfg):
    cfg["data_fetch"]["sec"]["entity_check"]["manual_overrides"] = {}               # 자동 판정만
    facts = {c: _facts_for(t, c, "Vistra Operations Company LLC" if t == "VST" else None, shares=t != "VST",
                           eps=t != "VST") for t, (c, _) in LISTED.items()}
    _write_manual(cfg, facts)
    sec.run(cfg, "2026-10-20", offline=True, out=lambda s: None)
    res = validate_peers.run(cfg, "2026-10-20")
    report = Path(res.outputs[0]).read_text(encoding="utf-8")
    assert "| 해외 | Vistra | VST | NYSE | CIK 0001692819 | Vistra Corp. | WARN | 재무 주체 확인 필요:" in report
    assert "| 해외 | Vertiv | VRT | NYSE | CIK 0001674101 | Vertiv Holdings Co | OK |" in report
    assert "## 시총(상장사) vs 재무(법인) 주체 검사" in report and "재무 주체 WARN 1" in res.message
    notes = Path(res.outputs[1]).read_text(encoding="utf-8")
    assert notes.startswith("# Vol.3 데이터 노트") and "WARN 1개" in notes
    assert "VST: 보통주·EPS 미보고 → 운영 자회사" in notes and "## 한계" in notes


OV = {"VST": {"cik": 1692819, "verdict": "OK", "note": "수동 확인: 10-K registrant = Vistra Corp.", "detail": "표기 차이",
              "url": "https://www.sec.gov/Archives/edgar/data/1692819/000169281922000005/vistra-20211231.htm", "verified_on": "2026-10-22"}}


def test_apply_entity_override_requires_cik_url_and_date():
    row = {"ticker": "VST", "listed_cik": "0001692819", "entity_cik": "0001692819", "verdict": "WARN",
           "same_consolidated": "likely", "reason": "auto"}
    out = sec.apply_entity_override(row, OV)
    assert out["verdict"] == "OK" and out["auto_verdict"] == "WARN" and out["auto_same"] == "likely"
    assert out["same_consolidated"] == "yes (manual)" and "2026-10-22" in out["reason"] and "sec.gov" in out["reason"]
    other = sec.apply_entity_override({**row, "entity_cik": "0001999999"}, OV)            # 다른 법인이면 적용 안 함
    assert other["verdict"] == "WARN" and other["manual_check"] == ""
    no_url = sec.apply_entity_override(row, {"VST": {**OV["VST"], "url": ""}})
    assert no_url["verdict"] == "WARN"


def test_validate_applies_manual_override_and_records_source(cfg):
    cfg["data_fetch"]["sec"]["entity_check"]["manual_overrides"] = OV
    facts = {c: _facts_for(t, c, "Vistra Operations Company LLC" if t == "VST" else None) for t, (c, _) in LISTED.items()}
    _write_manual(cfg, facts)
    sec.run(cfg, "2026-10-20", offline=True, out=lambda s: None)
    res = validate_peers.run(cfg, "2026-10-20")
    report = Path(res.outputs[0]).read_text(encoding="utf-8")
    assert "| 해외 | Vistra | VST | NYSE | CIK 0001692819 | Vistra Corp. | OK | OK(수동 확인: 10-K registrant = Vistra Corp.) |" in report
    assert "**수동 확인 (자동 판정 override)**" in report and "2026-10-22" in report and "vistra-20211231.htm" in report
    assert "WARN (likely)" in report and "재무 주체 WARN" not in res.message
    notes = Path(res.outputs[1]).read_text(encoding="utf-8")
    assert "WARN 0개" in notes and "VST: 수동 확인: 10-K registrant = Vistra Corp. (확인일 2026-10-22)" in notes


def test_vol03_notes_show_watchlist_before_collection(cfg):
    res = validate_peers.run(cfg, "2026-10-20")
    notes = Path(res.outputs[1]).read_text(encoding="utf-8")
    assert "TODO(data)" in notes and "Vistra Oper" in notes and "검사 대기" in notes


def test_fetch_all_sec_offline_flag(cfg, monkeypatch, capsys):
    _all_manual(cfg)
    monkeypatch.setattr(fetch_all, "load_config", lambda path=None: cfg)
    rc = fetch_all.main(["--source", "sec", "--sec-offline", "--no-post"])
    out = capsys.readouterr().out
    assert rc == 0 and "SUCCESS" in out and "오프라인 모드" in out


def test_sec_offline_check_cli(cfg, monkeypatch, capsys):
    monkeypatch.setattr(sec, "load_config", lambda path=None: cfg)
    assert sec.main(["--offline-check"]) == 0
    out = capsys.readouterr().out
    assert "CIK0001692819.json" in out and "없는 파일 6개" in out


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

    def history(self, start, end, auto_adjust=False, timeout=None):
        assert timeout == 20
        return self._hist


def test_fetch_quote_uses_close_on_or_before_asof():
    q = market_global.fetch_quote("VRT", "2026-10-20", 10, FakeTicker, timeout=20)
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


def test_validate_peers_sec_unavailable_is_not_fail(cfg):
    raw = Path(cfg["paths"]["raw"])
    (raw / "dart").mkdir(parents=True)
    pd.DataFrame([{"corp_code": f"0000000{i}", "corp_name": p["name"], "corp_eng_name": "",
                   "stock_code": p["ticker"], "modify_date": "1"} for i, p in enumerate(cfg["peers"]["domestic"])]
                 ).to_csv(raw / "dart" / "corp_codes_listed.csv", index=False)     # SEC 파일은 없음
    res = validate_peers.run(cfg, "2026-10-20")
    text = Path(res.outputs[0]).read_text(encoding="utf-8")
    assert res.status == base.STATUS_PARTIAL
    assert res.message == "FAIL 0, WARN 0, SKIPPED(sec unavailable) 5"
    assert text.count("| SKIPPED(sec unavailable) |") == 5 and "| FAIL |" not in text
    assert "N/A (SEC 비대상)" in text                                                # Schneider는 그대로
    assert "5개 검증 보류" in text


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
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)   # pandas 2.x concat 경고 재발 방지
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
    assert fetch_all.parse_args(["--source", "krx,ecos,sec"]).source == ["krx", "ecos", "sec"]
    assert fetch_all.parse_args(["--source", "krx,", "ECOS", "sec"]).source == ["krx", "ecos", "sec"]
    assert fetch_all.parse_args([]).source == ["all"]
    with pytest.raises(SystemExit):
        fetch_all.parse_args(["--source", "krx,bloomberg"])
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


def test_fetch_all_comma_sources_and_skip_filings(cfg, monkeypatch, capsys):
    cfg["data_fetch"]["dart"]["filings"]["enabled"] = True
    monkeypatch.setattr(fetch_all, "load_config", lambda path=None: cfg)
    seen = {}

    def fake(name):
        def run(c, a, **kw):
            seen[name] = c["data_fetch"]["dart"]["filings"]["enabled"]
            return base.FetchResult(name, "SUCCESS", 1)
        return run

    for n in ("krx", "ecos", "sec", "dart"):
        monkeypatch.setitem(fetch_all.SOURCES, n, fake(n))
    fetch_all.main(["--source", "krx,ecos,sec", "--no-post"])
    assert list(seen) == ["krx", "ecos", "sec"]
    seen.clear()
    fetch_all.main(["--source", "dart", "--skip-filings", "--no-post"])
    assert seen == {"dart": False}
    assert cfg["data_fetch"]["dart"]["filings"]["enabled"] is True     # 원본 config는 변경하지 않음


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


def test_consolidate_excludes_empty_frames_without_warning():
    empty = pd.DataFrame(columns=["company", "ticker", "fiscal_year", "currency", "unit", "revenue"])
    manual = pd.DataFrame([{"company": "S", "ticker": "SU.PA", "region": "EU", "basis": "IFRS",
                            "fiscal_year": "FY2025A", "currency": "EUR", "unit": "mn", "revenue": None,
                            "operating_income": None, "net_income": None, "total_debt": None, "cash": None,
                            "source": None, "notes": None}])
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        out = consolidate.consolidate(empty, None, manual, None)
    assert len(out) == 1 and out.loc[0, "revenue"] != out.loc[0, "revenue"]   # NaN 유지
    assert "TODO(data)" in out.loc[0, "flags"] and out["revenue"].dtype.kind == "f"


# ---------------------------------------------------------------------------
# 실제 소켓 회귀 테스트 (127.0.0.1 로컬 서버만 사용, 외부 네트워크 없음)
# ---------------------------------------------------------------------------
@pytest.fixture
def local_server():
    import threading
    import time as _time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if self.path.startswith("/trickle"):
                try:  # 0.3초마다 1바이트: 소켓 recv timeout은 영원히 안 걸리는 응답 (DART 무한대기 재현)
                    for _ in range(100):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                        _time.sleep(0.3)
                except OSError:
                    pass
            else:
                self.wfile.write(b'{"status": "000"}')

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_real_socket_trickle_is_cut_by_wall_clock(local_server):
    import threading
    import time as _time

    client = HttpClient("dart", {"connect_timeout_sec": 1, "read_timeout_sec": 1, "max_retries": 3,
                                 "backoff_base_sec": 0.5, "max_total_wait_sec": 2, "cache_ttl_hours": 0})
    t0 = _time.monotonic()
    with pytest.raises(RequestTimeout):
        client.get(local_server + "/trickle", params={"crtfc_key": "REALKEY_123"})
    assert _time.monotonic() - t0 < 6                     # 수정 전에는 여기서 무한대기
    assert client.get(local_server + "/ok").json() == {"status": "000"}   # 정상 응답 경로
    _time.sleep(0.5)
    assert not [t for t in threading.enumerate() if t.name.startswith("http-") and t.is_alive()]
