# Employee Mode Integration Guide for Mansi

**Date:** November 12, 2026  
**Status:** Ready for Integration  
**System:** Eko Sahayak Uploader - Employee Mode

---

## Overview

**Employee Mode recordings use PULL (on-demand) model only.**

- **Recording source:** All calls recorded by Employee (Kavya, future expansion)
- **Storage:** Stored locally on our server + synced to database
- **Access:** Mansi queries our server when she needs recordings
- **No credentials needed:** Employee mode is available at public PULL endpoint
- **No external push:** Recordings are not sent to Mansi's server automatically

---

## PULL (On-Demand Query) - Employee Mode

### How It Works (Kavya's Flow)
1. Sahayak Uploader app is installed on Kavya's phone
2. Kavya makes/receives calls with new leads
3. Uploader automatically records all calls
4. Recordings are stored locally + synced to our server
5. When Mansi needs recordings, she sends a GET request
6. Our server returns all recordings from that date range

### Key Differences from RM/DC:
- **No applicant numbers list** - All calls are recorded
- **No filtering** - All recordings available
- **No auto-push** - Mansi pulls on-demand
- **No consent needed** - Internal employee calls

---

## PULL (On-Demand Query) - General

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
