# AutoGMap Integration Guide

**From:** Mansi (AutoGMap team)  
**Date:** 2026-11-11  
**Purpose:** Integrate call-recorder with Eko Sahayak uploader system

---

## Overview

AutoGMap provides two endpoints for the call-recorder app:
1. **Numbers endpoint** - Fetch which numbers to record (pull every 15 min)
2. **Recordings endpoint** - Upload recorded calls (push when recording completes)

---

## Endpoint 1: Get Numbers to Record

**Request:**
```
GET https://indev.eko.in/autogmap/api/v1/call-recorder/numbers
Header: X-API-Key: <api_key>
```

**Response:**
```json
{
  "as_of": "2026-11-11T10:30:00Z",
  "count": 25,
  "numbers": [
    {
      "phone": "+919876543210",
      "local": "9876543210",
      "name": "Applicant Name",
      "since": "2026-11-01"
    },
    {
      "phone": "+919876543211",
      "local": "9876543211",
      "name": "Another Applicant",
      "since": "2026-11-05"
    }
  ]
}
```

**Key Points:**
- Fetch **every 15 minutes** (cron job or scheduler)
- Match using `local` field (last 10 digits)
- `phone` field has country code, `local` doesn't
- Use `since` to know when number was added
- `as_of` timestamp for tracking freshness

**Use in Uploader App:**
1. Fetch numbers periodically
2. Store in app memory/cache
3. When recording call: check if number matches any in list
4. If match: record the call
5. If no match: skip recording

---

## Endpoint 2: Upload Recordings

**Request:**
```
POST https://indev.eko.in/autogmap/api/v1/call-recorder/recordings
Header: X-API-Key: <api_key>
Content-Type: multipart/form-data

Fields:
- file (required) - Audio file (.m4a, .wav, .mp3, etc)
- phone (required) - Phone number that made/received call
- recording_id (optional) - Our internal recording ID
- direction (optional) - "in" or "out"
- started_at (optional) - ISO 8601 timestamp when call started
- duration_seconds (optional) - Call duration in seconds
- device (optional) - Device identifier
```

**Response - Success (201):**
```json
{
  "ok": true,
  "recording_id": 12345,
  "status": "received"
}
```

**Response - Not in Applicants (422):**
```json
{
  "detail": "Phone number 9876543210 is not one of our applicants"
}
```

**Response - Invalid Request (400):**
```json
{
  "detail": "Missing required field: file"
}
```

**Key Points:**
- Send immediately after recording completes
- 201 = accepted and kept
- 422 = number not in applicants list (check numbers endpoint)
- Include all available metadata
- Retry on network failure (exponential backoff)

---

## Integration Strategy

### Option A: Push Model (RECOMMENDED)
```
Eko App Records Call
    ↓
Check if number in AutoGMap list
    ↓
Upload to AutoGMap: POST /recordings
    ↓
AutoGMap stores + processes
```

**Pros:** Immediate, no polling  
**Cons:** Requires network each upload

### Option B: Pull Model (Alternative)
```
AutoGMap Polls Every 15 Min
    ↓
GET https://our-server/api/call-recorder/recordings
    ↓
Eko Server returns: [{file, phone, metadata}]
    ↓
AutoGMap downloads + processes
```

**Pros:** Batched, asynchronous  
**Cons:** More complex, polling overhead

**DECISION: Use Option A (Push) for now**
- Simpler integration
- Aligns with existing uploader pattern
- More reliable

---

## Implementation Checklist

### Phase 1: Numbers Sync (Priority 1)
- [ ] Create scheduled job (every 15 min)
- [ ] Call: `GET /autogmap/api/v1/call-recorder/numbers`
- [ ] Parse response, extract numbers
- [ ] Store in local cache (or database table)
- [ ] Match against incoming calls
- [ ] Log sync status (success/failure)

### Phase 2: Upload Recording (Priority 1)
- [ ] When recording completes in app
- [ ] Prepare multipart form data
- [ ] Upload to: `POST /autogmap/api/v1/call-recorder/recordings`
- [ ] Handle responses (201, 422, 500)
- [ ] Log result (success/failure/retry)
- [ ] Retry on network error (exponential backoff, max 3x)

### Phase 3: Error Handling (Priority 2)
- [ ] Handle 422 (number not in applicants)
  - Log warning
  - Continue (don't block app)
- [ ] Handle 500 (server error)
  - Retry with backoff
  - Alert admin if repeated
- [ ] Handle network timeout
  - Queue for retry
  - Don't block user

### Phase 4: Monitoring (Priority 3)
- [ ] Track numbers sync success rate
- [ ] Track recording upload success rate
- [ ] Alert on repeated failures
- [ ] Dashboard: last sync time, numbers count, upload status

---

## Configuration

### Environment Variables

```bash
# AutoGMap Integration (see .env.example for template)
AUTOGMAP_NUMBERS_URL=https://indev.eko.in/autogmap/api/v1/call-recorder/numbers
AUTOGMAP_RECORDINGS_URL=https://indev.eko.in/autogmap/api/v1/call-recorder/recordings
# AUTOGMAP_AUTH_KEY: [REQUEST FROM MANSI - store in .env only, never commit]

# Sync Settings
AUTOGMAP_SYNC_INTERVAL_MIN=15  # Fetch numbers every 15 minutes
AUTOGMAP_UPLOAD_RETRY_MAX=3    # Retry failed uploads up to 3 times
AUTOGMAP_UPLOAD_RETRY_BACKOFF=60  # Backoff in seconds (60, 300, 900)
```

### .env.example Template
See .env.example file in project root. This file contains the configuration structure without secrets—copy it to .env and fill in values from Mansi.

### .gitignore (ensure secrets not committed)
```
.env
.env.local
*.key
```

---

## Code Examples

### Fetch Numbers (Python)
```python
import requests
import os

def fetch_autogmap_numbers():
    """Fetch list of numbers to record from AutoGMap."""
    url = os.getenv('AUTOGMAP_NUMBERS_URL')
    key = os.getenv('AUTOGMAP_API_KEY')
    
    headers = {'X-API-Key': key}
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            numbers = {n['local'] for n in data['numbers']}
            return numbers
        else:
            log.error(f"Failed to fetch numbers: {resp.status_code}")
            return set()
    except Exception as e:
        log.error(f"Numbers sync error: {e}")
        return set()
```

### Upload Recording (Python)
```python
import requests
import os

def upload_to_autogmap(file_path, phone, direction='in', duration=0):
    """Upload recording to AutoGMap."""
    url = os.getenv('AUTOGMAP_RECORDINGS_URL')
    key = os.getenv('AUTOGMAP_API_KEY')
    
    headers = {'X-API-Key': key}
    
    with open(file_path, 'rb') as f:
        files = {
            'file': f,
            'phone': (None, phone),
            'direction': (None, direction),
            'duration_seconds': (None, str(duration))
        }
        
        try:
            resp = requests.post(url, headers=headers, files=files, timeout=30)
            
            if resp.status_code == 201:
                log.info(f"Recording uploaded: {phone}")
                return True
            elif resp.status_code == 422:
                log.warning(f"Phone not in applicants: {phone}")
                return False
            else:
                log.error(f"Upload failed: {resp.status_code} - {resp.text}")
                return False
                
        except Exception as e:
            log.error(f"Upload error: {e}")
            return False
```

---

## Testing

### Manual Test: Fetch Numbers
```bash
curl -H "X-API-Key: <actual-key>" \
  https://indev.eko.in/autogmap/api/v1/call-recorder/numbers
```

### Manual Test: Upload Recording
```bash
curl -X POST \
  -H "X-API-Key: <actual-key>" \
  -F "file=@/path/to/recording.m4a" \
  -F "phone=9876543210" \
  -F "direction=in" \
  -F "duration_seconds=45" \
  https://indev.eko.in/autogmap/api/v1/call-recorder/recordings
```

---

## Security Notes

⚠️ **CRITICAL:**
- Never commit API key to git
- Use .env file (add to .gitignore)
- Don't log API key
- Don't share key in emails/chat
- Rotate key periodically
- Use HTTPS only
- Validate SSL certificates

---

## Timeline

- **Week 1:** Implement numbers sync + basic upload
- **Week 2:** Error handling + retry logic
- **Week 3:** Monitoring + alerting
- **Week 4:** Testing + production rollout

---

## Questions for Mansi

1. What's the API key? (share separately, not in email)
2. Should we implement Option B (pull model) as fallback?
3. What's the upload size limit?
4. Should we compress audio before uploading?
5. Rate limits on the endpoints?

---

**Status:** ⏳ PENDING IMPLEMENTATION  
**Priority:** HIGH (blocks AutoGMap integration)  
**Owner:** Eko Sahayak Backend Team
