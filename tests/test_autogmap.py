"""Tests for AutoGMap integration (Phase 7a)."""
import asyncio
import json
import os
import tempfile
import time

import pytest

os.environ["AUTOGMAP_ENABLED"] = "true"
os.environ["AUTOGMAP_NUMBERS_URL"] = "https://indev.eko.in/autogmap/api/v1/call-recorder/numbers"
os.environ["AUTOGMAP_RECORDINGS_URL"] = "https://indev.eko.in/autogmap/api/v1/call-recorder/recordings"
os.environ["AUTOGMAP_API_KEY"] = "test_key_12345"
os.environ["AUTOGMAP_SYNC_INTERVAL_MINUTES"] = "15"
os.environ["AUTOGMAP_SYNC_TIMEOUT_SECONDS"] = "30"
os.environ["AUTOGMAP_UPLOAD_RETRY_MAX"] = "3"
os.environ["AUTOGMAP_UPLOAD_RETRY_BACKOFF"] = "60,300,900"


@pytest.fixture(autouse=True)
def fresh_db():
    from app import db
    from app.seed import seed
    import app.autogmap as autogmap_module

    path = os.path.join(tempfile.mkdtemp(), "t.db")
    db.reset_connection(path)
    seed()

    # Clear cached numbers between tests
    autogmap_module._cached_numbers.clear()
    autogmap_module._sync_stats = {
        "last_sync": None,
        "last_sync_success": None,
        "sync_count": 0,
        "sync_failures": 0,
        "failure_streak": 0,
        "numbers_count": 0,
    }

    yield


def test_autogmap_client_initializes_with_api_key():
    """Test that AutoGMapClient initializes with API key."""
    from app.autogmap import AutoGMapClient

    client = AutoGMapClient()
    assert client.api_key == "test_key_12345"


def test_autogmap_client_initializes_with_configured_urls():
    """Test that client initializes with URLs from environment."""
    from app.autogmap import AutoGMapClient

    client = AutoGMapClient()
    assert client.numbers_url == os.environ["AUTOGMAP_NUMBERS_URL"]
    assert client.recordings_url == os.environ["AUTOGMAP_RECORDINGS_URL"]


def test_autogmap_fetch_numbers_success():
    """Test successful fetch_numbers response parsing."""
    from app.autogmap import AutoGMapClient
    from unittest.mock import AsyncMock, patch

    client = AutoGMapClient()

    # Mock the response
    mock_response = {
        "as_of": "2026-01-15T10:30:00Z",
        "count": 3,
        "numbers": [
            {"phone": "9876543210", "local": "98765", "name": "Applicant 1", "since": "2025-10-01"},
            {"phone": "9876543211", "local": "98765", "name": "Applicant 2", "since": "2025-11-01"},
            {"phone": "9876543212", "local": "98765", "name": "Applicant 3", "since": "2025-12-01"},
        ]
    }

    async def mock_get(*args, **kwargs):
        class MockResponse:
            status_code = 200
            def json(self):
                return mock_response
        return MockResponse()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=mock_get):
        result = asyncio.run(client.fetch_numbers())
        assert result["count"] == 3
        assert len(result["numbers"]) == 3
        assert result["numbers"][0]["phone"] == "9876543210"


def test_autogmap_fetch_numbers_auth_error():
    """Test fetch_numbers with 401 authentication error."""
    from app.autogmap import AutoGMapClient, AutoGMapAPIError
    from unittest.mock import AsyncMock, patch

    client = AutoGMapClient()

    async def mock_get(*args, **kwargs):
        class MockResponse:
            status_code = 401
            text = "Unauthorized"
        return MockResponse()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=mock_get):
        with pytest.raises(AutoGMapAPIError) as exc:
            asyncio.run(client.fetch_numbers())
        assert exc.value.status_code == 401
        assert not exc.value.retriable


def test_autogmap_fetch_numbers_server_error():
    """Test fetch_numbers with 500 server error (retriable)."""
    from app.autogmap import AutoGMapClient, AutoGMapAPIError
    from unittest.mock import AsyncMock, patch

    client = AutoGMapClient()

    async def mock_get(*args, **kwargs):
        class MockResponse:
            status_code = 500
            text = "Internal Server Error"
        return MockResponse()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=mock_get):
        with pytest.raises(AutoGMapAPIError) as exc:
            asyncio.run(client.fetch_numbers())
        assert exc.value.status_code == 500
        assert exc.value.retriable


def test_autogmap_fetch_numbers_timeout():
    """Test fetch_numbers with timeout (retriable)."""
    from app.autogmap import AutoGMapClient, AutoGMapAPIError
    from unittest.mock import AsyncMock, patch
    import httpx

    client = AutoGMapClient()

    async def mock_get(*args, **kwargs):
        raise httpx.TimeoutException("Request timeout")

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=mock_get):
        with pytest.raises(AutoGMapAPIError) as exc:
            asyncio.run(client.fetch_numbers())
        assert exc.value.retriable


def test_autogmap_sync_stores_numbers():
    """Test that sync_numbers stores fetched numbers in database."""
    from app.autogmap import AutoGMapSync, AutoGMapClient
    from app import db
    from unittest.mock import AsyncMock, patch

    client = AutoGMapClient()
    sync = AutoGMapSync(client)

    mock_response = {
        "as_of": "2026-01-15T10:30:00Z",
        "count": 2,
        "numbers": [
            {"phone": "9876543210", "local": "98765", "name": "Test User 1", "since": "2025-10-01"},
            {"phone": "9876543211", "local": "98765", "name": "Test User 2", "since": "2025-11-01"},
        ]
    }

    async def mock_fetch(*args, **kwargs):
        return mock_response

    with patch.object(client, "fetch_numbers", side_effect=mock_fetch):
        result = asyncio.run(sync.sync_numbers())
        assert result["success"]
        assert result["count"] == 2
        assert result["new"] == 2

    # Verify numbers are in database
    rows = db.q("SELECT * FROM autogmap_numbers WHERE active=1")
    assert len(rows) == 2
    assert rows[0]["phone"] == "9876543210"


def test_autogmap_sync_updates_existing_numbers():
    """Test that sync updates existing numbers."""
    from app.autogmap import AutoGMapSync, AutoGMapClient
    from app import db
    from unittest.mock import AsyncMock, patch

    # Insert initial number
    db.x(
        "INSERT INTO autogmap_numbers(phone, local, name, since, synced_at, active) VALUES(?, ?, ?, ?, ?, 1)",
        ("9876543210", "98765", "Old Name", "2025-10-01", time.time()),
    )

    client = AutoGMapClient()
    sync = AutoGMapSync(client)

    mock_response = {
        "as_of": "2026-01-15T10:30:00Z",
        "count": 1,
        "numbers": [
            {"phone": "9876543210", "local": "98765", "name": "New Name", "since": "2025-10-01"},
        ]
    }

    async def mock_fetch(*args, **kwargs):
        return mock_response

    with patch.object(client, "fetch_numbers", side_effect=mock_fetch):
        result = asyncio.run(sync.sync_numbers())
        assert result["success"]
        assert result["updated"] == 1
        assert result["new"] == 0

    # Verify name was updated
    row = db.q("SELECT name FROM autogmap_numbers WHERE phone=?", ("9876543210",), one=True)
    assert row["name"] == "New Name"


def test_autogmap_sync_handles_partial_response():
    """Test that sync handles partial responses correctly."""
    from app.autogmap import AutoGMapSync, AutoGMapClient
    from app import db
    from unittest.mock import patch

    # Insert initial numbers
    db.x(
        "INSERT INTO autogmap_numbers(phone, local, name, since, synced_at, active) VALUES(?, ?, ?, ?, ?, 1)",
        ("9876543210", "98765", "User 1", "2025-10-01", time.time()),
    )
    db.x(
        "INSERT INTO autogmap_numbers(phone, local, name, since, synced_at, active) VALUES(?, ?, ?, ?, ?, 1)",
        ("9876543211", "98765", "User 2", "2025-11-01", time.time()),
    )

    client = AutoGMapClient()
    sync = AutoGMapSync(client)

    # Sync returns only one number
    # Current implementation doesn't deactivate missing numbers - they stay in DB
    # This is conservative: if sync fails, we don't lose data
    mock_response = {
        "as_of": "2026-01-15T10:30:00Z",
        "count": 1,
        "numbers": [
            {"phone": "9876543210", "local": "98765", "name": "User 1 Updated", "since": "2025-10-01"},
        ]
    }

    async def mock_fetch(*args, **kwargs):
        return mock_response

    with patch.object(client, "fetch_numbers", side_effect=mock_fetch):
        result = asyncio.run(sync.sync_numbers())
        assert result["success"]
        assert result["count"] == 1
        assert result["updated"] == 1

    # Both numbers stay in DB (conservative: no automatic deactivation)
    rows = db.q("SELECT COUNT(*) as count FROM autogmap_numbers WHERE active=1")
    assert rows[0]["count"] == 2  # Both still active


def test_autogmap_is_number_cached():
    """Test checking if a number is cached."""
    from app.autogmap import AutoGMapSync, AutoGMapClient, load_cached_numbers
    from app import db

    # Insert number directly
    db.x(
        "INSERT INTO autogmap_numbers(phone, local, name, since, synced_at, active) VALUES(?, ?, ?, ?, ?, 1)",
        ("9876543210", "98765", "Test User", "2025-10-01", time.time()),
    )

    client = AutoGMapClient()
    sync = AutoGMapSync(client)

    # Load cache from DB
    load_cached_numbers()

    assert sync.is_number_cached("9876543210")
    assert not sync.is_number_cached("9999999999")
    assert not sync.is_number_cached("")


def test_autogmap_get_stats():
    """Test getting sync statistics."""
    from app.autogmap import AutoGMapSync, AutoGMapClient, load_cached_numbers
    from app import db
    from unittest.mock import patch

    client = AutoGMapClient()
    sync = AutoGMapSync(client)

    # Insert numbers
    for i in range(3):
        db.x(
            "INSERT INTO autogmap_numbers(phone, local, name, since, synced_at, active) VALUES(?, ?, ?, ?, ?, 1)",
            (f"987654321{i}", "98765", f"User {i}", "2025-10-01", time.time()),
        )

    load_cached_numbers()

    mock_response = {
        "as_of": "2026-01-15T10:30:00Z",
        "count": 3,
        "numbers": [
            {"phone": "9876543210", "local": "98765", "name": "User 0", "since": "2025-10-01"},
            {"phone": "9876543211", "local": "98765", "name": "User 1", "since": "2025-10-01"},
            {"phone": "9876543212", "local": "98765", "name": "User 2", "since": "2025-10-01"},
        ]
    }

    async def mock_fetch(*args, **kwargs):
        return mock_response

    with patch.object(client, "fetch_numbers", side_effect=mock_fetch):
        asyncio.run(sync.sync_numbers())

    stats = sync.get_stats()
    assert stats["numbers_count"] == 3
    assert stats["sync_count"] == 1
    assert stats["last_sync_success"] is not None


def test_autogmap_retry_with_backoff():
    """Test that sync tracks retry attempts."""
    from app.autogmap import AutoGMapSync, AutoGMapClient, AutoGMapAPIError
    from unittest.mock import patch

    client = AutoGMapClient()
    sync = AutoGMapSync(client)

    # Mock network error (retriable)
    async def mock_fetch_error(*args, **kwargs):
        raise AutoGMapAPIError("Network timeout", retriable=True)

    with patch.object(client, "fetch_numbers", side_effect=mock_fetch_error):
        result = asyncio.run(sync.sync_numbers())
        assert not result["success"]

    stats = sync.get_stats()
    assert stats["sync_failures"] > 0
    assert stats["failure_streak"] > 0


def test_autogmap_no_retry_on_config_error():
    """Test that config errors don't increment retry counter unnecessarily."""
    from app.autogmap import AutoGMapSync, AutoGMapClient, AutoGMapAPIError
    from unittest.mock import patch

    client = AutoGMapClient()
    sync = AutoGMapSync(client)

    # Mock non-retriable error
    async def mock_fetch_error(*args, **kwargs):
        raise AutoGMapAPIError("Invalid API key", status_code=401, retriable=False)

    with patch.object(client, "fetch_numbers", side_effect=mock_fetch_error):
        result = asyncio.run(sync.sync_numbers())
        assert not result["success"]

    stats = sync.get_stats()
    assert stats["sync_failures"] > 0


def test_autogmap_validates_phone_numbers():
    """Test that invalid phone numbers are skipped silently."""
    from app.autogmap import AutoGMapSync, AutoGMapClient
    from app import db
    from unittest.mock import patch

    client = AutoGMapClient()
    sync = AutoGMapSync(client)

    mock_response = {
        "as_of": "2026-01-15T10:30:00Z",
        "count": 3,
        "numbers": [
            {"phone": "9876543210", "local": "98765", "name": "Valid", "since": "2025-10-01"},
            {"phone": "invalid-phone", "local": "98765", "name": "Invalid", "since": "2025-10-01"},
            {"phone": "", "local": "98765", "name": "Empty", "since": "2025-10-01"},
        ]
    }

    async def mock_fetch(*args, **kwargs):
        return mock_response

    with patch.object(client, "fetch_numbers", side_effect=mock_fetch):
        result = asyncio.run(sync.sync_numbers())
        assert result["success"]
        # Invalid numbers are skipped but don't cause sync to fail

    # Only valid number should be stored (invalid ones are silently skipped)
    rows = db.q("SELECT COUNT(*) as count FROM autogmap_numbers WHERE active=1")
    assert rows[0]["count"] == 1

    # Verify valid number was stored
    row = db.q("SELECT phone FROM autogmap_numbers WHERE active=1", one=True)
    assert row["phone"] == "9876543210"


def test_autogmap_has_number_utility():
    """Test has_number utility function."""
    from app.autogmap import has_number, load_cached_numbers
    from app import db

    # Insert numbers
    db.x(
        "INSERT INTO autogmap_numbers(phone, local, name, since, synced_at, active) VALUES(?, ?, ?, ?, ?, 1)",
        ("9876543210", "98765", "Test", "2025-10-01", time.time()),
    )

    load_cached_numbers()

    assert has_number("9876543210")
    assert not has_number("9999999999")
    assert not has_number("")


def test_autogmap_get_numbers_count():
    """Test get_numbers_count utility function."""
    from app.autogmap import get_numbers_count, load_cached_numbers
    from app import db

    # Insert numbers
    for i in range(5):
        db.x(
            "INSERT INTO autogmap_numbers(phone, local, name, since, synced_at, active) VALUES(?, ?, ?, ?, ?, 1)",
            (f"987654321{i}", "98765", f"User {i}", "2025-10-01", time.time()),
        )

    load_cached_numbers()

    assert get_numbers_count() == 5
