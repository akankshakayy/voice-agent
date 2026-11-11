"""Phase 8: Backup & Restore - Granular database export/import with JSON support.

Supports:
- Table-level exports (DCs, employees, allowed numbers, recordings, etc.)
- Mode-specific filtering (RM/DC/Employee recordings)
- ZIP archives with SQLite dumps + JSON exports
- Full restore with validation
- Backup metadata tracking (size, record counts, timestamps)
"""
import io
import json
import logging
import os
import sqlite3
import time
import zipfile
from datetime import datetime
from pathlib import Path

from . import db, recordings

log = logging.getLogger(__name__)

# Backup storage directory (next to database)
BACKUPS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(db.DB_PATH)), "backups"
)
os.makedirs(BACKUPS_DIR, exist_ok=True)

# Tables to export (in order)
EXPORTABLE_TABLES = {
    "rms": ("id", "name", "phone", "region", "email", "source"),
    "dcs": ("id", "name", "phone", "email", "region", "created_by", "created_at", "active", "updated_at"),
    "employees": ("id", "name", "phone", "email", "department", "created_by", "created_at", "active", "updated_at"),
    "allowed_numbers": ("id", "dc_id", "phone_number", "description", "added_by", "added_at", "active"),
    "csps": ("id", "csp_code", "name", "shop_name", "phone", "district", "rm_id", "shared_phone",
             "alt_phone", "email", "category", "state", "lho", "population", "terminal_status",
             "active", "source", "import_id", "updated_at"),
    "upload_tokens": ("id", "token_hash", "rm_id", "dc_id", "employee_id", "mode", "label",
                     "created_by", "created_at", "last_used_at", "revoked_at"),
    "recordings": ("id", "sha256", "rm_id", "dc_id", "employee_id", "token_id", "device_id", "mode",
                  "file_path", "orig_name", "size_bytes", "started_at", "duration_sec", "direction",
                  "other_number", "csp_id", "uploaded_at", "status", "attempts", "error", "processed_at",
                  "is_csp_call", "language", "transcript_json", "issue_segment", "intent", "intent_confidence",
                  "slots_json", "sentiment", "resolution", "rm_handling", "summary", "model"),
    "autogmap_numbers": ("id", "phone", "local", "name", "since", "synced_at", "active",
                        "description", "created_by", "created_at"),
    "prachi_sync_history": ("id", "sync_type", "status", "records_processed", "records_added",
                           "records_updated", "records_deleted", "error_message", "sync_source", "synced_at"),
}

# Metadata fields for backups
BACKUP_METADATA_FIELDS = {
    "backup_id": str,
    "created_at": float,
    "backup_type": str,  # "full" | "incremental" | "filtered"
    "rm_id": int,  # None for full backups
    "dc_id": int,  # None for full backups
    "employee_id": int,  # None for full backups
    "record_counts": dict,
    "file_count": int,
    "compressed_size_mb": float,
    "database_size_mb": float,
}


def _backup_filename(backup_type: str = "full", rm_id: int | None = None,
                     dc_id: int | None = None, employee_id: int | None = None) -> str:
    """Generate a unique backup filename with timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = ""
    if rm_id:
        suffix = f"_rm{rm_id}"
    elif dc_id:
        suffix = f"_dc{dc_id}"
    elif employee_id:
        suffix = f"_emp{employee_id}"
    return f"backup_{backup_type}{suffix}_{timestamp}.zip"


def export_to_json(rows: list[dict], indent: bool = True) -> str:
    """Convert records to JSON string."""
    return json.dumps(rows, indent=2 if indent else None, ensure_ascii=False, default=str)


def import_from_json(json_str: str) -> list[dict]:
    """Parse JSON string into records."""
    try:
        rows = json.loads(json_str)
        if not isinstance(rows, list):
            raise ValueError(f"Expected list of records, got {type(rows)}")
        return rows
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {str(e)}")


def export_table(table: str, rm_id: int | None = None, dc_id: int | None = None,
                 employee_id: int | None = None) -> list[dict]:
    """Export a single table with optional mode filtering.

    Args:
        table: Table name
        rm_id: Filter recordings by RM (mode='rm')
        dc_id: Filter recordings by DC (mode='dc')
        employee_id: Filter recordings by Employee (mode='employee')

    Returns:
        List of dict records
    """
    if table not in EXPORTABLE_TABLES:
        raise ValueError(f"Cannot export table {table}")

    cols = EXPORTABLE_TABLES[table]
    cols_sql = ", ".join(cols)

    # Apply mode-specific filtering for recordings
    if table == "recordings":
        where = ["1=1"]
        args = []
        if rm_id:
            where.append("rm_id = ?")
            args.append(rm_id)
        if dc_id:
            where.append("dc_id = ?")
            args.append(dc_id)
        if employee_id:
            where.append("employee_id = ?")
            args.append(employee_id)
        where_clause = " AND ".join(where)
        rows = db.q(f"SELECT {cols_sql} FROM {table} WHERE {where_clause} ORDER BY id", args)
    else:
        rows = db.q(f"SELECT {cols_sql} FROM {table} ORDER BY id")

    return rows


def export_database(backup_type: str = "full", rm_id: int | None = None,
                   dc_id: int | None = None, employee_id: int | None = None) -> dict:
    """Export database to ZIP archive with SQLite dump + JSON files.

    Args:
        backup_type: "full", "incremental", or "filtered"
        rm_id: For filtered exports (RM mode)
        dc_id: For filtered exports (DC mode)
        employee_id: For filtered exports (Employee mode)

    Returns:
        {"backup_id": str, "file_path": str, "metadata": dict}
    """
    backup_id = f"backup_{int(time.time())}_{os.urandom(4).hex()}"
    filename = _backup_filename(backup_type, rm_id, dc_id, employee_id)
    filepath = os.path.join(BACKUPS_DIR, filename)

    log.info(f"Starting database export: {backup_id} ({backup_type})")

    record_counts = {}
    file_count = 0

    try:
        with zipfile.ZipFile(filepath, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. Export SQLite database dump
            dump_buffer = io.StringIO()
            con = db.conn()
            for line in con.iterdump():
                dump_buffer.write(line + "\n")
            zf.writestr("database.sql", dump_buffer.getvalue())
            file_count += 1

            # 2. Export each table as JSON
            for table in EXPORTABLE_TABLES.keys():
                try:
                    rows = export_table(table, rm_id, dc_id, employee_id)
                    record_counts[table] = len(rows)

                    if rows:
                        json_str = export_to_json(rows)
                        zf.writestr(f"tables/{table}.json", json_str)
                        file_count += 1
                        log.debug(f"Exported {table}: {len(rows)} records")
                except Exception as e:
                    log.error(f"Error exporting table {table}: {e}")
                    record_counts[table] = 0

            # 3. Export recordings metadata (but not audio files - too large)
            if backup_type == "full" or not (rm_id or dc_id or employee_id):
                recs = db.q("SELECT id, file_path, orig_name, size_bytes, uploaded_at, status FROM recordings ORDER BY id")
            else:
                where = ["1=1"]
                args = []
                if rm_id:
                    where.append("rm_id = ?")
                    args.append(rm_id)
                if dc_id:
                    where.append("dc_id = ?")
                    args.append(dc_id)
                if employee_id:
                    where.append("employee_id = ?")
                    args.append(employee_id)
                where_clause = " AND ".join(where)
                recs = db.q(f"SELECT id, file_path, orig_name, size_bytes, uploaded_at, status FROM recordings WHERE {where_clause} ORDER BY id", args)

            if recs:
                metadata_json = export_to_json(recs)
                zf.writestr("recordings_metadata.json", metadata_json)
                file_count += 1

            # 4. Backup metadata
            backup_metadata = {
                "backup_id": backup_id,
                "created_at": time.time(),
                "created_at_str": datetime.now().isoformat(),
                "backup_type": backup_type,
                "rm_id": rm_id,
                "dc_id": dc_id,
                "employee_id": employee_id,
                "record_counts": record_counts,
                "file_count": file_count,
                "database_size_mb": round(os.path.getsize(db.DB_PATH) / 1e6, 2) if os.path.exists(db.DB_PATH) else 0,
            }
            zf.writestr("backup_metadata.json", json.dumps(backup_metadata, indent=2))

        # Get final file size
        backup_size_mb = round(os.path.getsize(filepath) / 1e6, 2)
        backup_metadata["compressed_size_mb"] = backup_size_mb

        log.info(f"Database export complete: {backup_id} ({backup_size_mb} MB, {sum(record_counts.values())} records)")

        return {
            "backup_id": backup_id,
            "file_path": filepath,
            "filename": filename,
            "metadata": backup_metadata,
        }

    except Exception as e:
        log.error(f"Export failed: {e}", exc_info=True)
        if os.path.exists(filepath):
            os.remove(filepath)
        raise ValueError(f"Export failed: {str(e)}")


def restore_database(backup_path: str | None = None, backup_file_obj: io.IOBase | None = None,
                    validate_only: bool = False) -> dict:
    """Restore database from backup ZIP file.

    Args:
        backup_path: Path to backup ZIP file
        backup_file_obj: File-like object (for API uploads)
        validate_only: Only validate, don't restore

    Returns:
        {"status": "restored", "backup_id": str, "record_counts": dict, "restored_at": float}
    """
    if not backup_path and not backup_file_obj:
        raise ValueError("Must provide backup_path or backup_file_obj")

    log.info("Starting database restore")

    try:
        # Read and validate backup
        if backup_file_obj:
            backup_data = backup_file_obj.read()
            zf = zipfile.ZipFile(io.BytesIO(backup_data), "r")
        else:
            if not os.path.exists(backup_path):
                raise ValueError(f"Backup file not found: {backup_path}")
            zf = zipfile.ZipFile(backup_path, "r")

        with zf:
            # 1. Validate backup structure
            required_files = ["database.sql", "backup_metadata.json"]
            filenames = zf.namelist()
            for rf in required_files:
                if rf not in filenames:
                    raise ValueError(f"Invalid backup: missing {rf}")

            # 2. Load and validate metadata
            metadata_str = zf.read("backup_metadata.json").decode("utf-8")
            metadata = json.loads(metadata_str)
            backup_id = metadata.get("backup_id", "unknown")

            if not isinstance(metadata.get("record_counts"), dict):
                raise ValueError("Invalid backup metadata: missing record_counts")

            log.info(f"Backup metadata valid: {backup_id}, {sum(metadata['record_counts'].values())} records")

            if validate_only:
                return {
                    "status": "valid",
                    "backup_id": backup_id,
                    "record_counts": metadata["record_counts"],
                    "message": "Backup is valid and can be restored",
                }

            # 3. Restore database (if not validate-only)
            database_sql = zf.read("database.sql").decode("utf-8")

            # Create a temporary connection to validate the SQL
            temp_db_path = os.path.join(BACKUPS_DIR, f"temp_restore_{int(time.time())}.db")
            temp_conn = sqlite3.connect(temp_db_path)

            try:
                # Execute the SQL dump to create schema
                temp_conn.executescript(database_sql)
                temp_conn.commit()

                # Verify integrity
                integrity = temp_conn.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise ValueError(f"Restored database failed integrity check: {integrity}")

                # Verify record counts match
                for table, count in metadata["record_counts"].items():
                    if table in EXPORTABLE_TABLES:
                        actual = temp_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                        if actual != count:
                            log.warning(f"Record count mismatch for {table}: expected {count}, got {actual}")

                # Backup current database
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                db_backup = f"{db.DB_PATH}.pre_restore_{timestamp}"
                if os.path.exists(db.DB_PATH):
                    import shutil
                    shutil.copy(db.DB_PATH, db_backup)
                    log.info(f"Current database backed up to {db_backup}")

                # Replace database
                with db._lock:
                    db.reset_connection()
                    import shutil
                    shutil.move(temp_db_path, db.DB_PATH)
                    db.conn()  # Reopen connection

                log.info(f"Database restored from backup: {backup_id}")

                return {
                    "status": "restored",
                    "backup_id": backup_id,
                    "record_counts": metadata["record_counts"],
                    "restored_at": time.time(),
                    "previous_database_backup": f"{os.path.basename(db_backup)}",
                }

            finally:
                temp_conn.close()
                if os.path.exists(temp_db_path):
                    os.remove(temp_db_path)

    except Exception as e:
        log.error(f"Restore failed: {e}", exc_info=True)
        raise ValueError(f"Restore failed: {str(e)}")


def list_backups() -> list[dict]:
    """List all available backups with metadata.

    Returns:
        List of backup info dicts, sorted by creation date (newest first)
    """
    backups = []

    if not os.path.exists(BACKUPS_DIR):
        return backups

    for filename in sorted(os.listdir(BACKUPS_DIR), reverse=True):
        if not filename.endswith(".zip"):
            continue

        filepath = os.path.join(BACKUPS_DIR, filename)

        try:
            with zipfile.ZipFile(filepath, "r") as zf:
                metadata_str = zf.read("backup_metadata.json").decode("utf-8")
                metadata = json.loads(metadata_str)

                backups.append({
                    "backup_id": metadata.get("backup_id", "unknown"),
                    "filename": filename,
                    "filepath": filepath,
                    "created_at": metadata.get("created_at"),
                    "created_at_str": metadata.get("created_at_str"),
                    "backup_type": metadata.get("backup_type"),
                    "rm_id": metadata.get("rm_id"),
                    "dc_id": metadata.get("dc_id"),
                    "employee_id": metadata.get("employee_id"),
                    "record_counts": metadata.get("record_counts", {}),
                    "total_records": sum(metadata.get("record_counts", {}).values()),
                    "compressed_size_mb": round(os.path.getsize(filepath) / 1e6, 2),
                    "database_size_mb": metadata.get("database_size_mb"),
                })
        except Exception as e:
            log.warning(f"Error reading backup {filename}: {e}")
            continue

    return backups


def delete_backup(backup_id: str) -> bool:
    """Delete a backup by ID.

    Returns:
        True if deleted, False if not found
    """
    for backup in list_backups():
        if backup["backup_id"] == backup_id:
            try:
                os.remove(backup["filepath"])
                log.info(f"Deleted backup: {backup_id}")
                return True
            except Exception as e:
                log.error(f"Failed to delete backup {backup_id}: {e}")
                return False

    return False


def get_backup_by_id(backup_id: str) -> dict | None:
    """Get backup info by ID.

    Returns:
        Backup info dict or None if not found
    """
    for backup in list_backups():
        if backup["backup_id"] == backup_id:
            return backup
    return None


def export_table_to_json(table: str, rm_id: int | None = None,
                        dc_id: int | None = None, employee_id: int | None = None) -> str:
    """Export a single table as JSON (for API response).

    Args:
        table: Table name
        rm_id: Filter recordings by RM
        dc_id: Filter recordings by DC
        employee_id: Filter recordings by Employee

    Returns:
        JSON string
    """
    rows = export_table(table, rm_id, dc_id, employee_id)
    return export_to_json(rows)


def import_table_from_json(table: str, json_str: str) -> dict:
    """Import a table from JSON (for bulk restore).

    Args:
        table: Table name
        json_str: JSON string with records

    Returns:
        {"imported": int, "failed": int, "errors": list}
    """
    rows = import_from_json(table, json_str)

    if table not in EXPORTABLE_TABLES:
        raise ValueError(f"Cannot import table {table}")

    imported = 0
    failed = 0
    errors = []

    cols = EXPORTABLE_TABLES[table]
    placeholders = ", ".join(["?"] * len(cols))
    cols_str = ", ".join(cols)

    for i, row in enumerate(rows):
        try:
            values = [row.get(col) for col in cols]
            db.x(f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders})", values)
            imported += 1
        except Exception as e:
            failed += 1
            errors.append(f"Row {i}: {str(e)}")

    return {
        "imported": imported,
        "failed": failed,
        "errors": errors,
    }
