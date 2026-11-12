# COMPLETE SYSTEM FIX PLAN - ALL ISSUES

**Date:** 2026-11-13  
**Status:** Recordings working ✅ | DC Management broken ❌ | Uploader unknown ❓

---

## PHASE 1: DATA VERIFICATION & BACKUP

### Task 1.1: Verify DC & SBI Officials Sheet
- [ ] Locate DC list sheet provided by user
- [ ] Locate SBI officials list provided by user
- [ ] Count records in each
- [ ] Document location: `docs/USER_PROVIDED_DATA.md`

### Task 1.2: Backup Current Data
- [ ] Backup /home/akanksha/voice_agent/data/eko_agent.db
- [ ] Location: `/home/akanksha/voice_agent/backups/eko_agent_backup_<date>.db`
- [ ] Document in `docs/BACKUP_RESTORE_INCIDENT_20261112.md`

### Task 1.3: Check Existing DCs in Database
- [ ] Query: `SELECT COUNT(*) FROM dcs;`
- [ ] Query: `SELECT * FROM dcs LIMIT 10;`
- [ ] Document count

---

## PHASE 2: FIX CRITICAL ENDPOINTS

### Task 2.1: Fix /api/dcs Endpoint
**Current Status:** Returns "Failed to fetch"
**Root Cause:** Database connection error on startup

**Fix:**
1. Remove ALL schema migration code from _ensure_schema()
2. Make it silently fail if columns don't exist
3. Add columns properly in conn() function AFTER SCHEMA runs
4. Test endpoint returns data

**Verify:**
```bash
curl -H "Authorization: Bearer <token>" https://indev.eko.in/rm-voice-agent/api/dcs
```
Should return: `[{id, name, phone, email, region, created_at, active}]`

### Task 2.2: Fix /api/users Endpoint
**Current Status:** Shows "Loading..." forever (never returns)
**Root Cause:** Unknown

**Fix:**
1. Check endpoint exists in app/main.py
2. Check database has users table
3. Debug what's causing hang
4. Return user list properly

**Verify:** Users section in Users page loads data

### Task 2.3: Fix /api/upload-tokens Endpoint
**Current Status:** Unknown if working

**Fix:**
1. Verify endpoint exists
2. Verify it returns token list
3. Verify it accepts `mode` parameter (rm, dc, employee)
4. Verify it creates tokens with correct mode

### Task 2.4: Check Sahayak Uploader Endpoints
**Unknown Status** - Need to verify all these work:
- `/api/uploader/config` - Device config
- `/api/uploader/auth` - Device authentication  
- `/api/uploader/upload` - Recording upload
- `/api/uploader/status` - Upload status
- `/api/uploader/allowed-numbers` - Get allowed numbers for DC

---

## PHASE 3: FIX FUNCTIONALITY ISSUES

### Task 3.1: Fix Terminology Completely
**All "Data Collector" → "District Coordinator"**

Remaining places:
- [ ] `app/bulk_load.py:226`
- [ ] `app/db.py:121`
- [ ] `app/main.py:547, 560, 1275, 1301, 1330`

### Task 3.2: Fix DC List Loading in Admin
**Current:** Shows "Failed to load data"

**Fix:**
1. Ensure /api/dcs works (Phase 2.1)
2. Check admin.html loadDCs() function
3. Ensure fetch headers include credentials
4. Verify response is rendered

### Task 3.3: Fix Allowed Numbers System
**Current:** Not loading

**Requirements:**
- DCs can call: CSP numbers + SBI officials (provided by user)
- Employees can call: Anyone (unrestricted)

**Fix:**
1. Load DC allowed numbers from user's sheet
2. Set employee allowed numbers to empty/unrestricted
3. Create endpoint: GET /api/allowed-numbers?dc_id={id}
4. Return: [phone_number, description, type]

### Task 3.4: Implement Mode-Specific Recording Filters
**Current:** Same filters for RM/DC/Employee (wrong)

**Fix:**
1. RM recordings: Status, Issue Type, RM, Date, Search
2. DC recordings: Status, Date, Search (NO issue type)
3. Employee recordings: Status, Date, Search (NO issue type)

### Task 3.5: Implement DC Lookup in Token Creation
**Current:** No DC search

**Fix:**
1. Add autocomplete to token creation "Person" dropdown
2. When "District Coordinator" selected, show DC list
3. Allow searching by name
4. On token creation, validate DC exists

---

## PHASE 4: DATA IMPORT

### Task 4.1: Import DCs from User Sheet
1. Get DC list from user (name, phone, email, region, etc.)
2. INSERT INTO dcs VALUES (...)
3. Verify all DCs appear in admin panel

### Task 4.2: Import Allowed Numbers
1. Get CSP phone numbers from user's calling sheet
2. Get SBI officials from user's sheet
3. For each DC: INSERT INTO allowed_numbers (dc_id, phone_number, description)
4. For employees: Leave allowed_numbers empty (unrestricted)

### Task 4.3: Import Employee Data
1. Get employee list if provided
2. INSERT INTO employees
3. Verify in admin panel

---

## PHASE 5: TEST & VERIFY

### Task 5.1: Test DC Creation
1. Create new DC via admin panel
2. Verify it appears in DC list immediately
3. Verify data persists after page refresh

### Task 5.2: Test DC Deletion
1. Delete a DC
2. Verify it's removed from list

### Task 5.3: Test Token Creation
1. Select "District Coordinator"
2. Search for DC by name
3. Create token
4. Verify token works with uploader app

### Task 5.4: Test Allowed Numbers
1. As DC user, verify can only call allowed numbers
2. As Employee user, verify can call anyone

### Task 5.5: Test Recording Filters
1. RM tab: See Issue Type filter
2. DC tab: NO Issue Type filter
3. Employee tab: NO Issue Type filter

### Task 5.6: Test Data Persistence
1. Add new DC via admin
2. Deploy new version (eko-deploy deploy)
3. Verify DC still exists after deployment
4. Add allowed number
5. Deploy again
6. Verify allowed number still exists

---

## PHASE 6: DOCUMENT & BACKUP STRATEGY

### Task 6.1: Document Everything
- [ ] Update `docs/BACKUP_RESTORE_INCIDENT_20261112.md`
- [ ] Add daily backup strategy
- [ ] Add recovery procedures
- [ ] Add troubleshooting guide

### Task 6.2: Implement Automated Backups
- [ ] Daily backup script at 22:00 IST
- [ ] 30-day retention
- [ ] Store at: `/home/akanksha/voice_agent/backups/`

---

## CRITICAL REQUIREMENTS

✅ **Functionality:** Whole system must work end-to-end
✅ **Data Safety:** NO data loss - guaranteed backup strategy
✅ **Verification:** Every endpoint tested and verified
✅ **User Data:** DCs and SBI officials sheet imported
✅ **Uploader:** Sahayak uploader endpoints all working

---

## EXECUTION ORDER

1. **Session Start:** Fix database schema permanently (removes blocker)
2. **Phase 1:** Data verification & backup
3. **Phase 2:** Fix all endpoints
4. **Phase 3:** Fix functionality
5. **Phase 4:** Import user data
6. **Phase 5:** Comprehensive testing
7. **Phase 6:** Document & backup strategy
8. **Session End:** Verify complete functionality, no data loss

---

## DEPLOYMENT SEQUENCE

After each phase:
- Commit changes
- Deploy via eko-deploy
- Test thoroughly
- Verify data persistence

Do NOT move to next phase until current phase fully works.

---

## NOTES FOR NEXT SESSION

- User provided: DC list, CSP numbers, SBI officials, allowed numbers
- Location: Need to confirm where these files are
- Database: Currently 358 recordings, must preserve
- Uploader: Unknown if working - must verify
- Goal: Complete, functional system with zero data loss risk

