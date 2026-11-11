# Phase 7b - Recording Upload + Prachi Integration

**Date:** November 11, 2026  
**Status:** Complete (Production Ready)  
**Module:** `app/autogmap.py`, `app/recordings.py`

## Overview

Phase 7b extends Phase 7a (AutoGMap Numbers Sync) with:
1. **AutoGMap Recording Upload** - Upload RM call recordings to AutoGMap after processing
2. **Prachi Integration** - Submit DC recordings with transcripts to Prachi API
3. **Retry Logic** - Exponential backoff for resilient uploads
4. **Database Tracking** - Full audit trail of upload attempts and statuses

## AutoGMap Recording Upload

### Architecture

```
Recording Processed (RM mode)
    ↓
Check if phone in AutoGMap applicants
    ├─ YES → Queue for upload
    │        └─ Background worker uploads with retries
    │
    └─ NO → Mark as "not_in_applicants"
```

### Upload Process

1. **Queueing** (non-blocking, instant)
   - Call `queue_autogmap_upload(rec_id, file_path, phone, direction, duration_sec)`
   - Checks if phone is in cached AutoGMap numbers
   - Sets `autogmap_status = "pending"`
   - Spawns background worker thread

2. **Background Upload**
   - Worker creates `AutoGMapClient` and `UploadRetryManager`
   - Attempts upload with retry on server errors
   - Updates database with final status

3. **Retry Logic**
   - Max retries: `AUTOGMAP_UPLOAD_RETRY_MAX` (default: 3)
   - Backoff delays: `AUTOGMAP_UPLOAD_RETRY_BACKOFF` (default: 60s, 300s, 900s)
   - Non-retriable errors (422, 404, file errors) → no retry
   - Retriable errors (500, timeout, network) → retry with backoff

### Database Schema

Columns added to `recordings` table:

```sql
autogmap_status VARCHAR(20)       -- pending | uploaded | failed | not_in_applicants
autogmap_sent_at REAL             -- Timestamp when sent to AutoGMap
autogmap_error TEXT               -- Error message if failed
autogmap_attempts INTEGER         -- Number of attempts made

-- Index for tracking
CREATE INDEX idx_recordings_autogmap ON recordings(autogmap_status, uploaded_at DESC);
```

### Return Values

```python
success, status, data = await client.upload_recording(
    file_path="/path/to/file.ogg",
    phone="9876543210",
    direction="inbound",
    duration_sec=120
)

# Returns tuple:
# - success: bool (True if uploaded)
# - status: str (uploaded | not_in_applicants | server_error | timeout | file_not_found | network_error)
# - data: dict (response data or error details)
```

### Status Meanings

| Status | Success | Retriable | Meaning |
|--------|---------|-----------|---------|
| `uploaded` | ✓ | - | File successfully uploaded |
| `not_in_applicants` | ✗ | ✗ | Phone not in AutoGMap list (check cache) |
| `server_error` | ✗ | ✓ | AutoGMap API returned 500+ (will retry) |
| `timeout` | ✗ | ✓ | Request timeout after 60s (will retry) |
| `network_error` | ✗ | ✓ | Network error (will retry) |
| `file_not_found` | ✗ | ✗ | Recording file doesn't exist |
| `file_error` | ✗ | ✗ | File is empty or unreadable |
| `upload_error` | ✗ | ✗ | AutoGMap returned 400-499 (don't retry) |
| `unexpected_error` | ✗ | ✗ | Unexpected error (don't retry) |

### Example Usage

```python
from app.recordings import queue_autogmap_upload
from app import db

# After recording is processed and saved to disk
queue_autogmap_upload(
    rec_id=123,
    file_path="rm1/2025-01-15/abc123def.ogg",
    phone="9876543210",
    direction="inbound",
    duration_sec=180
)

# Check status later
rec = db.q("SELECT autogmap_status, autogmap_error FROM recordings WHERE id=123", one=True)
if rec["autogmap_status"] == "uploaded":
    print("✓ Recording uploaded to AutoGMap")
elif rec["autogmap_status"] == "failed":
    print(f"✗ Upload failed: {rec['autogmap_error']}")
elif rec["autogmap_status"] == "not_in_applicants":
    print("Phone not in AutoGMap applicants")
```

## Prachi Integration (DC Mode)

### Architecture

```
DC Recording Processed
    ↓
Extract transcript, metadata
    ↓
POST to Prachi API
    ├─ Success (200) → Store request_id, mark as sent
    │
    ├─ Server Error (5xx) → Log for retry
    │
    └─ Client Error (4xx) → Log failure, don't retry
```

### Prachi API Submission

**Endpoint:** `POST /api/prachi/recordings`

**Required Metadata:**
- `recording_id` (int)
- `dc_id` (int)
- `timestamp` (float)
- `transcript` (list of transcript lines with speakers)
- `other_number` (str, CSP phone)
- `duration_sec` (int)

**Response:**
```json
{
  "status": "submitted",
  "request_id": "prachi_req_12345",
  "recording_id": 123
}
```

### Implementation

Function: `send_to_prachi_api(rec: dict) -> bool`

Returns:
- `True`: Success or fatal error (don't retry)
- `False`: Transient error, will retry on next run

```python
# Called automatically after DC recording is transcribed
rec_updated = db.q("SELECT * FROM recordings WHERE id=?", (rec_id,), one=True)
if not send_to_prachi_api(rec_updated):
    # Will be retried on next processing run
    log.warning(f"Recording {rec_id} failed to send to Prachi; will retry")
```

### Database Tracking

Columns on `recordings` table:
```sql
prachi_api_sent_at REAL        -- When sent to Prachi
prachi_request_id TEXT         -- Prachi's request ID for tracking
```

Separate table for detailed submissions:
```sql
CREATE TABLE prachi_submissions (
    id INTEGER PRIMARY KEY,
    recording_id INTEGER UNIQUE,
    dc_id INTEGER,
    dc_name TEXT,
    dc_phone TEXT,
    caller_number TEXT,
    recipient_number TEXT,
    call_direction TEXT,
    duration_sec INTEGER,
    uploaded_at TEXT,
    transcript TEXT,
    transcript_json TEXT,
    file_path TEXT,
    status TEXT,               -- pending | submitted | failed | success
    attempts INTEGER,
    prachi_request_id TEXT,
    received_at REAL,
    processed_at REAL,
    error_message TEXT
);
```

## Environment Variables

### Phase 7b Configuration

```bash
# AutoGMap Recording Upload
AUTOGMAP_UPLOAD_RETRY_MAX=3                    # Max retry attempts
AUTOGMAP_UPLOAD_RETRY_BACKOFF=60,300,900       # Backoff delays (seconds)
AUTOGMAP_UPLOAD_TIMEOUT_SECONDS=60             # Request timeout

# Prachi Integration (DC Mode)
PRACHI_API_URL=https://prachi.eko.in          # Prachi API base URL
# PRACHI_API_KEY: Set in .env.local (not in version control)
```

### Existing (Phase 7a)

```bash
# AutoGMap Numbers Sync
AUTOGMAP_ENABLED=true
AUTOGMAP_NUMBERS_URL=https://indev.eko.in/autogmap/api/v1/call-recorder/numbers
AUTOGMAP_RECORDINGS_URL=https://indev.eko.in/autogmap/api/v1/call-recorder/recordings
# AUTOGMAP_API_KEY: Request from Mansi team, set in .env.local
AUTOGMAP_SYNC_INTERVAL_MINUTES=15
AUTOGMAP_SYNC_TIMEOUT_SECONDS=30
```

## Test Coverage

### Unit Tests (test_autogmap_upload.py)

- ✓ Upload recording - success (201)
- ✓ Upload recording - not in applicants (422)
- ✓ Upload recording - server error (500)
- ✓ Upload recording - timeout
- ✓ Upload recording - file not found
- ✓ Upload recording - empty file
- ✓ Retry manager - retries on server error
- ✓ Retry manager - no retry on non-retriable error
- ✓ Retry manager - exhausts retries
- ✓ Recording integration - queue with valid number
- ✓ Recording integration - queue with invalid number

### Unit Tests (test_prachi.py)

- ✓ Prachi submission - success (200)
- ✓ Prachi submission - server error (500, retriable)
- ✓ Prachi submission - client error (400, not retriable)
- ✓ Prachi submission - timeout (retriable)
- ✓ Prachi submission - no transcript (skipped)
- ✓ Prachi submission - missing config (skipped)
- ✓ Prachi submission status tracking

### Manual Testing Checklist

- [ ] Upload recording to AutoGMap (with mock API)
  - Verify file is read correctly
  - Verify multipart form submission
  - Confirm success response is parsed
  
- [ ] Test retry logic
  - Simulate server error (500)
  - Verify retry happens after first delay
  - Verify second retry with longer delay
  - Confirm final failure after max retries
  
- [ ] Check database status tracking
  - Query recordings table for autogmap_* columns
  - Verify status transitions: pending → uploaded/failed
  - Verify error messages are saved
  
- [ ] Test Prachi submission
  - Create DC mode recording with transcript
  - Trigger processing
  - Verify POST to Prachi endpoint
  - Confirm prachi_request_id is saved
  
- [ ] Test mixed mode
  - RM recording → AutoGMap upload
  - DC recording → Prachi submission (mutually exclusive)
  - Employee recording → Mansi submission (no transcription)
  
- [ ] Test edge cases
  - Recording with no other_number → skip upload
  - Recording with zero duration → skip upload
  - Phone not in AutoGMap → mark not_in_applicants
  - Network failure → retry 3 times, then fail
  - Timeout on last retry → fail

## API Endpoints

### AutoGMap Upload Endpoint

**URL:** `https://indev.eko.in/autogmap/api/v1/call-recorder/recordings`  
**Method:** `POST`  
**Auth:** `X-API-Key` header  

**Request:**
```
multipart/form-data:
  file: <binary audio>
  phone: "9876543210"
  direction: "inbound" | "outbound"
  duration: "120"
  uploaded_at: "2026-01-15T10:00:00Z"
  device: "RM-001"  (optional)
```

**Response (201):**
```json
{
  "recording_id": "rec_abc123",
  "status": "accepted",
  "phone": "9876543210"
}
```

**Response (422):**
```json
{
  "error": "Phone number not in applicants list",
  "phone": "9876543210"
}
```

### Prachi Recording Endpoint

**URL:** `POST /api/prachi/recordings` (via app/main.py)  
**Auth:** Internal API, no auth required  

See `app/main.py` for full implementation.

## Logging

### AutoGMap Upload Logs

```
INFO: "Recording {id} queued for AutoGMap upload (phone={phone})"
DEBUG: "Uploading recording to AutoGMap: phone={phone}, direction={direction}, duration={duration_sec}, size={size_bytes} bytes"
INFO: "Recording uploaded to AutoGMap: phone={phone}, file={file_path}, size={size_bytes} bytes"
WARNING: "Recording not in AutoGMap applicants: phone={phone}, file={file_path}"
WARNING: "Upload failed (attempt {attempt}/{max}): {status}, retrying in {delay}s"
ERROR: "Upload failed after {max_attempts} attempts: {status}. Last error: {error}"
```

### Prachi Logs

```
INFO: "Recording {id} sent to Prachi API (req_id={request_id})"
WARNING: "Prachi API error {status_code} for recording {id}; will retry"
ERROR: "Prachi API rejected recording {id}: {status_code}"
WARNING: "Prachi API timeout for recording {id}; will retry"
ERROR: "Failed to send recording {id} to Prachi API: {error}"
```

## Error Handling

### Non-Retriable Errors (No Retry)
- File not found (ENOENT)
- File is empty (0 bytes)
- Phone not in applicants (422)
- Invalid request format (400)
- Authentication failure (401)
- Authorization failure (403)

### Retriable Errors (Automatic Retry)
- Server error (500, 502, 503, 504)
- Request timeout (after 60s)
- Network error (connection refused, DNS failure, etc.)
- Transient failures (temporary service degradation)

### Handling Strategy
1. First attempt: immediate
2. Second attempt: after 60 seconds
3. Third attempt: after 300 seconds (5 min)
4. Fourth attempt: after 900 seconds (15 min)
5. Give up: log error, mark as failed

## Performance Characteristics

- **Upload time:** 30-120 seconds depending on file size and network
- **Memory overhead:** ~100KB per concurrent upload (streaming)
- **DB operations:** 1 SELECT + 1 UPDATE per recording (minimal impact)
- **Thread pool:** One daemon thread per upload (auto-cleaned)
- **Disk I/O:** Single-threaded file read (no buffering)

## Security Considerations

1. **API Key Protection**
   - Never log API key or auth tokens
   - Never include in debug output
   - Use env variables only

2. **File Validation**
   - Verify file exists before upload
   - Check file size > 0
   - Verify file path is within storage_dir()
   - Don't allow arbitrary paths

3. **Phone Number Validation**
   - Normalize phone numbers (last 10 digits)
   - Validate format before upload
   - Check against AutoGMap applicants cache

4. **Error Messages**
   - Don't expose full server responses to users
   - Log full errors internally for debugging
   - Return generic messages to API clients

## Migration Notes

### Database
- Columns already added via `db.py` migrations
- Index on `autogmap_status` auto-created
- `prachi_submissions` table exists since Phase 7

### Backward Compatibility
- No breaking changes to existing APIs
- AutoGMap upload is opt-in (requires AUTOGMAP_API_KEY)
- Prachi submission only for DC mode recordings
- RM mode recordings unaffected

### Rollback Plan
1. Set `AUTOGMAP_ENABLED=false` to disable sync and uploads
2. Delete `autogmap_*` columns from recordings (optional cleanup)
3. Existing submissions remain in database for audit
4. No data loss - all statuses are tracked

## Future Enhancements

1. **Batch Uploads**
   - Group recordings by phone number
   - Upload multiple files in single request
   - Reduce API calls and network overhead

2. **Webhook Callbacks**
   - Register webhook for AutoGMap submission status
   - Real-time updates instead of polling
   - Async notification system

3. **Admin Dashboard**
   - View upload status for all recordings
   - Retry failed uploads manually
   - Inspect request/response logs

4. **Metrics & Monitoring**
   - Track upload success rate by hour/day
   - Monitor average upload time
   - Alert on sustained failures
   - Dashboard with success metrics

## Troubleshooting

### Uploads Not Happening
1. Check `AUTOGMAP_ENABLED=true` in `.env`
2. Verify `AUTOGMAP_API_KEY` is set and correct
3. Confirm phone numbers are in AutoGMap (check cache)
4. Look for logs: `autogmap_status` column should be "pending"

### "Not in Applicants" Error (422)
1. Sync may be stale - check `autogmap_numbers` table
2. Manual sync: `app.autogmap.AutoGMapSync().sync_numbers()`
3. Verify phone format (last 10 digits)
4. Confirm phone was in latest sync response

### Timeout Errors
1. Check network connectivity to AutoGMap API
2. Verify firewall rules allow HTTPS to indev.eko.in
3. Test with curl: `curl -H "X-API-Key: ..." https://indev.eko.in/autogmap/api/v1/call-recorder/numbers`
4. Increase `AUTOGMAP_UPLOAD_TIMEOUT_SECONDS` if needed (default: 60s)

### Prachi Submission Failures
1. Verify `PRACHI_API_URL` and `PRACHI_API_KEY` are set
2. Test endpoint with curl
3. Check transcript is valid JSON
4. Verify DC and recording are in database

## References

- [Phase 7a - Numbers Sync](./PHASE7A_AUTOGMAP_NUMBERS.md)
- [Phase 7 Action Plan](./PHASE7_ACTION_PLAN.md)
- [AutoGMap API Documentation](https://docs.autogmap.eko.in/)
- [Prachi API Documentation](https://docs.prachi.eko.in/)
