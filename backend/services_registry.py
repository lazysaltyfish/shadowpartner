from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import uuid
from typing import Dict, Optional

from services.aligner import Aligner
from services.analyzer import JapaneseAnalyzer
from services.downloader import VideoDownloader
from services.storage.base import BaseStorage
from services.storage.local import LocalStorage
from services.subtitle_linearizer import SubtitleLinearizer
from services.transcriber import AudioTranscriber
from services.translator import Translator
from services.vocabulary_analyzer import VocabularyAnalyzer
from settings import get_settings
from utils.logger import get_logger
from workers.manager import WorkerManager
from workers.storage_bridge import StorageBridge

logger = get_logger(__name__)
settings = get_settings()

subtitle_similarity_threshold = settings.subtitle_similarity_threshold

downloader: Optional[VideoDownloader] = None
transcriber: Optional[AudioTranscriber] = None
analyzer: Optional[JapaneseAnalyzer] = None
aligner: Optional[Aligner] = None
translator: Optional[Translator] = None
subtitle_linearizer: Optional[SubtitleLinearizer] = None
vocabulary_analyzer: Optional[VocabularyAnalyzer] = None
storage: Optional[BaseStorage] = None
whisper_lock: Optional[asyncio.Semaphore] = None
whisper_lock_label = "transcription"

# Worker instance ID (unique per backend instance for multi-instance deployments)
worker_instance_id: str = ""
# Worker temp directory (unique per instance to avoid conflicts)
worker_temp_dir: str = ""

# Worker-related services
worker_manager: Optional[WorkerManager] = None
storage_bridge: Optional[StorageBridge] = None


def init_services():
    global downloader
    global transcriber
    global analyzer
    global aligner
    global translator
    global subtitle_linearizer
    global vocabulary_analyzer
    global storage
    global whisper_lock
    global whisper_lock_label
    global worker_instance_id
    global worker_temp_dir
    global worker_manager
    global storage_bridge

    try:
        # Generate unique instance ID and temp directory for this backend instance
        worker_instance_id = uuid.uuid4().hex[:8]
        worker_temp_dir = os.path.join(
            tempfile.gettempdir(), f"shadowpartner_worker_{worker_instance_id}"
        )
        os.makedirs(worker_temp_dir, exist_ok=True)
        logger.info(f"Worker instance ID: {worker_instance_id}, temp dir: {worker_temp_dir}")
        whisper_device = settings.whisper_device
        whisper_fp16 = settings.whisper_fp16
        whisper_model_size = settings.whisper_model_size

        logger.info("Initializing services...")
        downloader = VideoDownloader()
        transcriber = AudioTranscriber(
            model_size=whisper_model_size,
            device=whisper_device,
            fp16=whisper_fp16,
        )
        analyzer = JapaneseAnalyzer()
        aligner = Aligner()
        translator = Translator()
        subtitle_linearizer = SubtitleLinearizer()
        vocabulary_analyzer = VocabularyAnalyzer()
        storage = LocalStorage(root_dir=settings.storage_root_dir)
        logger.info(f"Local storage initialized: {settings.storage_root_dir}")
        whisper_lock = asyncio.Semaphore(1)
        if transcriber is not None:
            whisper_lock_label = f"{transcriber.device.upper()} transcription"
        logger.info("Whisper transcription queue enabled (1 at a time)")

        # Initialize worker services
        try:
            worker_tokens: Dict[str, str] = json.loads(settings.worker_api_tokens)
            if worker_tokens:
                storage_bridge = StorageBridge(
                    backend_base_url=settings.backend_base_url,
                    ttl_seconds=settings.temp_file_ttl,
                )
                worker_manager = WorkerManager(
                    api_tokens=worker_tokens,
                    storage_bridge=storage_bridge,
                    heartbeat_interval=settings.worker_heartbeat_interval,
                    heartbeat_timeout=settings.worker_heartbeat_timeout,
                    job_timeout=settings.worker_job_timeout,
                )
                worker_manager.start()
                logger.info(
                    f"Worker manager initialized with {len(worker_tokens)} registered worker(s)"
                )
            else:
                logger.info("No GPU workers configured (WORKER_API_TOKENS is empty)")
        except Exception as e:
            logger.warning(
                f"Failed to initialize worker manager: {e}. Workers will not be available."
            )

        logger.info(
            "All services initialized successfully. Transcriber running on %s (fp16=%s, model=%s)",
            transcriber.device,
            transcriber.fp16,
            transcriber.model_size,
        )
    except Exception as e:
        logger.critical(f"Failed to initialize services: {e}", exc_info=True)


def set_executor(executor):
    if translator:
        translator.set_executor(executor)
    if vocabulary_analyzer:
        vocabulary_analyzer.set_executor(executor)


def cleanup_worker_temp_dir():
    """Clean up the worker temp directory on shutdown."""
    global worker_temp_dir
    if worker_temp_dir and os.path.exists(worker_temp_dir):
        try:
            shutil.rmtree(worker_temp_dir)
            logger.info(f"Cleaned up worker temp directory: {worker_temp_dir}")
        except Exception as e:
            logger.warning(f"Failed to clean up worker temp directory: {e}")
