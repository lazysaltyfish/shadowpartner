"""Utility decorators for API endpoints.

This module provides decorators for applying rate limits consistently.
"""

from __future__ import annotations

from functools import wraps
from inspect import iscoroutinefunction
from typing import Any, Callable, Optional

from fastapi import Request

from api_policy import RateLimitTier
from rate_limiter import get_limiter
from utils.cli_token import is_cli_request

limiter = get_limiter()


def _extract_request(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Optional[Request]:
    request = kwargs.get("request")
    if isinstance(request, Request):
        return request
    for arg in args:
        if isinstance(arg, Request):
            return arg
    return None


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

    def decorator(func: Callable[..., Any]):
        tier_value = tier.value if isinstance(tier, RateLimitTier) else tier
        if tier_value == "exempt":
            return limiter.exempt(func)

        limited_func = limiter.limit(tier_value)(func)

        if iscoroutinefunction(func):
            @wraps(func)
            async def wrapper(*args: Any, **kwargs: Any):
                request = _extract_request(args, kwargs)
                if request is not None and is_cli_request(request):
                    return await func(*args, **kwargs)
                return await limited_func(*args, **kwargs)
        else:
            @wraps(func)
            def wrapper(*args: Any, **kwargs: Any):
                request = _extract_request(args, kwargs)
                if request is not None and is_cli_request(request):
                    return func(*args, **kwargs)
                return limited_func(*args, **kwargs)

        wrapper._rate_limit = tier_value  # type: ignore[attr-defined]
        wrapper._use_rate_limit = True  # type: ignore[attr-defined]
        return wrapper

    return decorator


# Re-export limiter for direct use if needed
__all__ = ["rate_limit", "limiter"]
