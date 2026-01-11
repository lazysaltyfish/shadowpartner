from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import services_registry
import state
from uploads import sweep_upload_sessions
from utils.logger import get_logger
from utils.task_manager import TaskManager

logger = get_logger(__name__)


async def startup_event():
    """Initialize resources on startup."""
    services_registry.init_services()
    state.task_manager = TaskManager(logger)
    state.executor = ThreadPoolExecutor(max_workers=4)
    logger.info("ThreadPoolExecutor initialized with 4 workers")
    services_registry.set_executor(state.executor)
    state.upload_session_sweeper_task = asyncio.create_task(sweep_upload_sessions())
    logger.info("Upload session sweeper started")


async def shutdown_event():
    """Cleanup resources on shutdown."""
    if state.task_manager:
        await state.task_manager.shutdown(timeout=5.0)
    if state.executor:
        logger.info("Shutting down ThreadPoolExecutor")
        state.executor.shutdown(wait=True)
        logger.info("ThreadPoolExecutor shutdown complete")
    if state.upload_session_sweeper_task:
        state.upload_session_sweeper_task.cancel()
        try:
            await state.upload_session_sweeper_task
        except asyncio.CancelledError:
            pass
        logger.info("Upload session sweeper stopped")
