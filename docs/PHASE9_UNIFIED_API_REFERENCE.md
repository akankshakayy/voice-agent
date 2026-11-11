# Eko Sahayak - Unified API Reference

Complete API documentation for all 4 integrations serving the Uploader System.

---

## 📋 Table of Contents

1. [Mansi API](#mansi-api) - Pull-based RM recordings
2. [Prachi API](#prachi-api) - Push-based DC recordings webhook
3. [AutoGMap API](#autogmap-api) - Numbers sync & RM recording upload
4. [Admin Panel API](#admin-panel-api) - Internal CRUD endpoints

---

## Mansi API

**Purpose:** Pull-based API for Mansi (AutoGMap) to retrieve RM recordings for verification

### Authentication
```
Header: Authorization: Bearer {API_KEY}
```

### Endpoints

#### 1. Get RM Recordings List
```
GET /api/uploader/recordings
Query Parameters:
  - rm_id: (optional) Filter by RM ID
  - limit: (optional, default 50)
  - offset: (optional, default 0)
  - status: (optional) "pending" | "uploaded" | "verified"
```

**Response: 200 OK**
```json
{
  "recordings": [
    {
      "id": "rec_abc123",
      "rm_id": 1,
      "phone": "9876543210",
      "other_number": "8765432109",
      "direction": "outbound",
      "duration_sec": 120,
      "started_at": 1699756200,
      "uploaded_at": 1699756350,
      "status": "uploaded",
      "mode": "rm",
      "consent_given": true,
      "download_url": "https://indev.eko.in/api/recordings/download/rec_abc123"
    }
  ],
  "total": 245,
  "offset": 0
}
```

#### 2. Get Recording Details
```
GET /api/uploader/recordings/{id}
```

**Response: 200 OK**
```json
{
  "id": "rec_abc123",
  "rm_id": 1,
  "mode": "rm",
  "consent_given": true,
  "phone": "9876543210",
  "other_number": "8765432109",
  "direction": "outbound",
  "duration_sec": 120,
  "started_at": 1699756200,
  "uploaded_at": 1699756350,
  "status": "uploaded",
  "download_url": "https://indev.eko.in/api/recordings/download/rec_abc123",
  "metadata": {
    "device_id": "device_xyz",
    "watermark": "RM:phone_9876543210"
  }
}
```

---

## Prachi API

**Purpose:** Real-time webhook for pushing DC verification call recordings to Prachi CRM

### Authentication
```
Header: X-Recording-Secret: {PRACHI_RECORDING_SECRET}
```

### Endpoint
```
POST https://indev.eko.in/sbi-relationship-crm/api/v1/webhooks/recordings
```

### Request Payload (Single Recording)

```json
{
  "id": "rec_abc123",
  "dc_number": "9876543210",
  "other_number": "8765432109",
  "direction": "outbound",
  "started_at": "2026-11-11T10:30:00+05:30",
  "duration": 95,
  "audio_url": "https://indev.eko.in/api/recordings/download/rec_abc123"
}
```

### Batch Request (Multiple Recordings)

```json
[
  {
    "id": "rec_abc123",
    "dc_number": "9876543210",
    "other_number": "8765432109",
    "direction": "outbound",
    "started_at": "2026-11-11T10:30:00+05:30",
    "duration": 95,
    "audio_url": "https://indev.eko.in/api/recordings/download/rec_abc123"
  },
  {
    "id": "rec_def456",
    "dc_number": "9876543210",
    "other_number": "9999888877",
    "direction": "inbound",
    "started_at": "2026-11-11T11:15:00+05:30",
    "duration": 120,
    "audio_url": "https://indev.eko.in/api/recordings/download/rec_def456"
  }
]
```

### Field Descriptions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique recording ID |
| `dc_number` | string | Yes | Data Collector's 10-digit phone |
| `other_number` | string | Yes | Call recipient's 10-digit phone |
| `direction` | string | Yes | "outbound" or "inbound" |
| `started_at` | ISO 8601 | Yes | Call start time (UTC with timezone) |
| `duration` | integer | Yes | Call duration in seconds |
| `audio_url` | string | Yes | HTTPS URL to download audio |

### Response

**Success: 202 Accepted**
```json
{
  "ok": true,
  "id": "rec_abc123",
  "status": "received",
  "message": "Recording received and queued for processing"
}
```

**Error: 401 Unauthorized**
```json
{
  "detail": "Invalid or missing X-Recording-Secret header"
}
```

**Error: 400 Bad Request**
```json
{
  "detail": "Missing required field: dc_number"
}
```

### Rate Limits & Constraints

| Limit | Value | Notes |
|-------|-------|-------|
| Recordings per request | 50 (batch) | Max 50 per webhook call |
| Requests per minute | 100 | Rate limit per minute |
| Max payload size | 10 MB | JSON payload only (audio via URL) |
| Response timeout | 30 seconds | Server waits max 30s for response |
| Retry window | 24 hours | Server retries for up to 24 hours |

### Retry Logic

Server automatically retries on failure:
- Attempt 1: Immediate
- Attempt 2: After 5 minutes
- Attempt 3: After 1 hour
- Attempt 4: After 24 hours
- After 24h: Mark as failed

---

## AutoGMap API

**Purpose:** RM recording numbers sync and recording upload for verification

### Authentication
```
Header: Authorization: Bearer {AUTOGMAP_API_KEY}
```

### Endpoints

#### 1. Get Applicant Numbers
```
GET /autogmap/api/v1/call-recorder/numbers
```

**Response: 200 OK**
```json
{
  "numbers": [
    "9876543210",
    "9876543211",
    "9876543212"
  ]
}
```

#### 2. Upload RM Recording
```
POST /autogmap/api/v1/call-recorder/recordings
Content-Type: multipart/form-data

Fields:
  - file: (audio file, <60MB)
  - phone: (10-digit number)
  - direction: ("outbound" | "inbound")
  - duration: (seconds)
  - device_id: (device identifier)
```

**Response: 201 Created**
```json
{
  "id": "upload_abc123",
  "status": "accepted",
  "phone": "9876543210"
}
```

**Response: 422 Unprocessable Entity**
```json
{
  "detail": "Phone number not in applicants list"
}
```

**Response: 401 Unauthorized**
```json
{
  "detail": "Invalid API key"
}
```

---

## Admin Panel API

**Purpose:** Internal CRUD operations for DCs, Employees, Allowed Numbers

### Authentication
```
Header: Authorization: Bearer {ADMIN_API_KEY}
```

### Endpoints

#### DCs (Data Collectors)

**List DCs**
```
GET /api/admin/dcs
```

**Add DC**
```
POST /api/admin/dcs
Content-Type: application/json

{
  "name": "Arun Kumar",
  "phone": "9876543210",
  "email": "arun@example.com"
}
```

**Update DC**
```
PUT /api/admin/dcs/{id}
```

**Delete DC**
```
DELETE /api/admin/dcs/{id}
```

#### Employees

**List Employees**
```
GET /api/admin/employees
```

**Add Employee**
```
POST /api/admin/employees
```

**Update Employee**
```
PUT /api/admin/employees/{id}
```

**Delete Employee**
```
DELETE /api/admin/employees/{id}
```

#### Allowed Numbers (AutoGMap SBI Officials)

**List Allowed Numbers**
```
GET /api/admin/allowed-numbers
```

**Add Allowed Number**
```
POST /api/admin/allowed-numbers

{
  "phone": "9876543210",
  "name": "SBI Official - Branch 1"
}
```

**Update Allowed Number**
```
PUT /api/admin/allowed-numbers/{id}
```

**Delete Allowed Number**
```
DELETE /api/admin/allowed-numbers/{id}
```

---

## Common Workflows

### Workflow 1: RM Recording Upload to AutoGMap
```
1. Kotlin app detects Eko SIM call recording
2. Matches to applicant number from AutoGMap
3. App uploads to POST /autogmap/api/v1/call-recorder/recordings
4. Server receives 201 Created
5. Recording marked as verified in AutoGMap
```

### Workflow 2: DC Recording to Prachi CRM
```
1. Kotlin app detects DC verification call
2. User confirms consent checkbox
3. Upload to server POST /api/uploader/recordings
4. Server validates and formats payload
5. Server pushes to Prachi webhook (202 Accepted)
6. Prachi processes in CRM workflow
```

### Workflow 3: Pull-Based Access for Mansi
```
1. Mansi queries GET /api/uploader/recordings
2. Receives list of RM recordings ready for verification
3. Downloads audio via download_url
4. Verifies and processes in AutoGMap
```

---

## Error Handling

### Retry Strategy

All transient errors (5xx, timeouts) are automatically retried:
- Initial retry: Immediate
- Backoff: Exponential (5min → 1h → 24h)
- Max attempts: 4 total attempts
- Success: Any 2xx response

### Non-Retryable Errors

- 400 Bad Request: Fix payload format
- 401 Unauthorized: Check API key/secret
- 422 Unprocessable Entity: Invalid business logic (e.g., number not in list)

---

## Testing

### cURL Examples

**Test Prachi Webhook**
```bash
curl -X POST https://indev.eko.in/sbi-relationship-crm/api/v1/webhooks/recordings \
  -H "X-Recording-Secret: YOUR_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "rec_test_001",
    "dc_number": "9876543210",
    "other_number": "8765432109",
    "direction": "outbound",
    "started_at": "2026-11-11T10:30:00+05:30",
    "duration": 95,
    "audio_url": "https://indev.eko.in/api/recordings/download/rec_test_001"
  }'
```

**Test AutoGMap Numbers**
```bash
curl -X GET https://indev.eko.in/autogmap/api/v1/call-recorder/numbers \
  -H "Authorization: Bearer YOUR_API_KEY"
```

---

## Support & Troubleshooting

**Issues:** Contact dev-team@eko.co.in  
**API Problems:** api-support@eko.co.in  
**Questions:** prachi@eko.co.in (Prachi team)
