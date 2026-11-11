# Admin Panel Development Mode

## Problem Fixed

Previously, accessing `http://localhost:8000/admin` locally would redirect to the official Eko Sahayak URL (`https://indev.eko.in/rm-voice-agent`) even though the user was developing locally.

### Root Cause

- `/admin` was listed in `PUBLIC_PATHS` to bypass authentication
- However, the route handler still had `dependencies=[Depends(allow("admin"))]`
- The middleware skipped auth for PUBLIC_PATHS, so `request.state.user` was never set
- The route dependency then failed trying to access the non-existent user object

## Solution

A proper development mode bypass has been implemented:

1. **Removed** `/admin` from `PUBLIC_PATHS` (incorrect approach)
2. **Added** `/admin` to `PAGE_ROLES` with admin requirement (proper role-based access)
3. **Created** a development mode that:
   - Checks if `DEV_MODE=1` environment variable is set
   - Verifies the request originates from localhost (127.0.0.1, ::1, or localhost)
   - Sets a mock admin user (`dev@localhost`) for the request
   - Allows the request to proceed with full admin access

## Usage

### For Local Development

Start the server with `DEV_MODE=1`:

```bash
# Option 1: Set environment variable in shell
DEV_MODE=1 uvicorn app.main:app --reload --port 8000

# Option 2: Add to .env.local (create if needed)
echo "DEV_MODE=1" >> .env.local

# Option 3: Set in your IDE/terminal session
export DEV_MODE=1
uvicorn app.main:app --reload --port 8000
```

Then access the admin panel:

```
http://localhost:8000/admin
```

### Security Notes

- **Local Only**: Dev mode only works from localhost (127.0.0.1, ::1, localhost)
  - Remote IPs will still require proper authentication
  - This prevents accidental exposure on shared networks

- **Development Only**: Never use `DEV_MODE=1` on production servers
  - The production `.env` on `indev.eko.in` has `DEV_MODE=0` (or unset)
  - Production users must authenticate through the login page

- **Mock User**: The mock admin user set in dev mode:
  - Has `id: 0`, `email: "dev@localhost"`, `role: "admin"`
  - Is only used for request processing
  - Is NOT stored in the database
  - Resets with each request

## What Changed

### File: `app/main.py`

1. **Added import**: `sqlite3` (was missing, used in create_dc/update_dc endpoints)

2. **Removed** from `PUBLIC_PATHS`:
   ```python
   # Before: "/admin"  # Dev testing...
   # After: (removed)
   ```

3. **Added** to `PAGE_ROLES`:
   ```python
   "/admin": ("admin",)
   ```

4. **Added** dev mode function:
   ```python
   def is_dev_mode() -> bool:
       """Check if dev mode is enabled (checked at request time for testability)."""
       return os.environ.get("DEV_MODE", "0") == "1"
   ```

5. **Updated** middleware:
   ```python
   # Dev mode bypass: allow /admin from localhost without auth
   if is_dev_mode() and path == "/admin":
       client_host = request.client.host if request.client else None
       if client_host and client_host in ("127.0.0.1", "localhost", "::1"):
           # Set a mock admin user for dev testing
           request.state.user = {"id": 0, "email": "dev@localhost", "name": "Dev Admin", "role": "admin", "rm_id": None}
           return await call_next(request)
   ```

## Testing

Run the test suite to verify the fix:

```bash
# Test dev mode (DEV_MODE=1)
DEV_MODE=1 DEMO_DATA=1 python -c "
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)
response = client.get('/admin')
assert response.status_code == 200, f'Expected 200, got {response.status_code}'
print('✓ /admin is accessible in dev mode')
"
```

## Backward Compatibility

- **Production**: No changes to production behavior
  - Users must authenticate via login page
  - Admin panel is protected by admin role check
  
- **Existing Deployments**: 
  - No migration needed
  - Works with existing `.env` files
  - Set `DEV_MODE=1` only when needed for local development

## Related Documentation

- [Auth System](../app/auth.py) - User roles and authentication
- [Main App](../app/main.py) - FastAPI endpoints and middleware
