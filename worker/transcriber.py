"""Whisper transcriber with progress reporting for GPU Worker."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

import ffmpeg
import whisper
from logger import get_logger

logger = get_logger(__name__)


class ProgressReporter:
    """Progress reporter for transcription jobs."""

    def __init__(self, ws_callback: Callable, job_id: str, total_duration: float):
        """Initialize progress reporter.

        Args:
            ws_callback: Async callback to send progress updates
            job_id: Job ID for progress messages
            total_duration: Audio duration in seconds
        """
        self.ws_callback = ws_callback
        self.job_id = job_id
        self.total_duration = total_duration
        self.start_time: Optional[float] = None
        self.last_report = 0
        self.last_report_time = 0
        # Initial estimate: GPU processes ~6-7x faster than real-time
        self.processing_rate = 0.15  # seconds processing / second audio

    async def start(self):
        """Start progress tracking."""
        self.start_time = time.time()
        self.last_report_time = time.time()
        await self._send_progress(0, "Loading model...")

    async def phase(self, phase: str, progress: int):
        """Report a specific phase.

        Args:
            phase: Phase name (loading, preload, transcribing, postprocess)
            progress: Progress percentage (0-100)
        """
        messages = {
            "loading": "Loading model...",
            "preload": "Preprocessing audio...",
            "transcribing": "Transcribing...",
            "postprocess": "Post-processing...",
        }
        message = messages.get(phase, phase)
        await self._send_progress(progress, message)

    async def update(self):
        """Update progress based on elapsed time."""
        if not self.start_time:
            return

        elapsed = time.time() - self.start_time
        # Estimate progress based on processing rate
        estimated_total = self.total_duration * self.processing_rate
        progress = min(int(elapsed / estimated_total * 100), 95)

        # Report every 5% or every 5 seconds
        now = time.time()
        if progress - self.last_report >= 5 or now - self.last_report_time >= 5:
            await self._send_progress(progress, "Transcribing...")
            self.last_report = progress
            self.last_report_time = now

    async def complete(self):
        """Mark job as complete and update processing rate."""
        await self._send_progress(100, "Complete")
        if self.start_time and self.total_duration > 0:
            elapsed = time.time() - self.start_time
            self.processing_rate = elapsed / self.total_duration
            logger.info(f"[Transcriber] Processing rate: {self.processing_rate:.3f}x")

    async def _send_progress(self, progress: int, message: str):
        """Send progress update via WebSocket callback.

        Args:
            progress: Progress percentage (0-100)
            message: Status message
        """
        try:
            await self.ws_callback(
                {
                    "type": "job_progress",
                    "job_id": self.job_id,
                    "progress": progress,
                    "message": message,
                }
            )
        except Exception as e:
            logger.warning(f"[Transcriber] Failed to send progress: {e}")


class WhisperTranscriber:
    """Whisper transcriber for GPU worker."""

    def __init__(
        self, model_size: str = "base", device: str = "cuda", fp16: bool = False
    ):
        """Initialize transcriber.

        Args:
            model_size: Whisper model size (tiny, base, small, medium, large)
            device: Device to run on (cuda, cpu, None for auto)
            fp16: Whether to use FP16 precision
        """
        self.model_size = model_size
        self.device = device
        self.fp16 = fp16
        self.model: Optional[whisper.Whisper] = None
        self.executor = ThreadPoolExecutor(max_workers=1)

    def load_model(self):
        """Load Whisper model (blocking, call during startup)."""
        logger.info(f"[Transcriber] Loading model: {self.model_size} on {self.device}")
        self.model = whisper.load_model(self.model_size, device=self.device)
        logger.info("[Transcriber] Model loaded successfully")

    async def transcribe(
        self,
        audio_path: str,
        ws_callback: Callable,
        job_id: str,
        language: str = "ja",
    ) -> dict:
        """Transcribe audio file with progress reporting.

        Args:
            audio_path: Path to audio file
            ws_callback: Async callback to send progress updates (receives dict)
            job_id: Job ID for progress messages
            language: Language code (default: ja for Japanese)

        Returns:
            Transcription result dict with segments and language info

        Raises:
            Exception: If transcription fails - caller should handle WebSocket
                error notification (job_failed message) after catching.
        """
        if not self.model:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        # Get audio duration for progress estimation
        logger.info(f"[Transcriber] Getting audio duration: {audio_path}")
        try:
            probe = ffmpeg.probe(audio_path)
            duration = float(probe["format"]["duration"])
        except Exception as e:
            logger.warning(
                f"[Transcriber] Could not get duration: {e}, using default 60s"
            )
            duration = 60.0

        reporter = ProgressReporter(ws_callback, job_id, duration)

        try:
            await reporter.start()
            await reporter.phase("preload", 5)

            # Run transcription in thread pool to avoid blocking event loop
            loop = asyncio.get_event_loop()

            # Start progress updates
            progress_task = asyncio.create_task(self._progress_loop(reporter))

            try:
                result = await loop.run_in_executor(
                    self.executor,
                    lambda: self.model.transcribe(
                        audio_path,
                        language=language,
                        word_timestamps=True,
                        fp16=self.fp16,
                    ),
                )
            finally:
                progress_task.cancel()

            await reporter.phase("postprocess", 95)
            await reporter.complete()

            logger.info(f"[Transcriber] Transcription complete: {job_id}")

            return {
                "segments": result.get("segments", []),
                "language": result.get("language", language),
                "language_probs": result.get("language_probs", {}),
            }

        except Exception as e:
            logger.error(f"[Transcriber] Transcription failed: {e}")
            # Re-raise for caller to handle WebSocket error notification
            raise

    async def _progress_loop(self, reporter: ProgressReporter):
        """Background task to update progress during transcription.

        Args:
            reporter: Progress reporter instance
        """
        try:
            while True:
                await asyncio.sleep(1)
                await reporter.update()
        except asyncio.CancelledError:
            pass
