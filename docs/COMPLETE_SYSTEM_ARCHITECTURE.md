# Eko RM Voice Agent - Complete System Architecture & Understanding

## 1. THREE-MODE RECORDING ARCHITECTURE

### Upload Modes (Mutually Exclusive)

#### **RM Mode** (Resource Manager)
- **Actors**: Multiple RMs calling CSPs
- **Token ID**: `rm_id` (set), `dc_id`=NULL, `employee_id`=NULL
- **Allowed Numbers**: NONE - RMs can call any CSP
- **Validation**: Mode + rm_id check only
- **Directory**: `rm{id}/`
- **Use Case**: Existing RM calling workflow for CSP engagement
- **Uploader Shows**: Dropdown to select which RM is calling
- **DB Mode Field**: `mode='rm'`

#### **DC Mode** (District Coordinator)  
- **Actors**: One DC calling SBI officials in their region + assigned CSPs
- **Token ID**: `dc_id` (set), `rm_id`=NULL, `employee_id`=NULL
- **Allowed Numbers**: YES - PER DC - restricted list of phone numbers
  - Each DC has their own allowed_numbers table (UNIQUE(dc_id, phone_number))
  - Validation: `is_allowed_number(dc_id, phone_number)` must pass
  - Error if phone not in DC's list: "Phone number X not in DC allowed list"
- **DC Assignment**: NO - DCs are NOT assigned to other DCs. A DC IS their own actor.
- **Consent**: Optional consent token validation
- **Directory**: `dc{id}/`
- **Use Case**: DC coordinates SBI officials to reach applicants
- **Uploader Shows**: DC name + allowed phone numbers list
- **API Endpoint**: `/api/uploader/allowed-numbers` (DC mode only)
- **DB Mode Field**: `mode='dc'`

#### **Employee Mode** (Employee/Agent)
- **Actors**: Employees calling anyone (typically applicants)
- **Token ID**: `employee_id` (set), `rm_id`=NULL, `dc_id`=NULL
- **Allowed Numbers**: NONE - Employees can call anyone
- **DC Assignment**: NO - Employees are standalone, NOT assigned to DCs
- **Validation**: Mode + employee_id check only (NO allowed_numbers validation)
- **Directory**: `employee{id}/`
- **Use Case**: Employees/agents make calls tracked by individual employee
- **Uploader Shows**: Employee name only
- **DB Mode Field**: `mode='employee'`

### Key Differences Table

| Feature | RM Mode | DC Mode | Employee Mode |
|---------|---------|---------|---------------|
| Allowed Numbers | No restriction | YES - Per DC | No restriction |
| DC Assignment | No | N/A (IS a DC) | No |
| Validation Call | Mode/ID only | Mode/ID + allowed_numbers + consent | Mode/ID only |
| API Returns | RM list | DC name + 20-193 numbers | Employee name |
| Recording Path | rm{id}/ | dc{id}/ | employee{id}/ |

---

## 2. DATA STORAGE & BACKUP STRATEGY

### Current Database State (as of Nov 13, 2026)

```
Database: data/eko_agent.db (SQLite)

DCs:                   9 total (DC#2-DC#9)
Allowed Numbers:       336 total
  - Ajay:               20 numbers
  - Ajay Modgil:        2 numbers  
  - Anil Sharma:       193 numbers
  - Anish:              19 numbers
  - Ashutosh Pathak:    44 numbers
  - Balram:             16 numbers
  - Nadeem:              8 numbers
  - Ravi Shankar Kumar: 34 numbers

Employees:             0 (none configured)
Recordings:            2 total (both RM mode)
RMs:                   3 total
CSPs:                  595 total (from calling sheet)
```

### Backup System (Phase 8)

**Location**: `data/backups/` (next to database)

**Types**:
1. Full backup: All tables
2. Filtered: By RM ID / DC ID / Employee ID
3. Mode-specific: RM recordings, DC recordings, or Employee recordings

**Format**: ZIP archive containing:
- SQLite database dump (`.db` file)
- JSON exports of tables
- Metadata with record counts & timestamps

**Exportable Tables**:
- `dcs` - District Coordinators
- `employees` - Employees/Agents
- `allowed_numbers` - Per-DC phone restrictions
- `recordings` - All call recordings
- `upload_tokens` - Active device tokens
- `csps` - CSP reference data
- `autogmap_numbers` - Applicant numbers from AutoGMap
- `prachi_sync_history` - Sync audit trail

**Metadata Tracked**:
- Backup ID & timestamp
- Record counts per table
- Filtered mode (full/rm/dc/employee)
- Compressed size

---

## 3. THREE EXTERNAL INTEGRATIONS

### **Prachi** - Google Sheets Daily Sync

**Purpose**: Keeps DC and SBI official lists in sync with authoritative Google Sheets

**Configuration**:
- `PRACHI_SHEET_ID`: Google Sheets document ID
- `PRACHI_SYNC_ENABLED`: true/false
- `PRACHI_SYNC_SCHEDULE_HOUR`: 2 (2 AM daily)
- `PRACHI_SYNC_TIMEOUT_SECONDS`: 60
- `PRACHI_SYNC_RETRY_MAX`: 3

**Data Synced**:
1. **DCs Sheet** (gid=0)
   - Fetches: DC name, phone number, region
   - Updates: `dcs` table daily
   - Soft delete: Marks removed DCs as `active=0`

2. **SBI Officials Sheet** (gid=1881479143)
   - Fetches: Phone number, DC name assignment
   - Updates: `allowed_numbers` table per DC
   - Constraint: UNIQUE(dc_id, phone_number)
   - Soft delete: Marks removed numbers as `active=0`

**Workflow**:
```
Google Sheets (source of truth)
    ↓ (CSV export via Google API)
Prachi Sync Loop (every 24 hours at 2 AM)
    ↓ (Parse & deduplicate)
Database (dcs + allowed_numbers tables)
    ↓ (API queries)
Admin Panel (displays current state)
```

**Audit Trail**: `prachi_sync_history` table
- Tracks: sync type, success/failure, records added/updated/deleted
- Retry logic: Exponential backoff on failures
- Status: Degraded if 3+ consecutive failures

---

### **AutoGMap** - Applicant Numbers Sync & Recording Upload

**Purpose**: Tracks which phone numbers are active applicants and uploads Employee/RM recordings

**Configuration**:
- `AUTOGMAP_ENABLED`: true/false
- `AUTOGMAP_NUMBERS_URL`: API endpoint for applicant list
- `AUTOGMAP_RECORDINGS_URL`: API endpoint for recording upload
- `AUTOGMAP_API_KEY`: Bearer token for authentication
- `AUTOGMAP_SYNC_INTERVAL_MINUTES`: 15 (sync every 15 min)
- `AUTOGMAP_UPLOAD_MAX_WORKERS`: 2 (Mansi's rate limit: 2 req/sec)

**Two Operations**:

1. **Numbers Sync (every 15 minutes)**
   - Fetch: Current applicant numbers from AutoGMap API
   - Cache: In-memory + database (`autogmap_numbers` table)
   - Track: `phone`, `local`, `name`, `since` (when they became applicant)
   - Status: Keeps sync history and failure streaks

2. **Recording Upload Queue**
   - RM recordings: Auto-queued for upload to AutoGMap
   - Employee recordings: Sent to Mansi API instead (see below)
   - Upload workers: 2 concurrent uploads (Mansi's rate limit)
   - Retry logic: Exponential backoff [60s, 300s, 900s]
   - Size limit: 60 MB max (Mansi requirement)
   - Status codes: 201=kept, 422=not_applicant/not_audio/too_large, 401=auth_fail

**Response Parsing**:
```json
{
  "as_of": 1698765432,
  "count": 50,
  "numbers": [
    {"phone": "9876543210", "local": "10", "name": "John", "since": "2026-01-01"}
  ]
}
```

---

### **Mansi** - Employee Recording Pull API

**Purpose**: Provides Employee recordings on-demand to Mansi (external assessment system)

**Configuration**:
- `AUTOGMAP_RECORDINGS_URL`: Used for push (same as AutoGMap upload)
- `AUTOGMAP_API_KEY`: Bearer token
- `AUTOGMAP_UPLOAD_MAX_WORKERS`: 2 (rate limit)
- Upload size limit: 60 MB max

**How It Works**:

1. **Push (Send Recording)**
   - Employee uploads call recording via Sahayak app
   - System auto-sends to Mansi API (no transcription)
   - Tracks: `mansi_api_sent_at`, `mansi_request_id`
   - Retry on 5xx, give up on 422 (not_applicant/not_audio)
   - Rate limited: Max 2 uploads/second

2. **Pull (Mansi Queries Recordings)**
   - Mansi calls: `GET /api/mansi/recordings`
   - Filters: Employee ID, status, etc.
   - Returns: Raw audio + metadata
   - No authentication required on this endpoint (internal)

**Differences from RM/DC**:
- RM recordings: Sent to Prachi API (for assessment)
- DC recordings: Sent to Prachi API (with consent tracking)
- **Employee recordings: Sent to Mansi API (no transcription, assessor queries directly)**

---

## 4. DATA FLOW ARCHITECTURE

```
┌─────────────────────────────────────────────────────────┐
│  EXTERNAL DATA SOURCES                                  │
├─────────────────────────────────────────────────────────┤
│  Google Sheets (Prachi)          AutoGMap API           │
│  DCs + SBI Officials             Applicant Numbers      │
└──────────────┬────────────────────────┬─────────────────┘
               ↓ (Daily @ 2 AM)         ↓ (Every 15 min)
┌──────────────────────────────────────────────────────────┐
│  CORE DATABASE (data/eko_agent.db)                       │
├──────────────────────────────────────────────────────────┤
│  dcs                 - District Coordinators              │
│  employees           - Standalone agents                 │
│  rms                 - Resource managers                 │
│  allowed_numbers     - Per-DC phone restrictions        │
│  csps                - CSP reference data                │
│  autogmap_numbers    - Cached applicant list            │
│  recordings          - All call recordings              │
│  upload_tokens       - Device authentication            │
│  prachi_sync_history - Sync audit trail                │
└──────────────┬───────────────────────────────────────────┘
               ↓
┌──────────────────────────────────────────────────────────┐
│  BACKUP SYSTEM (data/backups/)                           │
├──────────────────────────────────────────────────────────┤
│  Full backups (all tables) or Filtered (by RM/DC/Emp)   │
│  ZIP archives with SQLite + JSON                        │
│  Metadata: record counts, timestamps, sizes             │
└──────────────────────────────────────────────────────────┘
               ↑
               │ (Restore on demand)
┌──────────────────────────────────────────────────────────┐
│  SAHAYAK UPLOADER APP (on RM/DC/Employee phones)        │
├──────────────────────────────────────────────────────────┤
│  RM Mode:      Call CSP → validate vs CSP list          │
│  DC Mode:      Call SBI → validate against allowed_nums│
│  Employee Mode: Call anyone → no validation            │
└──────────────────────────────────────────────────────────┘
               ↓ (POST /api/uploader/recordings)
        Store recording file + DB entry
               ↓
        Upload to external APIs:
        ├─ RM recordings → Prachi API
        ├─ DC recordings → Prachi API (with consent)
        └─ Employee recordings → Mansi API
```

---

## 5. AUTHENTICATION & ACCESS CONTROL

### User Roles
- `admin`: Full access to admin panel, all APIs
- `ops`: Access to recordings dashboard & metrics
- `rm`: Limited to their own RM's data
- `pending`: Not approved yet; access only to account settings

### Role-Based Endpoints

| Endpoint | Admin | Ops | RM | Dev Mode |
|----------|-------|-----|----|----|
| `/api/dcs` | ✅ | ❌ | ❌ | Bypass (mock admin) |
| `/api/allowed-numbers` | ✅ | ❌ | ❌ | Bypass |
| `/api/employees` | ✅ | ❌ | ❌ | Bypass |
| `/api/uploader/ping` | ❌ | ❌ | ❌ | N/A (token auth) |
| `/api/uploader/recordings` | ❌ | ❌ | ❌ | N/A (token auth) |
| `/api/mansi/recordings` | ❌ | ❌ | ❌ | N/A (internal) |

### Dev Mode (DEV_MODE=1)
- Bypasses authentication for localhost (127.0.0.1, ::1)
- Sets mock admin user: `email="dev@localhost"`, `role="admin"`
- Useful for testing without Google OAuth setup
- Must be enabled manually (`export DEV_MODE=1` or in .env)

---

## 6. CRITICAL DESIGN DECISIONS

1. **Allowed Numbers are DC-Specific**
   - Each DC has their own restricted list
   - UNIQUE(dc_id, phone_number) constraint prevents duplicates
   - SBI officials shared across DCs by listing in each DC's sheet
   - Validation happens on upload, not in Uploader app's validation

2. **Three Completely Independent Modes**
   - Not overlapping or hierarchical
   - An RM ≠ DC; An employee ≠ DC
   - Each has separate token, directory, validation logic
   - Mutually exclusive in upload_tokens table

3. **No Employee-DC Relationship**
   - Employees are NOT assigned to DCs
   - Employees have NO allowed_numbers restrictions
   - Unlike DCs which are area-specific, employees are standalone

4. **Data Sources (Authoritative)**
   - Google Sheets: Source of truth for DCs + SBI officials (via Prachi)
   - AutoGMap: Source of truth for applicant numbers
   - Calling Sheet: CSP reference data (595 CSPs)
   - Manual Excel: Used when Prachi sync fails (fallback)

5. **Backup Strategy**
   - Granular by mode (full/rm/dc/employee)
   - ZIP archives with metadata
   - Can restore individual tables or full database
   - Audit trail in prachi_sync_history

---

## 7. CURRENT STATE (Nov 13, 2026)

### Data Loaded
- ✅ 8 DCs with phone numbers (loaded from Excel file)
- ✅ 336 SBI officials distributed to DCs
- ✅ API endpoints responding correctly (with DEV_MODE=1)
- ✅ Database backup system operational
- ❌ Prachi sync disabled (no sheet configured)
- ❌ AutoGMap sync disabled (no API key)
- ❌ No employees created yet

### Known Issues
- Admin panel requires authentication (DEV_MODE=1 fixes for localhost testing)
- Database data persists only while app runs (not backed up to persistent volume)
- Prachi sync needs Google Sheets ID configured
- AutoGMap needs API key for applicant number syncing
