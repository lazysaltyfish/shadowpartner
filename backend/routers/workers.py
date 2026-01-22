"""WebSocket router for GPU worker connections."""

from fastapi import APIRouter, WebSocket

router = APIRouter()


@router.websocket("/ws/worker")
async def worker_websocket(websocket: WebSocket):
    """WebSocket endpoint for GPU worker connections.

    Workers connect to this endpoint to receive transcription jobs.
    The first message must be a 'register' message with authentication token.
    """
    # Import here to avoid circular import
    from services_registry import worker_manager

    if worker_manager is None:
        await websocket.accept()
        await websocket.close(code=1013)
        return

    await worker_manager.handle_connection(websocket)
