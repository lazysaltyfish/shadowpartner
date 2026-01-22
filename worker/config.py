"""Configuration loader for Whisper GPU Worker."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict

from dotenv import load_dotenv
from logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Config:
    """Worker configuration."""

    backend_ws_url: str
    worker_token: str
    worker_id: str
    whisper_model_size: str
    whisper_device: str
    whisper_fp16: bool
    audio_cache_dir: str
    max_cache_size_gb: int


def load_config() -> Config:
    """Load configuration from environment variables."""
    load_dotenv()

    backend_ws_url = os.getenv("BACKEND_WS_URL", "ws://localhost:8000/ws/worker")
    worker_token = os.getenv("WORKER_TOKEN", "")
    worker_id = os.getenv("WORKER_ID", "gpu-01")
    whisper_model_size = os.getenv("WHISPER_MODEL_SIZE", "base")
    whisper_device = os.getenv("WHISPER_DEVICE", "cuda")
    whisper_fp16 = os.getenv("WHISPER_FP16", "false").lower() == "true"
    audio_cache_dir = os.getenv("AUDIO_CACHE_DIR", "./cache/audio")
    max_cache_size_gb = int(os.getenv("MAX_CACHE_SIZE_GB", "10"))

    if not worker_token:
        raise ValueError("WORKER_TOKEN environment variable is required")

    config = Config(
        backend_ws_url=backend_ws_url,
        worker_token=worker_token,
        worker_id=worker_id,
        whisper_model_size=whisper_model_size,
        whisper_device=whisper_device,
        whisper_fp16=whisper_fp16,
        audio_cache_dir=audio_cache_dir,
        max_cache_size_gb=max_cache_size_gb,
    )

    logger.info(
        f"Config loaded: worker_id={worker_id}, model={whisper_model_size}, device={whisper_device}"
    )
    return config


def get_capabilities(config: Config) -> Dict:
    """Get worker capabilities for registration."""
    return {
        "model": config.whisper_model_size,
        "device": config.whisper_device,
        "fp16": config.whisper_fp16,
    }
