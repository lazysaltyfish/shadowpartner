from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Optional

from dotenv import load_dotenv

_BOOL_TRUE = {"1", "true", "yes", "y", "on"}
_BOOL_FALSE = {"0", "false", "no", "n", "off"}


def _normalize(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def _get_env(name: str) -> Optional[str]:
    return _normalize(os.getenv(name))


def _parse_bool(name: str, default: bool) -> bool:
    raw = _get_env(name)
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in _BOOL_TRUE:
        return True
    if lowered in _BOOL_FALSE:
        return False
    raise ValueError(f"Invalid boolean for {name}: {raw}")


def _parse_int(name: str, default: int) -> int:
    raw = _get_env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid integer for {name}: {raw}") from exc


def _parse_float(name: str, default: float) -> float:
    raw = _get_env(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid float for {name}: {raw}") from exc


def _parse_json_dict(name: str, default: str = "{}") -> Dict[str, str]:
    """Parse a JSON string into a dictionary."""
    raw = _get_env(name)
    if raw is None:
        raw = default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for {name}: {raw}") from exc


@dataclass(frozen=True)
class Settings:
    subtitle_similarity_threshold: float
    gemini_api_key: Optional[str]
    gemini_model_id: str
    translate_batch_chunk_size: int
    http_proxy: Optional[str]
    https_proxy: Optional[str]
    upload_session_ttl_seconds: int
    upload_session_sweep_seconds: int
    rate_limit_enabled: bool
    rate_limit_default_requests_per_minute: int
    rate_limit_health_check_per_minute: int
    rate_limit_status_per_minute: int
    rate_limit_upload_per_minute: int
    rate_limit_process_per_minute: int
    auth_session_ttl_seconds: int
    auth_session_max_uploads: int
    auth_session_max_total_size: int
    admin_username: Optional[str]
    admin_password: Optional[str]
    # Storage configuration
    storage_root_dir: str
    # Worker configuration
    worker_ws_port: int
    worker_api_tokens: str  # JSON string: {"worker_id": "token"}
    worker_heartbeat_interval: int
    worker_heartbeat_timeout: int
    worker_job_timeout: int
    worker_transcribe_retry_attempts: int  # Number of retries before failing
    backend_base_url: str
    temp_file_ttl: int

    @property
    def proxy(self) -> Optional[str]:
        return self.http_proxy or self.https_proxy


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        subtitle_similarity_threshold=_parse_float("SUBTITLE_SIMILARITY_THRESHOLD", 0.1),
        gemini_api_key=_get_env("GEMINI_API_KEY"),
        gemini_model_id=_get_env("GEMINI_MODEL_ID") or "gemini-3-flash-preview",
        translate_batch_chunk_size=_parse_int("TRANSLATE_BATCH_CHUNK_SIZE", 50),
        http_proxy=_get_env("HTTP_PROXY") or _get_env("http_proxy"),
        https_proxy=_get_env("HTTPS_PROXY") or _get_env("https_proxy"),
        upload_session_ttl_seconds=_parse_int("UPLOAD_SESSION_TTL_SECONDS", 600),
        upload_session_sweep_seconds=_parse_int("UPLOAD_SESSION_SWEEP_SECONDS", 60),
        rate_limit_enabled=_parse_bool("RATE_LIMIT_ENABLED", True),
        rate_limit_default_requests_per_minute=_parse_int(
            "RATE_LIMIT_DEFAULT_REQUESTS_PER_MINUTE", 60
        ),
        rate_limit_health_check_per_minute=_parse_int("RATE_LIMIT_HEALTH_CHECK_PER_MINUTE", 120),
        rate_limit_status_per_minute=_parse_int("RATE_LIMIT_STATUS_PER_MINUTE", 120),
        rate_limit_upload_per_minute=_parse_int("RATE_LIMIT_UPLOAD_PER_MINUTE", 5),
        rate_limit_process_per_minute=_parse_int("RATE_LIMIT_PROCESS_PER_MINUTE", 5),
        auth_session_ttl_seconds=_parse_int("AUTH_SESSION_TTL_SECONDS", 3600),
        auth_session_max_uploads=_parse_int("AUTH_SESSION_MAX_UPLOADS", 5),
        auth_session_max_total_size=_parse_int("AUTH_SESSION_MAX_TOTAL_SIZE", 524288000),
        admin_username=_get_env("ADMIN_USERNAME"),
        admin_password=_get_env("ADMIN_PASSWORD"),
        storage_root_dir=_get_env("STORAGE_ROOT_DIR") or "data/storage",
        # Worker settings
        worker_ws_port=_parse_int("WORKER_WS_PORT", 8000),
        worker_api_tokens=_get_env("WORKER_API_TOKENS") or "{}",
        worker_heartbeat_interval=_parse_int("WORKER_HEARTBEAT_INTERVAL", 15),
        worker_heartbeat_timeout=_parse_int("WORKER_HEARTBEAT_TIMEOUT", 30),
        worker_job_timeout=_parse_int("WORKER_JOB_TIMEOUT", 600),
        worker_transcribe_retry_attempts=_parse_int("WORKER_TRANSCRIBE_RETRY_ATTEMPTS", 2),
        backend_base_url=_get_env("BACKEND_BASE_URL") or "http://localhost:8000",
        temp_file_ttl=_parse_int("TEMP_FILE_TTL", 3600),
    )
