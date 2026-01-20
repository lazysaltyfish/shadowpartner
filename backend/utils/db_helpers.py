"""Database helper utilities.

This module provides common helper functions for database operations
that are used across multiple routers.
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy.sql import ColumnElement


def as_clause(value: Any) -> ColumnElement[bool]:
    """Cast value to SQLAlchemy boolean clause for Pyright compatibility.

    This helper function is used to tell Pyright the type of SQLAlchemy
    query clauses, which otherwise would be inferred as `Any`.

    Args:
        value: A SQLAlchemy expression that evaluates to a boolean clause

    Returns:
        The same value, cast to ColumnElement[bool] for type checking
    """
    return cast(ColumnElement[bool], value)
