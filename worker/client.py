"""WebSocket client for Whisper GPU Worker."""

from __future__ import annotations

import asyncio
import json

import websockets
from config import load_config
from downloader import AudioDownloader
from logger import get_logger
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
        self._running = False

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
            logger.info(f"Job complete: {job_id}")

        except Exception as e:
            logger.error(f"Job failed: {job_id} - {e}")
            await _send_job_failed(self.ws, job_id, str(e))
        finally:
            # Cleanup
            await self.downloader.cleanup(job_id)
            self.current_job_id = None

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
