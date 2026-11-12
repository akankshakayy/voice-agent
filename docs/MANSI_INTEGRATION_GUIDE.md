# Mansi Integration Guide - Employee Mode

**Date:** November 12, 2026  
**Status:** Ready for Integration  
**System:** Eko Sahayak Uploader - Employee Mode

---

## Overview

**Employee Mode recordings use both PUSH + PULL models:**

1. **PUSH Model** (Automatic)
   - Employee recordings auto-sent to Mansi's endpoint when processed
   - Requires: MANSI_API_URL, MANSI_API_KEY

2. **PULL Model** (On-Demand)
   - Mansi can query our server when she needs recordings
   - Endpoint: `GET https://indev.eko.in/rm-voice-agent/api/mansi/recordings`
   - No authentication required

---

## Model 1: PUSH (Automatic Send)

### How It Works
1. Employee (Kavya) makes/receives calls
2. Uploader records all calls automatically
3. When recording processing completes, we send to Mansi's endpoint
4. Mansi receives via POST webhook in real-time

### Endpoint (Mansi's Side)
```
POST {MANSI_API_URL}/api/recordings
```

### Requirements
- API URL: `MANSI_API_URL` (set in .env.local)
- API Key: `MANSI_API_KEY` (set in .env.local)
- Auth: Bearer token in Authorization header

### Payload Sent
```json
{
  "recording_id": 123,
  "employee_id": 1,
  "timestamp": "2026-11-12T10:30:00Z",
  "other_number": "+91-98765-43210",
  "duration_sec": 120,
  "file_path": "/path/to/audio.wav"
}
```

---

## Model 2: PULL (On-Demand Query)

### How It Works
Mansi queries our server when she needs recordings from specific numbers or date ranges.

### Endpoint (Your Access)
```
GET https://indev.eko.in/rm-voice-agent/api/mansi/recordings
```

### Query Parameters

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `other_number` | string | Filter by CSP phone number | `+91-98765-43210` |
| `employee_id` | integer | Filter by specific employee | `1` |
| `date_from` | string | Start date (ISO 8601) | `2026-11-01` |
| `date_to` | string | End date (ISO 8601) | `2026-11-30` |
| `days` | integer | Last N days (default 7) | `30` |
| `status` | string | Filter status | `new`, `done`, `failed` |
| `skip` | integer | Pagination offset | `0` |
| `limit` | integer | Max records (default 100, max 500) | `100` |

### Example Request
```bash
curl -X GET "https://indev.eko.in/rm-voice-agent/api/mansi/recordings?other_number=%2B91-98765-43210&date_from=2026-11-01&date_to=2026-11-30&limit=50"
```

### Response Format
```json
{
  "recordings": [
    {
      "id": 123,
      "phone": "+91 98765 43210",
      "employee_id": 1,
      "employee_name": "Rajesh Kumar",
      "direction": "inbound",
      "duration_sec": 120,
      "uploaded_at": "2026-11-12T10:30:00Z",
      "status": "done",
      "transcript": [...],
      "audio_url": "/api/recordings/123/audio"
    },
    ...
  ],
  "total": 15,
  "page": 1,
  "next_page": 2
}
```

---

## Authentication

No authentication needed for PULL endpoint - it's available to Mansi directly.

---

## Support

- Questions? Contact: akanksha.kashyap.intern@eko.co.in
- Docs: This guide + API reference in docs/MANSI_API.md
- Test environment: Available immediately

---

**Status:** 🟢 Ready to Integrate  
**No additional setup needed**
