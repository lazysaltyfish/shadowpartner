"""Validation utilities for API endpoints.

This module provides common validation functions used across multiple routers.
"""

import uuid

from fastapi import HTTPException


def parse_uuid(uuid_str: str, entity_name: str = "ID") -> uuid.UUID:
    """Parse UUID string, raising HTTPException if invalid.

    This is a centralized helper for validating UUID strings in API endpoints.
    It provides consistent error messages across all endpoints.

    Args:
        uuid_str: UUID string to parse
        entity_name: Name of entity for error message (e.g., "playlist ID", "asset ID")

    Returns:
        Parsed UUID object

    Raises:
        HTTPException 400 if UUID format is invalid
    """
    try:
        return uuid.UUID(uuid_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {entity_name} format")
