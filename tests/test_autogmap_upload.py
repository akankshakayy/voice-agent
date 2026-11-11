"""Tests for AutoGMap recording upload and retry logic (Phase 7b)."""
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
os.environ["AUTOGMAP_UPLOAD_RETRY_BACKOFF"] = "1,2,3"  # Short delays for testing


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


@pytest.fixture
def test_audio_file():
    """Create a temporary audio file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        # Write some dummy audio data
        f.write(b"OggS\x00\x00\x00\x00" + b"test data" * 100)
        f.flush()
        yield f.name
    try:
        os.unlink(f.name)
    except FileNotFoundError:
        pass


class TestUploadRecording:
    """Test AutoGMapClient.upload_recording() method."""

    def test_upload_recording_success(self, test_audio_file):
        """Test successful recording upload (201 response)."""
        from app.autogmap import AutoGMapClient
        from unittest.mock import AsyncMock, patch

        client = AutoGMapClient()

        async def mock_post(*args, **kwargs):
            class MockResponse:
                status_code = 201
                def json(self):
                    return {"recording_id": "rec_12345", "status": "accepted"}
            return MockResponse()

        async def test_upload():
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post):
                success, status, data = await client.upload_recording(
                    test_audio_file, "9876543210", "inbound", 120
                )
            return success, status, data

        success, status, data = asyncio.run(test_upload())
        assert success is True
        assert status == "uploaded"
        assert data.get("recording_id") == "rec_12345"

    def test_upload_recording_not_in_applicants(self, test_audio_file):
        """Test upload with 422 (not in applicants)."""
        from app.autogmap import AutoGMapClient
        from unittest.mock import AsyncMock, patch

        client = AutoGMapClient()

        async def mock_post(*args, **kwargs):
            class MockResponse:
                status_code = 422
                text = "Not in applicants"
            return MockResponse()

        async def test_upload():
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post):
                success, status, data = await client.upload_recording(
                    test_audio_file, "9999999999", "inbound", 120
                )
            return success, status, data

        success, status, data = asyncio.run(test_upload())
        assert success is False
        assert status == "not_in_applicants"
        assert "not in applicants" in data.get("error", "").lower()

    def test_upload_recording_server_error(self, test_audio_file):
        """Test upload with 500 server error."""
        from app.autogmap import AutoGMapClient
        from unittest.mock import AsyncMock, patch

        client = AutoGMapClient()

        async def mock_post(*args, **kwargs):
            class MockResponse:
                status_code = 500
                text = "Internal Server Error"
            return MockResponse()

        async def test_upload():
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post):
                success, status, data = await client.upload_recording(
                    test_audio_file, "9876543210", "inbound", 120
                )
            return success, status, data

        success, status, data = asyncio.run(test_upload())
        assert success is False
        assert status == "server_error"
        assert data.get("status_code") == 500

    def test_upload_recording_timeout(self, test_audio_file):
        """Test upload with timeout."""
        from app.autogmap import AutoGMapClient
        from unittest.mock import AsyncMock, patch
        import httpx

        client = AutoGMapClient()

        async def mock_post(*args, **kwargs):
            raise httpx.TimeoutException("Request timeout")

        async def test_upload():
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post):
                success, status, data = await client.upload_recording(
                    test_audio_file, "9876543210", "inbound", 120
                )
            return success, status, data

        success, status, data = asyncio.run(test_upload())
        assert success is False
        assert status == "timeout"

    def test_upload_recording_file_not_found(self):
        """Test upload with non-existent file."""
        from app.autogmap import AutoGMapClient

        client = AutoGMapClient()

        async def test_upload():
            success, status, data = await client.upload_recording(
                "/nonexistent/file.ogg", "9876543210", "inbound", 120
            )
            return success, status, data

        success, status, data = asyncio.run(test_upload())
        assert success is False
        assert status == "file_not_found"

    def test_upload_recording_empty_file(self):
        """Test upload with empty file."""
        from app.autogmap import AutoGMapClient

        client = AutoGMapClient()

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.flush()
            path = f.name

        try:
            async def test_upload():
                success, status, data = await client.upload_recording(
                    path, "9876543210", "inbound", 120
                )
                return success, status, data

            success, status, data = asyncio.run(test_upload())
            assert success is False
            assert status == "file_error"
        finally:
            os.unlink(path)

    def test_upload_recording_return_format(self, test_audio_file):
        """Test that upload returns correct tuple format."""
        from app.autogmap import AutoGMapClient
        from unittest.mock import AsyncMock, patch

        client = AutoGMapClient()

        async def mock_post(*args, **kwargs):
            class MockResponse:
                status_code = 201
                def json(self):
                    return {}
            return MockResponse()

        async def test_upload():
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post):
                result = await client.upload_recording(
                    test_audio_file, "9876543210", "inbound", 120
                )
            return result

        result = asyncio.run(test_upload())
        assert isinstance(result, tuple)
        assert len(result) == 3
        success, status, data = result
        assert isinstance(success, bool)
        assert isinstance(status, str)
        assert isinstance(data, dict)


class TestUploadRetryManager:
    """Test UploadRetryManager retry logic."""

    def test_retry_on_server_error(self, test_audio_file):
        """Test that retry manager retries on server error."""
        from app.autogmap import AutoGMapClient, UploadRetryManager
        from unittest.mock import AsyncMock, patch

        client = AutoGMapClient()
        retry_manager = UploadRetryManager(client, max_retries=2)

        attempt_count = 0

        async def mock_upload(*args, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                return False, "server_error", {"error": "Server error"}
            return True, "uploaded", {"recording_id": "rec_123"}

        async def test_upload():
            with patch.object(client, "upload_recording", side_effect=mock_upload):
                success, status, data = await retry_manager.upload_with_retry(
                    test_audio_file, "9876543210", "inbound", 120
                )
            return success, status, data

        success, status, data = asyncio.run(test_upload())
        assert success is True
        assert status == "uploaded"
        assert attempt_count == 3  # First attempt + 2 retries

    def test_no_retry_on_not_in_applicants(self, test_audio_file):
        """Test that retry manager doesn't retry on non-retriable error."""
        from app.autogmap import AutoGMapClient, UploadRetryManager
        from unittest.mock import AsyncMock, patch

        client = AutoGMapClient()
        retry_manager = UploadRetryManager(client, max_retries=2)

        attempt_count = 0

        async def mock_upload(*args, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            return False, "not_in_applicants", {"error": "Not in applicants"}

        async def test_upload():
            with patch.object(client, "upload_recording", side_effect=mock_upload):
                success, status, data = await retry_manager.upload_with_retry(
                    test_audio_file, "9999999999", "inbound", 120
                )
            return success, status, data

        success, status, data = asyncio.run(test_upload())
        assert success is False
        assert status == "not_in_applicants"
        assert attempt_count == 1  # Only one attempt, no retries

    def test_retry_exhaustion(self, test_audio_file):
        """Test that all retries are exhausted on persistent error."""
        from app.autogmap import AutoGMapClient, UploadRetryManager
        from unittest.mock import AsyncMock, patch

        client = AutoGMapClient()
        retry_manager = UploadRetryManager(client, max_retries=2)

        attempt_count = 0

        async def mock_upload(*args, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            return False, "timeout", {"error": "Timeout"}

        async def test_upload():
            with patch.object(client, "upload_recording", side_effect=mock_upload):
                success, status, data = await retry_manager.upload_with_retry(
                    test_audio_file, "9876543210", "inbound", 120
                )
            return success, status, data

        success, status, data = asyncio.run(test_upload())
        assert success is False
        assert status == "timeout"
        assert attempt_count == 3  # Initial + 2 retries


class TestRecordingIntegration:
    """Test integration of AutoGMap upload with recordings."""

    def test_queue_autogmap_upload_with_valid_number(self):
        """Test queuing upload for number in AutoGMap applicants."""
        from app import db, recordings
        from app.autogmap import load_cached_numbers
        import app.autogmap as autogmap_module

        # Add number to AutoGMap cache
        db.x(
            "INSERT INTO autogmap_numbers(phone, local, name, since, synced_at, active) VALUES(?, ?, ?, ?, ?, 1)",
            ("9876543210", "98765", "Test User", "2025-10-01", time.time()),
        )
        load_cached_numbers()

        # Create a test recording
        rid = db.x(
            """INSERT INTO recordings(sha256, rm_id, mode, file_path, size_bytes, duration_sec, direction, other_number)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
            ("abc123", 1, "rm", "test/file.ogg", 1000, 120, "incoming", "9876543210"),
        )

        # Mock the background upload to avoid threading complexity
        from unittest.mock import patch
        with patch("app.recordings._upload_to_autogmap_background"):
            recordings.queue_autogmap_upload(rid, "test/file.ogg", "9876543210", "inbound", 120)

        # Verify recording status is set to pending
        rec = db.q("SELECT autogmap_status FROM recordings WHERE id=?", (rid,), one=True)
        assert rec["autogmap_status"] == "pending"

    def test_queue_autogmap_upload_with_invalid_number(self):
        """Test queuing upload for number NOT in AutoGMap applicants."""
        from app import db, recordings

        # Don't add the number to AutoGMap cache

        # Create a test recording
        rid = db.x(
            """INSERT INTO recordings(sha256, rm_id, mode, file_path, size_bytes, duration_sec, direction, other_number)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
            ("abc123", 1, "rm", "test/file.ogg", 1000, 120, "incoming", "9999999999"),
        )

        recordings.queue_autogmap_upload(rid, "test/file.ogg", "9999999999", "inbound", 120)

        # Verify recording status is set to not_in_applicants
        rec = db.q("SELECT autogmap_status FROM recordings WHERE id=?", (rid,), one=True)
        assert rec["autogmap_status"] == "not_in_applicants"
