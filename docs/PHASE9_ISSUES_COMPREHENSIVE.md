# Phase 9 Comprehensive Issues List

**Session Date:** 2026-11-12 to 2026-11-13  
**Status:** Recordings loading ✅ | Database fixed ✅ | DC Management 🔴

---

## ALL ISSUES (Prioritized)

### 🔴 CRITICAL - Admin Panel DC Creation

**Issue:** DC creation fails with "failed to fetch" error  
**User Report:** "Failed to fetch when creating new DC"  
**Root Cause:** TBD - Need to check:
- API endpoint returns error
- Form data validation failing
- Fetch request headers missing
- CORS issue

**Fix Required:**
- [ ] Check browser console error message (F12 → Console)
- [ ] Verify POST /api/dcs endpoint accepts data
- [ ] Check form sends proper headers with credentials
- [ ] Verify admin user has permission to create DCs

---

### 🔴 CRITICAL - DC List Not Displaying

**Issue:** DC list provided by user not showing in admin panel  
**User Report:** "DC list not reflecting there"  
**Expected:** Admin panel should show list of District Coordinators
**Actual:** Empty or not loading

**Possible Causes:**
- [ ] API /api/dcs returns empty or error
- [ ] UI JavaScript not parsing response correctly  
- [ ] loadDCs() function not being called
- [ ] Table rendering function broken

**Fix Required:**
- [ ] Test API: `curl https://indev.eko.in/rm-voice-agent/api/dcs`
- [ ] Check browser Network tab - does /api/dcs return data?
- [ ] Check browser Console - any JS errors?
- [ ] Verify DC count in database

---

### 🔴 CRITICAL - Allowed Numbers List Not Displaying

**Issue:** Allowed numbers provided by user not showing  
**User Report:** "Allowed numbers list not reflecting"  
**Expected:** Admin panel shows phone numbers for each DC
**Actual:** Empty list

**Possible Causes:**
- [ ] API /api/allowed-numbers returns empty
- [ ] No allowed numbers imported from user data
- [ ] UI not loading/rendering list

**Fix Required:**
- [ ] Check database: `SELECT COUNT(*) FROM allowed_numbers`
- [ ] Test API endpoint
- [ ] Verify data import happened

---

### 🔴 CRITICAL - Data Persistence on New DC Add

**Issue:** When manually adding new DCs via admin panel, will data get lost?  
**User Concern:** "Will data get lost again????"  
**Related To:** Earlier r0062 incident where 569 recordings disappeared
**Context:** User scared of data loss recurring

**Fix Required:**
- [ ] Document that new DCs are now persisted in database
- [ ] Schema migration ensures columns exist
- [ ] Backups being taken
- [ ] Test: Add DC → Redeploy → Verify DC still exists

---

### 🟡 HIGH - Recording Filters Not Mode-Aware

**Issue:** RM-specific filters applied to DC and Employee recordings  
**User Report:** "Why same filters applied to dc and employees that applied to rms like filter by issue type"  
**Problem:**
- Issue Type filter only relevant for RMs
- DCs may have different recording purposes  
- Employees likely don't have issues

**Current Filters:**
- Status (All statuses, To check, Processed, Waiting, Failed)
- Issue Types (from CONFIG.categories)
- RM (hidden for non-admin)
- Employees (hidden for non-admin)
- Date Range
- Search

**Fix Required:**
- [ ] Define what filters DC recordings should have
- [ ] Define what filters Employee recordings should have
- [ ] Modify recordings.html to show mode-specific filters
- [ ] Update filter logic in render() function

---

### 🟡 HIGH - Token Creation: DC Lookup by Name

**Issue:** Token creation should allow finding DC by name  
**User Report:** "In token creation section we should be able to find dc by name for token creation"  
**Current:** Unknown if implemented
**Expected:** When creating upload token, user can search/select DC by name

**Endpoints to Check:**
- [ ] POST /api/upload-tokens
- [ ] GET /api/dcs (for DC list in dropdown)
- [ ] Is there DC search functionality?

**Fix Required:**
- [ ] Add DC name search to token creation form
- [ ] Implement autocomplete or searchable dropdown
- [ ] Backend should validate DC exists

---

### 🟡 HIGH - API Configuration Verification

**Issue:** User asks "are all the apis configured"  
**Requires:** Check all endpoints exist and work

**Endpoints to Verify:**
- [ ] GET /api/dcs - List DCs
- [ ] POST /api/dcs - Create DC  
- [ ] PATCH /api/dcs/{id} - Update DC
- [ ] DELETE /api/dcs/{id} - Delete DC
- [ ] GET /api/allowed-numbers - List allowed numbers
- [ ] POST /api/allowed-numbers - Add number
- [ ] GET /api/upload-tokens - List tokens
- [ ] POST /api/upload-tokens - Create token with DC
- [ ] GET /api/employees - List employees
- [ ] POST /api/employees - Create employee
- [ ] GET /api/recordings - List recordings (all modes)

**Fix Required:**
- [ ] Test each endpoint
- [ ] Verify all return correct data
- [ ] Check permissions are correct

---

## ISSUES FIXED (This Session)

✅ **r0086:** Database Schema Migration
- Auto-add missing columns: mode, dc_id, employee_id
- Runs on app startup

✅ **r0087:** Robust Migration  
- Better error handling
- WAL mode enabled
- Handles concurrent access

✅ **r0088-48a1823:** Terminology Fixed
- "Data Collectors" → "District Coordinators" everywhere
- Added active field to DC creation form
- Updated docstrings and UI labels

---

## ISSUES NOT YET FIXED

❌ DC creation "failed to fetch" error - BLOCKING  
❌ DC list empty - BLOCKING  
❌ Allowed numbers empty - BLOCKING  
❌ Recording filters not mode-aware  
❌ Token creation DC lookup  
❌ Data persistence verification  

---

## NEXT SESSION TASKS

1. Deploy r0089 with terminology fixes
2. **Debug DC creation error** - must see browser console error
3. Check if DC list loads from API
4. Check if allowed numbers exist in database
5. Implement mode-aware recording filters
6. Add DC name search to token creation
7. Run full API configuration test

---

## Questions for User

When you try to create a DC, what error appears in:
- Browser Console (F12 → Console tab)?  
- Network tab (F12 → Network → find /api/dcs)?
- Admin panel alert/modal?

Can you screenshot the exact error message?
