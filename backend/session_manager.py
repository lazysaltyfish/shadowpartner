from __future__ import annotations

import asyncio
import time
import uuid
from typing import Optional

from fastapi import Header, HTTPException, Request

import state
from db.models import User
from models import AdminLoginRequest, AuthSession
from settings import get_settings
from utils.cli_token import is_cli_token_valid
from utils.logger import get_logger

logger = get_logger(__name__)

settings = get_settings()
AUTH_SESSION_SWEEP_SECONDS = 60
ADMIN_SESSION_SWEEP_SECONDS = 300  # 5 minutes
CLI_AUTH_SESSION_ID = "cli-session"
CLI_ADMIN_SESSION_ID = "cli-admin"


def _build_cli_auth_session(request: Request) -> AuthSession:
    created_at = time.time()
    expires_at = created_at + settings.auth_session_ttl_seconds
    ip_address = request.client.host if request.client else "cli"
    return AuthSession(
        session_id=CLI_AUTH_SESSION_ID,
        ip_address=ip_address,
        created_at=created_at,
        expires_at=expires_at,
        user_id=uuid.UUID(int=0),
        is_cli=True,
    )


def _build_cli_admin_session() -> AdminSession:
    created_at = time.time()
    expires_at = created_at + 86400
    return AdminSession(
        session_id=CLI_ADMIN_SESSION_ID,
        username="cli",
        expires_at=expires_at,
    )


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
    """Update session upload statistics. Returns False if limits exceeded.

    Checks limits BEFORE incrementing to ensure accurate enforcement.
    """
    if session.is_cli:
        return True
    async with session.lock:
        if time.time() > session.expires_at:
            return False

        # Check limits BEFORE incrementing
        new_upload_count = session.upload_count + (1 if task_increment else 0)
        new_total_size = session.total_size + file_size

        if new_upload_count > settings.auth_session_max_uploads:
            logger.warning(
                f"Session {session.session_id} exceeded upload count limit: "
                f"{new_upload_count}/{settings.auth_session_max_uploads}"
            )
            return False

        if new_total_size > settings.auth_session_max_total_size:
            logger.warning(
                f"Session {session.session_id} exceeded total size limit: "
                f"{new_total_size}/{settings.auth_session_max_total_size}"
            )
            return False

        # Only increment after passing checks
        session.total_size = new_total_size
        if task_increment:
            session.upload_count = new_upload_count

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
    request: Request,
    session_id: Optional[str] = Header(None, alias="X-Session-Id"),
    cli_token: Optional[str] = Header(None, alias="X-CLI-Token"),
) -> Optional[AuthSession]:
    """Optional session validation - returns None if not provided, raises if invalid."""
    if is_cli_token_valid(cli_token):
        return _build_cli_auth_session(request)
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
    request: Request,
    session_id: Optional[str] = Header(None, alias="X-Session-Id"),
    cli_token: Optional[str] = Header(None, alias="X-CLI-Token"),
) -> AuthSession:
    """FastAPI dependency to validate auth session from header.

    Caches result in request.state to avoid redundant validation when called
    multiple times (e.g., router-level + endpoint-level dependencies).
    """
    # Check cache first
    if hasattr(request.state, "_auth_session"):
        return request.state._auth_session

    if is_cli_token_valid(cli_token):
        session = _build_cli_auth_session(request)
        request.state._auth_session = session
        return session

    if not session_id:
        raise HTTPException(status_code=401, detail="Session required")

    session = validate_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    # Cache for subsequent calls
    request.state._auth_session = session
    return session


# ==================== Admin Session Management ====================


class AdminSession:
    """Admin authentication session for management operations."""

    def __init__(self, session_id: str, username: str, expires_at: float):
        self.session_id = session_id
        self.username = username
        self.expires_at = expires_at


def validate_admin_login(request: AdminLoginRequest) -> bool:
    """Validate admin credentials against environment variables.

    Args:
        request: AdminLoginRequest with username and password

    Returns:
        True if credentials match admin credentials, False otherwise
    """
    settings = get_settings()
    if not settings.admin_username or not settings.admin_password:
        logger.warning("Admin credentials not configured in environment")
        return False

    return (
        request.username == settings.admin_username and request.password == settings.admin_password
    )


def create_admin_session(username: str, ttl_seconds: int = 86400) -> AdminSession:
    """Create a new admin session.

    Args:
        username: Admin username
        ttl_seconds: Time-to-live in seconds (default: 24 hours)

    Returns:
        AdminSession object
    """
    session_id = str(uuid.uuid4())
    created_at = time.time()
    expires_at = created_at + ttl_seconds

    session = AdminSession(session_id=session_id, username=username, expires_at=expires_at)
    state.admin_sessions[session_id] = session
    logger.info(f"Created admin session: {session_id} for user: {username}")
    return session


def validate_admin_session(session_id: str) -> Optional[AdminSession]:
    """Validate admin session and return it if valid, None otherwise.

    Args:
        session_id: Admin session ID to validate

    Returns:
        AdminSession if valid, None otherwise
    """
    if session_id not in state.admin_sessions:
        return None

    session = state.admin_sessions[session_id]

    if time.time() > session.expires_at:
        logger.info(f"Admin session expired: {session_id}")
        del state.admin_sessions[session_id]
        return None

    return session


def invalidate_admin_session(session_id: str) -> bool:
    """Invalidate an admin session. Returns True if session existed and was removed.

    Args:
        session_id: Admin session ID to invalidate

    Returns:
        True if session was found and removed, False otherwise
    """
    if session_id in state.admin_sessions:
        del state.admin_sessions[session_id]
        logger.info(f"Invalidated admin session: {session_id}")
        return True
    return False


async def get_current_admin_session(
    request: Request,
    session_id: Optional[str] = Header(None, alias="X-Admin-Session-Id"),
    cli_token: Optional[str] = Header(None, alias="X-CLI-Token"),
) -> AdminSession:
    """FastAPI dependency to validate admin session from header.

    Caches result in request.state to avoid redundant validation when called
    multiple times (e.g., router-level + endpoint-level dependencies).

    Args:
        request: FastAPI request object
        session_id: Admin session ID from X-Admin-Session-Id header

    Returns:
        AdminSession if valid

    Raises:
        HTTPException 401 if session is missing or invalid
    """
    # Check cache first
    if hasattr(request.state, "_admin_session"):
        return request.state._admin_session

    if is_cli_token_valid(cli_token):
        session = _build_cli_admin_session()
        request.state._admin_session = session
        return session

    if not session_id:
        raise HTTPException(status_code=401, detail="Admin session required")

    session = validate_admin_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired admin session")

    # Cache for subsequent calls
    request.state._admin_session = session
    return session


async def get_current_admin_session_optional(
    request: Request,
    session_id: Optional[str] = Header(None, alias="X-Admin-Session-Id"),
    cli_token: Optional[str] = Header(None, alias="X-CLI-Token"),
) -> Optional[AdminSession]:
    """FastAPI dependency to optionally validate admin session from header.

    Args:
        request: FastAPI request object
        session_id: Admin session ID from X-Admin-Session-Id header

    Returns:
        AdminSession if valid, None if missing or invalid (no exception raised)
    """
    if is_cli_token_valid(cli_token):
        return _build_cli_admin_session()

    if not session_id:
        return None

    return validate_admin_session(session_id)


async def sweep_admin_sessions():
    """Periodically clean up expired admin sessions."""
    while True:
        await asyncio.sleep(ADMIN_SESSION_SWEEP_SECONDS)
        current_time = time.time()
        expired_sessions = [
            session_id
            for session_id, session in state.admin_sessions.items()
            if current_time > session.expires_at
        ]

        for session_id in expired_sessions:
            del state.admin_sessions[session_id]

        if expired_sessions:
            logger.info(f"Cleaned up {len(expired_sessions)} expired admin sessions")
