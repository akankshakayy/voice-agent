"""AutoGMap integration: sync applicant numbers and upload recordings.

Phase 7a: Numbers Sync
  - Fetch applicant numbers from AutoGMap API every 15 minutes
  - Cache in database and memory
  - Track sync history and failures
  - Auto-retry with exponential backoff

Endpoints:
  GET https://indev.eko.in/autogmap/api/v1/call-recorder/numbers (every 15 min)
  POST https://indev.eko.in/autogmap/api/v1/call-recorder/recordings (after call)

Response format:
  {"as_of": timestamp, "count": N, "numbers": [{phone, local, name, since}]}

Status codes: 201 (success), 422 (not in applicants), 500 (server error), 400 (invalid)
"""
import asyncio
import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from . import db

log = logging.getLogger("eko.autogmap")

# Configuration from environment
AUTOGMAP_ENABLED = os.environ.get("AUTOGMAP_ENABLED", "false").lower() == "true"
AUTOGMAP_NUMBERS_URL = os.environ.get("AUTOGMAP_NUMBERS_URL", "").strip()
AUTOGMAP_RECORDINGS_URL = os.environ.get("AUTOGMAP_RECORDINGS_URL", "").strip()
AUTOGMAP_API_KEY = os.environ.get("AUTOGMAP_API_KEY", "").strip()
AUTOGMAP_SYNC_INTERVAL_MIN = int(os.environ.get("AUTOGMAP_SYNC_INTERVAL_MINUTES", "15"))
AUTOGMAP_SYNC_TIMEOUT_SEC = int(os.environ.get("AUTOGMAP_SYNC_TIMEOUT_SECONDS", "30"))
AUTOGMAP_UPLOAD_RETRY_MAX = int(os.environ.get("AUTOGMAP_UPLOAD_RETRY_MAX", "3"))
AUTOGMAP_UPLOAD_RETRY_BACKOFF = [
    int(x.strip()) for x in os.environ.get("AUTOGMAP_UPLOAD_RETRY_BACKOFF", "60,300,900").split(",")
]

# Global sync state
_sync_lock = threading.RLock()
_cached_numbers: dict[str, dict] = {}  # phone -> {local, name, since, synced_at}
_sync_stats = {
    "last_sync": None,
    "last_sync_success": None,
    "sync_count": 0,
    "sync_failures": 0,
    "failure_streak": 0,
    "numbers_count": 0,
}


class AutoGMapError(Exception):
    """Base exception for AutoGMap integration errors."""
    pass


class AutoGMapConfigError(AutoGMapError):
    """Configuration is incomplete or invalid."""
    pass


class AutoGMapAPIError(AutoGMapError):
    """API call failed."""
    def __init__(self, message: str, status_code: Optional[int] = None, retriable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retriable = retriable


class AutoGMapClient:
    """Async client for AutoGMap API calls."""

    def __init__(self, api_key: str = "", base_url: str = ""):
        """Initialize AutoGMap client.

        Args:
            api_key: AutoGMap API key (defaults to AUTOGMAP_API_KEY env var)
            base_url: Base URL for AutoGMap API (can be overridden per endpoint)

        Raises:
            AutoGMapConfigError: If API key is not configured
        """
        self.api_key = api_key or AUTOGMAP_API_KEY
        self.base_url = base_url or "https://indev.eko.in/autogmap/api/v1"

        if not self.api_key:
            raise AutoGMapConfigError(
                "AUTOGMAP_API_KEY not configured. Set it in .env or pass to __init__"
            )

        if not AUTOGMAP_NUMBERS_URL or not AUTOGMAP_RECORDINGS_URL:
            raise AutoGMapConfigError(
                "AUTOGMAP_NUMBERS_URL and AUTOGMAP_RECORDINGS_URL must be configured"
            )

        self.numbers_url = AUTOGMAP_NUMBERS_URL
        self.recordings_url = AUTOGMAP_RECORDINGS_URL
        self.timeout = AUTOGMAP_SYNC_TIMEOUT_SEC
        log.info("AutoGMapClient initialized: %s", self.numbers_url)

    async def fetch_numbers(self) -> dict:
        """Fetch applicant numbers from AutoGMap.

        Returns:
            dict: {"as_of": timestamp, "count": N, "numbers": [{"phone": str, "local": str, "name": str, "since": str}]}

        Raises:
            AutoGMapAPIError: If the API call fails
        """
        import httpx

        log.debug("Fetching numbers from AutoGMap")
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "Eko-RM-Voice-Agent/1.0",
        }

        try:
            async with httpx.AsyncClient(verify=True) as client:
                response = await client.get(
                    self.numbers_url,
                    headers=headers,
                    timeout=self.timeout,
                )

            if response.status_code == 401:
                log.error("AutoGMap authentication failed: Invalid API key")
                raise AutoGMapAPIError(
                    "Authentication failed: Invalid or expired API key",
                    status_code=401,
                    retriable=False,
                )

            if response.status_code == 403:
                log.error("AutoGMap authorization failed: Access denied")
                raise AutoGMapAPIError(
                    "Authorization failed: Access denied",
                    status_code=403,
                    retriable=False,
                )

            if response.status_code >= 500:
                log.error("AutoGMap server error: %d", response.status_code)
                raise AutoGMapAPIError(
                    f"Server error: HTTP {response.status_code}",
                    status_code=response.status_code,
                    retriable=True,
                )

            if response.status_code >= 400:
                log.error(
                    "AutoGMap API error: %d, body: %s",
                    response.status_code,
                    response.text[:200],
                )
                raise AutoGMapAPIError(
                    f"API error: HTTP {response.status_code}",
                    status_code=response.status_code,
                    retriable=False,
                )

            data = response.json()
            log.info(
                "Fetched numbers from AutoGMap: %d applicants (as of %s)",
                data.get("count", 0),
                data.get("as_of"),
            )
            return data

        except httpx.TimeoutException as e:
            log.error("AutoGMap fetch timeout after %ds: %s", self.timeout, e)
            raise AutoGMapAPIError(
                f"Request timeout after {self.timeout}s",
                retriable=True,
            )
        except httpx.RequestError as e:
            log.error("AutoGMap network error: %s", e)
            raise AutoGMapAPIError(
                f"Network error: {e}",
                retriable=True,
            )
        except (json.JSONDecodeError, KeyError) as e:
            log.error("AutoGMap response parse error: %s", e)
            raise AutoGMapAPIError(
                f"Invalid response format: {e}",
                retriable=False,
            )

    async def upload_recording(
        self, file_path: str, phone: str, direction: str, duration: int
    ) -> bool:
        """Upload a recording to AutoGMap.

        Args:
            file_path: Path to the audio file
            phone: Applicant's phone number
            direction: 'inbound' or 'outbound'
            duration: Call duration in seconds

        Returns:
            bool: True if upload succeeded, False otherwise

        Raises:
            AutoGMapAPIError: If upload fails (with retriable flag)
        """
        import httpx

        if not os.path.exists(file_path):
            log.error("Recording file not found: %s", file_path)
            raise AutoGMapAPIError("Recording file not found", retriable=False)

        file_size = os.path.getsize(file_path)
        if file_size == 0:
            log.error("Recording file is empty: %s", file_path)
            raise AutoGMapAPIError("Recording file is empty", retriable=False)

        log.debug("Uploading recording to AutoGMap: phone=%s, file=%s", phone, file_path)

        headers = {
            "X-API-Key": self.api_key,
            "User-Agent": "Eko-RM-Voice-Agent/1.0",
        }

        try:
            async with httpx.AsyncClient(verify=True) as client:
                with open(file_path, "rb") as f:
                    files = {"file": f}
                    data = {
                        "phone": phone,
                        "direction": direction,
                        "duration": str(duration),
                        "uploaded_at": datetime.now(tz=ZoneInfo("UTC")).isoformat(),
                    }

                    response = await client.post(
                        self.recordings_url,
                        headers=headers,
                        data=data,
                        files=files,
                        timeout=60,  # Upload timeout
                    )

            if response.status_code == 201:
                log.info(
                    "Recording uploaded to AutoGMap: phone=%s, file=%s, size=%d bytes",
                    phone,
                    file_path,
                    file_size,
                )
                return True

            if response.status_code == 422:
                # Not in applicants: log warning but don't retry
                log.warning(
                    "Recording not in AutoGMap applicants: phone=%s, file=%s",
                    phone,
                    file_path,
                )
                raise AutoGMapAPIError(
                    f"Phone number {phone} not in applicants",
                    status_code=422,
                    retriable=False,
                )

            if response.status_code >= 500:
                log.error(
                    "AutoGMap server error during upload: %d, body: %s",
                    response.status_code,
                    response.text[:200],
                )
                raise AutoGMapAPIError(
                    f"Server error: HTTP {response.status_code}",
                    status_code=response.status_code,
                    retriable=True,
                )

            if response.status_code >= 400:
                log.error(
                    "AutoGMap upload error: %d, body: %s",
                    response.status_code,
                    response.text[:200],
                )
                raise AutoGMapAPIError(
                    f"Upload error: HTTP {response.status_code}",
                    status_code=response.status_code,
                    retriable=False,
                )

            log.error("Unexpected response code from AutoGMap: %d", response.status_code)
            raise AutoGMapAPIError(
                f"Unexpected response: HTTP {response.status_code}",
                retriable=False,
            )

        except httpx.TimeoutException as e:
            log.error("AutoGMap upload timeout: %s", e)
            raise AutoGMapAPIError("Upload timeout", retriable=True)
        except httpx.RequestError as e:
            log.error("AutoGMap upload network error: %s", e)
            raise AutoGMapAPIError(f"Network error: {e}", retriable=True)
        except Exception as e:
            log.error("AutoGMap upload unexpected error: %s", e)
            raise AutoGMapAPIError(f"Unexpected error: {e}", retriable=False)


class AutoGMapSync:
    """Scheduler for syncing AutoGMap numbers periodically."""

    def __init__(self, client: Optional[AutoGMapClient] = None):
        """Initialize sync scheduler.

        Args:
            client: AutoGMapClient instance (created if not provided)
        """
        self.client = client or AutoGMapClient()
        log.info("AutoGMapSync scheduler initialized")

    async def sync_numbers(self) -> dict:
        """Fetch numbers from AutoGMap and store in cache + database.

        Returns:
            dict: Sync result with keys: success, count, new, updated, errors
        """
        global _cached_numbers, _sync_stats

        result = {"success": False, "count": 0, "new": 0, "updated": 0, "errors": []}

        with _sync_lock:
            _sync_stats["last_sync"] = datetime.now(tz=ZoneInfo("UTC")).isoformat()
            _sync_stats["sync_count"] += 1

        try:
            data = await self.client.fetch_numbers()
            numbers = data.get("numbers", [])
            as_of = data.get("as_of")

            log.info("Syncing %d numbers from AutoGMap (as_of: %s)", len(numbers), as_of)

            # Store in database
            synced_at = time.time()
            new_count = 0
            updated_count = 0

            for num in numbers:
                phone = (num.get("phone") or "").strip()
                local = (num.get("local") or "").strip()
                name = (num.get("name") or "").strip()
                since = num.get("since")

                if not phone:
                    log.warning("Skipping entry with no phone number: %s", num)
                    continue

                # Validate phone format (basic check)
                if not phone.replace("+", "").replace(" ", "").replace("-", "").isdigit():
                    log.warning("Skipping entry with invalid phone format: %s", phone)
                    continue

                existing = db.q(
                    "SELECT id FROM autogmap_numbers WHERE phone=?",
                    (phone,),
                    one=True,
                )

                try:
                    if existing:
                        db.update(
                            "autogmap_numbers",
                            existing["id"],
                            local=local,
                            name=name,
                            since=since,
                            synced_at=synced_at,
                            active=1,
                        )
                        updated_count += 1
                    else:
                        db.x(
                            """INSERT INTO autogmap_numbers(phone, local, name, since, synced_at, active)
                               VALUES(?, ?, ?, ?, ?, 1)""",
                            (phone, local, name, since, synced_at),
                        )
                        new_count += 1

                    # Update in-memory cache
                    with _sync_lock:
                        _cached_numbers[phone] = {
                            "local": local,
                            "name": name,
                            "since": since,
                            "synced_at": synced_at,
                        }

                except Exception as e:
                    log.error("Error storing number %s: %s", phone, e)
                    result["errors"].append({"phone": phone, "error": str(e)})

            with _sync_lock:
                _sync_stats["last_sync_success"] = datetime.now(tz=ZoneInfo("UTC")).isoformat()
                _sync_stats["numbers_count"] = len(_cached_numbers)
                _sync_stats["failure_streak"] = 0

            result.update({
                "success": True,
                "count": len(numbers),
                "new": new_count,
                "updated": updated_count,
            })

            log.info(
                "Numbers sync complete: %d total, %d new, %d updated (errors: %d)",
                len(numbers),
                new_count,
                updated_count,
                len(result["errors"]),
            )

            return result

        except AutoGMapAPIError as e:
            with _sync_lock:
                _sync_stats["sync_failures"] += 1
                _sync_stats["failure_streak"] += 1

            log.error("Numbers sync failed: %s (retriable: %s)", e, e.retriable)
            result["errors"] = [str(e)]

            if _sync_stats["failure_streak"] >= 3:
                log.critical(
                    "AutoGMap sync failed 3 times in a row. Last sync was %s",
                    _sync_stats.get("last_sync_success"),
                )

            return result

        except Exception as e:
            with _sync_lock:
                _sync_stats["sync_failures"] += 1
                _sync_stats["failure_streak"] += 1

            log.exception("Numbers sync unexpected error")
            result["errors"] = [str(e)]
            return result

    def get_cached_numbers(self) -> dict[str, dict]:
        """Get cached numbers (in-memory).

        Returns:
            dict: phone -> {local, name, since, synced_at}
        """
        with _sync_lock:
            return dict(_cached_numbers)

    def is_number_cached(self, phone: str) -> bool:
        """Check if a number is in the cache.

        Args:
            phone: Phone number to check

        Returns:
            bool: True if number is cached and active
        """
        phone = (phone or "").strip()
        if not phone:
            return False

        with _sync_lock:
            return phone in _cached_numbers

    def get_stats(self) -> dict:
        """Get sync statistics.

        Returns:
            dict: Sync stats with keys: last_sync, numbers_count, sync_count, failures, etc.
        """
        with _sync_lock:
            return dict(_sync_stats)


def load_cached_numbers() -> None:
    """Load numbers from database into memory cache on startup.

    This ensures we have data even if we haven't synced yet.
    """
    global _cached_numbers, _sync_stats

    try:
        rows = db.q(
            "SELECT phone, local, name, since, synced_at FROM autogmap_numbers WHERE active=1"
        )
        with _sync_lock:
            for row in rows:
                _cached_numbers[row["phone"]] = {
                    "local": row["local"],
                    "name": row["name"],
                    "since": row["since"],
                    "synced_at": row["synced_at"],
                }
            _sync_stats["numbers_count"] = len(_cached_numbers)

        log.info("Loaded %d numbers from database into cache", len(_cached_numbers))

    except Exception as e:
        log.error("Error loading cached numbers: %s", e)


def sync_loop(stop: threading.Event) -> None:
    """Background thread: sync numbers every AUTOGMAP_SYNC_INTERVAL_MIN minutes.

    Args:
        stop: Threading event to signal shutdown
    """
    if not AUTOGMAP_ENABLED:
        log.info("AutoGMap is disabled")
        return

    log.info("AutoGMap sync loop starting (interval: %d min)", AUTOGMAP_SYNC_INTERVAL_MIN)

    try:
        sync = AutoGMapSync()
    except AutoGMapConfigError as e:
        log.error("Cannot start AutoGMap sync: %s", e)
        return

    # Load cached numbers from database on startup
    load_cached_numbers()

    while not stop.is_set():
        try:
            # Run async sync in a new event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(sync.sync_numbers())
            finally:
                loop.close()

        except Exception:
            log.exception("AutoGMap sync loop error")

        # Wait for next sync interval (or until stop signal)
        stop.wait(AUTOGMAP_SYNC_INTERVAL_MIN * 60)


# Utility functions for database access

def has_number(phone: str) -> bool:
    """Check if a phone number is authorized for recording (cached or in DB).

    Args:
        phone: Phone number to check

    Returns:
        bool: True if the number is in AutoGMap's applicant list
    """
    phone = (phone or "").strip()
    if not phone:
        return False

    # Check in-memory cache first (fast path)
    if _get_sync().is_number_cached(phone):
        return True

    # Fall back to database (in case cache not yet loaded)
    try:
        return bool(
            db.q(
                "SELECT 1 FROM autogmap_numbers WHERE phone=? AND active=1",
                (phone,),
                one=True,
            )
        )
    except Exception as e:
        log.error("Error checking number in database: %s", e)
        return False


def get_numbers_count() -> int:
    """Get count of active AutoGMap numbers.

    Returns:
        int: Number of applicants
    """
    try:
        result = db.q(
            "SELECT COUNT(*) as count FROM autogmap_numbers WHERE active=1",
            one=True,
        )
        return result["count"] if result else 0
    except Exception as e:
        log.error("Error getting numbers count: %s", e)
        return 0


# Singleton sync instance
_sync_instance: Optional[AutoGMapSync] = None


def _get_sync() -> AutoGMapSync:
    """Get or create the sync instance."""
    global _sync_instance
    if _sync_instance is None:
        try:
            _sync_instance = AutoGMapSync()
        except AutoGMapConfigError:
            # Return a dummy instance that will fail gracefully
            pass
    return _sync_instance or AutoGMapSync.__new__(AutoGMapSync)
