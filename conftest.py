"""Pytest configuration."""
import pytest
import tempfile
import os
from app import db, telemetry

pytest_plugins = ("pytest_asyncio",)


@pytest.fixture(autouse=True)
def reset_database():
    """Reset database before each test."""
    # Create a temporary database for this test
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db.reset_connection(db_path)
        yield
    # Clean up: stop telemetry thread before closing connection
    telemetry.shutdown()
    db.reset_connection()
