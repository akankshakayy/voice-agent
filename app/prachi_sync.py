"""Prachi Google Sheets Daily Sync System.

Syncs DCs and SBI officials from a public Google Sheets document daily.

Sheet structure:
  - Sheet 0 (gid=0): Overview with DC name, mobile number, count
  - Sheet 1881479143 (gid=1881479143): SBI Officials with DC Name, Mobile Number

Configuration:
  PRACHI_SHEET_ID: Google Sheets ID
  PRACHI_SYNC_ENABLED: Enable/disable syncing
  PRACHI_SYNC_SCHEDULE_HOUR: Hour of day to run sync (0-23)
  PRACHI_SYNC_TIMEOUT_SECONDS: Request timeout
  PRACHI_SYNC_RETRY_MAX: Max retries on failure
"""
import asyncio
import csv
import io
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

from . import db

log = logging.getLogger("eko.prachi")

# Configuration from environment
PRACHI_SHEET_ID = os.environ.get("PRACHI_SHEET_ID", "").strip()
PRACHI_SYNC_ENABLED = os.environ.get("PRACHI_SYNC_ENABLED", "false").lower() == "true"
PRACHI_SYNC_SCHEDULE_HOUR = int(os.environ.get("PRACHI_SYNC_SCHEDULE_HOUR", "2"))
PRACHI_SYNC_TIMEOUT_SEC = int(os.environ.get("PRACHI_SYNC_TIMEOUT_SECONDS", "60"))
PRACHI_SYNC_RETRY_MAX = int(os.environ.get("PRACHI_SYNC_RETRY_MAX", "3"))

# Google Sheets export URL format
PRACHI_SHEET_URL_TEMPLATE = "https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

# Sheet IDs
SHEET_DCS_GID = 0
SHEET_SBI_OFFICIALS_GID = 1881479143

# Global sync state
_sync_lock = threading.RLock()
_sync_stats = {
    "last_sync": None,
    "last_sync_success": None,
    "last_sync_error": None,
    "sync_count": 0,
    "sync_failures": 0,
    "failure_streak": 0,  # consecutive failures; 3+ = degraded status
    "sync_source": "api",  # PRIMARY: Google Sheets API
    "dcs_count": 0,
    "officials_count": 0,
    "last_changes": {
        "dcs_added": 0,
        "dcs_updated": 0,
        "dcs_deleted": 0,
        "officials_added": 0,
        "officials_updated": 0,
        "officials_deleted": 0,
    },
}


class PrachiError(Exception):
    """Base exception for Prachi sync errors."""
    pass


class PrachiConfigError(PrachiError):
    """Configuration is incomplete or invalid."""
    pass


class PrachiAPIError(PrachiError):
    """API call failed."""
    def __init__(self, message: str, retriable: bool = False):
        super().__init__(message)
        self.retriable = retriable


@dataclass
class DCRecord:
    """Represents a DC from the sheet."""
    name: str
    phone: str
    region: Optional[str] = None

    def __hash__(self):
        return hash((self.name, self.phone))

    def __eq__(self, other):
        if not isinstance(other, DCRecord):
            return False
        return self.name == other.name and self.phone == other.phone


@dataclass
class SBIOfficial:
    """Represents an SBI official (allowed number) from the sheet."""
    phone: str
    dc_name: str
    description: Optional[str] = None

    def __hash__(self):
        return hash((self.phone, self.dc_name))

    def __eq__(self, other):
        if not isinstance(other, SBIOfficial):
            return False
        return self.phone == other.phone and self.dc_name == other.dc_name


class PrachiGoogleSheetsClient:
    """Client for fetching data from Prachi Google Sheets."""

    def __init__(self, sheet_id: str, timeout_sec: int = 60):
        """Initialize client.

        Args:
            sheet_id: Google Sheets ID
            timeout_sec: Request timeout in seconds

        Raises:
            PrachiConfigError: If sheet_id is not configured
        """
        if not sheet_id:
            raise PrachiConfigError("PRACHI_SHEET_ID is not configured")

        self.sheet_id = sheet_id
        self.timeout = timeout_sec
        self.client = httpx.AsyncClient(timeout=self.timeout)

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()

    async def _fetch_sheet_csv(self, gid: int) -> str:
        """Fetch sheet as CSV text.

        Args:
            gid: Sheet gid (tab ID)

        Returns:
            CSV text data

        Raises:
            PrachiAPIError: On network or parsing error
        """
        url = PRACHI_SHEET_URL_TEMPLATE.format(sheet_id=self.sheet_id, gid=gid)

        try:
            log.debug("Fetching sheet %d from Google Sheets", gid)
            response = await self.client.get(url)

            if response.status_code >= 500:
                log.error("Google Sheets server error: %d", response.status_code)
                raise PrachiAPIError(
                    f"Google Sheets server error: HTTP {response.status_code}",
                    retriable=True,
                )

            if response.status_code >= 400:
                log.error("Google Sheets API error: %d", response.status_code)
                raise PrachiAPIError(
                    f"Google Sheets error: HTTP {response.status_code}",
                    retriable=False,
                )

            text = response.text
            if not text.strip():
                log.warning("Sheet %d returned empty response", gid)
                return ""

            return text

        except httpx.TimeoutException as e:
            log.error("Google Sheets fetch timeout after %ds: %s", self.timeout, e)
            raise PrachiAPIError(f"Request timeout after {self.timeout}s", retriable=True)
        except httpx.RequestError as e:
            log.error("Google Sheets network error: %s", e)
            raise PrachiAPIError(f"Network error: {e}", retriable=True)

    async def fetch_dcs(self) -> list[DCRecord]:
        """Fetch DCs overview from Sheet 0.

        Expected columns: DC name, DC mobile number, Count

        Returns:
            List of DCRecord objects

        Raises:
            PrachiAPIError: On network or parsing error
        """
        csv_text = await self._fetch_sheet_csv(SHEET_DCS_GID)

        if not csv_text.strip():
            log.warning("DCs sheet is empty")
            return []

        dcs = []
        try:
            reader = csv.DictReader(io.StringIO(csv_text))
            if not reader.fieldnames:
                log.warning("DCs sheet has no header row")
                return []

            for i, row in enumerate(reader, start=2):
                try:
                    # Column names may vary, try common patterns
                    dc_name = (
                        row.get("DC name") or
                        row.get("dc_name") or
                        row.get("DC Name") or
                        row.get("Name") or
                        ""
                    ).strip()

                    phone = (
                        row.get("DC mobile number") or
                        row.get("dc_mobile_number") or
                        row.get("Mobile Number") or
                        row.get("Phone") or
                        ""
                    ).strip()

                    region = (
                        row.get("Region") or
                        row.get("region") or
                        ""
                    ).strip()

                    if not dc_name or not phone:
                        log.warning("Row %d missing DC name or phone: %s", i, row)
                        continue

                    # Validate phone format (basic check: digits only)
                    if not phone.replace("+", "").replace(" ", "").replace("-", "").isdigit():
                        log.warning("Row %d invalid phone format: %s", i, phone)
                        continue

                    dc = DCRecord(name=dc_name, phone=phone, region=region or None)
                    dcs.append(dc)

                except Exception as e:
                    log.warning("Error parsing DCs row %d: %s", i, e)
                    continue

        except csv.Error as e:
            raise PrachiAPIError(f"Failed to parse DCs CSV: {e}", retriable=False)

        log.info("Fetched %d DCs from sheet", len(dcs))
        return dcs

    async def fetch_sbi_officials(self) -> list[SBIOfficial]:
        """Fetch SBI officials from Sheet 1881479143.

        Expected columns: DC Name, Mobile Number (+ optional description)

        Returns:
            List of SBIOfficial objects

        Raises:
            PrachiAPIError: On network or parsing error
        """
        csv_text = await self._fetch_sheet_csv(SHEET_SBI_OFFICIALS_GID)

        if not csv_text.strip():
            log.warning("SBI Officials sheet is empty")
            return []

        officials = []
        try:
            reader = csv.DictReader(io.StringIO(csv_text))
            if not reader.fieldnames:
                log.warning("SBI Officials sheet has no header row")
                return []

            for i, row in enumerate(reader, start=2):
                try:
                    dc_name = (
                        row.get("DC Name") or
                        row.get("dc_name") or
                        row.get("DC name") or
                        row.get("Name") or
                        ""
                    ).strip()

                    phone = (
                        row.get("Mobile Number") or
                        row.get("mobile_number") or
                        row.get("Phone") or
                        row.get("phone") or
                        ""
                    ).strip()

                    description = (
                        row.get("Description") or
                        row.get("description") or
                        row.get("Notes") or
                        row.get("notes") or
                        ""
                    ).strip()

                    if not phone:
                        log.warning("Row %d missing phone: %s", i, row)
                        continue

                    # Validate phone format
                    if not phone.replace("+", "").replace(" ", "").replace("-", "").isdigit():
                        log.warning("Row %d invalid phone format: %s", i, phone)
                        continue

                    official = SBIOfficial(
                        phone=phone,
                        dc_name=dc_name or "",
                        description=description or None,
                    )
                    officials.append(official)

                except Exception as e:
                    log.warning("Error parsing SBI Officials row %d: %s", i, e)
                    continue

        except csv.Error as e:
            raise PrachiAPIError(f"Failed to parse SBI Officials CSV: {e}", retriable=False)

        log.info("Fetched %d SBI officials from sheet", len(officials))
        return officials


class DailySyncManager:
    """Manages change detection and database updates for Prachi sync."""

    def __init__(self, client: Optional[PrachiGoogleSheetsClient] = None):
        """Initialize sync manager.

        Args:
            client: PrachiGoogleSheetsClient instance (created if not provided)
        """
        self.client = client

    async def sync_dcs(self) -> dict:
        """Sync DCs from sheet to database.

        Returns:
            dict with keys: success, records_processed, added, updated, deleted, errors
        """
        if not self.client:
            raise PrachiConfigError("Client not initialized")

        result = {
            "success": False,
            "sync_type": "dcs",
            "records_processed": 0,
            "added": 0,
            "updated": 0,
            "deleted": 0,
            "errors": [],
        }

        try:
            sheet_dcs = await self.client.fetch_dcs()
            result["records_processed"] = len(sheet_dcs)

            # Get existing DCs from database
            existing_rows = db.q("SELECT id, name, phone, region, active FROM dcs WHERE 1=1")
            existing_map = {row["phone"]: row for row in existing_rows}

            sheet_phones = set()

            # Process each DC from the sheet
            for dc_record in sheet_dcs:
                sheet_phones.add(dc_record.phone)

                if dc_record.phone in existing_map:
                    # Update if changed
                    existing = existing_map[dc_record.phone]
                    changed = (
                        existing["name"] != dc_record.name or
                        existing["region"] != dc_record.region or
                        existing["active"] != 1
                    )

                    if changed:
                        try:
                            db.update(
                                "dcs",
                                existing["id"],
                                name=dc_record.name,
                                region=dc_record.region or "",
                                active=1,
                                updated_at=time.time(),
                            )
                            result["updated"] += 1
                            log.debug("Updated DC: %s (%s)", dc_record.name, dc_record.phone)
                        except Exception as e:
                            log.error("Error updating DC %s: %s", dc_record.phone, e)
                            result["errors"].append({"phone": dc_record.phone, "error": str(e)})
                else:
                    # Insert new DC
                    try:
                        db.x(
                            """INSERT INTO dcs(name, phone, region, created_by, created_at, active, updated_at)
                               VALUES(?, ?, ?, ?, ?, 1, ?)""",
                            (dc_record.name, dc_record.phone, dc_record.region or "", "prachi_sync",
                             time.time(), time.time()),
                        )
                        result["added"] += 1
                        log.debug("Added new DC: %s (%s)", dc_record.name, dc_record.phone)
                    except Exception as e:
                        log.error("Error adding DC %s: %s", dc_record.phone, e)
                        result["errors"].append({"phone": dc_record.phone, "error": str(e)})

            # Soft delete DCs that are no longer in the sheet
            for phone, existing in existing_map.items():
                if phone not in sheet_phones and existing["active"] == 1:
                    try:
                        db.update(
                            "dcs",
                            existing["id"],
                            active=0,
                            updated_at=time.time(),
                        )
                        result["deleted"] += 1
                        log.warning("Marked DC inactive (removed from sheet): %s", phone)
                    except Exception as e:
                        log.error("Error marking DC inactive %s: %s", phone, e)
                        result["errors"].append({"phone": phone, "error": str(e)})

            result["success"] = True
            log.info(
                "DCs sync: %d processed, %d added, %d updated, %d deleted (errors: %d)",
                result["records_processed"],
                result["added"],
                result["updated"],
                result["deleted"],
                len(result["errors"]),
            )

            return result

        except Exception as e:
            log.exception("DCs sync failed")
            result["errors"] = [str(e)]
            return result

    async def sync_sbi_officials(self) -> dict:
        """Sync SBI officials (allowed_numbers) from sheet to database.

        Returns:
            dict with keys: success, records_processed, added, updated, deleted, errors
        """
        if not self.client:
            raise PrachiConfigError("Client not initialized")

        result = {
            "success": False,
            "sync_type": "sbi_officials",
            "records_processed": 0,
            "added": 0,
            "updated": 0,
            "deleted": 0,
            "errors": [],
        }

        try:
            sheet_officials = await self.client.fetch_sbi_officials()
            result["records_processed"] = len(sheet_officials)

            # Get existing allowed numbers from database
            existing_rows = db.q("SELECT id, phone_number, description, active FROM allowed_numbers WHERE 1=1")
            existing_map = {row["phone_number"]: row for row in existing_rows}

            sheet_phones = set()

            # Process each official from the sheet
            for official in sheet_officials:
                sheet_phones.add(official.phone)

                if official.phone in existing_map:
                    # Update if changed
                    existing = existing_map[official.phone]
                    changed = (
                        existing["description"] != official.description or
                        existing["active"] != 1
                    )

                    if changed:
                        try:
                            db.update(
                                "allowed_numbers",
                                existing["id"],
                                description=official.description or "",
                                active=1,
                                added_at=time.time(),
                            )
                            result["updated"] += 1
                            log.debug("Updated SBI official: %s", official.phone)
                        except Exception as e:
                            log.error("Error updating SBI official %s: %s", official.phone, e)
                            result["errors"].append({"phone": official.phone, "error": str(e)})
                else:
                    # Insert new allowed number
                    try:
                        db.x(
                            """INSERT INTO allowed_numbers(phone_number, description, added_by, added_at, active)
                               VALUES(?, ?, ?, ?, 1)""",
                            (official.phone, official.description or "", "prachi_sync", time.time()),
                        )
                        result["added"] += 1
                        log.debug("Added new SBI official: %s", official.phone)
                    except Exception as e:
                        log.error("Error adding SBI official %s: %s", official.phone, e)
                        result["errors"].append({"phone": official.phone, "error": str(e)})

            # Soft delete officials that are no longer in the sheet
            for phone, existing in existing_map.items():
                if phone not in sheet_phones and existing["active"] == 1:
                    try:
                        db.update(
                            "allowed_numbers",
                            existing["id"],
                            active=0,
                            added_at=time.time(),
                        )
                        result["deleted"] += 1
                        log.warning("Marked SBI official inactive (removed from sheet): %s", phone)
                    except Exception as e:
                        log.error("Error marking SBI official inactive %s: %s", phone, e)
                        result["errors"].append({"phone": phone, "error": str(e)})

            result["success"] = True
            log.info(
                "SBI Officials sync: %d processed, %d added, %d updated, %d deleted (errors: %d)",
                result["records_processed"],
                result["added"],
                result["updated"],
                result["deleted"],
                len(result["errors"]),
            )

            return result

        except Exception as e:
            log.exception("SBI Officials sync failed")
            result["errors"] = [str(e)]
            return result


async def run_daily_sync() -> dict:
    """Run the full daily sync (DCs + SBI officials).

    Returns:
        dict with keys: success, status, dcs, officials, duration_sec
    """
    global _sync_stats

    start_time = time.time()
    result = {
        "success": False,
        "status": "failed",
        "dcs": None,
        "officials": None,
        "duration_sec": 0,
    }

    with _sync_lock:
        _sync_stats["last_sync"] = datetime.now(tz=ZoneInfo("UTC")).isoformat()
        _sync_stats["sync_count"] += 1

    try:
        if not PRACHI_SHEET_ID:
            raise PrachiConfigError("PRACHI_SHEET_ID not configured")

        log.info("Starting Prachi daily sync")

        # Create client and sync manager
        client = PrachiGoogleSheetsClient(PRACHI_SHEET_ID, PRACHI_SYNC_TIMEOUT_SEC)

        try:
            manager = DailySyncManager(client)

            # Sync DCs
            dcs_result = await manager.sync_dcs()
            result["dcs"] = dcs_result

            if not dcs_result.get("success"):
                raise PrachiError(f"DCs sync failed: {dcs_result.get('errors', ['Unknown error'])}")

            # Sync SBI officials
            officials_result = await manager.sync_sbi_officials()
            result["officials"] = officials_result

            if not officials_result.get("success"):
                raise PrachiError(f"SBI officials sync failed: {officials_result.get('errors', ['Unknown error'])}")

            # Update global stats
            with _sync_lock:
                _sync_stats["last_sync_success"] = datetime.now(tz=ZoneInfo("UTC")).isoformat()
                _sync_stats["last_sync_error"] = None
                _sync_stats["dcs_count"] = db.q("SELECT COUNT(*) as count FROM dcs WHERE active=1")[0]["count"]
                _sync_stats["officials_count"] = db.q(
                    "SELECT COUNT(*) as count FROM allowed_numbers WHERE active=1"
                )[0]["count"]
                _sync_stats["last_changes"] = {
                    "dcs_added": dcs_result.get("added", 0),
                    "dcs_updated": dcs_result.get("updated", 0),
                    "dcs_deleted": dcs_result.get("deleted", 0),
                    "officials_added": officials_result.get("added", 0),
                    "officials_updated": officials_result.get("updated", 0),
                    "officials_deleted": officials_result.get("deleted", 0),
                }
                _sync_stats["failure_streak"] = 0

            # Record sync in history (PRIMARY: API source)
            duration_sec = time.time() - start_time
            db.x(
                """INSERT INTO prachi_sync_history
                   (sync_type, status, records_processed, records_added, records_updated, records_deleted, sync_source, synced_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                ("dcs_and_officials", "success",
                 dcs_result.get("records_processed", 0) + officials_result.get("records_processed", 0),
                 dcs_result.get("added", 0) + officials_result.get("added", 0),
                 dcs_result.get("updated", 0) + officials_result.get("updated", 0),
                 dcs_result.get("deleted", 0) + officials_result.get("deleted", 0),
                 "api",  # PRIMARY: Google Sheets API
                 time.time()),
            )

            result["success"] = True
            result["status"] = "success"
            result["duration_sec"] = duration_sec

            log.info(
                "Prachi daily sync completed successfully in %.1f seconds: "
                "DCs (%d added, %d updated, %d deleted), "
                "Officials (%d added, %d updated, %d deleted)",
                duration_sec,
                dcs_result.get("added", 0),
                dcs_result.get("updated", 0),
                dcs_result.get("deleted", 0),
                officials_result.get("added", 0),
                officials_result.get("updated", 0),
                officials_result.get("deleted", 0),
            )

            return result

        finally:
            await client.close()

    except PrachiError as e:
        duration_sec = time.time() - start_time
        result["duration_sec"] = duration_sec

        log.error("Prachi sync failed: %s", e)

        # Track failure streak for degraded status
        with _sync_lock:
            _sync_stats["sync_failures"] += 1
            _sync_stats["failure_streak"] = _sync_stats.get("failure_streak", 0) + 1
            _sync_stats["last_sync_error"] = str(e)

        # Determine status: degraded if 3+ consecutive failures
        status = "degraded" if _sync_stats["failure_streak"] >= 3 else "failed"

        # Record failure in history (PRIMARY: API source, even on failure)
        db.x(
            """INSERT INTO prachi_sync_history
               (sync_type, status, error_message, sync_source, synced_at)
               VALUES(?, ?, ?, ?, ?)""",
            ("dcs_and_officials", status, str(e), "api", time.time()),
        )

        return result

    except Exception as e:
        duration_sec = time.time() - start_time
        result["duration_sec"] = duration_sec

        log.exception("Prachi sync unexpected error")

        # Track failure streak for degraded status
        with _sync_lock:
            _sync_stats["sync_failures"] += 1
            _sync_stats["failure_streak"] = _sync_stats.get("failure_streak", 0) + 1
            _sync_stats["last_sync_error"] = str(e)

        # Determine status: degraded if 3+ consecutive failures
        status = "degraded" if _sync_stats["failure_streak"] >= 3 else "failed"

        # Record failure in history (PRIMARY: API source, even on failure)
        db.x(
            """INSERT INTO prachi_sync_history
               (sync_type, status, error_message, sync_source, synced_at)
               VALUES(?, ?, ?, ?, ?)""",
            ("dcs_and_officials", status, str(e), "api", time.time()),
        )

        return result


def get_sync_status() -> dict:
    """Get current sync status.

    Returns:
        dict with sync statistics, sync source (PRIMARY: api), and last changes
    """
    with _sync_lock:
        failure_streak = _sync_stats.get("failure_streak", 0)
        # Determine overall health status
        if failure_streak >= 3:
            health = "DEGRADED"
        elif failure_streak > 0:
            health = "RECOVERING"
        else:
            health = "OK"

        return {
            "last_sync": _sync_stats.get("last_sync"),
            "last_sync_success": _sync_stats.get("last_sync_success"),
            "last_sync_error": _sync_stats.get("last_sync_error"),
            "sync_count": _sync_stats.get("sync_count", 0),
            "sync_failures": _sync_stats.get("sync_failures", 0),
            "failure_streak": failure_streak,
            "health_status": health,
            "sync_source": "api",  # PRIMARY: Google Sheets API (Excel is secondary override)
            "dcs_count": _sync_stats.get("dcs_count", 0),
            "officials_count": _sync_stats.get("officials_count", 0),
            "last_changes": dict(_sync_stats.get("last_changes", {})),
        }


async def manual_excel_upload(dcs_data: list[dict], officials_data: list[dict], actor_email: str) -> dict:
    """SECONDARY: Manually upload Prachi data from Excel file (manual override).

    This overrides the automatic API sync temporarily. The next scheduled API sync
    will overwrite this data with the current Google Sheets state.

    Args:
        dcs_data: List of DC records from Excel
        officials_data: List of SBI official records from Excel
        actor_email: Email of the user who uploaded the file

    Returns:
        dict with keys: success, dcs_result, officials_result, warning
    """
    start_time = time.time()
    result = {
        "success": False,
        "dcs_result": None,
        "officials_result": None,
        "warning": "This manual upload will be overwritten by the next scheduled API sync (in ~24 hours)",
    }

    try:
        log.info("Starting manual Excel upload for Prachi data (actor: %s)", actor_email)

        # Process DCs from Excel
        manager = DailySyncManager(None)

        # Temporarily insert DCs from Excel into database
        dcs_added = 0
        dcs_updated = 0
        dcs_deleted = 0

        for dc in dcs_data:
            phone = dc.get("phone", "").strip()
            if not phone:
                continue

            name = dc.get("name", "").strip()
            region = dc.get("region", "").strip()

            try:
                existing = db.q("SELECT id FROM dcs WHERE phone=?", (phone,), one=True)
                if existing:
                    db.update("dcs", existing["id"], name=name, region=region, active=1, updated_at=time.time())
                    dcs_updated += 1
                else:
                    db.x(
                        """INSERT INTO dcs(name, phone, region, created_by, created_at, active, updated_at)
                           VALUES(?, ?, ?, ?, ?, 1, ?)""",
                        (name, phone, region or "", "manual_excel", time.time(), time.time()),
                    )
                    dcs_added += 1
            except Exception as e:
                log.error("Error processing DC from Excel: %s", e)

        # Process SBI officials from Excel
        officials_added = 0
        officials_updated = 0
        officials_deleted = 0

        for official in officials_data:
            phone = official.get("phone", "").strip()
            if not phone:
                continue

            dc_name = official.get("dc_name", "").strip()
            description = official.get("description", "").strip()

            try:
                existing = db.q("SELECT id FROM allowed_numbers WHERE phone_number=?", (phone,), one=True)
                if existing:
                    db.update("allowed_numbers", existing["id"], description=description or "", active=1)
                    officials_updated += 1
                else:
                    db.x(
                        """INSERT INTO allowed_numbers(phone_number, description, added_by, added_at, active)
                           VALUES(?, ?, ?, ?, 1)""",
                        (phone, description or "", "manual_excel", time.time()),
                    )
                    officials_added += 1
            except Exception as e:
                log.error("Error processing SBI official from Excel: %s", e)

        result["dcs_result"] = {"added": dcs_added, "updated": dcs_updated, "deleted": dcs_deleted}
        result["officials_result"] = {"added": officials_added, "updated": officials_updated, "deleted": officials_deleted}

        # Record in sync history (SECONDARY: manual override)
        duration_sec = time.time() - start_time
        db.x(
            """INSERT INTO prachi_sync_history
               (sync_type, status, records_processed, records_added, records_updated, records_deleted, sync_source, synced_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
            ("dcs_and_officials", "success",
             dcs_data.__len__() + officials_data.__len__(),
             dcs_added + officials_added,
             dcs_updated + officials_updated,
             dcs_deleted + officials_deleted,
             "excel",  # SECONDARY: Manual Excel override
             time.time()),
        )

        result["success"] = True
        log.info("Manual Excel upload completed: %d DCs (%d added, %d updated), %d officials (%d added, %d updated)",
                 dcs_data.__len__(), dcs_added, dcs_updated, officials_data.__len__(), officials_added, officials_updated)

        return result

    except Exception as e:
        log.exception("Manual Excel upload failed")
        result["error"] = str(e)
        # Record failure
        db.x(
            """INSERT INTO prachi_sync_history
               (sync_type, status, error_message, sync_source, synced_at)
               VALUES(?, ?, ?, ?, ?)""",
            ("dcs_and_officials", "failed", str(e), "excel", time.time()),
        )
        return result


def sync_loop(stop: threading.Event) -> None:
    """Background thread: run daily sync at scheduled hour.

    Args:
        stop: Threading event to signal shutdown
    """
    if not PRACHI_SYNC_ENABLED:
        log.info("Prachi sync is disabled")
        return

    log.info(
        "Prachi sync loop starting (schedule: daily at %02d:00 UTC)",
        PRACHI_SYNC_SCHEDULE_HOUR,
    )

    while not stop.is_set():
        try:
            now = datetime.now(tz=ZoneInfo("UTC"))
            target_hour = PRACHI_SYNC_SCHEDULE_HOUR

            # Calculate seconds until next scheduled sync
            next_sync = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
            if now >= next_sync:
                next_sync += timedelta(days=1)

            wait_seconds = (next_sync - now).total_seconds()

            log.debug(
                "Next Prachi sync scheduled for %s (in %.0f seconds)",
                next_sync.isoformat(),
                wait_seconds,
            )

            # Wait for the scheduled time or until stop signal
            if stop.wait(wait_seconds):
                # stop signal was set
                break

            # Run async sync in a new event loop
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(run_daily_sync())
                finally:
                    loop.close()
            except Exception:
                log.exception("Error running Prachi sync in event loop")

        except Exception:
            log.exception("Prachi sync loop error")
            # Wait a bit before retrying to avoid tight loop on persistent errors
            if stop.wait(60):
                break
