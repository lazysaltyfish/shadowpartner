from __future__ import annotations

from typing import Optional

from fastapi import Request

from settings import get_settings
from utils.logger import get_logger

CLI_TOKEN_HEADER = "X-CLI-Token"

logger = get_logger(__name__)


def get_cli_token(request: Request) -> Optional[str]:
    return request.headers.get(CLI_TOKEN_HEADER)


def is_cli_token_valid(token: Optional[str]) -> bool:
    if not token:
        return False
    settings = get_settings()
    if not settings.cli_magic_token:
        logger.warning("CLI token provided but CLI_MAGIC_TOKEN is not configured")
        return False
    return token == settings.cli_magic_token


def is_cli_request(request: Request) -> bool:
    return is_cli_token_valid(get_cli_token(request))
