from __future__ import annotations

import fastapi
from fastapi import Request

from utils.logger import get_logger

logger = get_logger(__name__)


async def log_requests(request: Request, call_next):
    # Skip logging for frequent/unimportant requests
    skip_paths = ["/api/status/", "/api/upload/chunk", "/"]
    should_log = not any(path in str(request.url) for path in skip_paths)

    if should_log:
        logger.info(f"Incoming request: {request.method} {request.url}")

    try:
        response = await call_next(request)

        # Only log non-200 responses for important endpoints
        if should_log and response.status_code != 200:
            logger.info(f"Response status: {response.status_code}")

        return response
    except Exception as e:
        logger.error(f"Request failed: {e}", exc_info=True)
        raise e


async def add_cors_headers(request: Request, call_next):
    # Handle preflight requests
    if request.method == "OPTIONS":
        response = fastapi.Response()
    else:
        try:
            response = await call_next(request)
        except Exception as e:
            logger.error(f"Request failed in CORS middleware: {e}", exc_info=True)
            response = fastapi.Response(status_code=500)

    origin = request.headers.get("origin")

    # If no origin, we can just return (e.g. server-side curl)
    # But for browser requests, we mirror the origin
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        # Cannot use "*" with credentials: true, must echo back the requested headers
        requested_headers = request.headers.get("access-control-request-headers")
        if requested_headers:
            response.headers["Access-Control-Allow-Headers"] = requested_headers
        else:
            response.headers["Access-Control-Allow-Headers"] = (
                "content-type, authorization, x-requested-with"
            )
    else:
        # Fallback for some cases where Origin might be missing but we want to be permissive
        # Note: '*' cannot be used with credentials: true
        pass

    return response


async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses.

    Designed to be permissive for development while providing
    essential security protections for production.
    """
    response = await call_next(request)

    # Prevent MIME type sniffing attacks
    response.headers["X-Content-Type-Options"] = "nosniff"

    # Allow same-origin embedding for flexibility (if needed in future)
    # This prevents clickjacking from external origins
    response.headers["X-Frame-Options"] = "SAMEORIGIN"

    # Enable browser's built-in XSS filter
    # Note: Deprecated by modern browsers but still useful for older browsers
    response.headers["X-XSS-Protection"] = "1; mode=block"

    return response
