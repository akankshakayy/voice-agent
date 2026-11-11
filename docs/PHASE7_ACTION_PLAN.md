# Phase 7 Action Plan - Immediate Next Steps

**Status:** 🎯 READY TO EXECUTE  
**Waiting On:** Mansi's API Credentials  
**Timeline:** Start implementation once credentials received

---

## 📋 Checklist Before Implementation Starts

### 1. ✅ Credentials from Mansi (BLOCKING)

**What We Need:**
```
□ AutoGMap API Key (X-API-Key header value)
□ Numbers Endpoint: https://indev.eko.in/autogmap/api/v1/call-recorder/numbers
□ Recordings Endpoint: https://indev.eko.in/autogmap/api/v1/call-recorder/recordings
□ Staging environment access confirmation
□ Rate limits documentation
□ Upload size limits
□ Test applicant phone numbers (at least 5)
```

**Follow-up Email Template (send to Mansi):**

```
Subject: AutoGMap Integration - Need API Credentials & Test Setup

Hi Mansi,

Following up on your previous email about AutoGMap call-recorder integration.

We're ready to start implementing Phase 7 (integration with your system). 
To proceed, we need:

1. **API Key:** X-API-Key for requests (share separately, not in email)
2. **Staging Access:** Confirmation that we can use staging endpoints for testing
3. **Test Data:** 5-10 test applicant phone numbers we can use for testing
4. **Documentation:**
   - Rate limits on both endpoints
   - Upload file size limits
   - Expected response times
   - Retry/timeout behavior expectations

5. **Integration Questions:**
   - Should we cache applicant numbers locally if the sync fails (fail-safe)?
   - Is it OK to retry failed uploads for up to 24 hours?
   - Should we send call duration + device info in recordings upload?

Timeline: We can start implementation immediately once we have the API key
and staging access (this week if possible).

Thanks,
Eko Team
```

---

### 2. ✅ Staging Environment Setup

**Before Code Implementation:**

```bash
# Environment file setup
cd /home/cat/eko-rm-voice-agent

# 1. Add to .env (NEVER commit)
AUTOGMAP_ENABLED=true
AUTOGMAP_NUMBERS_URL=https://indev.eko.in/autogmap/api/v1/call-recorder/numbers
AUTOGMAP_RECORDINGS_URL=https://indev.eko.in/autogmap/api/v1/call-recorder/recordings
# AUTH_KEY: [Request from Mansi - never commit to git]
AUTOGMAP_SYNC_INTERVAL_MINUTES=15
AUTOGMAP_SYNC_TIMEOUT_SECONDS=30

# 2. Verify .env is in .gitignore
grep "\.env" .gitignore

# 3. Create .env.example (no secrets)
cat > .env.example << 'EOF'
AUTOGMAP_ENABLED=true
AUTOGMAP_NUMBERS_URL=https://indev.eko.in/autogmap/api/v1/call-recorder/numbers
AUTOGMAP_RECORDINGS_URL=https://indev.eko.in/autogmap/api/v1/call-recorder/recordings
# AUTOGMAP_AUTH_KEY: [Request from Mansi - store in .env, never commit]
AUTOGMAP_SYNC_INTERVAL_MINUTES=15
AUTOGMAP_SYNC_TIMEOUT_SECONDS=30
AUTOGMAP_UPLOAD_RETRY_MAX=3
AUTOGMAP_UPLOAD_RETRY_BACKOFF=60,300,900
EOF
```

---

### 3. ✅ Test Environment Preparation

**Test Data Setup (once Mansi provides numbers):**

```python
# tests/fixtures/autogmap_test_data.py

TEST_APPLICANT_NUMBERS = [
    {
        "phone": "+919876543210",
        "local": "9876543210",
        "name": "Test Applicant 1",
        "since": "2026-11-01"
    },
    {
        "phone": "+919876543211",
        "local": "9876543211",
        "name": "Test Applicant 2",
        "since": "2026-11-05"
    },
    # ... more test numbers from Mansi
]

TEST_RECORDINGS = [
    {
        "file": b"fake_audio_data",
        "phone": "9876543210",
        "direction": "in",
        "duration": 45,
    },
    # ... more test recordings
]
```

---

### 4. ✅ Database Schema Preparation

**Review & Prepare Migration:**

```sql
-- Migration: add_autogmap_support.sql
-- Status: Ready to execute (waiting on Phase 7 start)

-- Table: Store cached applicant numbers
CREATE TABLE IF NOT EXISTS autogmap_numbers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone VARCHAR(20) NOT NULL UNIQUE,
    local VARCHAR(10) NOT NULL,
    name VARCHAR(255),
    since DATETIME,
    synced_at DATETIME,
    active INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Index for quick lookups
CREATE INDEX IF NOT EXISTS idx_autogmap_local ON autogmap_numbers(local);
CREATE INDEX IF NOT EXISTS idx_autogmap_active ON autogmap_numbers(active);

-- Add to recordings table
ALTER TABLE recordings ADD COLUMN autogmap_status VARCHAR(20);
ALTER TABLE recordings ADD COLUMN autogmap_sent_at DATETIME;
ALTER TABLE recordings ADD COLUMN autogmap_error TEXT;
ALTER TABLE recordings ADD COLUMN autogmap_attempts INTEGER DEFAULT 0;

-- Index for tracking
CREATE INDEX IF NOT EXISTS idx_recordings_autogmap ON recordings(autogmap_status);
```

---

### 5. ✅ Code Structure Preparation

**Files to be created (skeleton ready):**

```
app/
├── autogmap.py                 # Core integration logic (NOT YET - waiting on API key)
│   ├── AutoGMapClient class
│   ├── sync_numbers() async function
│   ├── upload_recording() async function
│   └── RetryManager class
│
├── models/
│   └── autogmap.py             # Data models
│       ├── ApplicantNumber
│       └── RecordingUploadStatus
│
└── tests/
    ├── test_autogmap.py        # Unit tests
    │   ├── test_fetch_numbers()
    │   ├── test_upload_recording()
    │   ├── test_retry_logic()
    │   └── test_error_handling()
    │
    └── fixtures/
        └── autogmap_test_data.py
```

---

### 6. ✅ Documentation Review

**Read & Understand:**

- [x] AUTOGMAP_INTEGRATION.md (completed)
- [x] PHASE7_AUTOGMAP_PLAN.md (completed)
- [ ] Review error codes from Mansi's documentation
- [ ] Understand rate limits
- [ ] Review upload format requirements

---

### 7. ✅ Architecture Review

**Confirm Design Decisions:**

```
Decision 1: Sync Strategy
  ✅ Push model: App uploads directly to AutoGMap
  ✅ Backend caches numbers for app to query
  ✅ Fallback: Cache from last successful sync if current sync fails

Decision 2: Retry Strategy
  ✅ Max 3 retries
  ✅ Backoff: 60s, 300s, 900s
  ✅ Alert admin after 3 failures

Decision 3: Error Handling
  ✅ 422 (not in applicants): Log warning, continue
  ✅ 500 (server error): Retry with backoff
  ✅ Network timeout: Queue for retry

Decision 4: Monitoring
  ✅ Dashboard: Last sync time, numbers count
  ✅ Alerts: Sync failures, upload failures
  ✅ Logs: Every sync + upload attempt
```

---

## 🎯 Immediate Action Items (This Week)

### Priority 1: Get Credentials (DO THIS NOW)
- [ ] Email Mansi using template above
- [ ] Request: API key, staging access, test numbers
- [ ] ETA: 1-2 days

### Priority 2: Environment Setup (DO THIS NOW)
- [ ] Set up .env and .env.example
- [ ] Verify .gitignore has .env
- [ ] Add AUTOGMAP_* variables to config loading code

### Priority 3: Database Migration Ready (DO THIS NOW)
- [ ] Write migration file (ready to execute)
- [ ] Review SQL schema
- [ ] Test migration on dev database

### Priority 4: Test Setup (WAIT FOR MANSI'S NUMBERS)
- [ ] Create test fixtures
- [ ] Create test Excel files
- [ ] Set up test automation

### Priority 5: Code Skeleton (WAIT FOR API KEY)
- [ ] Create app/autogmap.py with empty functions
- [ ] Create test files with empty test functions
- [ ] Create app/models/autogmap.py with data classes

---

## ⚠️ Security Checklist

Before writing any code:

- [ ] .env in .gitignore (verified)
- [ ] Never log API key
- [ ] HTTPS only for all API calls
- [ ] Validate SSL certificates
- [ ] Rate limiting respected
- [ ] Input validation on all fields
- [ ] Error messages don't leak info
- [ ] Credentials rotation plan documented

---

## 📞 Communication Plan

**Week 1 (This Week):**
- [ ] Send follow-up to Mansi (get credentials)
- [ ] Await response with API key + test data

**Week 2:**
- [ ] Confirm staging access works
- [ ] Start Phase 7a (backend numbers sync)
- [ ] Daily standup updates to Mansi team

**Week 3:**
- [ ] Phase 7b (recording upload)
- [ ] Weekly sync with Mansi (testing progress)

**Week 4:**
- [ ] Phases 7c + 7d (app + monitoring)
- [ ] Pre-production testing

---

## 📊 Success Gates (Go/No-Go)

**Before Phase 7a starts:**
- ✅ API key received and verified working
- ✅ Test numbers provided
- ✅ .env setup complete
- ✅ Database schema reviewed
- ✅ Code skeleton created

**Before Phase 7b starts:**
- ✅ Numbers sync 95%+ success
- ✅ Caching working correctly
- ✅ Error handling tested

**Before Phase 7c starts:**
- ✅ Recording upload 95%+ success
- ✅ Retry logic working
- ✅ Error handling tested

**Before production:**
- ✅ Load test passed (1000+ calls/day)
- ✅ Security review approved
- ✅ Monitoring alerts working
- ✅ Runbooks documented

---

## 📅 Timeline with Dependencies

```
NOW (Waiting):
  └─ Email Mansi for credentials
     └─ Setup .env, database migration
        └─ Create test fixtures
           └─ [Credentials Received]
              └─ Phase 7a: Numbers Sync (Week 1)
                 └─ Phase 7b: Recording Upload (Week 1)
                    └─ Phase 7c: Kotlin Integration (Week 2)
                       └─ Phase 7d: Monitoring (Week 2-3)
                          └─ Production Deployment (Week 4)
```

---

## 🔑 Remember

**Critical Security:**
- Never commit API key
- Use .env file only
- No logging of credentials
- Rotate key periodically

**Critical Functionality:**
- 95%+ sync success rate
- 95%+ upload success rate
- Automatic retry + backoff
- Clear error messages

**Critical Monitoring:**
- Real-time dashboard
- Alert on failures
- Log every transaction
- Audit trail for compliance

---

## Next Steps

1. ✅ **Right Now:** Send email to Mansi (use template provided)
2. ✅ **While Waiting:** Review PHASE7_AUTOGMAP_PLAN.md in detail
3. ✅ **While Waiting:** Set up .env and database schema
4. ⏳ **After Credentials:** Begin Phase 7a implementation

**Estimated Time to Start Coding:** 1-2 days (waiting on Mansi)

