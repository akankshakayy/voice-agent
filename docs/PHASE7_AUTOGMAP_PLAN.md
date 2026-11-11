# Phase 7 - AutoGMap Integration Plan

**Status:** 📋 PLANNING  
**Priority:** HIGH (unblocks call recording feature)  
**Dependency:** AutoGMap API key from Mansi  
**Timeline:** 3-4 weeks  
**Owner:** Eko Sahayak Backend + Mobile Teams

---

## Executive Summary

Integrate Eko's uploader system with AutoGMap's call-recorder. This enables:
- Automatic recording of calls to/from specific applicants
- Real-time upload of recordings to AutoGMap
- 2-way sync: fetch applicant numbers every 15 min, upload recordings immediately

**Key Integration Points:**
1. Backend: Fetch numbers, validate, store in cache
2. Kotlin App: Filter call logs, auto-record matching numbers
3. Backend: Upload recordings to AutoGMap with metadata
4. Monitoring: Track sync success, alert on failures

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     AutoGMap System                          │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ GET /call-recorder/numbers  (every 15 min)         │   │
│  │ POST /call-recorder/recordings  (after call)        │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────┬──────────────────────────────────────────┘
                   │ (API Key: X-API-Key header)
                   │
    ┌──────────────┴──────────────┐
    ▼                             ▼
┌──────────────────┐    ┌─────────────────────┐
│ Eko Backend      │    │ Eko Kotlin App      │
│                  │    │                     │
│ 1. Fetch numbers │    │ 1. Check call log   │
│ 2. Cache them    │    │ 2. Match against    │
│ 3. Upload rec.   │    │    cached numbers   │
│ 4. Monitor       │    │ 3. Auto-record      │
│                  │    │ 4. Upload to API    │
└──────────────────┘    └─────────────────────┘
```

---

## Phase 7 Breakdown

### Phase 7a: Backend - Numbers Sync (Week 1)

**Goal:** Fetch applicant numbers from AutoGMap every 15 minutes

**Tasks:**

1. **Create scheduler job** (`app/autogmap.py`)
   ```python
   class AutoGMapSync:
       def __init__(self):
           self.numbers = set()
           self.last_sync = None
       
       async def sync_numbers(self):
           # Fetch from AutoGMap
           # Parse response
           # Store in memory + database
           # Log success/failure
   ```

2. **Add database table** (if not using memory cache)
   ```sql
   CREATE TABLE autogmap_numbers (
       id INTEGER PRIMARY KEY,
       phone VARCHAR(20) NOT NULL,
       local VARCHAR(10) NOT NULL,
       name VARCHAR(255),
       since DATETIME,
       synced_at DATETIME,
       active INTEGER DEFAULT 1
   )
   ```

3. **Setup cron job** (every 15 minutes)
   - Using APScheduler or similar
   - Trigger: `sync_numbers()`
   - Error handling: log + alert

4. **Add monitoring**
   - Last sync timestamp
   - Success/failure count
   - Numbers count
   - API response time

**Files to Create:**
- `app/autogmap.py` - Core integration logic
- `app/models/autogmap.py` - Data structures
- Database migration (if using DB)

**Tests:**
- [ ] Fetch numbers successfully
- [ ] Parse response correctly
- [ ] Store numbers in cache
- [ ] Handle API errors (retry logic)
- [ ] Handle network timeout
- [ ] Cron runs every 15 min

---

### Phase 7b: Backend - Recording Upload (Week 1)

**Goal:** Upload recordings to AutoGMap after call completes

**Tasks:**

1. **Enhance upload handler** (`app/recordings.py`)
   ```python
   async def upload_to_autogmap(recording):
       # After recording is saved
       # Prepare multipart form
       # Upload to AutoGMap
       # Track status
       # Retry on failure
   ```

2. **Add retry logic**
   - Max retries: 3
   - Backoff: 60s, 300s, 900s
   - Log each attempt
   - Alert after final failure

3. **Track upload status** (database)
   ```sql
   ALTER TABLE recordings ADD COLUMN autogmap_status VARCHAR(20);
   ALTER TABLE recordings ADD COLUMN autogmap_sent_at DATETIME;
   ALTER TABLE recordings ADD COLUMN autogmap_error TEXT;
   ```

4. **Error handling**
   - 201: Success ✅
   - 422: Not in applicants (log warning, continue)
   - 500: Server error (retry)
   - Network error: Queue for retry

**Files to Modify:**
- `app/recordings.py` - Add upload logic
- `app/autogmap.py` - Add upload methods

**Tests:**
- [ ] Upload successful recording
- [ ] Handle 422 (not in applicants)
- [ ] Retry on 500 error
- [ ] Retry on network timeout
- [ ] Max retries respected
- [ ] Status tracked in DB

---

### Phase 7c: Kotlin App - Call Recording (Week 2)

**Goal:** Auto-record calls to/from cached numbers

**Tasks:**

1. **Add numbers cache** (Kotlin)
   ```kotlin
   object AutoGMapCache {
       var numbers: Set<String> = emptySet()
       var lastSync: Long = 0
       
       fun contains(phone: String): Boolean
       fun update(newNumbers: Set<String>)
   }
   ```

2. **Fetch numbers on app startup**
   - Call `sync_numbers()` from backend
   - Cache in memory
   - Use cached list until next sync

3. **Check incoming/outgoing calls**
   ```kotlin
   fun onCallStarted(phone: String) {
       if (AutoGMapCache.contains(phone)) {
           startRecording()  // Auto-record
       }
   }
   ```

4. **On call end**
   - Stop recording
   - Upload to AutoGMap backend API
   - Track status in UI (optional)

**Files to Modify:**
- `MainActivity.kt` - Add cache sync
- `CallRecorder.kt` - Check numbers before recording
- `UploadWorker.kt` - Add AutoGMap upload

**Tests:**
- [ ] Cache updates on app start
- [ ] Detects matching numbers
- [ ] Auto-records when matched
- [ ] Uploads after call ends
- [ ] Handles non-matching numbers

---

### Phase 7d: Monitoring & Alerting (Week 2-3)

**Goal:** Track integration health, alert on failures

**Metrics to Track:**
- Numbers sync success rate
- Numbers count (should be stable)
- Recording upload success rate
- Upload failures by error type (422 vs 500)
- Average sync time
- Average upload time

**Logging:**
```
[INFO] AutoGMap sync: 25 numbers fetched (took 0.5s)
[INFO] Recording uploaded to AutoGMap: ID=361, phone=9876543210
[WARN] Recording not in AutoGMap applicants: phone=9111111111
[ERROR] AutoGMap upload failed: 500 Server Error (retry 1/3)
[ERROR] AutoGMap sync failed after 3 retries: Network timeout
```

**Alerting Rules:**
- Sync fails 3+ times → Alert
- Upload fails 5+ times → Alert
- Sync not run for 30 min → Alert
- Numbers count changes > 50% → Notify (expected?)

**Dashboard Metrics:**
- Last sync: timestamp + status
- Numbers count: X applicants
- Upload success: X% today
- Recent errors: last 5 failures

**Files:**
- `app/monitoring/autogmap.py` - Metrics collection
- Add to existing dashboard

---

### Phase 7e: Testing & QA (Week 3)

**Unit Tests:**
```python
# test_autogmap.py
def test_fetch_numbers():
    """Parse AutoGMap response correctly."""
    
def test_upload_recording():
    """Upload with correct multipart format."""
    
def test_retry_logic():
    """Retry after backoff delays."""
    
def test_error_handling():
    """Handle 422, 500, network errors."""
```

**Integration Tests:**
```python
def test_end_to_end():
    """1. Fetch numbers from AutoGMap
       2. Record call to matching number
       3. Upload recording
       4. Verify AutoGMap received it"""
```

**Manual Testing Checklist:**
- [ ] Deploy to dev environment
- [ ] Create test numbers in AutoGMap
- [ ] Make test calls to those numbers
- [ ] Verify recordings uploaded
- [ ] Check database status
- [ ] Test sync every 15 min
- [ ] Test retry on failure
- [ ] Verify metrics/logs
- [ ] Load test: 100 simultaneous calls
- [ ] Verify no data loss on restarts

---

## Implementation Timeline

```
Week 1:
  Mon: Backend numbers sync + database
  Tue: Recording upload + retry logic
  Wed: Testing + bug fixes
  Thu: Deploy to staging

Week 2:
  Mon-Tue: Kotlin app integration
  Wed: App testing + debugging
  Thu: End-to-end testing

Week 3:
  Mon-Tue: Monitoring + alerting
  Wed: Performance testing
  Thu: Load testing + optimization

Week 4:
  Mon-Tue: Security review + hardening
  Wed: Documentation + runbooks
  Thu: Production deployment + verification
```

---

## Configuration

### Environment Variables

```bash
# .env
AUTOGMAP_ENABLED=true
AUTOGMAP_NUMBERS_URL=https://indev.eko.in/autogmap/api/v1/call-recorder/numbers
AUTOGMAP_RECORDINGS_URL=https://indev.eko.in/autogmap/api/v1/call-recorder/recordings
# AUTOGMAP_AUTH_KEY: [REQUEST FROM MANSI - store in .env only]

# Sync settings
AUTOGMAP_SYNC_INTERVAL_MINUTES=15
AUTOGMAP_SYNC_TIMEOUT_SECONDS=30
AUTOGMAP_SYNC_MAX_RETRIES=3

# Upload settings
AUTOGMAP_UPLOAD_RETRY_MAX=3
AUTOGMAP_UPLOAD_RETRY_BACKOFF=60,300,900  # seconds
AUTOGMAP_UPLOAD_TIMEOUT=60

# Monitoring
AUTOGMAP_METRICS_ENABLED=true
AUTOGMAP_ALERT_ON_FAILURES=true
AUTOGMAP_ALERT_THRESHOLD=3  # Alert after N failures
```

### Configuration Template
See .env.example file for the complete configuration template. Copy it to .env and fill in the authentication key from Mansi (never commit).

---

## Dependencies & Blockers

### Dependencies:
- ✅ Phase 6 backend complete (bulk load)
- ✅ Phase 4 recording processing complete
- ⏳ Mansi's API key (BLOCKING)
- ⏳ AutoGMap staging environment access
- ⏳ Test numbers in AutoGMap

### Potential Blockers:
- Network latency between servers
- AutoGMap API rate limits
- Call recording permissions (Android)
- Database migration complexity
- Monitoring infrastructure

### Risk Mitigation:
- Start with staging environment
- Comprehensive logging + monitoring
- Automatic fallback (record all calls if sync fails)
- Weekly syncs with Mansi team

---

## Success Criteria

✅ **Functional:**
- Numbers synced every 15 minutes
- 95%+ of recordings uploaded successfully
- Failed uploads retry automatically
- Dashboard shows real-time status

✅ **Performance:**
- Sync takes < 5 seconds
- Upload takes < 10 seconds
- No impact on call recording

✅ **Reliability:**
- Zero data loss
- Automatic recovery from failures
- Clear error messages + logs
- Monitoring alerts on issues

✅ **Security:**
- API key never in logs
- HTTPS only
- Rate limiting respected
- Input validation on all fields

---

## Cost Analysis

**Infrastructure:**
- Database: +10GB (numbers table, status tracking)
- API calls: ~100/day (sync) + 1000+/day (uploads)
- Monitoring: Negligible

**Effort:**
- Backend: 40-60 hours
- Mobile: 20-30 hours
- Testing: 20-30 hours
- Monitoring: 10-15 hours
- **Total: ~100-150 hours (~3 weeks)**

**ROI:**
- Enables AutoGMap call recording feature
- Improves data quality (real recordings vs transcripts)
- Reduces manual work (auto-recording)

---

## Open Questions for Mansi

1. **API Key & Access:**
   - When can we get API key?
   - Can we test with staging endpoint?

2. **Data:**
   - Will test numbers be available?
   - What's the expected numbers count?

3. **SLA & Limits:**
   - Upload size limits?
   - Rate limits on endpoints?
   - Expected response times?

4. **Reliability:**
   - Should we cache numbers locally if sync fails?
   - What if AutoGMap is down?

5. **Metadata:**
   - Should we send call duration?
   - Should we send call transcripts?
   - Should we send device info?

---

## Files to Create/Modify

**New Files:**
- `app/autogmap.py` (Core integration, ~300 lines)
- `app/models/autogmap.py` (Data structures, ~100 lines)
- `tests/test_autogmap.py` (Tests, ~200 lines)
- `docs/AUTOGMAP_RUNBOOK.md` (Operations guide)

**Modified Files:**
- `app/main.py` (+50 lines for API endpoints)
- `app/recordings.py` (+60 lines for upload logic)
- `app/db.py` (Database migration)
- `Kotlin/MainActivity.kt` (+40 lines for sync)
- `Kotlin/CallRecorder.kt` (+20 lines for filtering)

**Database:**
- New table: `autogmap_numbers`
- New columns: `recordings.autogmap_status`, `.autogmap_sent_at`, `.autogmap_error`

---

## Next Actions

1. **Immediate (This week):**
   - [ ] Confirm API key availability with Mansi
   - [ ] Confirm staging environment access
   - [ ] Get test applicant numbers

2. **Week 1:**
   - [ ] Implement backend numbers sync
   - [ ] Implement recording upload
   - [ ] Create database schema

3. **Week 2:**
   - [ ] Integrate Kotlin app
   - [ ] End-to-end testing
   - [ ] Fix issues found

4. **Week 3:**
   - [ ] Add monitoring + alerting
   - [ ] Load testing
   - [ ] Security review

5. **Week 4:**
   - [ ] Documentation + runbooks
   - [ ] Production deployment
   - [ ] Post-deployment monitoring

---

## Success Indicators (Go/No-Go)

**Go criteria:**
- ✅ Sync succeeds 95%+ of times
- ✅ Upload succeeds 95%+ of times
- ✅ No manual intervention needed
- ✅ Monitoring alerts working
- ✅ Load test passes (1000+ calls/day)
- ✅ Security review approved
- ✅ Runbooks documented

**No-go criteria:**
- ❌ Data loss in any scenario
- ❌ Sync/upload < 90% success
- ❌ Performance impact on calls
- ❌ Security issues found
- ❌ API key leaked

---

## Phase 8 Dependency

This Phase 7 enables:
- Backup/Restore (Phase 8) can now include AutoGMap sync data
- Dashboard can show AutoGMap integration health
- Alerts can integrate with broader monitoring

---

## Questions for Implementation

1. Should we cache numbers in database or memory?
2. Should we auto-record ALL calls if sync fails (failsafe)?
3. Should recordings be uploaded synchronously or queued?
4. How long to retain failed upload records?
5. Should we support pull model as fallback?

---

**Status:** 📋 READY FOR IMPLEMENTATION  
**Waiting On:** Mansi's API key + staging access  
**Next Review:** When key is received

