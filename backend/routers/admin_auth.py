"""Admin authentication routes - login and logout.

This module contains endpoints for admin login/logout that do not require
an existing admin session.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from api_policy import RateLimitTier
from models import AdminLoginRequest
from routers.decorators import rate_limit
from session_manager import (
    create_admin_session,
    invalidate_admin_session,
    validate_admin_login,
)

router = APIRouter(prefix="/api/admin", tags=["admin-auth"])


class AdminLoginResponse(BaseModel):
    session_id: str
    expires_at: int


@router.post("/login", response_model=AdminLoginResponse)
@rate_limit(RateLimitTier.STRICT)
async def admin_login(
    request: Request,
    login_data: AdminLoginRequest,
):
    """Admin login endpoint.

    Validates admin credentials from environment variables and creates an admin session.

    Returns:
        AdminLoginResponse with session_id and expires_at timestamp
    """
    if not validate_admin_login(login_data):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

    session = create_admin_session(login_data.username)
    return AdminLoginResponse(session_id=session.session_id, expires_at=int(session.expires_at))


@router.post("/logout")
@rate_limit(RateLimitTier.ADMIN)
async def admin_logout(
    request: Request,
    session_id: str = Header(..., alias="X-Admin-Session-Id"),
):
    """Admin logout endpoint.

    Invalidates the admin session.

    Args:
        session_id: Admin session ID from X-Admin-Session-Id header

    Returns:
        Success message
    """
    if invalidate_admin_session(session_id):
        return {"message": "Logged out successfully"}
    raise HTTPException(status_code=404, detail="Session not found")


# Fix: Add missing import
