"""WebSocket client for Whisper GPU Worker."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
from typing import Any

import ffmpeg
import websockets
from config import load_config
from downloader import AudioDownloader
from logger import get_logger
from text_utils import clean_segments
from transcriber import WhisperTranscriber

logger = get_logger(__name__)


def _validate_capability_mismatch(
    requested: str | bool | None,
    actual: str | bool,
    capability_name: str,
) -> str | None:
    """Validate a worker capability against requested value.

    Args:
        requested: Requested capability value
        actual: Worker's actual capability value
        capability_name: Name of the capability (for error message)

    Returns:
        Error message if mismatch, None otherwise
    """
    if requested != actual:
        return (
            f"{capability_name} mismatch: requested {requested}, "
            f"worker has {actual}"
        )
    return None


async def _send_job_failed(ws: websockets.WebSocketClientProtocol, job_id: str, error: str):
    """Send a job_failed message to the server.

    Args:
        ws: WebSocket connection
        job_id: Job ID that failed
        error: Error message
    """
    msg = {
        "type": "job_failed",
        "job_id": job_id,
        "error": error,
    }
    try:
        await ws.send(json.dumps(msg))
    except Exception:
        logger.warning(f"Failed to send job_failed for {job_id}: connection closed")


def _generate_thumbnail_b64(source_path: str, timestamp: float) -> str:
    """Generate a JPEG thumbnail and return base64 payload."""
    temp_path = None
    capture_time = max(0.0, timestamp)
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            temp_path = tmp.name

        (
            ffmpeg.input(source_path, ss=capture_time)
            .output(
                temp_path,
                vframes=1,
                qscale=2,
                vf="scale=640:-1",
                an=None,
            )
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )

        with open(temp_path, "rb") as handle:
            return base64.b64encode(handle.read()).decode("ascii")
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def _annotate_segments_with_mecab(analyzer: Any, segments: list[dict]) -> None:
    """Attach mecab_tokens to each segment in-place."""
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        text = segment.get("text", "").strip()
        if not text:
            segment["mecab_tokens"] = []
            continue
        segment["mecab_tokens"] = analyzer.analyze(text)


def _analyze_texts(analyzer: Any, texts: list[str]) -> list[list[dict]]:
    """Analyze a list of texts into mecab token lists."""
    return analyzer.analyze_batch(texts)


class WhisperWorkerClient:
    """WebSocket client for GPU worker."""

    def __init__(self, config_path: str | None = None):
        """Initialize worker client.

        Args:
            config_path: Optional path to .env file (reserved for future use)
        """
        _ = config_path  # Reserved for future use
        self.config = load_config()
        self.reconnect_delay = 1
        self.max_reconnect_delay = 30
        self.current_job_id: str | None = None
        self.ws: websockets.WebSocketClientProtocol | None = None
        self.downloader = AudioDownloader(self.config.audio_cache_dir)
        self.transcriber = WhisperTranscriber(
            model_size=self.config.whisper_model_size,
            device=self.config.whisper_device,
            fp16=self.config.whisper_fp16,
        )
        self._analyzer = None
        self._running = False
        self._pending_cleanup_jobs: set[str] = set()

    async def start(self):
        """Start the worker client (connect and run forever)."""
        # Load model before connecting
        logger.info("Loading Whisper model...")
        self.transcriber.load_model()
        logger.info("Model loaded, starting connection...")

        self._running = True

        while self._running:
            try:
                await self._connect()
                # Reset delay on successful connection
                self.reconnect_delay = 1
            except Exception as e:
                logger.warning(f"Connection error: {e}")
                if self._running:
                    await self._reconnect()

    def stop(self):
        """Stop the worker client."""
        self._running = False
        if self.ws:
            # Notify server about in-progress job failure
            if self.current_job_id:
                logger.info(f"Aborting job {self.current_job_id} due to shutdown")
                asyncio.create_task(
                    _send_job_failed(
                        self.ws,
                        self.current_job_id,
                        "Worker shutdown during processing",
                    )
                )
            asyncio.create_task(self.ws.close())

    async def _connect(self):
        """Connect to backend and handle messages."""
        logger.info(f"Connecting to {self.config.backend_ws_url}...")

        async with websockets.connect(self.config.backend_ws_url) as ws:
            self.ws = ws
            logger.info("Connected")

            # Register worker
            await self._register()

            # Start message loop
            await self._message_loop()

    async def _register(self):
        """Send registration message."""
        msg = {
            "type": "register",
            "token": self.config.worker_token,
            "worker_id": self.config.worker_id,
            "capabilities": {
                "model": self.config.whisper_model_size,
                "device": self.config.whisper_device,
                "fp16": self.config.whisper_fp16,
            },
        }
        await self.ws.send(json.dumps(msg))

        # Wait for registered response
        response = json.loads(await self.ws.recv())
        if response.get("type") == "registered":
            logger.info(f"Registered as: {response['worker_id']}")
        elif response.get("type") == "error":
            raise Exception(f"Registration failed: {response['message']}")

    async def _message_loop(self):
        """Handle incoming messages."""
        heartbeat_task = asyncio.create_task(self._send_heartbeat())

        try:
            async for message in self.ws:
                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "job_assigned":
                    await self._handle_job_assigned(data)
                elif msg_type == "job_complete_ack":
                    await self._handle_job_complete_ack(data)
                elif msg_type == "heartbeat_ack":
                    pass  # Ignore ack
                elif msg_type == "error":
                    logger.error(f"Server error: {data['message']}")
                else:
                    logger.warning(f"Unknown message type: {msg_type}")

        finally:
            heartbeat_task.cancel()

    async def _handle_job_assigned(self, data: dict):
        """Handle job assignment from server.

        Args:
            data: Job assignment message
        """
        job_id = data.get("job_id")
        audio_url = data.get("audio_url")
        options = data.get("options", {})

        if not job_id or not audio_url:
            logger.error("Invalid job assignment")
            return

        self.current_job_id = job_id
        logger.info(f"Job assigned: {job_id}")

        # Validate options against worker capabilities
        requested_model = options.get("model_size", self.config.whisper_model_size)
        requested_fp16 = options.get("fp16", self.config.whisper_fp16)

        # Check model size mismatch
        error = _validate_capability_mismatch(
            requested_model,
            self.config.whisper_model_size,
            "Model size",
        )
        if error:
            logger.error(f"[Client] {error}")
            await _send_job_failed(self.ws, job_id, error)
            self.current_job_id = None
            return

        # Check fp16 mismatch
        error = _validate_capability_mismatch(
            requested_fp16,
            self.config.whisper_fp16,
            "FP16",
        )
        if error:
            logger.error(f"[Client] {error}")
            await _send_job_failed(self.ws, job_id, error)
            self.current_job_id = None
            return

        # Wrap ws.send to JSON-encode dict messages
        async def send_message(msg: dict) -> None:
            await self.ws.send(json.dumps(msg))

        sent_complete = False
        try:
            # Download audio
            audio_path, _ = await self.downloader.download(audio_url, job_id)

            # Enforce cache size limit
            await self.downloader.cleanup_old_files(self.config.max_cache_size_gb)

            # Transcribe with JSON-encoding callback
            result = await self.transcriber.transcribe(
                audio_path=audio_path,
                ws_callback=send_message,
                job_id=job_id,
                language=options.get("language", "ja"),
            )

            clean_segments(result)
            analyzer = self._get_analyzer()
            await asyncio.to_thread(
                _annotate_segments_with_mecab,
                analyzer,
                result.get("segments", []),
            )

            analysis_texts = options.get("analysis_texts")
            if isinstance(analysis_texts, list) and analysis_texts:
                analysis_tokens = await asyncio.to_thread(
                    _analyze_texts,
                    analyzer,
                    analysis_texts,
                )
                result["analysis_tokens"] = analysis_tokens

            if options.get("thumbnail"):
                timestamp = options.get("thumbnail_timestamp", 1.0)
                try:
                    thumbnail_b64 = await asyncio.to_thread(
                        _generate_thumbnail_b64,
                        audio_path,
                        float(timestamp),
                    )
                    result["thumbnail_b64"] = thumbnail_b64
                except Exception as e:
                    logger.warning(f"Thumbnail generation failed for {job_id}: {e}")

            # Send result
            await self.ws.send(
                json.dumps(
                    {
                        "type": "job_complete",
                        "job_id": job_id,
                        "result": result,
                    }
                )
            )
            sent_complete = True
            self._pending_cleanup_jobs.add(job_id)
            logger.info(f"Job complete: {job_id}")

        except Exception as e:
            logger.error(f"Job failed: {job_id} - {e}")
            await _send_job_failed(self.ws, job_id, str(e))
        finally:
            if not sent_complete:
                await self.downloader.cleanup(job_id)
            self.current_job_id = None

    def _get_analyzer(self):
        if self._analyzer is None:
            from analyzer import JapaneseAnalyzer

            self._analyzer = JapaneseAnalyzer()
        return self._analyzer

    async def _handle_job_complete_ack(self, data: dict) -> None:
        job_id = data.get("job_id")
        if not job_id:
            logger.warning("Invalid job_complete_ack")
            return
        if job_id not in self._pending_cleanup_jobs:
            logger.debug(f"Unexpected job_complete_ack for {job_id}")
        await self.downloader.cleanup(job_id)
        self._pending_cleanup_jobs.discard(job_id)
        logger.info(f"Job cleanup acknowledged: {job_id}")

    async def _send_heartbeat(self):
        """Send periodic heartbeat messages."""
        while True:
            try:
                await asyncio.sleep(15)
                if self.ws and not getattr(self.ws, "closed", False):
                    await self.ws.send(json.dumps({"type": "heartbeat"}))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Heartbeat failed: {e}")
                break

    async def _reconnect(self):
        """Wait before reconnecting with exponential backoff."""
        delay = self.reconnect_delay
        logger.info(f"Reconnecting in {delay} seconds...")
        await asyncio.sleep(delay)
        self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)
