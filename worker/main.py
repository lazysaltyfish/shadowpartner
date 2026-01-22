"""Whisper GPU Worker - Main entry point."""

import asyncio
import signal
import sys

from client import WhisperWorkerClient
from logger import get_logger

logger = get_logger(__name__)

worker: WhisperWorkerClient | None = None


def signal_handler(sig, frame):
    """Handle shutdown signals gracefully."""
    logger.info("Shutting down...")
    if worker:
        worker.stop()
    sys.exit(0)


def main():
    """Main entry point."""
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create and start worker
    global worker
    worker = WhisperWorkerClient()

    try:
        asyncio.run(worker.start())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Worker error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
