"""데이터 수집 공통 모듈.

- HttpClient: requests 세션, 재시도(지수 백오프), 타임아웃, 요청 간 지연, 응답 캐시
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
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

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
        self.timeout = float(cfg.get("timeout_sec", 30))
        self.max_retries = int(cfg.get("max_retries", 3))
        self.backoff_base = float(cfg.get("backoff_base_sec", 1.0))
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

    def get(self, url: str, params: Any = None, headers: Mapping | None = None,
            use_cache: bool = True) -> HttpResponse:
        key = self._cache_key(url, params, headers)
        if use_cache:
            cached = self._cache_read(key)
            if cached is not None:
                logger.debug("[%s] cache hit %s", self.source, cached.url)
                return cached

        masked_url = mask_secrets(url)
        last_err: str = ""
        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                wait = self.backoff_base * (2 ** (attempt - 1))
                logger.warning("[%s] 재시도 %d/%d (%.1fs 대기): %s", self.source, attempt,
                               self.max_retries, wait, last_err)
                self._sleep(wait)
            self._throttle()
            try:
                r = self.session.get(url, params=params, headers=dict(headers or {}), timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as e:
                last_err = mask_secrets(f"{type(e).__name__}: {e}")
                continue
            if r.status_code in self.retry_status:
                last_err = f"HTTP {r.status_code}"
                continue
            if r.status_code >= 400:
                raise FetchError(f"[{self.source}] HTTP {r.status_code} {masked_url}: "
                                 f"{mask_secrets(r.text[:300])}")
            resp = HttpResponse(url=mask_secrets(getattr(r, "url", url)), status_code=r.status_code,
                                content=r.content, headers=dict(r.headers), fetched_at=utc_now_iso())
            self._cache_write(key, resp)
            return resp
        raise FetchError(f"[{self.source}] {self.max_retries}회 재시도 후 실패 {masked_url}: {last_err}")


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
    meta_path_for(path).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


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
