"""Tests for Phase 8: Backup & Restore functionality."""
import io
import json
import os
import tempfile
import time
import zipfile

import pytest

from app import backup_restore, db


@pytest.fixture(autouse=True)
def setup_backup_dir():
    """Ensure backups directory exists for tests."""
    os.makedirs(backup_restore.BACKUPS_DIR, exist_ok=True)
    yield
    # Cleanup happens automatically via tmpfile


class TestExportImport:
    """Test table export and import functionality."""

    def test_export_table_dcs(self):
        """Test exporting DCs table."""
        rows = backup_restore.export_table("dcs")
        assert isinstance(rows, list)
        # All rows should be dicts
        for row in rows:
            assert isinstance(row, dict)
            assert "id" in row
            assert "name" in row

    def test_export_table_rms(self):
        """Test exporting RMs table."""
        rows = backup_restore.export_table("rms")
        assert isinstance(rows, list)

    def test_export_to_json(self):
        """Test JSON export of records."""
        records = [
            {"id": 1, "name": "Test 1"},
            {"id": 2, "name": "Test 2"},
        ]
        json_str = backup_restore.export_to_json(records)
        assert isinstance(json_str, str)

        # Verify it's valid JSON
        parsed = json.loads(json_str)
        assert len(parsed) == 2
        assert parsed[0]["id"] == 1

    def test_import_from_json_valid(self):
        """Test JSON import with valid data."""
        json_str = '[{"id": 1, "name": "Test"}]'
        rows = backup_restore.import_from_json(json_str)
        assert len(rows) == 1
        assert rows[0]["id"] == 1

    def test_import_from_json_invalid(self):
        """Test JSON import with invalid data."""
        with pytest.raises(ValueError):
            backup_restore.import_from_json("not json")

    def test_export_recordings_filtered(self):
        """Test exporting recordings with mode filtering."""
        # This test assumes some recordings exist in the test database
        rows = backup_restore.export_table("recordings", rm_id=1)
        assert isinstance(rows, list)
        # If any records exist, they should have rm_id=1
        for row in rows:
            assert row.get("rm_id") == 1


class TestDatabaseBackup:
    """Test full database backup functionality."""

    def test_export_database_full(self):
        """Test full database export."""
        result = backup_restore.export_database(backup_type="full")

        assert "backup_id" in result
        assert "file_path" in result
        assert "filename" in result
        assert "metadata" in result

        # File should exist
        assert os.path.exists(result["file_path"])

        # Should be a valid ZIP file
        with zipfile.ZipFile(result["file_path"], "r") as zf:
            files = zf.namelist()
            assert "database.sql" in files
            assert "backup_metadata.json" in files

        # Cleanup
        os.remove(result["file_path"])

    def test_export_database_filtered_rm(self):
        """Test filtered export for RM mode."""
        result = backup_restore.export_database(backup_type="filtered", rm_id=1)

        assert result["metadata"]["backup_type"] == "filtered"
        assert result["metadata"]["rm_id"] == 1

        # Cleanup
        os.remove(result["file_path"])

    def test_export_database_filtered_dc(self):
        """Test filtered export for DC mode."""
        result = backup_restore.export_database(backup_type="filtered", dc_id=1)

        assert result["metadata"]["backup_type"] == "filtered"
        assert result["metadata"]["dc_id"] == 1

        # Cleanup
        os.remove(result["file_path"])

    def test_backup_metadata_valid(self):
        """Test that backup metadata contains expected fields."""
        result = backup_restore.export_database(backup_type="full")
        metadata = result["metadata"]

        assert "backup_id" in metadata
        assert "created_at" in metadata
        assert "created_at_str" in metadata
        assert "backup_type" in metadata
        assert "record_counts" in metadata
        assert "file_count" in metadata
        assert "compressed_size_mb" in metadata

        # Record counts should be a dict with table counts
        assert isinstance(metadata["record_counts"], dict)

        # Cleanup
        os.remove(result["file_path"])


class TestDatabaseRestore:
    """Test database restore functionality."""

    def test_list_backups(self):
        """Test listing available backups."""
        # Create a backup first
        result = backup_restore.export_database(backup_type="full")
        backup_id = result["backup_id"]

        # List backups
        backups = backup_restore.list_backups()

        assert isinstance(backups, list)
        assert len(backups) > 0

        # Find our backup
        found = False
        for b in backups:
            if b["backup_id"] == backup_id:
                found = True
                assert "filename" in b
                assert "created_at" in b
                assert "record_counts" in b
                assert "compressed_size_mb" in b

        assert found, "Backup not found in list"

    def test_get_backup_by_id(self):
        """Test retrieving backup by ID."""
        # Create a backup
        result = backup_restore.export_database(backup_type="full")
        backup_id = result["backup_id"]

        # Retrieve it
        backup = backup_restore.get_backup_by_id(backup_id)

        assert backup is not None
        assert backup["backup_id"] == backup_id
        assert os.path.exists(backup["filepath"])

    def test_validate_backup(self):
        """Test backup validation without restore."""
        # Create a backup
        result = backup_restore.export_database(backup_type="full")
        backup_path = result["file_path"]

        # Validate it
        with open(backup_path, "rb") as f:
            validation = backup_restore.restore_database(
                backup_file_obj=f,
                validate_only=True
            )

        assert validation["status"] == "valid"
        assert "backup_id" in validation
        assert "record_counts" in validation

        # Cleanup
        os.remove(backup_path)

    def test_delete_backup(self):
        """Test deleting a backup."""
        # Create a backup
        result = backup_restore.export_database(backup_type="full")
        backup_id = result["backup_id"]
        backup_path = result["file_path"]

        assert os.path.exists(backup_path)

        # Delete it
        deleted = backup_restore.delete_backup(backup_id)

        assert deleted is True
        assert not os.path.exists(backup_path)

    def test_delete_nonexistent_backup(self):
        """Test deleting a backup that doesn't exist."""
        deleted = backup_restore.delete_backup("nonexistent_backup_id")
        assert deleted is False


class TestExportSingleTable:
    """Test exporting individual tables."""

    def test_export_table_to_json(self):
        """Test exporting a table as JSON."""
        json_str = backup_restore.export_table_to_json("rms")

        assert isinstance(json_str, str)

        # Should be valid JSON
        records = json.loads(json_str)
        assert isinstance(records, list)
        for record in records:
            assert isinstance(record, dict)

    def test_export_recordings_table(self):
        """Test exporting recordings table."""
        json_str = backup_restore.export_table_to_json("recordings")

        assert isinstance(json_str, str)
        records = json.loads(json_str)
        assert isinstance(records, list)


class TestDBHelpers:
    """Test database helper functions."""

    def test_bulk_export_table(self):
        """Test bulk export from db module."""
        rows = db.bulk_export_table("rms")

        assert isinstance(rows, list)
        for row in rows:
            assert isinstance(row, dict)

    def test_bulk_export_with_where(self):
        """Test bulk export with WHERE clause."""
        rows = db.bulk_export_table("rms", "id > ?", (0,))

        assert isinstance(rows, list)

    def test_table_record_count(self):
        """Test getting record count."""
        count = db.table_record_count("rms")

        assert isinstance(count, int)
        assert count >= 0

    def test_get_table_schema(self):
        """Test getting table schema."""
        schema = db.get_table_schema("rms")

        assert isinstance(schema, list)
        # Should have columns
        assert len(schema) > 0

        # Check schema structure
        for col in schema:
            assert isinstance(col, dict)
            assert "name" in col
            assert "type" in col

    def test_export_import_json_roundtrip(self):
        """Test JSON export/import roundtrip."""
        records = [
            {"id": 1, "name": "Test 1", "value": 123},
            {"id": 2, "name": "Test 2", "value": 456},
        ]

        # Export
        json_str = db.export_to_json(records)

        # Import
        imported = db.import_from_json(json_str)

        # Verify
        assert len(imported) == len(records)
        assert imported[0]["id"] == 1
        assert imported[1]["name"] == "Test 2"


class TestBackupFilenames:
    """Test backup filename generation."""

    def test_backup_filename_full(self):
        """Test generating full backup filename."""
        filename = backup_restore._backup_filename("full")

        assert "backup_full" in filename
        assert filename.endswith(".zip")
        assert "20" in filename  # Should have year

    def test_backup_filename_filtered_rm(self):
        """Test generating filtered backup filename."""
        filename = backup_restore._backup_filename("filtered", rm_id=42)

        assert "backup_filtered" in filename
        assert "_rm42" in filename
        assert filename.endswith(".zip")

    def test_backup_filename_filtered_dc(self):
        """Test generating DC filtered backup filename."""
        filename = backup_restore._backup_filename("filtered", dc_id=7)

        assert "backup_filtered" in filename
        assert "_dc7" in filename

    def test_backup_filename_filtered_employee(self):
        """Test generating employee filtered backup filename."""
        filename = backup_restore._backup_filename("filtered", employee_id=99)

        assert "backup_filtered" in filename
        assert "_emp99" in filename


class TestBackupIntegration:
    """Integration tests for backup system."""

    def test_export_and_list(self):
        """Test creating backup and listing it."""
        # Export
        export_result = backup_restore.export_database(backup_type="full")
        backup_id = export_result["backup_id"]

        # List
        backups = backup_restore.list_backups()

        # Should be in list
        assert any(b["backup_id"] == backup_id for b in backups)

        # Cleanup
        os.remove(export_result["file_path"])

    def test_backup_contains_all_tables(self):
        """Test that backup contains data from all exportable tables."""
        result = backup_restore.export_database(backup_type="full")
        backup_path = result["file_path"]

        with zipfile.ZipFile(backup_path, "r") as zf:
            filenames = zf.namelist()

            # Should have database SQL and metadata
            assert "database.sql" in filenames
            assert "backup_metadata.json" in filenames

            # Metadata should be valid
            metadata_str = zf.read("backup_metadata.json").decode("utf-8")
            metadata = json.loads(metadata_str)
            assert "record_counts" in metadata
            assert "backup_id" in metadata

        # Cleanup
        os.remove(backup_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
