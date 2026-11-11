"""Tests for Phase 7d Monitoring Dashboard."""
import hashlib
import json
import pytest
import time
from fastapi.testclient import TestClient

from app import db, main


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(main.app)


def create_user(email: str, role: str = "admin"):
    """Helper to create a user."""
    db.x("""
        INSERT INTO users (email, name, password_hash, role, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (email, f"Test {role.title()}", "hash", role, db.now()))

    user = db.q("SELECT * FROM users WHERE email=?", (email,), one=True)

    # Create session
    token = f"token_{email}_{int(time.time() * 1000000)}"
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    db.x("""
        INSERT INTO sessions (token_hash, user_id, created_at, expires_at)
        VALUES (?, ?, ?, ?)
    """, (token_hash, user["id"], db.now(), db.now() + 86400))

    return user, token


@pytest.fixture
def admin_client(client):
    """Create client with admin login."""
    user, token = create_user("admin@test.com", "admin")
    client.cookies.set("eko_session", token)
    return client


@pytest.fixture
def ops_client(client):
    """Create client with ops login."""
    user, token = create_user("ops@test.com", "ops")
    client.cookies.set("eko_session", token)
    return client


class TestMonitoringAPI:
    """Tests for monitoring dashboard API endpoints."""

    def test_monitor_status_requires_auth(self, client):
        """Monitor status API should require auth."""
        response = client.get("/api/monitor/status")
        assert response.status_code == 401

    def test_monitor_status_admin_access(self, admin_client):
        """Admin should access monitor status."""
        response = admin_client.get("/api/monitor/status")
        assert response.status_code == 200
        data = response.json()
        assert "timestamp" in data
        assert "autogmap" in data
        assert "prachi" in data
        assert "system" in data

    def test_monitor_status_ops_access(self, ops_client):
        """Ops should access monitor status."""
        response = ops_client.get("/api/monitor/status")
        assert response.status_code == 200

    def test_monitor_status_structure(self, admin_client):
        """Verify monitor status response structure."""
        response = admin_client.get("/api/monitor/status")
        data = response.json()

        # AutoGMap structure
        assert "sync" in data["autogmap"]
        assert "uploads" in data["autogmap"]
        assert data["autogmap"]["sync"]["status"] in ["OK", "DEGRADED", "ERROR", "UNKNOWN"]
        assert "success_rate" in data["autogmap"]["sync"]
        assert "numbers_count" in data["autogmap"]["sync"]

        # Prachi structure
        assert "sync" in data["prachi"]
        assert "submissions" in data["prachi"]
        assert data["prachi"]["sync"]["status"] in ["OK", "DEGRADED", "ERROR", "UNKNOWN"]

        # System structure
        assert "database" in data["system"]
        assert "recording_counts" in data["system"]

    def test_monitor_autogmap_stats(self, admin_client):
        """Test AutoGMap stats endpoint."""
        response = admin_client.get("/api/monitor/autogmap/stats?days=7")
        assert response.status_code == 200
        data = response.json()

        assert "sync" in data
        assert "uploads" in data
        assert "daily_history" in data
        assert isinstance(data["daily_history"], list)

    def test_monitor_prachi_stats(self, admin_client):
        """Test Prachi stats endpoint."""
        response = admin_client.get("/api/monitor/prachi/stats?hours=24")
        assert response.status_code == 200
        data = response.json()

        assert "sync" in data
        assert "submissions" in data
        assert "status_breakdown" in data

    def test_monitor_alerts(self, admin_client):
        """Test alerts endpoint."""
        response = admin_client.get("/api/monitor/alerts?limit=20")
        assert response.status_code == 200
        data = response.json()

        assert "alerts" in data
        assert "count" in data

    def test_sync_autogmap_endpoint(self, admin_client):
        """Test manual sync endpoint."""
        response = admin_client.post("/api/monitor/sync-autogmap")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_retry_uploads_endpoint(self, admin_client):
        """Test retry uploads endpoint."""
        response = admin_client.post("/api/monitor/retry-failed-uploads")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data


class TestDatabaseHelpers:
    """Tests for database helper functions."""

    def test_autogmap_sync_stats_empty(self):
        """Test sync stats with no data."""
        stats = db.get_autogmap_sync_stats(days=7)
        assert stats["status"] == "UNKNOWN"
        assert stats["total_syncs"] == 0
        assert stats["success_rate"] is None

    def test_autogmap_sync_stats_with_data(self):
        """Test sync stats with successful syncs."""
        now = db.now()
        db.x("""
            INSERT INTO prachi_sync_history (sync_type, status, synced_at, records_processed)
            VALUES (?, ?, ?, ?)
        """, ("dcs", "success", now, 10))

        db.x("""
            INSERT INTO prachi_sync_history (sync_type, status, synced_at, records_processed)
            VALUES (?, ?, ?, ?)
        """, ("dcs", "success", now - 3600, 10))

        stats = db.get_autogmap_sync_stats(days=7)
        assert stats["status"] == "OK"
        assert stats["total_syncs"] >= 2
        assert stats["success_rate"] == 100.0

    def test_autogmap_upload_stats_empty(self):
        """Test upload stats with no data."""
        stats = db.get_autogmap_upload_stats(hours=24)
        assert stats["status"] == "UNKNOWN"
        assert stats["total_uploads"] == 0

    def test_autogmap_upload_stats_with_data(self):
        """Test upload stats with upload records."""
        now = db.now()

        # Insert recordings
        db.x("""
            INSERT INTO recordings (sha256, mode, autogmap_status, uploaded_at, autogmap_sent_at)
            VALUES (?, ?, ?, ?, ?)
        """, ("abc123", "rm", "uploaded", now, now + 10))

        db.x("""
            INSERT INTO recordings (sha256, mode, autogmap_status, uploaded_at)
            VALUES (?, ?, ?, ?)
        """, ("def456", "rm", "failed", now))

        stats = db.get_autogmap_upload_stats(hours=24)
        assert stats["total_uploads"] >= 2
        assert stats["successful"] >= 1
        assert stats["failed"] >= 1

    def test_prachi_sync_stats_empty(self):
        """Test Prachi sync stats with no data."""
        stats = db.get_prachi_sync_stats()
        assert stats["status"] == "UNKNOWN"
        assert stats["dcs_count"] == 0

    def test_prachi_sync_stats_with_data(self):
        """Test Prachi sync stats with sync records."""
        now = db.now()

        # Insert DC
        db.x("""
            INSERT INTO dcs (name, phone, email, created_at, active)
            VALUES (?, ?, ?, ?, ?)
        """, ("DC1", "9876543210", "dc@test.com", now, 1))

        # Insert sync
        db.x("""
            INSERT INTO prachi_sync_history (sync_type, status, synced_at, records_processed)
            VALUES (?, ?, ?, ?)
        """, ("dcs", "success", now, 1))

        stats = db.get_prachi_sync_stats()
        assert stats["status"] == "OK"
        assert stats["dcs_count"] >= 1

    def test_prachi_submission_stats_empty(self):
        """Test Prachi submission stats with no data."""
        stats = db.get_prachi_submission_stats(hours=24)
        assert stats["status"] == "UNKNOWN"
        assert stats["total_submissions"] == 0

    def test_prachi_submission_stats_with_data(self):
        """Test Prachi submission stats with submission records."""
        now = db.now()

        # Insert submissions
        db.x("""
            INSERT INTO prachi_submissions (dc_id, dc_name, status, received_at, processed_at)
            VALUES (?, ?, ?, ?, ?)
        """, (1, "DC1", "success", now, now + 10))

        db.x("""
            INSERT INTO prachi_submissions (dc_id, dc_name, status, received_at)
            VALUES (?, ?, ?, ?)
        """, (1, "DC1", "pending", now))

        stats = db.get_prachi_submission_stats(hours=24)
        assert stats["total_submissions"] >= 2
        assert stats["successful"] >= 1
        assert stats["pending"] >= 1

    def test_get_recent_errors_empty(self):
        """Test recent errors with no data."""
        errors = db.get_recent_errors(limit=20)
        assert errors == []

    def test_get_recent_errors_with_data(self):
        """Test recent errors with error records."""
        now = db.now()

        # Insert error records
        db.x("""
            INSERT INTO prachi_sync_history (sync_type, status, error_message, synced_at)
            VALUES (?, ?, ?, ?)
        """, ("dcs", "failed", "Connection timeout", now))

        errors = db.get_recent_errors(limit=20)
        assert len(errors) >= 1
        assert errors[0]["status"] == "failed"

    def test_get_system_health(self):
        """Test system health check."""
        health = db.get_system_health()
        assert "database" in health
        assert health["database"] in ["OK", "ERROR"]
        assert "recording_counts" in health
        assert "dcs_count" in health
        assert "rms_count" in health


class TestMonitoringMetrics:
    """Tests for monitoring metrics calculations."""

    def test_success_rate_100_percent(self):
        """Test 100% success rate."""
        now = db.now()

        # Insert all successful syncs
        for i in range(5):
            db.x("""
                INSERT INTO prachi_sync_history (sync_type, status, synced_at)
                VALUES (?, ?, ?)
            """, ("dcs", "success", now - (i * 3600)))

        stats = db.get_autogmap_sync_stats(days=7)
        assert stats["success_rate"] == 100.0
        assert stats["status"] == "OK"

    def test_success_rate_partial(self):
        """Test partial success rate (70%)."""
        now = db.now()

        # Insert 7 successful and 3 failed = 70%
        for i in range(7):
            db.x("""
                INSERT INTO prachi_sync_history (sync_type, status, synced_at)
                VALUES (?, ?, ?)
            """, ("dcs", "success", now - (i * 3600)))

        for i in range(3):
            db.x("""
                INSERT INTO prachi_sync_history (sync_type, status, synced_at)
                VALUES (?, ?, ?)
            """, ("dcs", "failed", now - ((i + 7) * 3600)))

        stats = db.get_autogmap_sync_stats(days=7)
        assert stats["success_rate"] == 70.0
        assert stats["status"] == "DEGRADED"

    def test_success_rate_all_failed(self):
        """Test all failed rate (0%)."""
        now = db.now()

        # Insert all failed syncs
        for i in range(5):
            db.x("""
                INSERT INTO prachi_sync_history (sync_type, status, synced_at)
                VALUES (?, ?, ?)
            """, ("dcs", "failed", now - (i * 3600)))

        stats = db.get_autogmap_sync_stats(days=7)
        assert stats["success_rate"] == 0.0
        assert stats["status"] == "ERROR"

    def test_time_range_filtering(self):
        """Test that time range filtering works correctly."""
        now = db.now()

        # Insert sync outside range (8 days ago)
        db.x("""
            INSERT INTO prachi_sync_history (sync_type, status, synced_at)
            VALUES (?, ?, ?)
        """, ("dcs", "success", now - (8 * 86400)))

        # Insert sync within range (3 hours ago)
        db.x("""
            INSERT INTO prachi_sync_history (sync_type, status, synced_at)
            VALUES (?, ?, ?)
        """, ("dcs", "success", now - (3 * 3600)))

        stats_7d = db.get_autogmap_sync_stats(days=7)
        stats_1d = db.get_autogmap_sync_stats(days=1)

        # Both should have at least the recent one
        assert stats_7d["total_syncs"] >= 1
        assert stats_1d["total_syncs"] >= 1


class TestMonitoringIntegration:
    """Integration tests for the monitoring system."""

    def test_full_monitoring_flow(self, admin_client):
        """Test complete monitoring flow."""
        now = db.now()

        # Setup test data
        db.x("""
            INSERT INTO autogmap_numbers (phone, active, synced_at)
            VALUES (?, ?, ?)
        """, ("9876543210", 1, now))

        db.x("""
            INSERT INTO recordings (sha256, mode, autogmap_status, uploaded_at)
            VALUES (?, ?, ?, ?)
        """, ("hash1", "rm", "uploaded", now))

        db.x("""
            INSERT INTO prachi_sync_history (sync_type, status, synced_at, records_added)
            VALUES (?, ?, ?, ?)
        """, ("dcs", "success", now, 1))

        # Fetch dashboard status
        response = admin_client.get("/api/monitor/status")
        assert response.status_code == 200
        data = response.json()

        # Verify data
        assert data["autogmap"]["sync"]["numbers_count"] >= 1
        assert data["autogmap"]["uploads"]["successful"] >= 1
        assert data["system"]["database"] == "OK"

    def test_monitoring_with_errors(self, admin_client):
        """Test monitoring with error records."""
        now = db.now()

        # Insert failed syncs
        for i in range(3):
            db.x("""
                INSERT INTO prachi_sync_history (sync_type, status, error_message, synced_at)
                VALUES (?, ?, ?, ?)
            """, ("dcs", "failed", f"Error {i+1}", now - (i * 3600)))

        # Fetch dashboard
        response = admin_client.get("/api/monitor/status")
        assert response.status_code == 200
        data = response.json()

        # Verify errors are included
        assert len(data["recent_errors"]) >= 3
        assert all(e["status"] == "failed" for e in data["recent_errors"])

    def test_monitoring_dashboard_consistency(self, admin_client):
        """Test that all dashboard data sources are consistent."""
        response = admin_client.get("/api/monitor/status")
        assert response.status_code == 200
        data = response.json()

        # Verify types are consistent
        assert isinstance(data["autogmap"]["sync"]["success_rate"], (int, float, type(None)))
        assert isinstance(data["autogmap"]["uploads"]["successful"], int)
        assert data["system"]["database"] in ["OK", "ERROR"]
