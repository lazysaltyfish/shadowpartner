"""Utility decorators for API endpoints.

This module provides decorators for applying rate limits consistently.
"""

from __future__ import annotations

from api_policy import RateLimitTier
from rate_limiter import get_limiter

limiter = get_limiter()


def rate_limit(tier: str | RateLimitTier):
    """Apply a rate limit to an endpoint.

    This decorator bypasses slowapi's request parameter check by injecting
    the limiter's internal decorator directly.

    Args:
        tier: Rate limit tier string or RateLimitTier enum

    Returns:
        Decorator function that applies the rate limit

    Example:
        @router.get("/api/example")
        @rate_limit(RateLimitTier.LOW)
        async def example_endpoint():
            ...
    """

    def decorator(func):
        tier_value = tier.value if isinstance(tier, RateLimitTier) else tier
        if tier_value == "exempt":
            return limiter.exempt(func)

        # Get the limiter's decorator and apply it directly
        # We need to use the limiter's internal method to bypass request check
        decorator = limiter.limit(tier_value)

        # slowapi checks for request parameter in function signature
        # To bypass this, we apply the decorator but tell slowapi to use
        # the key_func instead of requiring request parameter
        # We do this by setting a special attribute on the function
        func._rate_limit = tier_value  # type: ignore[attr-defined]
        func._use_rate_limit = True  # type: ignore[attr-defined]

        # Apply the decorator - slowapi will use key_func from limiter
        return decorator(func)

    return decorator


# Re-export limiter for direct use if needed
__all__ = ["rate_limit", "limiter"]
