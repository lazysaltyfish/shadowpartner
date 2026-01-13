from __future__ import annotations

import asyncio
import time
import uuid
from typing import Optional

from fastapi import Header, HTTPException, Request

import state
from db.models import User
from models import AuthSession
from settings import get_settings
from utils.logger import get_logger

logger = get_logger(__name__)

settings = get_settings()
AUTH_SESSION_SWEEP_SECONDS = 60


def create_session(ip_address: str, user: User) -> AuthSession:
    """Create a new anonymous authentication session with Guest User record."""
    session_id = str(uuid.uuid4())
    created_at = time.time()
    expires_at = created_at + settings.auth_session_ttl_seconds

    session = AuthSession(
        session_id=session_id,
        ip_address=ip_address,
        created_at=created_at,
        expires_at=expires_at,
        user_id=user.id,
    )

    state.auth_sessions[session_id] = session
    logger.info(f"Created auth session: {session_id} for IP: {ip_address}, user_id: {user.id}")
    return session


def validate_session(session_id: str) -> Optional[AuthSession]:
    """Validate session and return it if valid, None otherwise."""
    if session_id not in state.auth_sessions:
        return None

    session = state.auth_sessions[session_id]

    if time.time() > session.expires_at:
        logger.info(f"Session expired: {session_id}")
        del state.auth_sessions[session_id]
        return None

    return session


def invalidate_session(session_id: str) -> bool:
    """Invalidate a session. Returns True if session existed and was removed."""
    if session_id in state.auth_sessions:
        del state.auth_sessions[session_id]
        logger.info(f"Invalidated session: {session_id}")
        return True
    return False


async def update_session_upload(
    session: AuthSession, file_size: int, task_increment: bool = False
) -> bool:
    """Update session upload statistics. Returns False if limits exceeded."""
    async with session.lock:
        if time.time() > session.expires_at:
            return False

        session.total_size += file_size

        if task_increment:
            session.upload_count += 1

        if session.upload_count > settings.auth_session_max_uploads:
            logger.warning(
                f"Session {session.session_id} exceeded upload count limit: "
                f"{session.upload_count}/{settings.auth_session_max_uploads}"
            )
            return False

        if session.total_size > settings.auth_session_max_total_size:
            logger.warning(
                f"Session {session.session_id} exceeded total size limit: "
                f"{session.total_size}/{settings.auth_session_max_total_size}"
            )
            return False

    return True


def cleanup_expired_sessions() -> int:
    """Remove all expired sessions. Returns count of removed sessions."""
    current_time = time.time()
    expired_sessions = [
        session_id
        for session_id, session in state.auth_sessions.items()
        if current_time > session.expires_at
    ]

    for session_id in expired_sessions:
        del state.auth_sessions[session_id]

    if expired_sessions:
        logger.info(f"Cleaned up {len(expired_sessions)} expired auth sessions")

    return len(expired_sessions)


async def get_current_session_optional(
    request: Request, session_id: Optional[str] = Header(None, alias="X-Session-Id")
) -> Optional[AuthSession]:
    """Optional session validation - returns None if not provided, raises if invalid."""
    if not session_id:
        return None

    session = validate_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return session


def get_session_stats() -> dict:
    """Get statistics about current auth sessions."""
    return {
        "total_sessions": len(state.auth_sessions),
        "total_uploads": sum(s.upload_count for s in state.auth_sessions.values()),
        "total_size_bytes": sum(s.total_size for s in state.auth_sessions.values()),
    }


async def sweep_auth_sessions():
    """Periodically clean up expired auth sessions."""
    while True:
        await asyncio.sleep(AUTH_SESSION_SWEEP_SECONDS)
        cleanup_expired_sessions()


async def get_current_session(
    request: Request, session_id: Optional[str] = Header(None, alias="X-Session-Id")
) -> AuthSession:
    """FastAPI dependency to validate auth session from header."""
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required")

    session = validate_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    return session
