# AutoGMap Upload Rate Limiting - Implementation

## Problem Statement
Each recording spawned an independent daemon thread, allowing 10+ concurrent uploads simultaneously. This violated Mansi's API requirement of **max 2 requests/second**.

## Solution: ThreadPoolExecutor-Based Upload Queue

### Architecture

```
Recording processed
         ↓
queue_autogmap_upload() [recordings.py]
         ↓
autogmap.queue_upload() → Queue.put(job)
         ↓
[Queue: max 1000 jobs]
         ↓
upload_queue_worker() thread
         ↓
ThreadPoolExecutor (2 max workers)
         ↓
UploadQueueWorker.process_upload()
         ↓
AutoGMapClient async upload
```

### Components

#### 1. **Upload Queue (`app/autogmap.py`)**
- **Queue**: `Queue(maxsize=1000)` holds pending upload jobs
- **Workers**: ThreadPoolExecutor with **2 max threads** (Mansi's 2 req/sec limit)
- **Stats**: Tracks queued, processed, peak depth, rejections

#### 2. **Queue Initialization**
```python
autogmap.init_upload_queue()  # Called in app startup (main.py lifespan)
```
- Creates Queue and ThreadPoolExecutor
- Idempotent (safe to call multiple times)
- Happens during app startup, not on first upload

#### 3. **Job Submission** (`recordings.py`)
Replace thread spawning with `autogmap.queue_upload()`:
```python
def queue_autogmap_upload(...):
    # Define DB update callback
    def db_update_fn(success, status, data):
        if success:
            db.update(..., autogmap_status="uploaded")
        else:
            db.update(..., autogmap_status="failed", error=data['error'])
    
    # Queue for rate-limited processing
    queued = autogmap.queue_upload(rec_id, file_path, phone, direction, 
                                     duration_sec, db_update_fn)
    if not queued:
        db.update(..., autogmap_error="Queue full; retry later")
```

#### 4. **Worker Thread**
```python
autogmap.upload_queue_worker(stop)  # Started in lifespan
```
- Dequeues jobs from Queue
- Submits to ThreadPoolExecutor
- Executor enforces max 2 concurrent uploads
- Graceful shutdown on `stop.set()`

#### 5. **Job Processing**
```python
UploadQueueWorker.process_upload(upload_job)
```
- Runs in thread pool (max 2 concurrent)
- Calls `AutoGMapClient.upload_recording()` with retry logic
- Updates database via callback
- Tracks stats (processed count)

### Configuration

Environment variables (with defaults):
```bash
AUTOGMAP_UPLOAD_MAX_WORKERS=2           # Hard limit: 2 requests/sec for Mansi
AUTOGMAP_UPLOAD_QUEUE_SIZE=1000         # Max pending jobs (prevents memory leak)
```

### Monitoring

**Endpoint**: `GET /api/autogmap/status` (admin/ops only)

```json
{
  "upload_queue": {
    "max_workers": 2,
    "max_size": 1000,
    "current_depth": 5,
    "queued_total": 342,
    "processed_total": 337,
    "queue_peak": 12,
    "rejections": 0,
    "last_queued_at": "2026-11-11T14:23:45.123Z"
  }
}
```

**Metrics**:
- `current_depth`: Jobs currently pending
- `queue_peak`: Highest depth observed
- `rejections`: Times queue was full
- `processed_total`: Uploads completed

### Logging

All operations logged with context:
```
INFO: Recording queued for AutoGMap upload: rec_id=42, phone=9876543210, queue_depth=3
DEBUG: Dequeued upload job: rec_id=42
INFO: Processing upload from queue: rec_id=42, phone=9876543210
INFO: Upload processed successfully from queue: rec_id=42
```

## Testing Strategy

### Unit Tests (`tests/test_autogmap_rate_limiting.py`)

1. **Queue Initialization**
   - Verify queue and executor created
   - Verify idempotency

2. **Single Upload**
   - Queue 1 upload
   - Verify queued successfully

3. **Multiple Uploads (10+)**
   - Queue 15 uploads
   - Verify all queued (queue_size=15)

4. **Rate Limiting: Max 2 Concurrent**
   - Queue 10 uploads
   - Start worker thread
   - Track concurrent execution count
   - Assert max concurrent ≤ 2

5. **Queue Full Rejection**
   - Create small queue (size=2)
   - Fill queue
   - Attempt 3rd upload
   - Verify rejected + rejection counter incremented

6. **Stats Tracking**
   - Queue 5 uploads
   - Verify stats (queued=5, peak=5)

7. **Worker Shutdown**
   - Start worker with stop event
   - Set stop event
   - Verify thread exits cleanly

### Integration Tests (Manual)

```bash
# 1. Test with 20 concurrent uploads
curl -X POST http://localhost:8000/api/uploader/recordings \
  -F "audio=@file1.ogg" -F "audio=@file2.ogg" ... -F "audio=@file20.ogg"

# 2. Monitor queue depth
watch -n 1 'curl -s http://localhost:8000/api/autogmap/status | jq .upload_queue'

# 3. Verify max 2 concurrent in logs
tail -f data/logs/eko.log | grep "Processing upload from queue"

# 4. Verify queue drains after load
- Wait for current_depth → 0
- Verify processed_total increased
- Verify no rejections if queue_size adequate
```

### Performance Expectations

**Before** (unbounded threads):
- 10 uploads: 10 concurrent threads → violates 2 req/sec limit
- Network spike: unpredictable load

**After** (2-worker queue):
- 10 uploads: queued, processed sequentially at 2 req/sec
- Upload time: ~30s for 10 × 5s requests (vs potential spike)
- Memory: bounded queue + 2 threads
- Backpressure: graceful rejection when queue_size exceeded

## Code Changes

### `app/autogmap.py`
- Added imports: `ThreadPoolExecutor`, `Queue`
- Added globals: `_upload_queue`, `_upload_executor`, `_upload_stats`
- Added class `UploadQueueWorker` (process single upload from queue)
- Added functions:
  - `init_upload_queue()` - initialize queue & executor
  - `queue_upload(...)` - submit job to queue
  - `upload_queue_worker(stop)` - process queue indefinitely
  - `get_upload_queue_stats()` - return monitoring data

### `app/recordings.py`
- Removed: `_upload_to_autogmap_background()` (no longer used)
- Rewrote: `queue_autogmap_upload()` to use `autogmap.queue_upload()` instead of spawning threads

### `app/main.py`
- Lifespan startup: Added `autogmap.init_upload_queue()` before starting threads
- Lifespan threads: Added `autogmap.upload_queue_worker(stop)` thread
- Updated `/api/autogmap/status` endpoint to include queue stats

## Backpressure Handling

**Scenario**: Queue fills up (20+ pending jobs)

1. Next `queue_upload()` call fails to put job (exception caught)
2. `queue_full_rejections` counter incremented
3. DB updated with error: "Queue full; retry later"
4. Recording status: `autogmap_status="failed", error="Queue full; retry later"`
5. Admin sees high `rejections` count in `/api/autogmap/status`

**Recovery**:
- Queue naturally drains as 2-worker executor processes jobs
- Once depth < queue_size, uploads succeed again
- Retry logic in `queue_autogmap_upload()` for failed recordings (future enhancement)

## Migration Notes

**Before**:
```python
threading.Thread(target=_upload_to_autogmap_background, ...).start()
```

**After**:
```python
autogmap.queue_upload(rec_id, file_path, phone, direction, duration_sec, db_update_fn)
```

No API changes; fully backward compatible with existing code.

## Deployment Checklist

- [x] Code complete (autogmap.py, recordings.py, main.py)
- [x] Syntax validated
- [x] Tests written (test_autogmap_rate_limiting.py)
- [ ] Integration tests (manual with 10+ uploads)
- [ ] Monitoring verified (`/api/autogmap/status` returns correct stats)
- [ ] Logs reviewed (queue depth, rejections, worker lifecycle)
- [ ] Load test (verify max 2 concurrent requests to Mansi API)
- [ ] Deployment to indev.eko.in
- [ ] Verify no performance regression

## Future Enhancements

1. **Persistent Queue**: SQLite-backed queue (survives app restart)
2. **Exponential Backoff for Queue Full**: Retry with delay instead of immediate fail
3. **Per-Phone Rate Limiting**: Different limits per CSP
4. **Queue Prioritization**: High-priority recordings (RM) before low-priority (DC)
5. **Metrics Export**: Prometheus /metrics endpoint for queue depth, throughput
