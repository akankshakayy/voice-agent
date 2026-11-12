# User-Stated Issues (Exact)

## Your exact words:

1. **"i've already given you the allowed numbers list and dc list, why aren't they reflecting there now?"**
   - Allowed numbers list not showing in admin panel
   - DC list not showing in admin panel

2. **"that manual upload section in admin panel is fine but you already have certain DATA"**
   - Manual upload section exists and works
   - But already-provided data (DCs, allowed numbers) not being used/displayed

3. **"in the token creation section we should be able to find dc by name for token creation, is it configured?"**
   - Token creation should have DC name search/lookup
   - Unknown if configured

4. **"are all the apis configured?"**
   - Need to verify all required APIs exist and work

5. **"suppose we manually add new dcs where will that data be stored, will the data get lost again????"**
   - Concern about data persistence
   - Fear of losing data like the r0062 incident (569 recordings lost)

6. **"one more thing when i try to create new dc by admin panel there is error occurring"**
   - DC creation in admin panel throws an error
   - "failed to fetch" error observed

7. **"dc is being referred as data collectors everywhere, it is wrong it is district coordinators"**
   - Terminology issue: "Data Collectors" should be "District Coordinators"
   - Appears in multiple places

8. **"check all the end points"**
   - Verify all API endpoints are correct
   - Check terminology in API responses/docs

9. **"why are the same filters applied to dc and employees that are applied to rms like filter by issue type and all"**
   - Recording filters: same filters for RM, DC, Employee
   - Issue type filter shouldn't apply to DC/Employee recordings
   - Filters should be mode-specific

---

## STATUS OF EACH ISSUE

| # | Issue | Status |
|---|-------|--------|
| 1 | DC list not showing | ❌ NOT FIXED |
| 2 | Allowed numbers not showing | ❌ NOT FIXED |
| 3 | Data not being used | ❌ NOT FIXED |
| 4 | Token creation DC lookup | ❌ NOT FIXED |
| 5 | All APIs configured? | ❓ UNKNOWN |
| 6 | Data persistence/loss fear | ❓ UNKNOWN |
| 7 | DC creation error | ❌ NOT FIXED |
| 8 | Terminology "Data Collectors" | ⚠️ PARTIALLY FIXED (only some places) |
| 9 | Filter by mode | ❌ NOT FIXED |
| 10 | Check all endpoints | ❌ NOT DONE |

---

## WHAT I ACTUALLY FIXED

- ✅ Some "Data Collectors" → "District Coordinators" (not all)
- ✅ Added `active` field to DC form data
- ✅ Database schema migration (mode, dc_id, employee_id columns)

## WHAT I DIDN'T FIX

- ❌ DC list loading/displaying
- ❌ Allowed numbers loading/displaying  
- ❌ DC creation error
- ❌ ALL terminology (still many "Data Collectors" references)
- ❌ Filter mode-awareness
- ❌ Token creation DC lookup
- ❌ Verify all APIs configured
- ❌ Data persistence testing
