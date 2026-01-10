from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

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


@dataclass(frozen=True)
class Settings:
    whisper_device: Optional[str]
    whisper_fp16: bool
    whisper_model_size: str
    subtitle_similarity_threshold: float
    gemini_api_key: Optional[str]
    gemini_model_id: str
    translate_batch_chunk_size: int
    http_proxy: Optional[str]
    https_proxy: Optional[str]
    upload_session_ttl_seconds: int
    upload_session_sweep_seconds: int

    @property
    def proxy(self) -> Optional[str]:
        return self.http_proxy or self.https_proxy


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        whisper_device=_get_env("WHISPER_DEVICE"),
        whisper_fp16=_parse_bool("WHISPER_FP16", False),
        whisper_model_size=_get_env("WHISPER_MODEL_SIZE") or "base",
        subtitle_similarity_threshold=_parse_float("SUBTITLE_SIMILARITY_THRESHOLD", 0.1),
        gemini_api_key=_get_env("GEMINI_API_KEY"),
        gemini_model_id=_get_env("GEMINI_MODEL_ID") or "gemini-3-flash-preview",
        translate_batch_chunk_size=_parse_int("TRANSLATE_BATCH_CHUNK_SIZE", 50),
        http_proxy=_get_env("HTTP_PROXY") or _get_env("http_proxy"),
        https_proxy=_get_env("HTTPS_PROXY") or _get_env("https_proxy"),
        upload_session_ttl_seconds=_parse_int("UPLOAD_SESSION_TTL_SECONDS", 600),
        upload_session_sweep_seconds=_parse_int("UPLOAD_SESSION_SWEEP_SECONDS", 60),
    )
