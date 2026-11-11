"""Tests for Prachi Google Sheets sync system.

Test coverage:
  - CSV parsing (DCs and SBI officials)
  - Change detection (new, updated, deleted)
  - Database operations (soft delete)
  - Error handling (network, invalid format, missing columns)
  - Sync history tracking
"""
import asyncio
import csv
import io
import json
import sqlite3
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import db, prachi_sync


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    # Initialize test database
    conn = sqlite3.connect(db_path)
    conn.executescript(db.SCHEMA)
    conn.close()

    original_path = db.DB_PATH
    db.DB_PATH = db_path
    db._conn = None  # Reset connection

    yield db_path

    # Cleanup
    db.DB_PATH = original_path
    db._conn = None
    import os
    os.unlink(db_path)


class TestPrachiGoogleSheetsClient:
    """Tests for PrachiGoogleSheetsClient."""

    async def test_init_missing_sheet_id(self):
        """Should raise error if sheet_id not provided."""
        with pytest.raises(prachi_sync.PrachiConfigError):
            prachi_sync.PrachiGoogleSheetsClient("")

    async def test_fetch_dcs_empty_sheet(self, temp_db):
        """Should handle empty DCs sheet."""
        client = prachi_sync.PrachiGoogleSheetsClient("test-id", timeout_sec=5)

        with patch.object(client, "_fetch_sheet_csv") as mock_fetch:
            mock_fetch.return_value = ""

            dcs = await client.fetch_dcs()
            assert dcs == []

        await client.close()

    async def test_fetch_dcs_valid_csv(self, temp_db):
        """Should parse valid DCs CSV."""
        client = prachi_sync.PrachiGoogleSheetsClient("test-id", timeout_sec=5)

        csv_data = """DC name,DC mobile number,Count
DC1,9876543210,100
DC2,9876543211,50"""

        with patch.object(client, "_fetch_sheet_csv") as mock_fetch:
            mock_fetch.return_value = csv_data

            dcs = await client.fetch_dcs()

            assert len(dcs) == 2
            assert dcs[0].name == "DC1"
            assert dcs[0].phone == "9876543210"
            assert dcs[1].name == "DC2"
            assert dcs[1].phone == "9876543211"

        await client.close()

    async def test_fetch_dcs_invalid_phone(self, temp_db):
        """Should skip rows with invalid phone format."""
        client = prachi_sync.PrachiGoogleSheetsClient("test-id", timeout_sec=5)

        csv_data = """DC name,DC mobile number,Count
DC1,9876543210,100
DC2,invalid-phone,50
DC3,9876543211,75"""

        with patch.object(client, "_fetch_sheet_csv") as mock_fetch:
            mock_fetch.return_value = csv_data

            dcs = await client.fetch_dcs()

            # Should skip DC2 with invalid phone
            assert len(dcs) == 2
            assert dcs[0].name == "DC1"
            assert dcs[1].name == "DC3"

        await client.close()

    async def test_fetch_dcs_missing_columns(self, temp_db):
        """Should skip rows missing required columns."""
        client = prachi_sync.PrachiGoogleSheetsClient("test-id", timeout_sec=5)

        csv_data = """DC name,Count
DC1,100"""

        with patch.object(client, "_fetch_sheet_csv") as mock_fetch:
            mock_fetch.return_value = csv_data

            dcs = await client.fetch_dcs()

            # Should skip row missing phone
            assert len(dcs) == 0

        await client.close()

    async def test_fetch_sbi_officials_valid_csv(self, temp_db):
        """Should parse valid SBI officials CSV."""
        client = prachi_sync.PrachiGoogleSheetsClient("test-id", timeout_sec=5)

        csv_data = """DC Name,Mobile Number,Description
DC1,9876543210,Officer A
DC2,9876543211,Officer B"""

        with patch.object(client, "_fetch_sheet_csv") as mock_fetch:
            mock_fetch.return_value = csv_data

            officials = await client.fetch_sbi_officials()

            assert len(officials) == 2
            assert officials[0].phone == "9876543210"
            assert officials[0].dc_name == "DC1"
            assert officials[0].description == "Officer A"

        await client.close()

    async def test_fetch_sheet_csv_network_error(self, temp_db):
        """Should raise PrachiAPIError on network error."""
        client = prachi_sync.PrachiGoogleSheetsClient("test-id", timeout_sec=5)

        import httpx
        with patch.object(client.client, "get") as mock_get:
            mock_get.side_effect = httpx.RequestError("Network error")

            with pytest.raises(prachi_sync.PrachiAPIError):
                await client._fetch_sheet_csv(0)

        await client.close()

    async def test_fetch_sheet_csv_server_error(self, temp_db):
        """Should raise PrachiAPIError on server error (5xx)."""
        client = prachi_sync.PrachiGoogleSheetsClient("test-id", timeout_sec=5)

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_get.return_value = mock_response

            with pytest.raises(prachi_sync.PrachiAPIError) as exc_info:
                await client._fetch_sheet_csv(0)

            assert exc_info.value.retriable is True

        await client.close()


@pytest.mark.asyncio
class TestDailySyncManager:
    """Tests for DailySyncManager."""

    async def test_sync_dcs_insert_new(self, temp_db):
        """Should insert new DCs into database."""
        client = MagicMock()
        manager = prachi_sync.DailySyncManager(client)

        dc_record = prachi_sync.DCRecord(name="DC1", phone="9876543210", region="North")

        client.fetch_dcs = AsyncMock(return_value=[dc_record])

        result = await manager.sync_dcs()

        assert result["success"] is True
        assert result["added"] == 1
        assert result["updated"] == 0
        assert result["deleted"] == 0

        # Verify in database
        rows = db.q("SELECT * FROM dcs WHERE phone=?", ("9876543210",))
        assert len(rows) == 1
        assert rows[0]["name"] == "DC1"
        assert rows[0]["active"] == 1

    async def test_sync_dcs_update_existing(self, temp_db):
        """Should update existing DCs."""
        # Insert initial DC
        db.x(
            """INSERT INTO dcs(name, phone, region, created_by, created_at, active, updated_at)
               VALUES(?, ?, ?, ?, ?, 1, ?)""",
            ("DC1", "9876543210", "South", "test", time.time(), time.time()),
        )

        client = MagicMock()
        manager = prachi_sync.DailySyncManager(client)

        # Update with different region
        dc_record = prachi_sync.DCRecord(name="DC1", phone="9876543210", region="North")

        client.fetch_dcs = AsyncMock(return_value=[dc_record])

        result = await manager.sync_dcs()

        assert result["success"] is True
        assert result["added"] == 0
        assert result["updated"] == 1

        # Verify updated in database
        rows = db.q("SELECT * FROM dcs WHERE phone=?", ("9876543210",))
        assert rows[0]["region"] == "North"

    async def test_sync_dcs_soft_delete(self, temp_db):
        """Should mark DCs inactive when removed from sheet."""
        # Insert DC
        db.x(
            """INSERT INTO dcs(name, phone, region, created_by, created_at, active, updated_at)
               VALUES(?, ?, ?, ?, ?, 1, ?)""",
            ("DC1", "9876543210", "North", "test", time.time(), time.time()),
        )

        client = MagicMock()
        manager = prachi_sync.DailySyncManager(client)

        # Sync with empty sheet (DC no longer exists)
        client.fetch_dcs = AsyncMock(return_value=[])

        result = await manager.sync_dcs()

        assert result["success"] is True
        assert result["deleted"] == 1

        # Verify marked inactive
        rows = db.q("SELECT * FROM dcs WHERE phone=?", ("9876543210",))
        assert rows[0]["active"] == 0

    async def test_sync_sbi_officials_insert_new(self, temp_db):
        """Should insert new SBI officials into allowed_numbers."""
        client = MagicMock()
        manager = prachi_sync.DailySyncManager(client)

        official = prachi_sync.SBIOfficial(phone="9876543210", dc_name="DC1", description="Officer")

        client.fetch_sbi_officials = AsyncMock(return_value=[official])

        result = await manager.sync_sbi_officials()

        assert result["success"] is True
        assert result["added"] == 1

        # Verify in database
        rows = db.q("SELECT * FROM allowed_numbers WHERE phone_number=?", ("9876543210",))
        assert len(rows) == 1
        assert rows[0]["description"] == "Officer"

    async def test_sync_sbi_officials_soft_delete(self, temp_db):
        """Should mark SBI officials inactive when removed from sheet."""
        # Insert allowed number
        db.x(
            """INSERT INTO allowed_numbers(phone_number, description, added_by, added_at, active)
               VALUES(?, ?, ?, ?, 1)""",
            ("9876543210", "Officer", "test", time.time()),
        )

        client = MagicMock()
        manager = prachi_sync.DailySyncManager(client)

        # Sync with empty sheet
        client.fetch_sbi_officials = AsyncMock(return_value=[])

        result = await manager.sync_sbi_officials()

        assert result["success"] is True
        assert result["deleted"] == 1

        # Verify marked inactive
        rows = db.q("SELECT * FROM allowed_numbers WHERE phone_number=?", ("9876543210",))
        assert rows[0]["active"] == 0


@pytest.mark.asyncio
class TestRunDailySync:
    """Tests for run_daily_sync function."""

    async def test_run_daily_sync_success(self, temp_db):
        """Should complete full sync successfully."""
        with patch("app.prachi_sync.PRACHI_SHEET_ID", "test-id"):
            mock_client = MagicMock()
            mock_client.fetch_dcs = AsyncMock(return_value=[])
            mock_client.fetch_sbi_officials = AsyncMock(return_value=[])
            mock_client.close = AsyncMock()

            with patch("app.prachi_sync.PrachiGoogleSheetsClient") as mock_client_class:
                mock_client_class.return_value = mock_client

                result = await prachi_sync.run_daily_sync()

                assert result["success"] is True
                assert result["status"] == "success"
                assert result["dcs"]["success"] is True
                assert result["officials"]["success"] is True
                assert result["duration_sec"] > 0

                # Verify sync history recorded
                rows = db.q("SELECT * FROM prachi_sync_history")
                assert len(rows) > 0
                assert rows[-1]["status"] == "success"

    async def test_run_daily_sync_error_handling(self, temp_db):
        """Should handle sync errors gracefully."""
        with patch("app.prachi_sync.PRACHI_SHEET_ID", ""):
            result = await prachi_sync.run_daily_sync()

            assert result["success"] is False
            assert result["status"] == "failed"

            # Verify failure recorded in history
            rows = db.q("SELECT * FROM prachi_sync_history WHERE status='failed'")
            assert len(rows) > 0


class TestSyncStatus:
    """Tests for sync status tracking."""

    async def test_get_sync_status(self, temp_db):
        """Should return current sync status."""
        status = prachi_sync.get_sync_status()

        assert "last_sync" in status
        assert "last_sync_success" in status
        assert "sync_count" in status
        assert "dcs_count" in status
        assert "officials_count" in status
        assert "last_changes" in status

    async def test_sync_status_after_sync(self, temp_db):
        """Should track sync statistics."""
        # Manually update sync stats (as run_daily_sync would do)
        prachi_sync._sync_stats["dcs_count"] = 1
        prachi_sync._sync_stats["officials_count"] = 2
        prachi_sync._sync_stats["last_sync"] = "2026-11-11T02:00:00Z"

        status = prachi_sync.get_sync_status()
        assert status["dcs_count"] == 1
        assert status["officials_count"] == 2


class TestChangeDetection:
    """Tests for accurate change detection."""

    async def test_no_changes_when_data_same(self, temp_db):
        """Should detect no changes when data is identical."""
        # Insert DC
        db.x(
            """INSERT INTO dcs(name, phone, region, created_by, created_at, active, updated_at)
               VALUES(?, ?, ?, ?, ?, 1, ?)""",
            ("DC1", "9876543210", "North", "test", time.time(), time.time()),
        )

        client = MagicMock()
        manager = prachi_sync.DailySyncManager(client)

        dc_record = prachi_sync.DCRecord(name="DC1", phone="9876543210", region="North")

        client.fetch_dcs = AsyncMock(return_value=[dc_record])

        result = await manager.sync_dcs()

        # No changes should be detected
        assert result["added"] == 0
        assert result["updated"] == 0
        assert result["deleted"] == 0

    async def test_detect_multiple_changes(self, temp_db):
        """Should handle multiple simultaneous changes."""
        # Insert initial DCs
        db.x(
            """INSERT INTO dcs(name, phone, region, created_by, created_at, active, updated_at)
               VALUES(?, ?, ?, ?, ?, 1, ?)""",
            ("DC1", "9876543210", "North", "test", time.time(), time.time()),
        )
        db.x(
            """INSERT INTO dcs(name, phone, region, created_by, created_at, active, updated_at)
               VALUES(?, ?, ?, ?, ?, 1, ?)""",
            ("DC2", "9876543211", "South", "test", time.time(), time.time()),
        )

        client = MagicMock()
        manager = prachi_sync.DailySyncManager(client)

        # Change: DC1 updated, DC2 deleted, DC3 added
        dc_records = [
            prachi_sync.DCRecord(name="DC1", phone="9876543210", region="East"),  # Updated
            prachi_sync.DCRecord(name="DC3", phone="9876543212", region="West"),   # New
        ]

        client.fetch_dcs = AsyncMock(return_value=dc_records)

        result = await manager.sync_dcs()

        assert result["added"] == 1
        assert result["updated"] == 1
        assert result["deleted"] == 1


class TestErrorHandling:
    """Tests for error handling and edge cases."""

    async def test_malformed_csv_handling(self, temp_db):
        """Should handle malformed CSV gracefully."""
        client = prachi_sync.PrachiGoogleSheetsClient("test-id", timeout_sec=5)

        csv_data = """DC name,DC mobile number
DC1,"9876543210  # Unclosed quote"""

        with patch.object(client, "_fetch_sheet_csv", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = csv_data

            # Should not raise exception
            dcs = await client.fetch_dcs()
            # May be empty or partial, but should not crash

        await client.close()

    async def test_duplicate_phone_handling(self, temp_db):
        """Should handle duplicate phone numbers in sheet."""
        client = prachi_sync.PrachiGoogleSheetsClient("test-id", timeout_sec=5)

        csv_data = """DC name,DC mobile number,Count
DC1,9876543210,100
DC1_Duplicate,9876543210,50"""

        with patch.object(client, "_fetch_sheet_csv", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = csv_data

            dcs = await client.fetch_dcs()

            # Should process both (database will handle uniqueness)
            assert len(dcs) == 2

        await client.close()

    async def test_sync_history_tracking(self, temp_db):
        """Should track all sync operations in history."""
        # Record multiple syncs
        for i in range(3):
            db.x(
                """INSERT INTO prachi_sync_history
                   (sync_type, status, records_processed, records_added, records_updated, records_deleted, sync_source, synced_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                ("dcs", "success" if i < 2 else "failed", 10, 1, 0, 0, "api", time.time() + i),
            )

        # Query history
        rows = db.q("SELECT * FROM prachi_sync_history ORDER BY synced_at DESC LIMIT 10")

        assert len(rows) == 3
        assert rows[0]["status"] == "failed"
        assert rows[0]["sync_source"] == "api"
        assert rows[1]["status"] == "success"
        assert rows[2]["status"] == "success"


@pytest.mark.asyncio
class TestManualExcelUpload:
    """Tests for manual Excel upload (secondary, temporary override)."""

    async def test_manual_excel_upload_creates_records(self, temp_db):
        """Should insert/update records from manual Excel upload."""
        dcs_data = [
            {"name": "DC1", "phone": "9876543210", "region": "North"},
            {"name": "DC2", "phone": "9876543211", "region": "South"},
        ]
        officials_data = [
            {"phone": "9876543210", "dc_name": "DC1", "description": "Officer A"},
        ]

        result = await prachi_sync.manual_excel_upload(dcs_data, officials_data, "admin@test.com")

        assert result["success"] is True
        assert result["dcs_result"]["added"] == 2
        assert result["officials_result"]["added"] == 1
        assert "warning" in result

        # Verify records in database
        dcs = db.q("SELECT * FROM dcs WHERE phone=?", ("9876543210",), one=True)
        assert dcs is not None
        assert dcs["name"] == "DC1"

        # Verify sync history marks source as "excel" (manual override)
        history = db.q("SELECT * FROM prachi_sync_history WHERE sync_source='excel' ORDER BY synced_at DESC LIMIT 1", one=True)
        assert history is not None
        assert history["status"] == "success"

    async def test_manual_excel_upload_updates_existing(self, temp_db):
        """Should update existing records from manual Excel upload."""
        # Insert initial DC
        db.x(
            """INSERT INTO dcs(name, phone, region, created_by, created_at, active, updated_at)
               VALUES(?, ?, ?, ?, ?, 1, ?)""",
            ("DC1_Old", "9876543210", "South", "test", time.time(), time.time()),
        )

        dcs_data = [
            {"name": "DC1_Updated", "phone": "9876543210", "region": "North"},
        ]

        result = await prachi_sync.manual_excel_upload(dcs_data, [], "admin@test.com")

        assert result["success"] is True
        assert result["dcs_result"]["updated"] == 1

        # Verify updated in database
        dc = db.q("SELECT * FROM dcs WHERE phone=?", ("9876543210",), one=True)
        assert dc["name"] == "DC1_Updated"
        assert dc["region"] == "North"

    async def test_manual_excel_upload_marks_as_manual_override(self, temp_db):
        """Should mark sync as manual override in history."""
        dcs_data = [{"name": "DC1", "phone": "9876543210", "region": "North"}]

        result = await prachi_sync.manual_excel_upload(dcs_data, [], "admin@test.com")

        assert result["success"] is True

        # Verify sync history shows "excel" source (manual override)
        history = db.q(
            "SELECT * FROM prachi_sync_history WHERE sync_source='excel' ORDER BY synced_at DESC LIMIT 1",
            one=True
        )
        assert history is not None
        assert history["sync_source"] == "excel"
        assert "override" not in history["sync_source"].lower()  # Not marked as "api"


@pytest.mark.asyncio
class TestSyncSourceTracking:
    """Tests for sync_source tracking (API primary vs manual Excel secondary)."""

    async def test_api_sync_marked_as_api_source(self, temp_db):
        """Should mark automatic API syncs with sync_source='api'."""
        with patch("app.prachi_sync.PRACHI_SHEET_ID", "test-id"):
            mock_client = MagicMock()
            mock_client.fetch_dcs = AsyncMock(return_value=[])
            mock_client.fetch_sbi_officials = AsyncMock(return_value=[])
            mock_client.close = AsyncMock()

            with patch("app.prachi_sync.PrachiGoogleSheetsClient") as mock_client_class:
                mock_client_class.return_value = mock_client

                result = await prachi_sync.run_daily_sync()

                assert result["success"] is True

                # Verify sync history shows "api" source
                history = db.q(
                    "SELECT * FROM prachi_sync_history WHERE sync_source='api' ORDER BY synced_at DESC LIMIT 1",
                    one=True
                )
                assert history is not None
                assert history["sync_source"] == "api"

    async def test_api_sync_failure_marks_as_api_source(self, temp_db):
        """Should mark API sync failures with sync_source='api' and track degraded status."""
        with patch("app.prachi_sync.PRACHI_SHEET_ID", "test-id"):
            mock_client = MagicMock()
            mock_client.fetch_dcs = AsyncMock(side_effect=prachi_sync.PrachiAPIError("Network error", retriable=True))
            mock_client.close = AsyncMock()

            with patch("app.prachi_sync.PrachiGoogleSheetsClient") as mock_client_class:
                mock_client_class.return_value = mock_client

                result = await prachi_sync.run_daily_sync()

                assert result["success"] is False

                # Verify failure is marked with "api" source
                history = db.q(
                    "SELECT * FROM prachi_sync_history WHERE sync_source='api' AND status='failed' ORDER BY synced_at DESC LIMIT 1",
                    one=True
                )
                assert history is not None

    async def test_get_sync_status_shows_api_as_primary(self, temp_db):
        """Should return sync_source='api' in status (PRIMARY)."""
        status = prachi_sync.get_sync_status()

        assert status["sync_source"] == "api"
        assert "health_status" in status
        assert status["health_status"] in ("OK", "RECOVERING", "DEGRADED")

    async def test_degraded_status_after_three_failures(self, temp_db):
        """Should mark status as degraded after 3 consecutive API failures."""
        # Manually reset failure_streak
        prachi_sync._sync_stats["failure_streak"] = 0

        with patch("app.prachi_sync.PRACHI_SHEET_ID", "test-id"):
            mock_client = MagicMock()
            mock_client.fetch_dcs = AsyncMock(side_effect=prachi_sync.PrachiAPIError("Network error", retriable=True))
            mock_client.fetch_sbi_officials = AsyncMock(side_effect=prachi_sync.PrachiAPIError("Network error", retriable=True))
            mock_client.close = AsyncMock()

            with patch("app.prachi_sync.PrachiGoogleSheetsClient") as mock_client_class:
                mock_client_class.return_value = mock_client

                # Trigger 3 failures
                for i in range(3):
                    result = await prachi_sync.run_daily_sync()

                # Check the database for degraded status record
                # The third failure should be marked as degraded
                history = db.q(
                    "SELECT * FROM prachi_sync_history WHERE status='degraded' ORDER BY synced_at DESC LIMIT 1",
                    one=True
                )
                assert history is not None, "Should have at least one degraded record after 3 failures"
                assert history["status"] == "degraded"
                assert history["sync_source"] == "api"

                # Also verify the global state shows degraded
                status = prachi_sync.get_sync_status()
                assert status["health_status"] == "DEGRADED"


# Run tests with: pytest tests/test_prachi_sync.py -v
