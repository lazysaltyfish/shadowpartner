"""Pytest configuration for test database isolation.

This module ensures tests use a separate test database instead of the production database.
"""

from __future__ import annotations

import os
import tempfile

_test_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_test_db_path = _test_db_file.name
_test_db_file.close()

os.environ["DATABASE_URL"] = f"sqlite:///{_test_db_path}"

import atexit  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402


def _cleanup_test_db():
    try:
        os.unlink(_test_db_path)
    except OSError:
        pass


atexit.register(_cleanup_test_db)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Set up test database engine and session factory."""
    from db.engine import engine
    from db.models import Asset, SubtitleTrack, User  # noqa: F401

    SQLModel.metadata.create_all(engine)

    yield engine


@pytest.fixture(scope="function", autouse=True)
def clean_database(setup_test_database):
    """Clean database tables after each test function."""
    test_engine = setup_test_database

    yield

    with test_engine.connect() as conn:
        conn.execute(text("DELETE FROM subtitle_track"))
        conn.execute(text("DELETE FROM asset"))
        conn.execute(text("DELETE FROM user"))
        conn.commit()
