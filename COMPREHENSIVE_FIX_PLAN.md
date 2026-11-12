# COMPREHENSIVE FIX FOR ALL 9 ISSUES

## Root Cause Analysis
The /api/dcs endpoint is failing with "failed to fetch". This blocks everything.

## Fixes to Apply in Parallel

### FIX 1: Verify /api/dcs endpoint works
- Check endpoint returns data
- Verify authentication
- Check CORS headers

### FIX 2: Fix ALL "Data Collectors" → "District Coordinators"
- admin.html: ALL occurrences
- app/main.py: ALL docstrings  
- token creation section

### FIX 3: Recording Filters by Mode
- Remove "Issue Type" filter for DC/Employee
- Add mode-specific filter logic

### FIX 4: Load DC List Properly
- GET /api/dcs returns data
- Admin UI renders list

### FIX 5: Load Allowed Numbers with Restrictions
- DCs: CSP numbers + SBI officials only
- Employees: No restrictions (anyone)

### FIX 6: Token Creation DC Lookup
- Add DC name search/autocomplete
- Backend validates DC exists

### FIX 7: Verify All APIs Configured
- /api/dcs (GET, POST, PATCH, DELETE)
- /api/allowed-numbers (GET, POST)
- /api/upload-tokens (GET, POST with DC)
- /api/employees (GET, POST)

### FIX 8: Guarantee Data Persistence
- New DCs saved to database
- Test: Add DC → Redeploy → Verify exists
- Document backup strategy

### FIX 9: Complete DC Terminology
- All "Data Collector" → "District Coordinator"
- Update error messages
- Update docstrings
- Update UI labels

## Current Status
- r0090 deployed but /api/dcs still failing
- Issue likely in app startup or endpoint
- Need to check server logs
