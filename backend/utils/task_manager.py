from __future__ import annotations

import asyncio
from typing import Optional, Set


class TaskManager:
    def __init__(self, logger):
        self._logger = logger
        self._tasks: Set[asyncio.Task] = set()
        self._closing = False

    @property
    def closing(self) -> bool:
        return self._closing

    def create_task(self, coro, name: Optional[str] = None) -> asyncio.Task:
        if self._closing:
            raise RuntimeError("Task manager is shutting down")
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return task

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            self._logger.info("Background task cancelled")
        except Exception:
            self._logger.error("Background task failed", exc_info=True)

    async def shutdown(self, timeout: float = 5.0) -> None:
        self._closing = True
        if not self._tasks:
            return

        tasks = set(self._tasks)
        self._logger.info(f"Waiting up to {timeout:.1f}s for {len(tasks)} background tasks")
        done, pending = await asyncio.wait(tasks, timeout=timeout)

        if pending:
            self._logger.warning(f"Cancelling {len(pending)} background tasks after timeout")
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
