"""Router module for ShadowPartner API.

This module organizes all API routes by access level:
- public: No authentication required
- auth: Requires X-Session-Id header
- admin_auth: Admin login/logout (no auth required)
- admin: Requires X-Admin-Session-Id header
- playlist: Playlist management (requires admin session)
"""

from routers.admin import router as admin_router
from routers.admin_auth import router as admin_auth_router
from routers.auth import router as auth_router
from routers.playlist import router as playlist_router
from routers.public import router as public_router

__all__ = [
    "public_router",
    "auth_router",
    "admin_auth_router",
    "admin_router",
    "playlist_router",
]
