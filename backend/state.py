from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional

from models import TaskInfo, TaskStatus, UploadSession
from utils.task_manager import TaskManager

# In-memory task store (Use Redis/DB in production)
tasks: Dict[str, TaskInfo] = {}
upload_sessions: Dict[str, UploadSession] = {}

# Global thread pool executor for CPU-bound tasks
executor: Optional[ThreadPoolExecutor] = None
upload_session_sweeper_task: Optional[asyncio.Task] = None
task_manager: Optional[TaskManager] = None


def update_task(
    task_id: str,
    status: TaskStatus,
    progress: int = 0,
    message: str = "",
    result: Optional[object] = None,
    error: Optional[str] = None,
):
    if task_id in tasks:
        tasks[task_id].status = status
        tasks[task_id].progress = progress
        tasks[task_id].message = message
        if result:
            tasks[task_id].result = result
        if error:
            tasks[task_id].error = error
