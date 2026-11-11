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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from queue import Queue
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
AUTOGMAP_UPLOAD_TIMEOUT_SEC = int(os.environ.get("AUTOGMAP_UPLOAD_TIMEOUT_SECONDS", "60"))
AUTOGMAP_UPLOAD_QUEUE_SIZE = int(os.environ.get("AUTOGMAP_UPLOAD_QUEUE_SIZE", "1000"))
AUTOGMAP_UPLOAD_MAX_WORKERS = int(os.environ.get("AUTOGMAP_UPLOAD_MAX_WORKERS", "2"))  # Mansi's 2 req/sec limit

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

# Global upload queue and worker pool
_upload_queue: Optional[Queue] = None
_upload_executor: Optional[ThreadPoolExecutor] = None
_upload_stats = {
    "queued": 0,
    "processed": 0,
    "queue_peak": 0,
    "queue_full_rejections": 0,
    "last_queued_at": None,
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
        self,
        file_path: str,
        phone: str,
        direction: str = "in",
        duration_sec: int = 0,
        device: str = None,
    ) -> tuple[bool, str, dict]:
        """Upload a recording to AutoGMap.

        Args:
            file_path: Path to the audio file
            phone: Applicant's phone number
            direction: 'inbound' or 'outbound' (default: 'in')
            duration_sec: Call duration in seconds (default: 0)
            device: Device identifier (optional)

        Returns:
            tuple: (success: bool, status: str, data: dict)
              - success: True if upload succeeded, False otherwise
              - status: Status string ('uploaded', 'not_in_applicants', 'server_error', 'timeout', 'file_not_found')
              - data: Response data or error details, including 'recording_id' on success

        Example:
            success, status, data = await client.upload_recording(
                '/path/to/file.ogg', '9876543210', 'inbound', 120
            )
            if success:
                print(f"Uploaded with ID: {data.get('recording_id')}")
            elif status == 'not_in_applicants':
                print("Number not in AutoGMap applicants list")
        """
        import httpx

        if not os.path.exists(file_path):
            log.error("Recording file not found: %s", file_path)
            return False, "file_not_found", {"error": "File not found"}

        file_size = os.path.getsize(file_path)
        max_size_bytes = 60 * 1024 * 1024  # Mansi's requirement: 60 MB max

        if file_size == 0:
            log.error("Recording file is empty: %s", file_path)
            return False, "file_error", {"error": "File is empty"}

        # Pre-check: reject files that exceed Mansi's 60 MB limit
        if file_size > max_size_bytes:
            log.error(
                "Recording file exceeds 60 MB limit: %s (size: %d bytes = %.1f MB)",
                file_path,
                file_size,
                file_size / (1024 * 1024),
            )
            return False, "file_too_large", {
                "error": f"File too large: {file_size // (1024*1024)}MB exceeds 60MB limit"
            }

        log.debug(
            "Uploading recording to AutoGMap: phone=%s, direction=%s, duration=%d, size=%d bytes",
            phone,
            direction,
            duration_sec,
            file_size,
        )

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
                        "duration": str(duration_sec),
                        "uploaded_at": datetime.now(tz=ZoneInfo("UTC")).isoformat(),
                    }
                    if device:
                        data["device"] = device

                    response = await client.post(
                        self.recordings_url,
                        headers=headers,
                        data=data,
                        files=files,
                        timeout=60,
                    )

            # Mansi API Response Codes: 201=kept, 422=not_applicant/not_audio/too_large, 401=auth_fail
            if response.status_code == 201:
                log.info(
                    "Recording uploaded to AutoGMap: phone=%s, file=%s, size=%d bytes",
                    phone,
                    file_path,
                    file_size,
                )
                try:
                    resp_data = response.json()
                    return True, "uploaded", {
                        "recording_id": resp_data.get("recording_id"),
                        "status": resp_data.get("status", "accepted"),
                    }
                except Exception:
                    return True, "uploaded", {"status": "accepted"}

            if response.status_code == 401:
                log.error(
                    "AutoGMap authentication failed: invalid/missing API key"
                )
                return False, "auth_error", {
                    "error": "Authentication failed: check AUTOGMAP_API_KEY"
                }

            if response.status_code == 422:
                # Mansi returns 422 for: not in applicants, not audio file, or >60MB
                log.warning(
                    "Recording rejected by AutoGMap (422): phone=%s, file=%s, size=%d bytes. Likely: not in applicants, invalid format, or >60MB",
                    phone,
                    file_path,
                    file_size,
                )
                # Check file size to provide better error message
                max_size_mb = 60
                if file_size > (max_size_mb * 1024 * 1024):
                    return False, "file_too_large", {
                        "error": f"File too large: {file_size // (1024*1024)}MB > {max_size_mb}MB limit"
                    }
                return False, "not_in_applicants", {
                    "error": f"Recording rejected: phone not in applicants, invalid audio format, or file too large"
                }
                log.warning(
                    "Recording not in AutoGMap applicants: phone=%s, file=%s",
                    phone,
                    file_path,
                )
                return False, "not_in_applicants", {
                    "error": f"Phone number {phone} not in applicants"
                }

            if response.status_code >= 500:
                log.error(
                    "AutoGMap server error during upload: %d, body: %s",
                    response.status_code,
                    response.text[:200],
                )
                return False, "server_error", {
                    "error": f"Server error: HTTP {response.status_code}",
                    "status_code": response.status_code,
                }

            if response.status_code >= 400:
                log.error(
                    "AutoGMap upload error: %d, body: %s",
                    response.status_code,
                    response.text[:200],
                )
                return False, "upload_error", {
                    "error": f"Upload error: HTTP {response.status_code}",
                    "status_code": response.status_code,
                }

            log.error("Unexpected response code from AutoGMap: %d", response.status_code)
            return False, "unexpected_error", {
                "error": f"Unexpected response: HTTP {response.status_code}",
                "status_code": response.status_code,
            }

        except httpx.TimeoutException as e:
            log.error("AutoGMap upload timeout after %ds: %s", self.timeout, e)
            return False, "timeout", {"error": f"Request timeout after {self.timeout}s"}
        except httpx.RequestError as e:
            log.error("AutoGMap upload network error: %s", e)
            return False, "network_error", {"error": f"Network error: {e}"}
        except Exception as e:
            log.error("AutoGMap upload unexpected error: %s", e, exc_info=True)
            return False, "unexpected_error", {"error": f"Unexpected error: {e}"}


class UploadRetryManager:
    """Manages recording upload retries with exponential backoff."""

    def __init__(
        self,
        client: AutoGMapClient,
        max_retries: int = AUTOGMAP_UPLOAD_RETRY_MAX,
        backoff_delays: list[int] = None,
    ):
        """Initialize retry manager.

        Args:
            client: AutoGMapClient instance
            max_retries: Maximum number of retries (default from env)
            backoff_delays: Backoff delays in seconds for each retry
        """
        self.client = client
        self.max_retries = max_retries
        self.backoff_delays = backoff_delays or AUTOGMAP_UPLOAD_RETRY_BACKOFF
        log.info("UploadRetryManager initialized: max_retries=%d, backoff=%s", max_retries, self.backoff_delays)

    async def upload_with_retry(
        self,
        file_path: str,
        phone: str,
        direction: str = "in",
        duration_sec: int = 0,
        device: str = None,
    ) -> tuple[bool, str, dict]:
        """Upload recording with automatic retry on retriable errors.

        Args:
            file_path: Path to audio file
            phone: Phone number
            direction: Call direction ('in' or 'out')
            duration_sec: Duration in seconds
            device: Device identifier

        Returns:
            tuple: (success, status, data) after all retries exhausted
        """
        for attempt in range(self.max_retries + 1):
            success, status, data = await self.client.upload_recording(
                file_path, phone, direction, duration_sec, device
            )

            if success:
                log.info("Upload succeeded on attempt %d", attempt + 1)
                return success, status, data

            # Non-retriable errors: don't retry
            if status in ("not_in_applicants", "file_not_found", "file_error"):
                log.warning("Upload failed with non-retriable error: %s", status)
                return success, status, data

            # Retriable errors: retry if attempts left
            if attempt < self.max_retries:
                delay = self.backoff_delays[min(attempt, len(self.backoff_delays) - 1)]
                log.warning(
                    "Upload failed (attempt %d/%d): %s, retrying in %ds",
                    attempt + 1,
                    self.max_retries + 1,
                    status,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            # All retries exhausted
            log.error(
                "Upload failed after %d attempts: %s. Last error: %s",
                self.max_retries + 1,
                status,
                data.get("error"),
            )
            return success, status, data


class UploadQueueWorker:
    """Worker for processing queued uploads at rate-limited pace (2 req/sec max)."""

    def __init__(self, client: AutoGMapClient, retry_manager: UploadRetryManager):
        """Initialize worker.

        Args:
            client: AutoGMapClient instance
            retry_manager: UploadRetryManager for retry logic
        """
        self.client = client
        self.retry_manager = retry_manager

    def process_upload(self, upload_job: dict) -> None:
        """Process a single upload job from the queue.

        Args:
            upload_job: dict with keys: rec_id, file_path, phone, direction, duration_sec, db_update_fn
        """
        import asyncio
        import time

        rec_id = upload_job["rec_id"]
        file_path = upload_job["file_path"]
        phone = upload_job["phone"]
        direction = upload_job["direction"]
        duration_sec = upload_job["duration_sec"]
        db_update_fn = upload_job["db_update_fn"]

        try:
            log.debug(f"Processing upload from queue: rec_id={rec_id}, phone={phone}")

            # Run async upload with retries
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                success, status, data = loop.run_until_complete(
                    self.retry_manager.upload_with_retry(
                        file_path, phone, direction, duration_sec
                    )
                )
            finally:
                loop.close()

            # Call the database update function with results
            db_update_fn(success, status, data)

            # Track stats
            with _sync_lock:
                _upload_stats["processed"] += 1

            if success:
                log.info(f"Upload processed successfully from queue: rec_id={rec_id}")
            else:
                log.warning(f"Upload failed from queue: rec_id={rec_id}, status={status}")

        except Exception as e:
            log.exception(f"Error processing upload from queue: rec_id={rec_id}")
            db_update_fn(False, "worker_error", {"error": str(e)})


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


def init_upload_queue() -> None:
    """Initialize the upload queue and worker thread pool on startup.

    Call once during app startup to prepare for rate-limited uploads.
    """
    global _upload_queue, _upload_executor

    if _upload_queue is not None:
        log.warning("Upload queue already initialized")
        return

    try:
        _upload_queue = Queue(maxsize=AUTOGMAP_UPLOAD_QUEUE_SIZE)
        _upload_executor = ThreadPoolExecutor(
            max_workers=AUTOGMAP_UPLOAD_MAX_WORKERS,
            thread_name_prefix="autogmap-upload-worker"
        )
        log.info(
            "AutoGMap upload queue initialized: max_workers=%d, queue_size=%d",
            AUTOGMAP_UPLOAD_MAX_WORKERS,
            AUTOGMAP_UPLOAD_QUEUE_SIZE
        )
    except Exception as e:
        log.error("Failed to initialize upload queue: %s", e)
        _upload_queue = None
        _upload_executor = None


def queue_upload(
    rec_id: int,
    file_path: str,
    phone: str,
    direction: str,
    duration_sec: int,
    db_update_fn,
) -> bool:
    """Queue a recording for rate-limited upload to AutoGMap.

    Args:
        rec_id: Recording ID
        file_path: Path to audio file
        phone: Phone number
        direction: Call direction ('in' or 'out')
        duration_sec: Call duration in seconds
        db_update_fn: Callable(success, status, data) to update database

    Returns:
        bool: True if queued successfully, False if queue is full
    """
    global _upload_queue

    if _upload_queue is None:
        log.error("Upload queue not initialized; cannot queue upload for rec_id=%d", rec_id)
        return False

    upload_job = {
        "rec_id": rec_id,
        "file_path": file_path,
        "phone": phone,
        "direction": direction,
        "duration_sec": duration_sec,
        "db_update_fn": db_update_fn,
    }

    try:
        # Non-blocking put with immediate check for full queue
        _upload_queue.put_nowait(upload_job)

        with _sync_lock:
            _upload_stats["queued"] += 1
            _upload_stats["last_queued_at"] = datetime.now(tz=ZoneInfo("UTC")).isoformat()
            queue_depth = _upload_queue.qsize()
            if queue_depth > _upload_stats["queue_peak"]:
                _upload_stats["queue_peak"] = queue_depth

        log.info(
            "Recording queued for AutoGMap upload: rec_id=%d, phone=%s, queue_depth=%d",
            rec_id,
            phone,
            queue_depth,
        )
        return True

    except Exception as e:
        with _sync_lock:
            _upload_stats["queue_full_rejections"] += 1

        log.error(
            "Failed to queue upload for rec_id=%d: %s (queue may be full)",
            rec_id,
            e,
        )
        return False


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


def upload_queue_worker(stop: threading.Event) -> None:
    """Background thread: process queued uploads with rate limiting (max 2 concurrent).

    Args:
        stop: Threading event to signal shutdown
    """
    global _upload_queue, _upload_executor

    if not AUTOGMAP_ENABLED:
        log.info("AutoGMap is disabled; upload worker not starting")
        return

    if _upload_queue is None:
        log.error("Upload queue not initialized; cannot start upload worker")
        return

    log.info("AutoGMap upload worker starting (max_workers=%d)", AUTOGMAP_UPLOAD_MAX_WORKERS)

    try:
        client = AutoGMapClient()
        retry_manager = UploadRetryManager(client)
        worker = UploadQueueWorker(client, retry_manager)
    except AutoGMapConfigError as e:
        log.error("Cannot start upload worker: %s", e)
        return

    while not stop.is_set():
        try:
            # Get next job from queue (blocking, 1 sec timeout to check stop signal)
            from queue import Empty
            try:
                upload_job = _upload_queue.get(timeout=1)
            except Empty:
                # Queue timeout (no job available), continue waiting
                continue

            log.debug(f"Dequeued upload job: rec_id={upload_job['rec_id']}")

            # Submit to thread pool executor
            _upload_executor.submit(worker.process_upload, upload_job)

        except Exception:
            log.exception("Error in upload worker loop")

    log.info("AutoGMap upload worker shutting down")


def get_upload_queue_stats() -> dict:
    """Get current queue statistics.

    Returns:
        dict: Stats with keys: queued, processed, queue_peak, queue_full_rejections, last_queued_at, current_queue_depth
    """
    with _sync_lock:
        stats = dict(_upload_stats)
        if _upload_queue is not None:
            stats["current_queue_depth"] = _upload_queue.qsize()
        else:
            stats["current_queue_depth"] = 0
    return stats


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
