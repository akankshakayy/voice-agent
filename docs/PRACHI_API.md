# Prachi API Documentation

**Purpose:** Data Collector (DC) Recording Processing API  
**Use Case:** Transcribe and submit DC call recordings for workflow processing  
**Model:** Push-based (Server sends data when recording is ready)  
**Authentication:** API Key (PRACHI_API_KEY)

---

## Overview

Prachi receives call recordings from Data Collectors (DCs). When a DC uploads a call recording:

1. **Server receives** the uploaded file
2. **Server transcribes** the audio (Speech-to-Text)
3. **Server sends** recording metadata + transcript to Prachi's API
4. **Prachi processes** the data in her workflows

**Workflow:**
```
DC uploads recording → Server transcribes → Server calls Prachi API → Prachi receives data
```

**Why Prachi?** DCs handle outbound verification calls. The transcripts and metadata help Prachi process, verify, and track verification results.

---

## Quick Start

### What Prachi Receives (Example)
When a DC named "Arun" uploads a call recording:

```json
{
  "recording_id": 360,
  "dc_id": 1,
  "dc_name": "Arun Kumar",
  "dc_phone": "9876543210",
  "caller_number": "9876543210",
  "recipient_number": "8765432109",
  "call_direction": "outbound",
  "duration_sec": 95,
  "uploaded_at": "2026-11-11T10:30:00Z",
  "transcript": "Arun: Hello, I'm calling about your recent order. Customer: Yes, I received it today. Arun: Great! Is everything working...",
  "transcript_json": [
    {
      "speaker": "arun",
      "text": "Hello, I'm calling about your recent order.",
      "duration": 3.2
    },
    {
      "speaker": "customer",
      "text": "Yes, I received it today.",
      "duration": 2.1
    }
  ],
  "file_path": "dc1/2026-11-11/rec_001.m4a",
  "status": "done"
}
```

This is **exactly what Prachi receives** via the Prachi API.

---

## Use Cases

### Use Case 1: Verification Workflow
**Scenario:** DC makes outbound verification call, uploads recording

```
1. DC uploads → Recording marked 'new'
2. Server transcribes → Transcript created
3. Server calls Prachi API → Sends transcript + metadata
4. Prachi reviews → Marks as verified/unverified
5. Prachi uses transcript → To validate customer responses
```

**Prachi receives:** Full recording metadata + searchable transcript

---

### Use Case 2: Quality Assurance
**Scenario:** Prachi spots unusual call pattern in transcript

```
Example: Recipient repeating NTB (non-technical background) answers
Prachi uses: speaker_json to identify "customer" responses
Prachi acts: Marks for manager review, flag potential language issue
```

---

### Use Case 3: Performance Tracking
**Scenario:** Weekly report on DC call quality

```
Prachi queries: Transcript to count call duration, topic mentions
Prachi analyzes: Average call time, common objections, resolution rate
Prachi reports: Performance metrics per DC (Arun, Babita, etc.)
```

---

## API Reference

### Endpoint (Push)
```
POST /api/prachi/recordings
```

**Note:** This is **push-based**. The server sends data when recording is done. Prachi does **not** query the server.

### Authentication
```
Header: Authorization: Bearer PRACHI_API_KEY
```

### Request Body

```json
{
  "recording_id": 360,
  "dc_id": 1,
  "dc_name": "string",
  "dc_phone": "string",
  "caller_number": "string",
  "recipient_number": "string",
  "call_direction": "outbound|inbound",
  "duration_sec": 95,
  "uploaded_at": "2026-11-11T10:30:00Z",
  "transcript": "Full text transcript as single string",
  "transcript_json": [
    {
      "speaker": "arun|customer",
      "text": "What was said",
      "duration": 3.2
    }
  ],
  "file_path": "dc1/2026-11-11/rec_001.m4a",
  "status": "done",
  "attempts": 1
}
```

### Field Descriptions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `recording_id` | integer | Yes | Unique recording ID in Eko system |
| `dc_id` | integer | Yes | Data Collector ID |
| `dc_name` | string | Yes | DC's full name (e.g., "Arun Kumar") |
| `dc_phone` | string | Yes | DC's phone number |
| `caller_number` | string | Yes | Who initiated the call |
| `recipient_number` | string | Yes | Who received the call |
| `call_direction` | string | Yes | "outbound" (DC calling) or "inbound" (customer calling DC) |
| `duration_sec` | integer | Yes | Call duration in seconds |
| `uploaded_at` | ISO 8601 | Yes | When recording was uploaded (UTC) |
| `transcript` | string | Yes | Full text transcript (plain text, searchable) |
| `transcript_json` | array | Yes | Structured transcript with speaker labels |
| `file_path` | string | Yes | Where audio file is stored (for audit/review) |
| `status` | string | Yes | "done" (ready for processing) |
| `attempts` | integer | Yes | Upload attempt count (usually 1) |

### transcript_json Structure

Each entry in the `transcript_json` array:

```json
{
  "speaker": "arun",                    // who is speaking (lowercase)
  "text": "What was said",              // the actual words
  "duration": 3.2,                      // duration of this segment (seconds)
  "confidence": 0.95                    // optional: STT confidence (0.0-1.0)
}
```

**Speaker values:**
- `"arun"` (or DC name) - Data Collector speaking
- `"customer"` - Call recipient speaking
- `"system"` - System messages (e.g., "Call ended")

---

## Response Format

### Success (200)
```json
{
  "ok": true,
  "recording_id": 360,
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
# Setup
PRACHI_ENDPOINT="https://api.eko.co.in"

# Send recording
curl -X POST \
  -H "Authorization: Bearer <your-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "recording_id": 360,
    "dc_id": 1,
    "dc_name": "Arun Kumar",
    "dc_phone": "9876543210",
    "caller_number": "9876543210",
    "recipient_number": "8765432109",
    "call_direction": "outbound",
    "duration_sec": 95,
    "uploaded_at": "2026-11-11T10:30:00Z",
    "transcript": "Arun: Hello. Customer: Hi.",
    "transcript_json": [
      {"speaker": "arun", "text": "Hello.", "duration": 1.0},
      {"speaker": "customer", "text": "Hi.", "duration": 0.8}
    ],
    "file_path": "dc1/2026-11-11/rec_001.m4a",
    "status": "done",
    "attempts": 1
  }' \
  "$PRACHI_ENDPOINT/api/prachi/recordings"
```

### With All Optional Fields

```bash
curl -X POST \
  -H "Authorization: Bearer <your-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "recording_id": 360,
    "dc_id": 1,
    "dc_name": "Arun Kumar",
    "dc_phone": "9876543210",
    "caller_number": "9876543210",
    "recipient_number": "8765432109",
    "call_direction": "outbound",
    "duration_sec": 95,
    "uploaded_at": "2026-11-11T10:30:00Z",
    "transcript": "Full transcript here...",
    "transcript_json": [
      {
        "speaker": "arun",
        "text": "Hello, is this regarding your order?",
        "duration": 2.5,
        "confidence": 0.98
      },
      {
        "speaker": "customer",
        "text": "Yes, I have a question.",
        "duration": 1.8,
        "confidence": 0.95
      }
    ],
    "file_path": "dc1/2026-11-11/rec_001.m4a",
    "status": "done",
    "attempts": 1
  }' \
  "$API_BASE/api/prachi/recordings"
```

---

## Common Workflows

### Workflow 1: Daily DC Uploads
```bash
# Every recording from DC "Arun" is sent automatically
# Server processes: upload → transcribe → POST /api/prachi/recordings
# Prachi receives: All of Arun's daily recordings
```

**What happens:**
- Arun uploads 5 calls in the morning
- Server transcribes all 5
- Server makes 5 POST requests (one per recording)
- Prachi receives 5 notifications
- Prachi processes each transcript

---

### Workflow 2: Quality Review
```bash
# Prachi wants to review a specific DC's calls from yesterday
# Instead of pulling from server, Prachi can:
# 1. Check her own records (already received via API)
# 2. Or query the Prachi pull API (if available)
# 3. Filter by dc_id and date range
```

**Pull-based alternative:** If Prachi wants to query instead:
```bash
GET /api/prachi/recordings?dc_id=1&date_from=2026-11-10&date_to=2026-11-10
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
| `recording_id` | Must be positive integer | ✅ 360 |
| `dc_id` | Must exist in DCs table | ✅ dc_id=1 |
| `dc_name` | Non-empty string | ✅ "Arun Kumar" |
| `dc_phone` | Valid phone format | ✅ "9876543210" |
| `caller_number` | Valid phone or system | ✅ "9876543210" |
| `recipient_number` | Valid phone | ✅ "8765432109" |
| `call_direction` | "outbound" or "inbound" | ✅ "outbound" |
| `duration_sec` | Non-negative integer | ✅ 95 |
| `transcript` | Non-empty string, min 10 words | ✅ "Arun: Hello..." |
| `transcript_json` | Non-empty array | ✅ [{...}, {...}] |
| `status` | "done" only | ✅ "done" |

---

## Rate Limits

| Metric | Limit | Reset |
|--------|-------|-------|
| Requests/minute | 60 | Per minute |
| Requests/hour | 3000 | Per hour |
| Requests/day | 50000 | Per day |
| Max payload size | 10 MB | Per request |

---

## Retry Logic

**Server behavior when calling Prachi API:**

```
Attempt 1: Immediate send
  ↓
  Error (5xx, timeout, connection error)?
  ├─ YES → Wait 5 minutes → Attempt 2
  └─ NO → Success! Record attempt #1

Attempt 2: After 5 minutes
  ├─ Error? → Wait 1 hour → Attempt 3
  └─ Success! Record attempt #2

Attempt 3: After 1 hour
  ├─ Error? → Wait 2 hours → Attempt 4
  └─ Success! Record attempt #3

Attempt 4+: Exponential backoff, max 24 hours
  ├─ Error after 24 hours? → Mark as failed
  └─ Success! Record final attempt
```

**Prachi receives:**
```json
{
  "attempts": 3,        // if this is the 3rd attempt
  "prachi_api_sent_at": 1234567890,
  "prachi_request_id": "req_abc123xyz"
}
```

---

## Error Scenarios & Solutions

### Problem: API key is invalid
```bash
curl -X POST ... \
  -H "Authorization: Bearer invalid_key" \
  ...
```

**Response:**
```json
{
  "detail": "Invalid or missing API key"
}
```

**Solution:**
1. Verify API key in .env: `echo $PRACHI_API_KEY`
2. Check key hasn't expired (contact admin)
3. Ensure header format: `Authorization: Bearer <key>`

---

### Problem: Transcript is too short
```bash
curl -X POST ... \
  -d '{
    "transcript": "Hi.",  # Only 1 word!
    ...
  }' \
  ...
```

**Response:**
```json
{
  "detail": "Failed to process recording: transcript too short (< 10 words)"
}
```

**Solution:**
1. Ensure STT generated enough words
2. Check if audio file was corrupted
3. Retry upload with better audio quality

---

### Problem: Recording already received
```bash
# Same recording_id sent twice
```

**Response:**
```json
{
  "detail": "Recording 360 already received. Ignoring duplicate."
}
```

**Solution:**
- This is expected for retries (safe to ignore)
- Server tracks `prachi_request_id` to avoid duplicates
- No action needed

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
| 1.0 | Nov 11, 2026 | Initial release - Push-based API for DC recordings |

---

## Server-to-Prachi Flow

```
┌─────────────────────────────────────────────────────────────┐
│ Data Collector Workflow                                     │
└─────────────────────────────────────────────────────────────┘

1. DC uses uploader app to record call
   └─> Recording file uploaded to server

2. Server receives recording
   └─> Marked as status='new'

3. Server processes recording (Phase 4, DC mode)
   ├─> Runs Speech-to-Text (STT) on audio
   ├─> Generates transcript + transcript_json
   └─> Marked as status='done'

4. Server calls Prachi API (POST /api/prachi/recordings)
   ├─> Includes: recording_id, dc_info, transcript, metadata
   ├─> Retry logic: Auto-retry on failures
   └─> Tracks: prachi_request_id, prachi_api_sent_at

5. Prachi receives recording data
   ├─> Processes transcript in her workflow
   ├─> Validates responses
   └─> Marks as verified/unverified

6. Prachi acts on data
   └─> Quality review, reporting, follow-ups
```

---

## Key Differences from Employee Mode (Mansi)

| Aspect | DC Mode (Prachi) | Employee Mode (Mansi) |
|--------|------------------|----------------------|
| **Initiation** | Push (server sends) | Pull (Mansi queries) |
| **Transcription** | YES (STT enabled) | NO (skipped) |
| **Workflow** | Verification/QA | Audit/Review |
| **Data Flow** | Upload → Transcribe → Push to Prachi | Upload → Skip STT → Mansi queries |
| **API Type** | POST (server sends) | GET (Mansi retrieves) |
| **Timing** | Async, retries for 24hrs | On-demand |

---

## Contact

**Technical Support:** dev-team@eko.co.in  
**API Issues:** api-support@eko.co.in  
**Questions about use:** prachi@eko.co.in (your team)
