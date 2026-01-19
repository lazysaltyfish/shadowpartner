"""API policy configuration for rate limiting and access control.

This module centralizes all rate limit tiers and endpoint policies.
"""

from __future__ import annotations

from enum import Enum


class RateLimitTier(str, Enum):
    """Rate limit tiers for API endpoints.

    Each tier defines a specific rate limit string compatible with slowapi.
    """

    EXEMPT = "exempt"  # Exempt from rate limiting (health checks, etc.)
    LOW = "60/minute"  # Default for public endpoints
    MEDIUM = "30/minute"  # For streaming endpoints
    HIGH = "120/minute"  # For frequent polling
    UPLOAD = "5/minute"  # For expensive operations (upload/process)
    CHUNK = "300/minute"  # For chunked upload
    STRICT = "10/minute"  # For sensitive operations (login)
    ADMIN = "60/minute"  # For admin endpoints


# Pre-defined rate limit values for easy reference
DEFAULT_RATE_LIMIT = RateLimitTier.LOW.value
