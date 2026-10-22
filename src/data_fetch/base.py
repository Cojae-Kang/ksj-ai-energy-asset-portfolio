"""데이터 수집 공통 모듈.

- HttpClient: requests 세션, 재시도(지수 백오프), 타임아웃(연결/응답), 총 소요 상한, 요청 간 지연, 응답 캐시
- Progress: 요청마다 "[소스] 단계 i/N 라벨 ... 완료(x.x초)" 진행 로그
- save_raw: raw 파일 저장 + 같은 이름의 .meta.json 자동 생성
- 비밀값: python-dotenv로 .env에서만 로드, 로그·meta·예외 메시지에서 마스킹
- SkipSource: 키가 없을 때 해당 소스만 건너뛰기 위한 예외

이 모듈은 로컬에서 실행하는 수집 스크립트 전용이다. 클라우드 세션에서는 호출하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import socket
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping

import pandas as pd
import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"

logger = logging.getLogger("data_fetch")


# ---------------------------------------------------------------------------
# 예외 / 결과 타입
# ---------------------------------------------------------------------------
class SkipSource(Exception):
    """키 미설정 등으로 해당 소스를 건너뛸 때 사용 (전체 파이프라인은 계속)."""


class FetchError(Exception):
    """API 응답 오류 (HTTP 오류, API status 오류 등)."""


class HttpStatusError(FetchError):
    """4xx 등 재시도 대상이 아닌 HTTP 오류. 호출부가 상태코드별로 요약 메시지를 만들 수 있게 정보 보관."""

    def __init__(self, message: str, *, status_code: int, url: str, body: bytes = b"", content_type: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.body = body[:65536]          # 진단용 (메시지에는 넣지 않음)
        self.content_type = content_type


def summarize_body(body: bytes, content_type: str = "", limit: int = 200) -> str:
    """오류 응답 본문 한 줄 요약. HTML이면 원문 대신 <title>/<h1>과 크기만."""
    text = body.decode("utf-8", errors="replace")
    if "html" in (content_type or "").lower() or text.lstrip()[:1] == "<":
        m = re.search(r"<title[^>]*>(.*?)</title>|<h1[^>]*>(.*?)</h1>", text, re.S | re.I)
        title = re.sub(r"\s+", " ", next((g for g in (m.groups() if m else ()) if g), "")).strip()
        return f"HTML 응답 {len(body):,} bytes" + (f" (title: {title[:80]})" if title else "")
    return re.sub(r"\s+", " ", text).strip()[:limit]


class RequestTimeout(FetchError):
    """연결/응답 타임아웃이 재시도 후에도 해소되지 않음 → 호출부는 해당 요청만 건너뛰고 기록."""


class _BodyDeadline(Exception):
    """응답 본문 수신이 read_timeout(벽시계)을 넘김."""


STATUS_SUCCESS = "SUCCESS"
STATUS_PARTIAL = "PARTIAL"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED = "SKIPPED"


@dataclass
class FetchResult:
    source: str
    status: str
    n_items: int = 0
    outputs: list[str] = field(default_factory=list)
    message: str = ""
    elapsed_sec: float = 0.0


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------
def load_config(path: str | Path | None = None) -> dict:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_path(p: str | Path, root: Path | None = None) -> Path:
    p = Path(p)
    return p if p.is_absolute() else (root or PROJECT_ROOT) / p


def build_url(base_url: str, endpoint: str = "", **path_params: Any) -> str:
    """config의 base_url + endpoint 결합. endpoint 안의 {name}은 path_params로 치환."""
    endpoint = endpoint.format(**path_params) if path_params else endpoint
    if not endpoint:
        return base_url.rstrip("/")
    return base_url.rstrip("/") + "/" + endpoint.lstrip("/")


# ---------------------------------------------------------------------------
# 비밀값 로드 / 마스킹
# ---------------------------------------------------------------------------
_REGISTERED_SECRETS: set[str] = set()
_DOTENV_LOADED = False
DEFAULT_SECRET_PARAM_NAMES = ("crtfc_key", "api_key", "apikey", "auth_key", "key", "servicekey")


def load_env(dotenv_path: str | Path | None = None) -> None:
    """.env를 한 번만 로드. 이미 설정된 환경변수는 덮어쓰지 않는다."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - requirements.txt에 포함
        logger.warning("python-dotenv 미설치: .env를 읽지 못했습니다 (pip install python-dotenv)")
        _DOTENV_LOADED = True
        return
    load_dotenv(dotenv_path or PROJECT_ROOT / ".env", override=False)
    _DOTENV_LOADED = True


def register_secret(value: str | None) -> None:
    if value and len(value) >= 4:
        _REGISTERED_SECRETS.add(value)


def get_secret(name: str, required: bool = True) -> str | None:
    """환경변수(.env)에서 비밀값 로드. 없으면 SkipSource (required=True)."""
    load_env()
    value = (os.environ.get(name) or "").strip().strip('"').strip("'")
    if not value:
        if required:
            raise SkipSource(f"{name} 미설정 (.env에 값을 넣으면 수집됩니다)")
        return None
    register_secret(value)
    return value


_QUERY_SECRET_RE = re.compile(
    r"(?i)((?:crtfc_key|api_key|apikey|auth_key|servicekey|key)=)([^&\s'\"]+)"
)
# ECOS는 키가 URL 경로에 들어간다: /StatisticSearch/{KEY}/json/...
_ECOS_PATH_RE = re.compile(r"(?i)(/StatisticSearch/)([^/\s]+)(/)")


def mask_secrets(text: Any) -> str:
    """문자열 안의 등록된 비밀값, 쿼리 키 파라미터, ECOS 경로 키를 ***로 마스킹."""
    s = str(text)
    for secret in sorted(_REGISTERED_SECRETS, key=len, reverse=True):
        s = s.replace(secret, "***")
    s = _QUERY_SECRET_RE.sub(r"\1***", s)
    s = _ECOS_PATH_RE.sub(r"\1***\3", s)
    return s


def sanitize_params(params: Mapping[str, Any] | Iterable[tuple[str, Any]] | None,
                    secret_names: Iterable[str] = DEFAULT_SECRET_PARAM_NAMES) -> dict:
    """meta 기록용 params: 키 파라미터 제거 (리스트형 params도 지원)."""
    if not params:
        return {}
    lowered = {n.lower() for n in secret_names}
    items = params.items() if isinstance(params, Mapping) else params
    out: dict[str, Any] = {}
    for k, v in items:
        if str(k).lower() in lowered:
            continue
        if k in out:  # 동일 키 반복 (예: facets[sectorid][]) → 리스트로 묶기
            out[k] = out[k] if isinstance(out[k], list) else [out[k]]
            out[k].append(v)
        else:
            out[k] = v
    return out


class SecretMaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask_secrets(record.getMessage())
        record.args = ()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if not any(isinstance(f, SecretMaskingFilter) for h in root.handlers for f in h.filters):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        handler.addFilter(SecretMaskingFilter())
        root.addHandler(handler)
    root.setLevel(level)


# ---------------------------------------------------------------------------
# HTTP 클라이언트
# ---------------------------------------------------------------------------
@dataclass
class HttpResponse:
    url: str               # 마스킹된 URL
    status_code: int
    content: bytes
    headers: dict
    fetched_at: str
    from_cache: bool = False

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class HttpClient:
    """재시도·지연·캐시를 갖춘 GET 전용 클라이언트.

    session/sleep/clock을 주입할 수 있어 네트워크 없이 테스트 가능하다.
    """

    def __init__(self, source: str, http_cfg: Mapping | None = None, *,
                 request_delay_sec: float = 0.0, cache_dir: str | Path | None = None,
                 session: Any = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic, use_cache: bool = True,
                 default_headers: Mapping[str, str] | None = None):
        cfg = dict(http_cfg or {})
        self.source = source
        self.connect_timeout = float(cfg.get("connect_timeout_sec", 5))
        self.read_timeout = float(cfg.get("read_timeout_sec", 20))
        self.max_retries = int(cfg.get("max_retries", 3))
        self.backoff_base = float(cfg.get("backoff_base_sec", 1.0))
        self.max_total_wait = float(cfg.get("max_total_wait_sec", 60))
        self.retry_status = set(cfg.get("retry_status", [429, 500, 502, 503, 504]))
        self.cache_ttl_sec = float(cfg.get("cache_ttl_hours", 24)) * 3600
        self.secret_names = tuple(cfg.get("secret_param_names", DEFAULT_SECRET_PARAM_NAMES))
        self.request_delay = float(request_delay_sec)
        self.cache_dir = Path(cache_dir) / source if cache_dir else None
        self.use_cache = use_cache and self.cache_dir is not None and self.cache_ttl_sec > 0
        self.session = session or requests.Session()
        if default_headers:
            self.session.headers.update(dict(default_headers))
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None

    # --- cache -------------------------------------------------------------
    def _cache_key(self, url: str, params: Any, headers: Mapping | None) -> str:
        safe = {
            "url": mask_secrets(url),
            "params": sanitize_params(params, self.secret_names),
            "headers": sanitize_params(headers, self.secret_names + ("authorization",)),
        }
        return hashlib.sha256(json.dumps(safe, sort_keys=True, default=str).encode()).hexdigest()[:32]

    def _cache_read(self, key: str) -> HttpResponse | None:
        if not self.use_cache:
            return None
        body, hdr = self.cache_dir / f"{key}.bin", self.cache_dir / f"{key}.hdr.json"
        if not (body.exists() and hdr.exists()):
            return None
        if time.time() - body.stat().st_mtime > self.cache_ttl_sec:
            return None
        h = json.loads(hdr.read_text(encoding="utf-8"))
        return HttpResponse(url=h["url"], status_code=h["status_code"], content=body.read_bytes(),
                            headers=h.get("headers", {}), fetched_at=h["fetched_at"], from_cache=True)

    def _cache_write(self, key: str, resp: HttpResponse) -> None:
        if not self.use_cache:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / f"{key}.bin").write_bytes(resp.content)
        (self.cache_dir / f"{key}.hdr.json").write_text(json.dumps({
            "url": resp.url, "status_code": resp.status_code, "fetched_at": resp.fetched_at,
            "headers": {k: v for k, v in resp.headers.items() if k.lower() == "content-type"},
        }, ensure_ascii=False), encoding="utf-8")

    # --- request -----------------------------------------------------------
    def _throttle(self) -> None:
        if self.request_delay > 0 and self._last_request_at is not None:
            wait = self.request_delay - (self._clock() - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = self._clock()

    def _read_body(self, r: Any, deadline: float) -> bytes:
        """stream 응답을 청크 단위로 읽으며 deadline 확인 (청크 사이 점검. 최종 상한은 _fetch_once의 감시 스레드)."""
        chunks = []
        try:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    chunks.append(chunk)
                if self._clock() > deadline:
                    raise _BodyDeadline()
        finally:
            close = getattr(r, "close", None)
            if close:
                close()
        return b"".join(chunks)

    @staticmethod
    def _find_socket(resp: Any) -> socket.socket | None:
        raw = getattr(resp, "raw", None)
        conn_sock = getattr(getattr(raw, "_connection", None), "sock", None)
        if conn_sock is not None:
            return conn_sock
        fp = getattr(getattr(raw, "_fp", None), "fp", None)          # http.client.HTTPResponse.fp
        return getattr(getattr(fp, "raw", None), "_sock", None)        # BufferedReader → SocketIO._sock

    @classmethod
    def _abort(cls, resp: Any) -> None:
        """감시 시간 초과 시 소켓을 shutdown해 작업 스레드의 블로킹 recv를 깨운다 (best effort).

        resp.close()는 작업 스레드가 쥔 버퍼 락 때문에 메인 스레드를 막을 수 있어 호출하지 않는다
        (작업 스레드의 _read_body finally에서 닫힌다).
        """
        sock = cls._find_socket(resp) if resp is not None else None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _fetch_once(self, url: str, params: Any, headers: Mapping | None, read_limit: float) -> tuple[Any, bytes]:
        """요청 1회: 응답 헤더+본문 수신을 벽시계 (connect + read_limit)초 안에 끝내지 못하면 _BodyDeadline.

        requests의 read timeout은 '소켓 recv 1회' 기준이고, urllib3는 청크 크기만큼 모일 때까지 recv를
        반복한다. 서버가 바이트를 조금씩 흘려보내면 timeout이 영원히 안 걸린다(DART 공시검색 무한대기 원인).
        그래서 작업을 데몬 스레드에서 돌리고 메인 스레드가 상한 시간만 기다린다.
        """
        box: dict[str, Any] = {}
        start = self._clock()

        def work() -> None:
            try:
                r = self.session.get(url, params=params, headers=dict(headers or {}),
                                     timeout=(self.connect_timeout, read_limit), stream=True)
                box["resp"] = r
                box["body"] = self._read_body(r, start + read_limit)
            except BaseException as e:  # noqa: BLE001 - 메인 스레드로 전달
                box["err"] = e

        t = threading.Thread(target=work, name=f"http-{self.source}", daemon=True)
        t.start()
        t.join(self.connect_timeout + read_limit)
        if t.is_alive():
            self._abort(box.get("resp"))
            raise _BodyDeadline(f"응답 수신이 {self.connect_timeout + read_limit:.0f}초를 넘김")
        if "err" in box:
            raise box["err"]
        return box["resp"], box["body"]

    @staticmethod
    def _is_timeout(e: Exception) -> bool:
        # iter_content 중 urllib3 ReadTimeoutError는 requests.ConnectionError로 감싸져 올라온다
        return isinstance(e, (requests.Timeout, _BodyDeadline)) or "timed out" in str(e).lower()

    def get(self, url: str, params: Any = None, headers: Mapping | None = None,
            use_cache: bool = True) -> HttpResponse:
        """GET + 재시도. 타임아웃이 끝내 해소되지 않으면 RequestTimeout (호출부에서 건너뛰고 기록)."""
        key = self._cache_key(url, params, headers)
        if use_cache:
            cached = self._cache_read(key)
            if cached is not None:
                logger.debug("[%s] cache hit %s", self.source, cached.url)
                return cached

        masked_url = mask_secrets(url)
        last_err, last_was_timeout = "", False
        budget_end = self._clock() + self.max_total_wait
        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                wait = self.backoff_base * (2 ** (attempt - 1))
                if self._clock() + wait >= budget_end:
                    last_err += f" (총 대기 상한 {self.max_total_wait:.0f}초 도달)"
                    break
                logger.warning("[%s] 재시도 %d/%d (%.1fs 대기): %s", self.source, attempt,
                               self.max_retries, wait, last_err)
                self._sleep(wait)
            self._throttle()
            read_limit = min(self.read_timeout, budget_end - self._clock())
            if read_limit <= 0:
                last_err += f" (총 대기 상한 {self.max_total_wait:.0f}초 도달)"
                break
            try:
                r, body = self._fetch_once(url, params, headers, read_limit)
            except (requests.ConnectionError, requests.Timeout, _BodyDeadline) as e:
                last_was_timeout = self._is_timeout(e)
                kind = "타임아웃" if last_was_timeout else "연결 오류"
                last_err = mask_secrets(f"{kind}: {type(e).__name__}: {e}")
                continue
            last_was_timeout = False
            if r.status_code in self.retry_status:
                last_err = f"HTTP {r.status_code}"
                continue
            if r.status_code >= 400:
                ctype = dict(r.headers).get("Content-Type", "") if getattr(r, "headers", None) else ""
                raise HttpStatusError(
                    f"[{self.source}] HTTP {r.status_code} {masked_url}: {mask_secrets(summarize_body(body, ctype))}",
                    status_code=r.status_code, url=masked_url, body=body, content_type=ctype)
            resp = HttpResponse(url=mask_secrets(getattr(r, "url", url)), status_code=r.status_code,
                                content=body, headers=dict(r.headers), fetched_at=utc_now_iso())
            self._cache_write(key, resp)
            return resp
        err_cls = RequestTimeout if last_was_timeout else FetchError
        raise err_cls(f"[{self.source}] 재시도 후 실패 {masked_url}: {last_err.strip()}")


def make_client(source: str, cfg: Mapping, source_cfg: Mapping, *, use_cache: bool = True,
                session: Any = None, **kwargs) -> HttpClient:
    """config.yaml의 data_fetch.http + 소스별 request_delay_sec로 HttpClient 생성."""
    df = cfg["data_fetch"]
    return HttpClient(
        source, df.get("http", {}),
        request_delay_sec=source_cfg.get("request_delay_sec", 0.0),
        cache_dir=resolve_path(df["output"]["cache"]),
        use_cache=use_cache, session=session, **kwargs,
    )


# ---------------------------------------------------------------------------
# 진행 로그
# ---------------------------------------------------------------------------
progress_logger = logging.getLogger("data_fetch.progress")


class Progress:
    """요청 단위 진행 로그: "[dart] 재무제표 3/12 HD현대일렉트릭 FY2025 ... 완료(1.2초)".

    with prog.step("라벨") as st: ... 블록이 끝나면 한 줄 출력. st["note"]에 부가 설명(예: OFS 대체),
    st["status"]에 완료 외 상태(예: 데이터 없음)를 넣을 수 있다. 예외는 '실패'로 기록 후 그대로 전파.
    """

    def __init__(self, source: str, stage: str, total: int | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.source, self.stage, self.total, self.i = source, stage, total, 0
        self._clock = clock

    @contextmanager
    def step(self, label: str = "") -> Iterator[dict]:
        self.i += 1
        i = self.i
        info: dict = {"status": "완료", "note": ""}
        t0 = self._clock()

        def head() -> str:  # total은 블록 안에서 확정될 수 있어(예: EIA 페이지 수) 출력 시점에 계산
            pos = f"{i}/{self.total}" if self.total else f"{i}"
            return f"[{self.source}] {self.stage} {pos} {label}".rstrip()

        try:
            yield info
        except Exception as e:
            kind = "타임아웃→건너뜀" if isinstance(e, RequestTimeout) else "실패"
            progress_logger.warning("%s ... %s(%.1f초): %s", head(), kind, self._clock() - t0,
                                    mask_secrets(str(e))[:200])
            raise
        note = f" {info['note']}" if info.get("note") else ""
        progress_logger.info("%s ... %s(%.1f초)%s", head(), info["status"], self._clock() - t0, note)


# ---------------------------------------------------------------------------
# raw 저장 + meta.json
# ---------------------------------------------------------------------------
META_FIELDS = ("source", "endpoint", "params", "fetched_at", "as_of", "license_note")


def meta_path_for(path: str | Path) -> Path:
    path = Path(path)
    return path.with_name(path.stem + ".meta.json")


def save_raw(path: str | Path, data: bytes | str | dict | list | pd.DataFrame, *, source: str,
             endpoint: str, params: Any = None, as_of: str | None, license_note: str,
             fetched_at: str | None = None, extra: Mapping | None = None,
             secret_names: Iterable[str] = DEFAULT_SECRET_PARAM_NAMES) -> Path:
    """raw 파일 저장 + 같은 이름(stem)의 .meta.json 생성. 키는 meta에 남기지 않는다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, pd.DataFrame):
        data.to_csv(path, index=False, encoding="utf-8-sig")
    elif isinstance(data, (dict, list)):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    elif isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    write_meta(path, source=source, endpoint=endpoint, params=params, as_of=as_of, license_note=license_note,
               fetched_at=fetched_at, extra=extra, secret_names=secret_names)
    return path


def write_meta(path: str | Path, *, source: str, endpoint: str, params: Any = None, as_of: str | None,
               license_note: str, fetched_at: str | None = None, extra: Mapping | None = None,
               secret_names: Iterable[str] = DEFAULT_SECRET_PARAM_NAMES) -> Path:
    """data 파일은 그대로 두고 같은 이름의 .meta.json만 쓴다 (수기·브라우저 다운로드 파일용)."""
    meta = {
        "source": source,
        "endpoint": mask_secrets(endpoint),
        "params": json.loads(mask_secrets(json.dumps(sanitize_params(params, secret_names),
                                                     ensure_ascii=False, default=str))),
        "fetched_at": fetched_at or utc_now_iso(),
        "as_of": as_of,
        "license_note": license_note,
    }
    if extra:
        meta.update(json.loads(mask_secrets(json.dumps(dict(extra), ensure_ascii=False, default=str))))
    mp = meta_path_for(path)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return mp


def save_processed(path: str | Path, df: pd.DataFrame, *, sources: list[str], as_of: str | None,
                   note: str = "") -> Path:
    """가공 데이터 저장 (+ 추적용 meta)."""
    return save_raw(path, df, source=", ".join(sources), endpoint="(processed)", params=None,
                    as_of=as_of, license_note=note or "원 소스 라이선스 적용 (raw meta 참조)")


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------
def to_number(x: Any) -> float:
    """'1,234' / '-5' / '' / None / '.' → float (없으면 NaN)."""
    if x is None:
        return float("nan")
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(",", "")
    if s in ("", "-", ".", "N/A", "NaN", "nan"):
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def markdown_table(rows: list[Mapping], columns: list[str] | None = None) -> str:
    """tabulate 의존성 없이 Markdown 표 생성."""
    if not rows:
        return "_(없음)_\n"
    columns = columns or list(rows[0].keys())

    def cell(v: Any) -> str:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        return str(v).replace("|", "\\|").replace("\n", " ")

    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    lines += ["| " + " | ".join(cell(r.get(c)) for c in columns) + " |" for r in rows]
    return "\n".join(lines) + "\n"


_CORP_SUFFIXES = (r"(주식회사|주|㈜|inc\.?|corp\.?|corporation|co\.?|company|plc|holdings?|ltd\.?|limited|s\.?a\.?|se"
                  r"|llc|lp)$")


def normalize_name(name: str) -> str:
    """회사명 비교용: 소문자, 구두점·공백 제거, 법인격 표기(Inc., Corp., 주식회사, LLC 등) 제거."""
    s = str(name or "").lower().strip()
    s = re.sub(r"[\s,.\-&'()]", " ", s)
    tokens = [t for t in s.split() if not re.fullmatch(_CORP_SUFFIXES, t)]
    return "".join(tokens)


def names_match(expected: str, actual: str) -> bool:
    """부분일치 (티커 검증용, 표기 차이에 관대)."""
    a, b = normalize_name(expected), normalize_name(actual)
    return bool(a) and bool(b) and (a in b or b in a)


def names_equal(a: str, b: str) -> bool:
    """완전일치 (법인 주체 검사용): 'Vistra Corp.' vs 'Vistra Operations Co LLC'는 다른 법인으로 본다."""
    x, y = normalize_name(a), normalize_name(b)
    return bool(x) and x == y
