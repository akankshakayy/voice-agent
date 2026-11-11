# Prachi Recording Webhook API

**Purpose:** Data Collector (DC) Recording Webhook API  
**Use Case:** Send DC verification call recordings to Prachi CRM for workflow processing  
**Model:** Real-time push (Server sends data immediately after recording is ready)  
**Authentication:** X-Recording-Secret header (shared secret key)

> **Note:** This is the Recording Webhook API. For DC/Official data sync via Google Sheets, see [prachi-sync-api-primary.md](prachi-sync-api-primary.md).

---

## Overview

Prachi receives DC call recordings via webhook. When a DC uploads a verification call recording:

1. **Server receives** the uploaded recording file
2. **Server processes** the recording (validation, metadata extraction)
3. **Server pushes** recording data to Prachi's webhook in real-time
4. **Prachi receives** recording data and processes in CRM workflows

**Workflow:**
```
DC uploads recording → Server validates → Server calls Prachi webhook → Prachi receives & processes
```

**Why Prachi?** DCs handle outbound verification calls. Recording metadata (caller, recipient, duration, direction) enables Prachi to:
- Track verification attempts in CRM
- Correlate with customer interactions
- Monitor DC performance metrics
- Automate workflow triggers based on call outcomes

---

## Quick Start

### What Prachi Receives (Example)
When a DC named "Arun" uploads a verification call recording:

```json
{
  "id": "rec_abc123xyz789",
  "dc_number": "9876543210",
  "other_number": "8765432109",
  "direction": "outbound",
  "started_at": "2026-11-11T10:30:00Z",
  "duration": 95,
  "audio_url": "https://indev.eko.in/api/recordings/download/rec_abc123xyz789"
}
```

**Note:** Prachi receives **recording metadata only**, not transcript. Audio file is available via URL for Prachi to retrieve if needed.

---

## Use Cases

### Use Case 1: Real-Time Verification Tracking
**Scenario:** DC makes outbound verification call, uploads recording

```
1. DC uploads recording via uploader app
2. Server validates metadata (DC number, recipient, duration)
3. Server pushes to Prachi webhook in real-time
4. Prachi receives in CRM and links to customer account
5. Prachi uses metadata to track verification attempt
6. Prachi can download audio if detailed review needed
```

**Prachi receives:** Recording metadata (id, dc_number, other_number, direction, timestamp, duration, audio URL)

---

### Use Case 2: Performance Tracking
**Scenario:** Prachi wants to analyze DC verification patterns

```
Prachi queries her CRM for all recordings received via webhook
Filters by: dc_number, date range, call direction (outbound)
Analyzes: Verification success rate, average call duration, attempt patterns
Reports: DC performance metrics
```

**Data available:** Timestamp, duration, caller/recipient numbers, call direction

---

## API Reference

### Endpoint (Webhook)
```
POST https://indev.eko.in/sbi-relationship-crm/api/v1/webhooks/recordings
```

**Note:** This is **real-time push**. The server sends data immediately when recording is ready. Prachi receives via webhook.

### Authentication
```
Header: X-Recording-Secret: <shared-secret-key>
```
(Set in .env as PRACHI_RECORDING_SECRET)

### Request Body

```json
{
  "id": "rec_abc123xyz789",
  "dc_number": "9876543210",
  "other_number": "8765432109",
  "direction": "outbound",
  "started_at": "2026-11-11T10:30:00Z",
  "duration": 95,
  "audio_url": "https://indev.eko.in/api/recordings/download/rec_abc123xyz789"
}
```

### Field Descriptions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique recording ID (e.g., "rec_abc123xyz789") |
| `dc_number` | string | Yes | Data Collector's phone number |
| `other_number` | string | Yes | Call recipient's phone number |
| `direction` | string | Yes | "outbound" (DC calling) or "inbound" (customer calling DC) |
| `started_at` | ISO 8601 | Yes | When call started (UTC timestamp) |
| `duration` | integer | Yes | Call duration in seconds |
| `audio_url` | string | Yes | HTTPS URL to download audio file |


## Response Format

### Success (202 Accepted)
```json
{
  "ok": true,
  "id": "rec_abc123xyz789",
  "status": "received",
  "message": "Recording received and queued for processing"
}
```

### Error (400) - Invalid Data
```json
{
  "detail": "Field 'dc_id' is required"
}
```

### Error (401) - Authentication Failed
```json
{
  "detail": "Invalid or missing API key"
}
```

### Error (409) - Duplicate
```json
{
  "detail": "Recording 360 already received. Ignoring duplicate."
}
```

### Error (422) - Processing Error
```json
{
  "detail": "Failed to process recording: transcript too short (< 10 words)"
}
```

---

## CURL Examples

### Basic: Send a DC Recording

```bash
# Setup (PRACHI_RECORDING_SECRET in .env.local, not in git)
PRACHI_ENDPOINT="https://indev.eko.in/sbi-relationship-crm/api/v1/webhooks/recordings"

# Send single recording
curl -X POST \
  -H "X-Recording-Secret: $PRACHI_RECORDING_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "rec_abc123xyz789",
    "dc_number": "9876543210",
    "other_number": "8765432109",
    "direction": "outbound",
    "started_at": "2026-11-11T10:30:00Z",
    "duration": 95,
    "audio_url": "https://indev.eko.in/api/recordings/download/rec_abc123xyz789"
  }' \
  "$PRACHI_ENDPOINT"
```

### Batch: Send Multiple DC Recordings (Max 50 per request)

```bash
curl -X POST \
  -H "X-Recording-Secret: $PRACHI_RECORDING_SECRET" \
  -H "Content-Type: application/json" \
  -d '[
    {
      "id": "rec_abc123xyz789",
      "dc_number": "9876543210",
      "other_number": "8765432109",
      "direction": "outbound",
      "started_at": "2026-11-11T10:30:00Z",
      "duration": 95,
      "audio_url": "https://indev.eko.in/api/recordings/download/rec_abc123xyz789"
    },
    {
      "id": "rec_def456uvw012",
      "dc_number": "9876543210",
      "other_number": "9999888877",
      "direction": "inbound",
      "started_at": "2026-11-11T11:15:00Z",
      "duration": 120,
      "audio_url": "https://indev.eko.in/api/recordings/download/rec_def456uvw012"
    }
  ]' \
  "$PRACHI_ENDPOINT"
```

---

## Common Workflows

### Workflow 1: Real-Time DC Upload
```
DC records verification call → Server receives upload → Server validates → 
Server pushes to Prachi webhook (within seconds) → Prachi processes in CRM
```

**What happens:**
- DC (e.g., Arun) completes verification call and uploads
- Server validates recording metadata within seconds
- Server makes real-time POST to Prachi webhook
- Prachi receives notification and processes automatically
- Recording becomes available in Prachi's CRM workflow

---

### Workflow 2: Batch Processing (End of Day)
```bash
# Server can batch up to 50 DC recordings per request for efficiency
# Typical use: accumulate DC recordings throughout day, send batch at EOF
```

**Batch request:**
```bash
POST /webhooks/recordings (with array of up to 50 recording objects)
```

---

### Workflow 3: Error Handling & Retry
```bash
# Server sends recording → Prachi API returns 500 error
# Server automatically retries:
# - Attempt 1: Immediate retry
# - Attempt 2: After 5 minutes
# - Attempt 3: After 1 hour
# - Attempt 4+: Exponential backoff up to 24 hours
```

---

## Data Validation Rules

Prachi's API validates:

| Field | Rule | Example |
|-------|------|---------|
| `id` | Non-empty string, unique | ✅ "rec_abc123xyz789" |
| `dc_number` | Valid 10-digit phone | ✅ "9876543210" |
| `other_number` | Valid 10-digit phone | ✅ "8765432109" |
| `direction` | "outbound" or "inbound" | ✅ "outbound" |
| `started_at` | ISO 8601 UTC timestamp | ✅ "2026-11-11T10:30:00Z" |
| `duration` | Non-negative integer (seconds) | ✅ 95 |
| `audio_url` | Valid HTTPS URL | ✅ "https://indev.eko.in/api/recordings/download/rec_abc123xyz789" |

**Additional constraints:**
- Only DC recordings with consent are sent (verified via consent flag in database)
- Batch requests: max 50 recordings per request

---

## Rate Limits & Constraints

| Metric | Limit | Notes |
|--------|-------|-------|
| Recordings per request | 50 (batch) | Max 50 per webhook call |
| Requests/minute | 100 | Per minute limit |
| Max payload size | 10 MB | JSON payload only (audio via URL) |
| Response timeout | 30 seconds | Server waits max 30s for 202 Accepted |
| Retry window | 24 hours | Server retries for up to 24 hours |

---

## Retry Logic

**Server behavior when pushing to Prachi webhook:**

```
Attempt 1: Immediate send
  ↓
  Prachi responds with 202 Accepted?
  ├─ YES → Success! Recording queued
  └─ NO (5xx, timeout, connection error) → Wait 5 minutes → Attempt 2

Attempt 2: After 5 minutes (Retry 1)
  ├─ Prachi responds with 202? → Success!
  └─ Error? → Wait 1 hour → Attempt 3

Attempt 3: After 1 hour (Retry 2)
  ├─ Prachi responds with 202? → Success!
  └─ Error? → Wait 24 hours → Attempt 4

Attempt 4: After 24 hours (Final retry)
  ├─ Prachi responds with 202? → Success!
  └─ Error? → Mark as failed, recording not sent
```

**Note:** Server tracks attempt count internally. Prachi webhook endpoint is idempotent (duplicate sends are safe).

---

## Error Scenarios & Solutions

### Problem: Invalid X-Recording-Secret header
```bash
curl -X POST ... \
  -H "X-Recording-Secret: invalid_secret" \
  ...
```

**Response:** `401 Unauthorized`
```json
{
  "detail": "Invalid or missing X-Recording-Secret header"
}
```

**Solution:**
1. Verify secret in .env: `echo $PRACHI_RECORDING_SECRET`
2. Ensure header name is exactly `X-Recording-Secret`
3. Contact Prachi team to get the correct shared secret
4. Server will auto-retry after 5 minutes

---

### Problem: Missing required field (dc_number)
```bash
curl -X POST ... \
  -d '{
    "id": "rec_abc123xyz789",
    "other_number": "8765432109",
    # Missing dc_number!
    ...
  }' \
  ...
```

**Response:** `400 Bad Request`
```json
{
  "detail": "Missing required field: dc_number"
}
```

**Solution:**
1. Ensure all required fields are present: id, dc_number, other_number, direction, started_at, duration, audio_url
2. Validate phone numbers (10 digits)
3. Server marks this as failed and does NOT retry (400 errors are not retryable)

---

### Problem: Webhook timeout
```bash
# Server waits 30 seconds for Prachi to respond with 202
# If no response within 30 seconds → timeout
```

**Server behavior:**
- Timeout is treated as a temporary failure
- Server will retry after 5 minutes
- Common causes: High Prachi server load, network latency

**Solution:**
- Check Prachi webhook status page
- Server auto-retries; no manual action needed
- If repeated timeouts, contact Prachi team

---

## Support & Troubleshooting

### Debug Logs
To see what server is sending to Prachi:

```bash
# On server:
tail -f /home/cat/eko-rm-voice-agent/data/logs/eko.log | grep "PRACHI"
```

**Example log:**
```
2026-11-11 10:30:00 | INFO | eko.recordings | Sending recording 360 to Prachi API (attempt 1)
2026-11-11 10:30:01 | INFO | eko.recordings | Prachi API response: 200 OK (req_abc123xyz)
```

### Check Recording Status in Database
```bash
sqlite3 /path/to/eko_agent.db << 'EOF'
SELECT id, dc_id, transcript, prachi_api_sent_at, prachi_request_id 
FROM recordings 
WHERE mode='dc' 
ORDER BY uploaded_at DESC 
LIMIT 5;
EOF
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.0 | Nov 11, 2026 | **Official Prachi webhook requirements** - Endpoint: https://indev.eko.in/sbi-relationship-crm/api/v1/webhooks/recordings; Auth: X-Recording-Secret header; Payload: id, dc_number, other_number, direction, started_at, duration, audio_url; Response: 202 Accepted; Real-time push (not batch daily); DC-only with consent; Max 50 per request |
| 1.0 | Nov 1, 2026 | Initial release - Push-based API for DC recordings |

---

## Server-to-Prachi Flow

```
┌─────────────────────────────────────────────────────────────┐
│ Data Collector Verification Workflow                        │
└─────────────────────────────────────────────────────────────┘

1. DC uses uploader app to make verification call
   └─> Recording file uploaded to server

2. Server receives recording
   ├─> Validates metadata (dc_number, other_number, duration)
   ├─> Checks consent flag (only send DC recordings with consent)
   └─> Marked as ready_to_send

3. Server pushes to Prachi webhook (real-time)
   ├─> Endpoint: https://indev.eko.in/sbi-relationship-crm/api/v1/webhooks/recordings
   ├─> Auth: X-Recording-Secret header
   ├─> Payload: id, dc_number, other_number, direction, started_at, duration, audio_url
   ├─> Response: 202 Accepted (queued, not processed yet)
   └─> Retry logic: Auto-retry on failures (up to 24 hours)

4. Prachi receives recording data via webhook
   ├─> Recording queued in CRM system
   ├─> Links to customer account
   └─> Triggers verification workflow

5. Prachi processes in CRM
   ├─> Correlates with customer interaction history
   ├─> Marks verification status
   └─> Updates customer record

6. Prachi can retrieve audio if needed
   └─> Uses audio_url to download call recording
```

---

## Key Differences: DC Mode (Prachi) vs Employee Mode (Mansi)

| Aspect | DC Mode (Prachi) | Employee Mode (Mansi) |
|--------|------------------|----------------------|
| **Purpose** | Verification workflows in CRM | Internal audit & review |
| **Data Sent** | Metadata only (no transcript) | Metadata + transcript |
| **Initiation** | Real-time push webhook | On-demand pull (Mansi queries) |
| **Timing** | Immediate (within seconds) | On-demand, daily batches |
| **Endpoint** | https://indev.eko.in/sbi-relationship-crm/api/v1/webhooks/recordings | /api/recordings (internal) |
| **Auth** | X-Recording-Secret header | API key |
| **Response** | 202 Accepted (async) | 200 OK + data |
| **Retry Policy** | Up to 24 hours (exponential backoff) | Not applicable (pull-based) |

---

## Testing & Rollout

### Pre-Production Testing

**Phase 1: Sample Recordings**
1. Create 2-3 test DC recordings via uploader app
2. Ensure recordings have:
   - Valid DC phone number
   - Valid recipient phone number
   - Clear direction (outbound/inbound)
   - Metadata completeness
3. Verify server pushes to Prachi webhook (check logs):
   ```bash
   tail -f /home/cat/eko-rm-voice-agent/data/logs/eko.log | grep "PRACHI"
   ```
4. Confirm server receives 202 Accepted response

**Phase 2: Prachi Verification**
1. Prachi team confirms recordings appear in CRM
2. Verify webhook delivery and CRM integration
3. Check recording details are correct (DC number, other number, duration, timestamp)
4. Confirm audio URL is accessible

**Phase 3: Full Rollout**
1. Once Prachi confirms test recordings working
2. Enable full DC recording sync to Prachi
3. Monitor first day's recordings
4. Validate workflow in CRM

### Monitoring

**Key Metrics:**
- Webhook delivery success rate (should be > 99%)
- Average response time (should be < 5 seconds)
- Failed recordings requiring retry
- Recording latency (upload to webhook push)

**Logs to monitor:**
```bash
grep "PRACHI_WEBHOOK" /home/cat/eko-rm-voice-agent/data/logs/eko.log
```

### Rollback Plan

If issues detected:
1. Set `PRACHI_WEBHOOK_ENABLED=false` in .env
2. Recordings continue uploading but won't send to Prachi
3. After fix, re-enable and retry failed recordings

---

## Contact

**Technical Support:** dev-team@eko.co.in  
**API Issues:** api-support@eko.co.in  
**Questions about use:** prachi@eko.co.in (your team)
