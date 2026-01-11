from __future__ import annotations

from typing import Callable, TypeVar

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_T = TypeVar("_T")

DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_MIN_SECONDS = 2
DEFAULT_RETRY_MAX_SECONDS = 10

RETRYABLE_HTTP_EXCEPTIONS = (httpx.TimeoutException, httpx.ConnectError, TimeoutError)


def retry_on_http_errors(
    attempts: int = DEFAULT_RETRY_ATTEMPTS,
) -> Callable[[Callable[..., _T]], Callable[..., _T]]:
    return retry(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(
            multiplier=1,
            min=DEFAULT_RETRY_MIN_SECONDS,
            max=DEFAULT_RETRY_MAX_SECONDS,
        ),
        retry=retry_if_exception_type(RETRYABLE_HTTP_EXCEPTIONS),
        reraise=True,
    )


def retry_on_ytdlp_errors(
    attempts: int = DEFAULT_RETRY_ATTEMPTS,
) -> Callable[[Callable[..., _T]], Callable[..., _T]]:
    import yt_dlp

    retryable = (
        yt_dlp.utils.DownloadError,
        yt_dlp.utils.ExtractorError,
        TimeoutError,
        ConnectionError,
    )
    return retry(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(
            multiplier=1,
            min=DEFAULT_RETRY_MIN_SECONDS,
            max=DEFAULT_RETRY_MAX_SECONDS,
        ),
        retry=retry_if_exception_type(retryable),
        reraise=True,
    )
