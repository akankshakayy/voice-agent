"""Tests for Prachi API integration (Phase 7b - DC Mode)."""
import json
import os
import tempfile
import time

import pytest

os.environ["PRACHI_API_URL"] = "https://prachi.eko.in"
os.environ["PRACHI_API_KEY"] = "test_prachi_key_12345"


@pytest.fixture(autouse=True)
def fresh_db():
    from app import db
    from app.seed import seed

    path = os.path.join(tempfile.mkdtemp(), "t.db")
    db.reset_connection(path)
    seed()
    yield


class TestPrachiRecordingSubmission:
    """Test Prachi API recording submission."""

    def test_send_to_prachi_api_success(self):
        """Test successful Prachi API submission."""
        from app import db, recordings
        from unittest.mock import patch, MagicMock

        # Create a DC mode recording with transcript
        rid = db.x(
            """INSERT INTO recordings(sha256, dc_id, mode, file_path, size_bytes, duration_sec,
                                     direction, other_number, status, transcript_json, uploaded_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "abc123",
                1,
                "dc",
                "dc1/2025-01-15/abc123.ogg",
                1000,
                120,
                "incoming",
                "9876543210",
                "done",
                json.dumps([{"text": "Test transcript", "speaker": "csp"}]),
                time.time(),
            ),
        )

        # Mock requests.post
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"request_id": "prachi_req_123"}

        with patch("requests.post", return_value=mock_response):
            rec = db.q("SELECT * FROM recordings WHERE id=?", (rid,), one=True)
            result = recordings.send_to_prachi_api(rec)

        assert result is True
        # Verify database was updated
        rec = db.q("SELECT prachi_api_sent_at, prachi_request_id FROM recordings WHERE id=?", (rid,), one=True)
        assert rec["prachi_api_sent_at"] is not None
        assert rec["prachi_request_id"] == "prachi_req_123"

    def test_send_to_prachi_api_server_error(self):
        """Test Prachi API with server error (retriable)."""
        from app import db, recordings
        from unittest.mock import patch, MagicMock

        rid = db.x(
            """INSERT INTO recordings(sha256, dc_id, mode, file_path, size_bytes, duration_sec,
                                     direction, other_number, status, transcript_json, uploaded_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "abc123",
                1,
                "dc",
                "dc1/2025-01-15/abc123.ogg",
                1000,
                120,
                "incoming",
                "9876543210",
                "done",
                json.dumps([{"text": "Test", "speaker": "csp"}]),
                time.time(),
            ),
        )

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("requests.post", return_value=mock_response):
            rec = db.q("SELECT * FROM recordings WHERE id=?", (rid,), one=True)
            result = recordings.send_to_prachi_api(rec)

        # Should return False (retry)
        assert result is False

    def test_send_to_prachi_api_bad_request(self):
        """Test Prachi API with client error (not retriable)."""
        from app import db, recordings
        from unittest.mock import patch, MagicMock

        rid = db.x(
            """INSERT INTO recordings(sha256, dc_id, mode, file_path, size_bytes, duration_sec,
                                     direction, other_number, status, transcript_json, uploaded_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "abc123",
                1,
                "dc",
                "dc1/2025-01-15/abc123.ogg",
                1000,
                120,
                "incoming",
                "9876543210",
                "done",
                json.dumps([{"text": "Test", "speaker": "csp"}]),
                time.time(),
            ),
        )

        mock_response = MagicMock()
        mock_response.status_code = 400

        with patch("requests.post", return_value=mock_response):
            rec = db.q("SELECT * FROM recordings WHERE id=?", (rid,), one=True)
            result = recordings.send_to_prachi_api(rec)

        # Should return True (don't retry)
        assert result is True

    def test_send_to_prachi_api_timeout(self):
        """Test Prachi API with timeout (retriable)."""
        from app import db, recordings
        from unittest.mock import patch
        import requests

        rid = db.x(
            """INSERT INTO recordings(sha256, dc_id, mode, file_path, size_bytes, duration_sec,
                                     direction, other_number, status, transcript_json, uploaded_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "abc123",
                1,
                "dc",
                "dc1/2025-01-15/abc123.ogg",
                1000,
                120,
                "incoming",
                "9876543210",
                "done",
                json.dumps([{"text": "Test", "speaker": "csp"}]),
                time.time(),
            ),
        )

        with patch("requests.post", side_effect=requests.Timeout("Request timeout")):
            rec = db.q("SELECT * FROM recordings WHERE id=?", (rid,), one=True)
            result = recordings.send_to_prachi_api(rec)

        # Should return False (retry)
        assert result is False

    def test_send_to_prachi_api_no_transcript(self):
        """Test that recording without transcript is skipped."""
        from app import db, recordings
        from unittest.mock import patch

        rid = db.x(
            """INSERT INTO recordings(sha256, dc_id, mode, file_path, size_bytes, duration_sec,
                                     direction, other_number, status, transcript_json, uploaded_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "abc123",
                1,
                "dc",
                "dc1/2025-01-15/abc123.ogg",
                1000,
                120,
                "incoming",
                "9876543210",
                "done",
                None,  # No transcript
                time.time(),
            ),
        )

        with patch("requests.post") as mock_post:
            rec = db.q("SELECT * FROM recordings WHERE id=?", (rid,), one=True)
            result = recordings.send_to_prachi_api(rec)

        # Should return True (skipped) and not call post
        assert result is True
        mock_post.assert_not_called()

    def test_send_to_prachi_api_missing_config(self):
        """Test that missing Prachi config is handled gracefully."""
        from app import db, recordings
        from unittest.mock import patch

        rid = db.x(
            """INSERT INTO recordings(sha256, dc_id, mode, file_path, size_bytes, duration_sec,
                                     direction, other_number, status, transcript_json, uploaded_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "abc123",
                1,
                "dc",
                "dc1/2025-01-15/abc123.ogg",
                1000,
                120,
                "incoming",
                "9876543210",
                "done",
                json.dumps([{"text": "Test", "speaker": "csp"}]),
                time.time(),
            ),
        )

        # Mock missing environment variables
        with patch.dict(os.environ, {"PRACHI_API_URL": "", "PRACHI_API_KEY": ""}):
            rec = db.q("SELECT * FROM recordings WHERE id=?", (rid,), one=True)
            result = recordings.send_to_prachi_api(rec)

        # Should return True (skipped)
        assert result is True


class TestPrachiRecordingTracking:
    """Test database tracking of Prachi submissions."""

    def test_prachi_submission_status_tracking(self):
        """Test that Prachi submission status is tracked correctly."""
        from app import db

        # Create a prachi submission record
        sid = db.x(
            """INSERT INTO prachi_submissions(recording_id, dc_id, dc_name, dc_phone,
                                             caller_number, recipient_number, call_direction,
                                             duration_sec, uploaded_at, status, attempts)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                123,
                1,
                "DC Name",
                "9876543210",
                "9999999999",
                "9111111111",
                "inbound",
                120,
                "2025-01-15T10:00:00Z",
                "submitted",
                1,
            ),
        )

        # Verify submission was created
        sub = db.q("SELECT * FROM prachi_submissions WHERE id=?", (sid,), one=True)
        assert sub["recording_id"] == 123
        assert sub["status"] == "submitted"
        assert sub["attempts"] == 1
        assert sub["prachi_request_id"] is None

        # Update with request ID
        db.update("prachi_submissions", sid, prachi_request_id="prachi_req_456", status="processed")

        # Verify update
        sub = db.q("SELECT * FROM prachi_submissions WHERE id=?", (sid,), one=True)
        assert sub["prachi_request_id"] == "prachi_req_456"
        assert sub["status"] == "processed"
