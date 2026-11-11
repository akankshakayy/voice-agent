# Prachi Sync Refactoring: API Primary, Excel Secondary

**Status**: ✅ Complete (Nov 11, 2026)

**Objective**: Flip the primary/secondary relationship so Google Sheets API is the source of truth, with manual Excel upload as a temporary override only.

## Overview

The Prachi sync system now follows a clear data flow hierarchy:

```
┌─────────────────────────────────────┐
│  SOURCE OF TRUTH: Google Sheets     │
│  (Updated by Prachi team manually)  │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│  PRIMARY SYNC: API (Automatic)      │
│  - Runs daily at 2 AM UTC           │
│  - Fetches from Google Sheets export│
│  - Updates DCs & allowed_numbers    │
│  - Tracks changes: add/update/delete│
└────────────┬────────────────────────┘
             │
             ├─ SUCCESS? Update DB + mark "ok"
             │
             └─ FAILURE? Mark "failed"
                  │
                  └─ 3+ consecutive? Mark "degraded"
                       (Do NOT fall back to Excel)
                       │
                       └─ Wait for next scheduled API sync
                            (Admin can use Excel as temporary override)
             │
             ▼
┌─────────────────────────────────────┐
│  SECONDARY OVERRIDE: Excel (Manual) │
│  - Manual upload by admin only      │
│  - Temporary data override          │
│  - WARNING: Will be overwritten by  │
│    next scheduled API sync          │
└─────────────────────────────────────┘
```

## Key Behavioral Changes

| Action | Old Behavior | New Behavior |
|--------|--------------|--------------|
| Automatic sync | Falls back to Excel if missing | Always runs (primary) |
| Manual Excel upload | Permanent override | Temporary override |
| Conflict resolution | Excel wins (default) | API wins (after next sync) |
| API failure (3x) | Use Excel data | Mark DEGRADED, no fallback |
| User expectation | "Excel is the truth" | "Google Sheets is the truth" |
| Sync history | Only API tracked | Both API & manual tracked |

## Architecture

### Database Schema

**prachi_sync_history** table additions:
- `sync_source VARCHAR(20)` - "api" (primary) | "excel" (manual override)
- `status` now includes "degraded" (3+ consecutive API failures)

### Data Flow

1. **Automatic API Sync (Daily, 2 AM UTC)**
   - Fetch DCs from Google Sheets (Sheet 0)
   - Fetch SBI officials from Google Sheets (Sheet 1881479143)
   - Insert/update records in database
   - Log sync history with `sync_source = "api"`

2. **On API Failure**
   - Log error and increment `failure_streak`
   - If `failure_streak >= 3` → mark status as "degraded"
   - Do NOT fall back to Excel
   - Wait for next scheduled sync
   - Admin can manually upload Excel as emergency override

3. **Manual Excel Upload (Secondary, Temporary)**
   - Admin uploads file with `POST /api/prachi/upload-excel`
   - Parse DCs and SBI officials from Excel
   - Update database records
   - Log sync history with `sync_source = "excel"`
   - Display warning: "Will be overwritten by next API sync"

4. **Next Scheduled API Sync**
   - API data takes precedence (overwrites any Excel changes)
   - Soft-delete records no longer in Google Sheets
   - Clear failure_streak on success

### Global State Tracking

**_sync_stats** dict tracks:
- `last_sync` - timestamp of last sync attempt
- `last_sync_success` - timestamp of last successful sync
- `last_sync_error` - error message from last failure
- `sync_count` - total sync attempts
- `sync_failures` - total failure count
- `failure_streak` - consecutive failures (3+ = degraded)
- `sync_source: "api"` - always PRIMARY
- `dcs_count` - active DCs in database
- `officials_count` - active SBI officials
- `last_changes` - breakdown of adds/updates/deletes

## API Endpoints

### GET /api/prachi/sync-status
Returns current sync status and health.

**Response:**
```json
{
  "last_sync": "2026-11-11T02:00:00Z",
  "last_sync_success": "2026-11-10T02:00:00Z",
  "last_sync_error": null,
  "sync_count": 10,
  "sync_failures": 0,
  "failure_streak": 0,
  "health_status": "OK",
  "sync_source": "api",
  "dcs_count": 42,
  "officials_count": 18,
  "last_changes": {
    "dcs_added": 2,
    "dcs_updated": 1,
    "dcs_deleted": 0,
    "officials_added": 0,
    "officials_updated": 1,
    "officials_deleted": 0
  }
}
```

Health status values:
- `OK` - 0 consecutive failures
- `RECOVERING` - 1-2 consecutive failures (recovering)
- `DEGRADED` - 3+ consecutive failures (no automatic fallback)

### GET /api/prachi/sync-history?limit=50
Returns sync audit trail (both API and manual Excel uploads).

**Response:**
```json
{
  "history": [
    {
      "id": 25,
      "sync_type": "dcs_and_officials",
      "status": "success",
      "records_processed": 60,
      "records_added": 2,
      "records_updated": 1,
      "records_deleted": 0,
      "error_message": null,
      "sync_source": "api",
      "synced_at": 1731336000.123
    },
    {
      "id": 24,
      "sync_type": "dcs_and_officials",
      "status": "success",
      "records_processed": 55,
      "records_added": 0,
      "records_updated": 5,
      "records_deleted": 0,
      "error_message": null,
      "sync_source": "excel",
      "synced_at": 1731330000.456
    }
  ],
  "total": 50
}
```

### POST /api/prachi/upload-excel
SECONDARY override: manually upload Excel file.

**Request:**
```json
{
  "dcs": [
    {
      "name": "DC Name",
      "phone": "9876543210",
      "region": "North"
    }
  ],
  "officials": [
    {
      "phone": "9876543210",
      "dc_name": "DC Name",
      "description": "Officer A"
    }
  ]
}
```

**Response:**
```json
{
  "success": true,
  "dcs_result": {
    "added": 1,
    "updated": 0,
    "deleted": 0
  },
  "officials_result": {
    "added": 1,
    "updated": 0,
    "deleted": 0
  },
  "warning": "This manual upload will be overwritten by the next scheduled API sync (in ~24 hours)"
}
```

## Configuration

### Environment Variables (.env.example)

```
# Prachi Google Sheets Daily Sync (app/prachi_sync.py)
PRACHI_SHEET_ID=1lz7RihRysA10akqcwrxrRUq2fVYw4Mr-w7DclVRApLw
PRACHI_SYNC_ENABLED=true
PRACHI_SYNC_SCHEDULE_HOUR=2           # Hour of day (0-23, default: 2 AM UTC)
PRACHI_SYNC_TIMEOUT_SECONDS=60        # Request timeout
PRACHI_SYNC_RETRY_MAX=3               # Max retries on transient failures

# Primary/Secondary sources (NEW)
PRACHI_SYNC_PRIMARY=api               # "api" (Google Sheets, always primary)
PRACHI_SYNC_FALLBACK=excel            # "excel" (manual override, not automatic)
```

## Testing

### Test Coverage

**test_prachi_sync.py** includes:

1. **API Sync Tests**
   - `test_api_sync_marked_as_api_source` - Verify `sync_source = "api"`
   - `test_api_sync_failure_marks_as_api_source` - Failures stay "api" source

2. **Manual Excel Upload Tests**
   - `test_manual_excel_upload_creates_records` - Creates new records
   - `test_manual_excel_upload_updates_existing` - Updates existing records
   - `test_manual_excel_upload_marks_as_manual_override` - `sync_source = "excel"`

3. **Sync Source Tracking**
   - `test_sync_history_tracking` - Both API and manual tracked separately
   - `test_get_sync_status_shows_api_as_primary` - Status API returns `sync_source = "api"`

4. **Degraded Status**
   - `test_degraded_status_after_three_failures` - 3+ failures → degraded, no fallback

Run tests:
```bash
pytest tests/test_prachi_sync.py -v
```

## UI Flow (Admin Panel)

### Prachi Data Page

```
┌──────────────────────────────────────────────────┐
│  Prachi Data Management                          │
├──────────────────────────────────────────────────┤
│                                                  │
│  🔄 AUTOMATIC SYNC (PRIMARY)                    │
│  ├─ Source: Google Sheets API                   │
│  ├─ Last sync: 15 mins ago                      │
│  ├─ Next sync: In 14h 45m                       │
│  ├─ Status: ✅ OK                                │
│  ├─ DCs: 42 active                              │
│  ├─ Officers: 18 active                         │
│  └─ [Manual Sync Now] [View History]            │
│                                                  │
│  📤 MANUAL OVERRIDE (SECONDARY)                 │
│  ├─ Upload Excel file                           │
│  ├─ ⚠️  Warning: Will be overwritten by         │
│  │   the next API sync                          │
│  ├─ Last manual upload: 2 hours ago             │
│  └─ [Upload Excel] [View Details]               │
│                                                  │
│  📊 Sync History                                 │
│  ├─ ID | Type | Source | Status | Time          │
│  ├─ 25 | API  | api    | ✅ OK  | 15 mins ago  │
│  ├─ 24 | API  | api    | ✅ OK  | 1 day ago    │
│  └─ 23 | Excel| excel  | ✅ OK  | 2 days ago   │
│                                                  │
└──────────────────────────────────────────────────┘
```

## Migration Guide

### For Existing Deployments

1. **Database Migration**
   - Run app once (auto-migration adds `sync_source` column)
   - No manual steps required

2. **Behavior Change**
   - API sync now runs every 24 hours regardless of Excel data
   - Manual Excel uploads are temporary (next API sync overwrites)
   - 3+ API failures mark system as DEGRADED (no automatic fallback)

3. **Admin Guidance**
   - Google Sheets is now the source of truth
   - Use Excel upload only for emergency temporary fixes
   - Check sync status in dashboard regularly
   - If DEGRADED, open Google Sheets to verify latest data

### Backward Compatibility

- All existing API endpoints still work
- Sync history shows both API and manual uploads
- Old records without `sync_source` handled gracefully (NULL)
- No breaking changes to public APIs

## Monitoring & Alerting

### Dashboard Integration

The monitoring dashboard (`/monitor`) shows:
- Prachi sync status (primary API source)
- Last sync timestamp
- Success/degraded status with color coding
- Recent error history
- Manual sync button

### Alert Conditions

- **DEGRADED Status**: 3+ consecutive API failures
  - No automatic fallback (differs from old behavior)
  - Admin can manually upload Excel temporarily
  - Email/webhook alert (future enhancement)

- **Failed Upload**: Manual Excel upload error
  - Logged in sync history
  - Visible in error alerts

## Performance

### Efficiency

- Single daily API call (2 AM UTC)
- Soft-delete for removed records (no hard deletes)
- Indexed queries on sync_source and status
- Async Excel upload (non-blocking)

### Resource Usage

- Network: One 60-second timeout per sync
- Database: 3-4 queries per sync operation
- Memory: ~1MB for sheet data (42 DCs + 18 officials)

## Documentation References

- **Google Sheets**: https://docs.google.com/spreadsheets/d/1lz7RihRysA10akqcwrxrRUq2fVYw4Mr-w7DclVRApLw
- **Phase 7d Dashboard**: docs/phase7d-monitoring-dashboard.md
- **Phase 7b Recording Upload**: docs/phase7b-recording-upload.md

## Related Phases

- Phase 7a: AutoGMap numbers sync
- Phase 7b: Recording upload + Prachi integration
- Phase 7d: Monitoring dashboard

## Files Modified

1. **app/db.py** (+10 lines)
   - Added `sync_source` column to prachi_sync_history
   - Added migration for existing databases

2. **app/prachi_sync.py** (+150 lines)
   - `manual_excel_upload()` - NEW: Handle manual Excel uploads
   - Updated `run_daily_sync()` - Track sync_source, failure_streak, degraded status
   - Updated `get_sync_status()` - Return sync_source and health_status

3. **app/main.py** (+130 lines)
   - `GET /api/prachi/sync-status` - NEW
   - `GET /api/prachi/sync-history` - NEW
   - `POST /api/prachi/upload-excel` - NEW

4. **tests/test_prachi_sync.py** (+180 lines)
   - Added test classes for manual Excel upload
   - Added test classes for sync_source tracking
   - Added test classes for degraded status

## Summary

✅ **API is now PRIMARY** (always runs, no fallback)
✅ **Excel is now SECONDARY** (manual override only, temporary)
✅ **Degraded status** (3+ API failures, no automatic fallback)
✅ **Sync history tracks source** (both API and manual uploads)
✅ **Clear user warnings** (Excel data will be overwritten)
✅ **Production-ready** (tested, documented, backward compatible)
