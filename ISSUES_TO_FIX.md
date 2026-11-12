# ALL ISSUES YOU STATED - EXACT LIST

## Issue #1: Recording Filters
**"Why are the same filters applied to dc and employees that are applied to rms like filter by issue type and all"**
- RM recordings have: Status, Issue Type, RM, Employee, Date, Search
- DC recordings should NOT have "Issue Type" filter
- Employee recordings should NOT have "Issue Type" filter
- **CURRENT STATE:** Same filters for all modes
- **REQUIRED:** Mode-specific filters

---

## Issue #2: DC List Not Showing
**"I've already given you the allowed numbers list and dc list, why aren't they reflecting there now?"**
- You provided DC list
- DC list not appearing in admin panel
- In your screenshot: Admin panel shows "Error: Failed to fetch"
- Network tab shows multiple /api/dcs requests FAILING
- **CURRENT STATE:** DC list empty, API failing
- **REQUIRED:** Fix /api/dcs endpoint so DC list displays

---

## Issue #3: Allowed Numbers List Not Showing  
**"[Same question] why aren't they reflecting there now?"**
- You provided allowed numbers list
- Allowed numbers not appearing in admin panel
- **CURRENT STATE:** Empty
- **REQUIRED:** Load and display allowed numbers

---

## Issue #4: Data Not Being Used
**"That manual upload section in admin panel is fine but you already have certain DATA"**
- Manual upload section exists and works
- But your provided data (DCs, allowed numbers) should be displayed
- Currently not being displayed/used
- **CURRENT STATE:** Data ignored
- **REQUIRED:** Display and use the data you provided

---

## Issue #5: Token Creation DC Lookup
**"In the token creation section we should be able to find dc by name for token creation, is it configured?"**
- Token creation should have DC name search
- Unknown if implemented
- **CURRENT STATE:** Unknown
- **REQUIRED:** Verify if configured, if not implement DC name search

---

## Issue #6: API Configuration Verification
**"Are all the apis configured?"**
- Need to verify ALL required APIs exist and work
- **CURRENT STATE:** /api/dcs failing (proven in screenshot)
- **REQUIRED:** Check all API endpoints

---

## Issue #7: Data Persistence / Data Loss Fear
**"Suppose we manually add new dcs where will that data be stored, will the data get lost again????"**
- User fear: data loss like r0062 incident (569 recordings lost)
- Where are new DCs stored?
- Will deployments cause data loss?
- **CURRENT STATE:** Unknown
- **REQUIRED:** Guarantee data persistence, test it

---

## Issue #8: DC Creation Error
**"One more thing when i try to create new dc by admin panel there is error occurring"**
- User tries to create DC
- Form modal appears with fields: Name, Phone, Email, Region, Status
- User clicks "Add"
- **ERROR:** "Failed to fetch" appears
- Network tab shows: Multiple /api/dcs requests with status "failed..."
- **ROOT CAUSE:** POST /api/dcs endpoint is failing/not responding
- **CURRENT STATE:** DC creation broken
- **REQUIRED:** Fix /api/dcs POST endpoint

---

## Issue #9: Terminology "Data Collectors" vs "District Coordinators"
**"DC is being referred as data collectors everywhere, it is wrong it is district coordinators. Check all the end points"**
- Admin panel still shows "Data Collectors" (proven in screenshot)
- Should be "District Coordinators" everywhere
- Check in: UI labels, API comments, error messages, all endpoints
- **CURRENT STATE:** Still says "Data Collectors" in many places
- **REQUIRED:** Replace ALL occurrences

---

## SUMMARY TABLE

| # | Issue | Status | Priority |
|---|-------|--------|----------|
| 1 | Mode-specific recording filters | ❌ NOT FIXED | HIGH |
| 2 | DC list not showing | ❌ NOT FIXED | **CRITICAL** |
| 3 | Allowed numbers not showing | ❌ NOT FIXED | **CRITICAL** |
| 4 | Data not being used | ❌ NOT FIXED | HIGH |
| 5 | Token creation DC lookup | ❓ UNKNOWN | MEDIUM |
| 6 | API configuration check | ❌ NOT DONE | HIGH |
| 7 | Data persistence guarantee | ❓ UNKNOWN | MEDIUM |
| 8 | DC creation error | ❌ NOT FIXED | **CRITICAL** |
| 9 | "Data Collectors" terminology | ❌ NOT FIXED | HIGH |

---

## BLOCKING ISSUES (Must Fix First)

1. **#8 - DC Creation Error: /api/dcs POST failing**
   - Fix the POST /api/dcs endpoint
   - Currently all fetch requests to this endpoint are failing
   
2. **#2 - DC List Not Loading**
   - Fix the GET /api/dcs endpoint  
   - Network tab shows all requests failing
   
3. **#3 - Allowed Numbers Not Loading**
   - Fix the GET /api/allowed-numbers endpoint
   - Similar issue to DC list

---

## Your Screenshot Evidence

Shows:
- ✅ Form modal working (can fill in fields)
- ❌ "Error: Failed to fetch" message
- ❌ Network tab showing multiple failed /api/dcs requests
- ❌ Page title still says "Data Collectors" (not fixed)
- ❌ Modal title says "Add Data Collector" (not fixed)

This proves the /api/dcs endpoint is broken.
