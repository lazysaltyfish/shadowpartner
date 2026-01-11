from __future__ import annotations

import asyncio
from typing import Optional

from services.aligner import Aligner
from services.analyzer import JapaneseAnalyzer
from services.downloader import VideoDownloader
from services.subtitle_linearizer import SubtitleLinearizer
from services.transcriber import AudioTranscriber
from services.translator import Translator
from settings import get_settings
from utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

subtitle_similarity_threshold = settings.subtitle_similarity_threshold

downloader: Optional[VideoDownloader] = None
transcriber: Optional[AudioTranscriber] = None
analyzer: Optional[JapaneseAnalyzer] = None
aligner: Optional[Aligner] = None
translator: Optional[Translator] = None
subtitle_linearizer: Optional[SubtitleLinearizer] = None
whisper_lock: Optional[asyncio.Semaphore] = None
whisper_lock_label = "transcription"


def init_services():
    global downloader
    global transcriber
    global analyzer
    global aligner
    global translator
    global subtitle_linearizer
    global whisper_lock
    global whisper_lock_label

    try:
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
        whisper_lock = asyncio.Semaphore(1)
        if transcriber is not None:
            whisper_lock_label = f"{transcriber.device.upper()} transcription"
        logger.info("Whisper transcription queue enabled (1 at a time)")
        logger.info(
            "All services initialized successfully. Transcriber running on %s "
            "(fp16=%s, model=%s)",
            transcriber.device,
            transcriber.fp16,
            transcriber.model_size,
        )
    except Exception as e:
        logger.critical(f"Failed to initialize services: {e}", exc_info=True)


def set_executor(executor):
    if translator:
        translator.set_executor(executor)

