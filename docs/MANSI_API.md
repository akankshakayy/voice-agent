# Mansi API Documentation

**Purpose:** Employee Recording Retrieval API  
**Use Case:** Mansi fetches employee recordings on-demand for her workflows  
**Model:** Pull-based (Mansi queries, Server responds)  
**Authentication:** API Key (MANSI_API_KEY)

---

## Overview

Mansi receives employee call recordings from Eko's uploader app. Instead of receiving all data at once (push), Mansi can query for specific recordings based on:
- Employee ID
- Caller phone number
- Date range
- Status

**Default behavior:** Last 7 days (prevents data overload)  
**Flexible:** Can customize time range as needed

---

## Quick Start

### Most Common Query
```bash
# Get all calls from employee with a specific caller (last 7 days)
curl -H "Authorization: Bearer MANSI_API_KEY" \
  "https://api.eko.co.in/api/mansi/recordings?employee_id=1&other_number=9876543210"
```

**Response:**
```json
{
  "recordings": [
    {
      "id": 361,
      "employee_id": 1,
      "other_number": "9876543210",
      "duration_sec": 45,
      "uploaded_at": "2026-11-11T10:30:00Z",
      "status": "done",
      "file_path": "employee1/2026-11-11/rec001.m4a"
    },
    {
      "id": 360,
      "employee_id": 1,
      "other_number": "9876543210",
      "duration_sec": 32,
      "uploaded_at": "2026-11-11T09:15:00Z",
      "status": "done",
      "file_path": "employee1/2026-11-11/rec002.m4a"
    }
  ],
  "total": 2,
  "filters_applied": {
    "employee_id": 1,
    "other_number": "9876543210",
    "days": 7
  }
}
```

---

## Use Cases

### Use Case 1: Follow-up with a Caller
**Scenario:** You need to review all interactions between Employee 1 and caller 9876543210

```bash
GET /api/mansi/recordings?employee_id=1&other_number=9876543210
```

**Returns:** All calls from last 7 days between them (conversation history)

---

### Use Case 2: Review Employee's Calls Today
**Scenario:** Quick daily check of what Employee 2 did today

```bash
GET /api/mansi/recordings?employee_id=2&days=1
```

**Returns:** All recordings from Employee 2 from today only

---

### Use Case 3: Deep Dive on Caller Across All Employees
**Scenario:** Caller 9876543210 had issues - check all employee interactions

```bash
GET /api/mansi/recordings?other_number=9876543210&days=30
```

**Returns:** All recordings with this number from any employee (last 30 days)

---

### Use Case 4: Historical Analysis (Custom Date Range)
**Scenario:** Analyze November's performance for Employee 1

```bash
GET /api/mansi/recordings?employee_id=1&date_from=2026-11-01&date_to=2026-11-30
```

**Returns:** All recordings from Employee 1 in November

---

### Use Case 5: Filter by Status
**Scenario:** Only completed calls (no processing issues)

```bash
GET /api/mansi/recordings?employee_id=1&status=done
```

**Returns:** Only successfully processed recordings

---

## API Reference

### Endpoint
```
GET /api/mansi/recordings
```

### Authentication
```
Header: Authorization: Bearer MANSI_API_KEY
```

### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `employee_id` | integer | No | - | Filter by specific employee |
| `other_number` | string | No | - | Filter by caller phone number |
| `days` | integer | No | 7 | Last N days (overridden by date_from/date_to) |
| `date_from` | string | No | - | Start date (ISO format: 2026-11-01) |
| `date_to` | string | No | - | End date (ISO format: 2026-11-30) |
| `status` | string | No | - | Filter by status: 'new', 'done', 'failed' |
| `skip` | integer | No | 0 | Pagination offset |
| `limit` | integer | No | 100 | Max records per request (max 500) |

### Default Behavior
```
Without any filters: Returns ALL employee recordings from last 7 days
With employee_id: Returns that employee's recordings from last 7 days
With date_from/date_to: Ignores 'days' parameter
```

---

## Response Format

### Success (200)
```json
{
  "recordings": [
    {
      "id": 361,
      "employee_id": 1,
      "mode": "employee",
      "other_number": "9876543210",
      "duration_sec": 45,
      "uploaded_at": "2026-11-11T10:30:00Z",
      "status": "done",
      "file_path": "employee1/2026-11-11/rec001.m4a",
      "timestamp": "2026-11-11T10:30:00Z"
    }
  ],
  "total": 1,
  "default_timeframe": "last 7 days",
  "filters_applied": {
    "employee_id": 1,
    "other_number": "9876543210",
    "days": 7
  }
}
```

### Error (400)
```json
{
  "detail": "Invalid employee_id: must be positive integer"
}
```

### Error (401)
```json
{
  "detail": "Invalid or missing API key"
}
```

---

## Query Examples (CURL)

```bash
# Setup
MANSI_ENDPOINT="https://api.eko.co.in"

# 1. All calls from Employee 1 (last 7 days)
curl -H "Authorization: Bearer <your-token>" \
  "$MANSI_ENDPOINT/api/mansi/recordings?employee_id=1"

# 2. Specific caller conversation (last 7 days)
curl -H "Authorization: Bearer <your-token>" \
  "$MANSI_ENDPOINT/api/mansi/recordings?employee_id=1&other_number=9876543210"

# 3. Today only
curl -H "Authorization: Bearer <your-token>" \
  "$MANSI_ENDPOINT/api/mansi/recordings?employee_id=1&days=1"

# 4. Last 30 days
curl -H "Authorization: Bearer <your-token>" \
  "$MANSI_ENDPOINT/api/mansi/recordings?employee_id=1&days=30"

# 5. Specific date range
curl -H "Authorization: Bearer <your-token>" \
  "$MANSI_ENDPOINT/api/mansi/recordings?employee_id=1&date_from=2026-11-01&date_to=2026-11-15"

# 6. Only completed calls
curl -H "Authorization: Bearer <your-token>" \
  "$MANSI_ENDPOINT/api/mansi/recordings?employee_id=1&status=done"

# 7. With pagination (page 2, 50 per page)
curl -H "Authorization: Bearer <your-token>" \
  "$MANSI_ENDPOINT/api/mansi/recordings?employee_id=1&skip=50&limit=50"

# 8. All calls with specific number from any employee
curl -H "Authorization: Bearer <your-token>" \
  "$MANSI_ENDPOINT/api/mansi/recordings?other_number=9876543210&days=7"
```

---

## Key Differences from Direct Database Access

| Aspect | Mansi API | Direct DB |
|--------|-----------|-----------|
| **Time to set up** | Minutes (API key) | Hours (DB access) |
| **Security** | Scoped permissions | Full DB access |
| **Rate limiting** | Built-in | None |
| **Monitoring** | Logged & audited | No audit trail |
| **Filtering** | Optimized queries | Manual filtering |
| **Default safety** | Last 7 days (bounded) | No limit (overload risk) |

---

## Common Workflows

### Workflow 1: Daily Quality Check
```bash
# Every morning, check all recordings from yesterday
date_yesterday=$(date -d yesterday +%Y-%m-%d)
curl -H "Authorization: Bearer $MANSI_API_KEY" \
  "$API_BASE/api/mansi/recordings?days=1&status=done"
```

### Workflow 2: Follow-up Investigation
```bash
# Customer complained → check all their interactions
phone="9876543210"
curl -H "Authorization: Bearer $MANSI_API_KEY" \
  "$API_BASE/api/mansi/recordings?other_number=$phone&days=30"
```

### Workflow 3: Employee Onboarding Report
```bash
# New employee started → review their calls from first week
employee_id=5
date_start=$(date -d "7 days ago" +%Y-%m-%d)
date_today=$(date +%Y-%m-%d)
curl -H "Authorization: Bearer $MANSI_API_KEY" \
  "$API_BASE/api/mansi/recordings?employee_id=$employee_id&date_from=$date_start&date_to=$date_today"
```

---

## Rate Limits

| Metric | Limit | Reset |
|--------|-------|-------|
| Requests/minute | 60 | Per minute |
| Requests/hour | 3000 | Per hour |
| Records per request | 500 max | Per request |

---

## Support & Troubleshooting

### Problem: No recordings returned
**Possible causes:**
1. Date range doesn't have data → try `&days=30`
2. Employee ID doesn't exist → verify employee is in system
3. Phone number never called → check if number is correct

### Problem: API Key invalid
1. Verify key is correct: `echo $MANSI_API_KEY`
2. Check key hasn't expired (contact admin)
3. Ensure header format: `Authorization: Bearer <key>`

### Problem: Too many records returned
**Solution:** Use pagination
```bash
# Get first 50
curl ... "?employee_id=1&limit=50&skip=0"

# Get next 50
curl ... "?employee_id=1&limit=50&skip=50"
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Nov 11, 2026 | Initial release - Pull-based API with flexible filtering |

---

## Contact

**Technical Support:** dev-team@eko.co.in  
**API Issues:** api-support@eko.co.in  
**Questions about use:** mansi@eko.co.in (your team)
