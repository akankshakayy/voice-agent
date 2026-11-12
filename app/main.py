"""FastAPI app: agent API + dashboards.

Run:  uvicorn app.main:app --reload --port 8000
"""
import io
import json
import logging
import os
import re
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from urllib.parse import quote, urlparse

# Environment variables are loaded by the deployment system (eko-deploy secrets)
# and from Docker environment. Local development uses .env files via python-dotenv,
# but production relies on deployment-managed environment variables.

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from . import agent, auth, autogmap, bootstrap, bulk_load, db, google_auth, integrations, mailer, metrics, misheard, prachi_sync, recordings, report, stt, telemetry, tts  # noqa: E402
from .logging_config import setup_logging  # noqa: E402
from .seed import seed_if_demo  # noqa: E402
from .taxonomy import CATEGORIES, SLOT_LABELS, STT_CONFIDENCE_MIN, INTENT_CONFIDENCE_MIN, MAX_MISUNDERSTOOD  # noqa

STATIC = os.path.join(os.path.dirname(__file__), "..", "static")
log = setup_logging("eko")


def _reap_stale_calls(stop: threading.Event):
    """Every minute, close calls nobody has touched for CALL_IDLE_TIMEOUT_MIN minutes."""
    while not stop.is_set():
        try:
            closed = agent.close_stale_calls()
            if closed:
                log.warning("Closed %d idle call(s): %s", len(closed), closed)
        except Exception:
            log.exception("Idle-call cleanup failed")
        stop.wait(60)


@asynccontextmanager
async def lifespan(_app):
    # Auto-migrate database from /tmp if needed
    try:
        bootstrap.migrate_db_if_needed()
    except Exception as e:
        log.error("Bootstrap failed: %s", e)

    # Initialize AutoGMap upload queue for rate-limited uploads (max 2 req/sec)
    autogmap.init_upload_queue()

    stop = threading.Event()
    threading.Thread(target=_reap_stale_calls, args=(stop,), daemon=True, name="call-reaper").start()
    threading.Thread(target=recordings.processing_loop, args=(stop,), daemon=True, name="recordings").start()
    threading.Thread(target=integrations.delivery_loop, args=(stop,), daemon=True, name="webhooks").start()
    threading.Thread(target=autogmap.sync_loop, args=(stop,), daemon=True, name="autogmap-sync").start()
    threading.Thread(target=autogmap.upload_queue_worker, args=(stop,), daemon=True, name="autogmap-upload-worker").start()
    threading.Thread(target=prachi_sync.sync_loop, args=(stop,), daemon=True, name="prachi-sync").start()
    yield
    stop.set()
    integrations.wake()
    recordings.wake()


app = FastAPI(title="Eko RM Voice Agent", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _writable_tmp():
    """Large uploads are spooled to a temp file. In a container with a read-only system disk, put those next to
    the database (the platform's writable /data) instead of /tmp."""
    import tempfile
    try:
        with tempfile.TemporaryFile():
            return
    except OSError:
        tmp = os.path.join(os.path.dirname(os.path.abspath(db.DB_PATH)), "tmp")
        os.makedirs(tmp, exist_ok=True)
        tempfile.tempdir = tmp


_writable_tmp()
seed_if_demo()

# ------------------------------------------------------------------ auth
PUBLIC_PATHS = {"/login", "/signup", "/forgot", "/reset", "/verify-email", "/favicon.ico", "/api/auth/login",
                 "/status", "/healthz", "/health", "/api/health", "/ping",  # Health check endpoints - no auth required
                "/api/auth/signup", "/api/auth/forgot", "/api/auth/reset", "/api/auth/verify", "/api/auth/options",
                "/api/auth/verify/send", "/api/auth/google/start", "/api/auth/google/callback", "/healthz",
                "/api/recordings/cleanup"}
PUBLIC_PREFIXES = ("/static/",)  # All admin APIs require auth via @allow("admin") decorator
DEVICE_PATHS = {"/api/uploader/ping", "/api/uploader/recordings"}   # the uploader app: upload token, not a login
STAFF = ("admin", "ops")                       # full access to calls, dashboards and metrics
PAGE_ROLES = {"/": ("admin", "ops", "rm"), "/call": STAFF, "/ops": STAFF, "/harness": STAFF, "/rm": ("admin", "ops", "rm"),
              "/users": ("admin",), "/recordings": ("admin", "ops", "rm"), "/account": ("admin", "ops", "rm", "pending"),
              "/metrics-trends": STAFF, "/admin": ("admin",), "/monitor": STAFF}  # Admin panel - admin role required
# All a not-yet-approved account can reach: its own account settings
PENDING_OK = {"/pending", "/account", "/api/auth/me", "/api/auth/logout", "/api/auth/logout-all", "/api/auth/password",
              "/api/auth/email", "/api/auth/verify/resend", "/api/auth/activity"}
TRUST_PROXY = os.environ.get("TRUST_PROXY", "0") == "1"   # behind nginx: take the client address from X-Forwarded-For

def is_dev_mode() -> bool:
    """Check if dev mode is enabled (checked at request time for testability)."""
    return os.environ.get("DEV_MODE", "0") == "1"
# The login cookie is sent only to Sahayak's own path. On a shared host (indev.eko.in runs other people's apps too)
# a cookie for "/" would reach every app there. Taken from APP_BASE_URL (".../rm-voice-agent"), or COOKIE_PATH.
def cookie_path() -> str:
    return (os.environ.get("COOKIE_PATH") or urlparse(os.environ.get("APP_BASE_URL", "")).path or "/").rstrip("/") or "/"


def client_ip(request: Request) -> str | None:
    if TRUST_PROXY:
        fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if fwd:
            return fwd[:64]
    return request.client.host if request.client else None


def is_https(request: Request) -> bool:
    """Opened over HTTPS (directly, or through nginx with TRUST_PROXY): the sign-in cookie is then sent only
    over HTTPS, even if COOKIE_SECURE was left at 0."""
    if TRUST_PROXY and request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https":
        return True
    return request.url.scheme == "https"




# Redirects and page links are relative ("login", "static/..."), so Sahayak works at the top of an address
# (localhost:8000) and under a prefix (https://indev.eko.in/rm-voice-agent) alike. Every page is one level deep.
def route_path(request: Request) -> str:
    """The path without the address prefix. Behind the deploy platform uvicorn runs with --root-path /rm-voice-agent
    and the request path then starts with that prefix; the access rules below are written without it."""
    path, root = request.url.path, (request.scope.get("root_path") or "").rstrip("/")
    if root and (path == root or path.startswith(root + "/")):
        return path[len(root):] or "/"
    return path


@app.middleware("http")
async def require_login(request: Request, call_next):
    """Every page and API needs a signed-in user, except the login/signup pages and static files.
    Pages are also checked against the user's role here; API routes check roles with `allow(...)`."""
    path = route_path(request)

    # Dev mode bypass: allow requests from localhost without auth
    if is_dev_mode():
        client_host = request.client.host if request.client else None
        if client_host and client_host in ("127.0.0.1", "localhost", "::1"):
            # Set a mock admin user for dev testing
            request.state.user = {"id": 0, "email": "dev@localhost", "name": "Dev Admin", "role": "admin", "rm_id": None}
            return await call_next(request)

    if path in PUBLIC_PATHS or path in DEVICE_PATHS or path.startswith(PUBLIC_PREFIXES):
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer ") and (path.startswith("/api/") or path == "/openapi.json"):
        # Another system using a service API key (app/integrations.py): acts as Ops, no cookie involved
        service = integrations.service_for_key(header[7:].strip())
        if not service:
            return JSONResponse({"detail": "API key is wrong or revoked"}, status_code=401)
        request.state.user = service
        return await call_next(request)
    user = auth.user_for_token(request.cookies.get(auth.COOKIE))
    if not user:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Not signed in"}, status_code=401)
        nxt = path.lstrip("/") if path in PAGE_ROLES and path != "/" else "./"
        return RedirectResponse(f"login?next={nxt}", status_code=303)
    role = user.get("role") or "pending"
    if role == "pending" and path not in PENDING_OK:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Your account has no access. Ask an admin."}, status_code=403)
        return RedirectResponse("pending", status_code=303)
    if role != "pending" and path == "/pending":
        return RedirectResponse("./", status_code=303)
    if path in PAGE_ROLES and role not in PAGE_ROLES[path]:
        return RedirectResponse("./?denied=1", status_code=303)
    request.state.user = user
    return await call_next(request)


# Added after require_login, so it runs first and also covers its redirects and 401s
@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    # Reset and verification links carry a token in the address; never pass it on to another site
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Permissions-Policy", "camera=(), geolocation=()")
    if route_path(request).startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    if auth.COOKIE_SECURE or is_https(request):
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return resp


def allow(*roles):
    """Route dependency: only these roles may call the endpoint."""
    def check(request: Request):
        if request.state.user.get("role") not in roles:
            raise HTTPException(403, "You don't have access to this")
        return request.state.user
    return check


def rm_scope(request: Request, rm_id: int | None) -> int | None:
    """RMs only ever see their own data, whatever rm_id they ask for."""
    u = request.state.user
    return u["rm_id"] if u.get("role") == "rm" else rm_id


def check_rm_owns(request: Request, rm_id: int | None, what: str):
    u = request.state.user
    if u.get("role") == "rm" and rm_id != u["rm_id"]:
        raise HTTPException(404, f"{what} not found")   # 404, not 403: don't reveal other RMs' data exists


class SignupBody(BaseModel):
    email: str
    password: str
    name: str
    rm_id: int | None = None


class LoginBody(BaseModel):
    email: str
    password: str


class EmailBody(BaseModel):
    email: str


class ResetBody(BaseModel):
    token: str
    password: str


class TokenBody(BaseModel):
    token: str


class PasswordBody(BaseModel):
    current: str
    new: str


class EmailChangeBody(BaseModel):
    email: str
    password: str


def _signed_in(user: dict, request: Request) -> JSONResponse:
    resp = JSONResponse(auth.public_user(user))
    auth.end_session(request.cookies.get(auth.COOKIE))   # signing in again replaces this browser's old session
    token = auth.create_session(user["id"], client_ip(request), request.headers.get("user-agent"))
    _set_session_cookie(resp, token, request)
    return resp


def _set_session_cookie(resp, token: str, request: Request):
    resp.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400,
                    httponly=True, samesite="lax", secure=auth.COOKIE_SECURE or is_https(request), path=cookie_path())


def _clear_session_cookie(resp):
    resp.delete_cookie(auth.COOKIE, path=cookie_path())
    if cookie_path() != "/":
        resp.delete_cookie(auth.COOKIE, path="/")          # one set by an older version, for the whole host


def _auth_call(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except auth.AuthError as e:
        raise HTTPException(e.status, str(e))


@app.post("/api/auth/signup")
def signup(body: SignupBody, request: Request):
    u = _auth_call(auth.signup, body.email, body.password, body.name, body.rm_id, client_ip(request))
    if u.get("must_verify"):
        # Not signed in yet: the account works once the link in the email is opened
        return {"verify": True, "email": u["email"]}
    return _signed_in(u, request)


@app.post("/api/auth/verify/send")
def send_confirmation_again(body: LoginBody, request: Request):
    return {"sent": _auth_call(auth.resend_confirmation, body.email, body.password, client_ip(request))}


@app.get("/api/auth/google/start")
def google_start(request: Request, next: str = "./"):
    """Off to Google's sign-in page; it comes back to /api/auth/google/callback."""
    if not google_auth.configured():
        return RedirectResponse("../../../login?error=" + quote("Sign in with Google isn't set up on this server."), 303)
    url, flow = google_auth.start(next if re.fullmatch(r"(\./|[a-z][a-z-]*|/(?!/)[\w/.-]*)", next or "") else "./",
                                  auth.allowed_domains())
    resp = RedirectResponse(url, 303)
    resp.set_cookie(google_auth.COOKIE, flow, max_age=google_auth.FLOW_SECONDS, httponly=True, samesite="lax",
                    secure=auth.COOKIE_SECURE or is_https(request), path=cookie_path())
    return resp


@app.get("/api/auth/google/callback")
def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    back = "../../../"                                  # from /api/auth/google/callback to the site's root
    try:
        if error:
            raise google_auth.GoogleError("Google sign-in was cancelled." if error == "access_denied" else
                                          f"Google sign-in failed ({error[:40]}).")
        who = google_auth.finish(code, state, request.cookies.get(google_auth.COOKIE))
        u = auth.google_sign_in(who["email"], who["name"], who["sub"], client_ip(request))
    except (google_auth.GoogleError, auth.AuthError) as e:
        resp = RedirectResponse(back + "login?error=" + quote(str(e)), 303)
    else:
        nxt = who["next"]                               # checked at start: a page name, ./ or a same-site path
        resp = RedirectResponse(nxt if nxt.startswith("/") else back + nxt, 303)
        auth.end_session(request.cookies.get(auth.COOKIE))
        _set_session_cookie(resp, auth.create_session(u["id"], client_ip(request), request.headers.get("user-agent")),
                            request)
    resp.delete_cookie(google_auth.COOKIE, path=cookie_path())
    return resp


@app.post("/api/auth/login")
def login(body: LoginBody, request: Request):
    return _signed_in(_auth_call(auth.login, body.email, body.password, client_ip(request)), request)


@app.get("/healthz")
@app.get("/status", tags=["health"])
def healthz(request: Request):
    """For the deploy platform's health check: the app is up and its database answers. No login, no data."""
    # Bypass auth for health check
    db.q("SELECT 1")
    return {"ok": True, "status": "healthy"}


@app.get("/api/auth/options")
def auth_options():
    """What the sign-in pages can offer: email links only work once SMTP is set up."""
    return {"email": mailer.configured(), "min_password": auth.MIN_PASSWORD, "domains": auth.allowed_domains(),
            "google": google_auth.configured(), "password_signup": auth.password_signup_open()}


@app.post("/api/auth/forgot")
def forgot(body: EmailBody, request: Request):
    auth.request_password_reset(body.email, client_ip(request))
    # The same reply whether or not the account exists, so this can't be used to find out who has one
    return {"ok": True}


@app.post("/api/auth/reset")
def reset(body: ResetBody, request: Request):
    _auth_call(auth.reset_password, body.token, body.password, client_ip(request))
    resp = JSONResponse({"ok": True})
    _clear_session_cookie(resp)
    return resp


@app.post("/api/auth/verify")
def verify(body: TokenBody, request: Request):
    return auth.public_user(_auth_call(auth.verify_email, body.token, client_ip(request)))


@app.post("/api/auth/verify/resend")
def resend_verification(request: Request):
    u = request.state.user
    if u.get("email_verified_at"):
        return {"sent": False, "verified": True}
    return {"sent": auth.send_verification(u)}


@app.post("/api/auth/password")
def change_password(body: PasswordBody, request: Request):
    _auth_call(auth.change_password, request.state.user, body.current, body.new, request.cookies.get(auth.COOKIE),
               client_ip(request))
    return {"ok": True}


@app.post("/api/auth/email")
def change_email(body: EmailChangeBody, request: Request):
    return {"sent": _auth_call(auth.start_email_change, request.state.user, body.email, body.password,
                               client_ip(request))}


@app.post("/api/auth/logout-all")
def logout_all(request: Request):
    auth.end_all_sessions(request.state.user, client_ip(request))
    resp = JSONResponse({"ok": True})
    _clear_session_cookie(resp)
    return resp


@app.get("/api/auth/activity")
def my_activity(request: Request):
    u = request.state.user
    return {"events": auth.activity(u["id"]), "sessions": auth.session_count(u["id"]),
            "password_changed_at": u.get("password_changed_at")}


@app.post("/api/auth/logout")
def logout(request: Request):
    auth.end_session(request.cookies.get(auth.COOKIE))
    resp = JSONResponse({"ok": True})
    _clear_session_cookie(resp)
    return resp


@app.get("/api/auth/me")
def me(request: Request):
    return auth.public_user(request.state.user)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(os.path.join(STATIC, "favicon.ico"), media_type="image/x-icon")


@app.get("/login")
def login_page():
    return FileResponse(os.path.join(STATIC, "login.html"))


@app.get("/signup")
@app.get("/forgot")
@app.get("/reset")
@app.get("/verify-email")
def signup_page():
    return FileResponse(os.path.join(STATIC, "login.html"))


@app.get("/account")
def account_page():
    return FileResponse(os.path.join(STATIC, "account.html"))


@app.get("/pending")
def pending_page():
    return FileResponse(os.path.join(STATIC, "pending.html"))


@app.get("/users")
def users_page():
    return FileResponse(os.path.join(STATIC, "users.html"))


# ------------------------------------------------------------------ user management (admin)
class RoleBody(BaseModel):
    role: str
    rm_id: int | None = None


@app.get("/api/users", dependencies=[Depends(allow("admin"))])
def list_users():
    return [auth.public_user(u) for u in db.q("SELECT * FROM users ORDER BY role='pending' DESC, created_at")]


@app.patch("/api/users/{user_id}")
def change_role(user_id: int, body: RoleBody, actor=Depends(allow("admin"))):
    try:
        return auth.public_user(auth.set_role(actor, user_id, body.role, body.rm_id))
    except auth.AuthError as e:
        raise HTTPException(e.status, str(e))


@app.post("/api/users/{user_id}/reset-link")
def user_reset_link(user_id: int, actor=Depends(allow("admin"))):
    """One-time password reset link for a user, for when email isn't set up. Shown to the admin only once."""
    return {"path": f"reset?token={_auth_call(auth.admin_reset_link, actor, user_id)}",
            "minutes": auth.RESET_MINUTES}


@app.delete("/api/users/{user_id}")
def remove_user(user_id: int, actor=Depends(allow("admin"))):
    try:
        auth.delete_user(actor, user_id)
    except auth.AuthError as e:
        raise HTTPException(e.status, str(e))
    return {"ok": True}


@app.get("/api/admin/restore", dependencies=[Depends(allow("admin"))])
def restore_allowed():
    """Whether this site can still take another Sahayak's data (only while it's empty: app/backup.py)."""
    from . import backup
    return {"allowed": backup.site_is_empty()}


@app.post("/api/admin/restore", dependencies=[Depends(allow("admin"))])
def restore_backup(backup_file: UploadFile = File(...)):
    """Replace this (empty) site's data with a backup made by `python -m app.backup make` on another Sahayak."""
    from . import backup
    try:
        return backup.restore(backup_file.file)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/call")
def call_page():
    return FileResponse(os.path.join(STATIC, "call.html"))


@app.get("/rm")
def rm_page():
    return FileResponse(os.path.join(STATIC, "rm.html"))


@app.get("/ops")
def ops_page():
    return FileResponse(os.path.join(STATIC, "ops.html"))


@app.get("/metrics-trends", dependencies=[Depends(allow(*STAFF))])
def metrics_trends_page():
    return FileResponse(os.path.join(STATIC, "metrics-trends.html"))


@app.get("/recordings")
def recordings_page():
    return FileResponse(os.path.join(STATIC, "recordings.html"))


@app.get("/harness", dependencies=[Depends(allow(*STAFF))])
def harness_page():
    return FileResponse(os.path.join(STATIC, "harness.html"))


@app.get("/admin", dependencies=[Depends(allow("admin"))])
def admin_page():
    """Admin panel: Manage District Coordinators, Employees, and Allowed Numbers."""
    return FileResponse(os.path.join(STATIC, "admin.html"))


@app.get("/monitor", dependencies=[Depends(allow(*STAFF))])
def monitor_page():
    """Monitoring dashboard: Real-time system health, sync status, and alerts."""
    return FileResponse(os.path.join(STATIC, "monitor.html"))


# ------------------------------------------------------------------ bulk load
@app.post("/api/bulk-load/dcs", dependencies=[Depends(allow("admin"))])
async def bulk_load_dcs_endpoint(file: UploadFile = File(...), actor=Depends(allow("admin"))):
    """Bulk load District Coordinators from Excel file."""
    try:
        # Validate file type
        if not file.filename.endswith(('.xlsx', '.xls')):
            raise HTTPException(400, "File must be .xlsx or .xls")

        # Read file content
        content = await file.read()
        if not content:
            raise HTTPException(400, "File is empty")

        if len(content) > 5 * 1024 * 1024:  # 5 MB limit
            raise HTTPException(413, "File too large (max 5 MB)")

        # Perform bulk load
        result = bulk_load.bulk_load_dcs(content, actor.get("email", "unknown"))
        return result

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Bulk load DCs failed: {e}", exc_info=True)
        raise HTTPException(500, f"Bulk load failed: {str(e)}")


@app.post("/api/bulk-load/employees", dependencies=[Depends(allow("admin"))])
async def bulk_load_employees_endpoint(file: UploadFile = File(...), actor=Depends(allow("admin"))):
    """Bulk load Employees from Excel file."""
    try:
        # Validate file type
        if not file.filename.endswith(('.xlsx', '.xls')):
            raise HTTPException(400, "File must be .xlsx or .xls")

        # Read file content
        content = await file.read()
        if not content:
            raise HTTPException(400, "File is empty")

        if len(content) > 5 * 1024 * 1024:  # 5 MB limit
            raise HTTPException(413, "File too large (max 5 MB)")

        # Perform bulk load
        result = bulk_load.bulk_load_employees(content, actor.get("email", "unknown"))
        return result

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Bulk load Employees failed: {e}", exc_info=True)
        raise HTTPException(500, f"Bulk load failed: {str(e)}")


# ------------------------------------------------------------------ reference data
@app.get("/api/config", dependencies=[Depends(allow("admin", "ops", "rm"))])
def config():
    from .llm_engine import label_for, model_for
    mode = agent.engine_mode()
    return {"engine": mode, "engine_label": label_for(mode), "model": model_for(mode), "stt": stt.available(),
            "thresholds": {"stt_confidence_min": STT_CONFIDENCE_MIN, "intent_confidence_min": INTENT_CONFIDENCE_MIN,
                           "max_misunderstood": MAX_MISUNDERSTOOD},
            "categories": {k: {"label": v["label"], "priority": v["priority"], "slots": v["slots"]}
                           for k, v in CATEGORIES.items()},
            "slot_labels": SLOT_LABELS}


@app.get("/api/rms", dependencies=[Depends(allow("admin", "ops", "rm"))])
def rms():
    return db.q("SELECT * FROM rms ORDER BY id")


@app.get("/api/csps", dependencies=[Depends(allow(*STAFF))])
def csps(rm_id: int | None = None):
    if rm_id:
        return db.q("SELECT * FROM csps WHERE rm_id=? ORDER BY name", (rm_id,))
    return db.q("SELECT c.*, r.name rm_name FROM csps c JOIN rms r ON r.id=c.rm_id ORDER BY c.rm_id, c.name")


@app.get("/api/console/csps", dependencies=[Depends(allow(*STAFF))])
def console_csps(rm_id: int | None = None, q: str = "", limit: int = 40):
    """The call console's CSP picker for one RM (or all): test CSPs, which can be called, and real CSPs from the
    knowledge base, which are view only while real calls are off. Search matches the CSP code or name."""
    where, args = ["c.source IN ({})"], []
    if rm_id:
        where.append("c.rm_id=?")
        args.append(rm_id)
    q = q.strip()[:60]
    if q:
        like = "%" + q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(lower(c.csp_code) LIKE ? ESCAPE '\\' OR lower(c.name) LIKE ? ESCAPE '\\')")
        args += [like, like]
    cond = " AND ".join(where)
    limit = max(1, min(limit, 200))
    month = time.strftime("%Y-%m")

    def part(sources):
        marks = ",".join("?" * len(sources))
        rows = db.q(f"""SELECT c.id, c.csp_code, c.name, c.shop_name, c.district, c.state, c.category, c.active,
                               c.source, c.rm_id, r.name rm_name, m.slab
                        FROM csps c LEFT JOIN rms r ON r.id=c.rm_id
                        LEFT JOIN csp_monthly m ON m.csp_id=c.id AND m.month=?
                        WHERE {cond.format(marks)} ORDER BY c.active DESC, c.name LIMIT ?""",
                    (month, *sources, *args, limit))
        total = db.q(f"SELECT COUNT(*) n FROM csps c WHERE {cond.format(marks)}", (*sources, *args), one=True)["n"]
        return rows, total

    test, n_test = part(("synthetic", "demo"))
    real, n_real = part(("kb",))
    return {"test": test, "test_total": n_test, "real": real, "real_total": n_real,
            "real_calls": agent.real_calls_on()}


# ------------------------------------------------------------------ calls
class StartCall(BaseModel):
    direction: str = "inbound"
    phone: str | None = None
    purpose: str = "support"
    lang: str = "hi"   # hi | en | ask (agent asks the caller to pick)
    csp_id: int | None = None   # the caller picked from the console's CSP list


class Turn(BaseModel):
    text: str
    stt_confidence: float | None = None


@app.post("/api/calls", dependencies=[Depends(allow(*STAFF))])
def start_call(body: StartCall):
    try:
        return agent.start_call(body.direction, body.phone, body.purpose, lang=body.lang, csp_id=body.csp_id)
    except agent.RealCspBlocked as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/calls/{call_id}/turn", dependencies=[Depends(allow(*STAFF))])
def turn(call_id: int, body: Turn):
    try:
        return agent.handle_turn(call_id, body.text, body.stt_confidence)
    except KeyError:
        raise HTTPException(404, "call not found")


@app.post("/api/calls/{call_id}/hangup", dependencies=[Depends(allow(*STAFF))])
def hangup(call_id: int):
    try:
        return agent.hangup(call_id)
    except KeyError:
        raise HTTPException(404, "call not found")


@app.get("/api/calls")
def list_calls(limit: int = Query(100)):
    """List recent calls for the harness UI (any authenticated user)."""
    return db.q("SELECT id, csp_id, rm_id, (SELECT name FROM csps WHERE id=calls.csp_id) csp_name, started_at, ended_at "
                "FROM calls ORDER BY started_at DESC LIMIT ?", (limit,))


@app.get("/api/calls/{call_id}", dependencies=[Depends(allow("admin", "ops", "rm"))])
def get_call(call_id: int, request: Request):
    try:
        c = agent.public_call(call_id)
    except Exception:
        raise HTTPException(404, "call not found")
    check_rm_owns(request, c["rm_id"], "call")
    c["turns"] = db.q("SELECT role,text,ts,stt_confidence,latency_ms,engine,intent,intent_confidence,error "
                      "FROM turns WHERE call_id=? ORDER BY id", (call_id,))
    return c


# ------------------------------------------------------------------ tickets
@app.get("/api/tickets", dependencies=[Depends(allow("admin", "ops", "rm"))])
def tickets(request: Request, rm_id: int | None = None, status: str | None = None, escalated: int | None = None,
            limit: int = 200):
    rm_id = rm_scope(request, rm_id)
    where, args = ["1=1"], []
    if rm_id:
        where.append("t.rm_id=?"); args.append(rm_id)
    if status:
        where.append("t.status IN (%s)" % ",".join("?" * len(status.split(",")))); args += status.split(",")
    if escalated is not None:
        where.append("t.escalated=?"); args.append(escalated)
    rows = db.q(f"""SELECT t.*, s.name csp_name, s.csp_code, s.shop_name, s.phone csp_phone, s.district,
                    c.duration_sec, c.sentiment, c.direction
                    FROM tickets t LEFT JOIN csps s ON s.id=t.csp_id LEFT JOIN calls c ON c.id=t.call_id
                    WHERE {' AND '.join(where)} ORDER BY t.created_at DESC LIMIT ?""", (*args, limit))
    for r in rows:
        r["details"] = json.loads(r.pop("details_json") or "{}")
    return rows


@app.get("/api/tickets/{ticket_id}", dependencies=[Depends(allow("admin", "ops", "rm"))])
def ticket(ticket_id: int, request: Request):
    t = db.q("""SELECT t.*, s.name csp_name, s.csp_code, s.shop_name, s.phone csp_phone, s.district, r.name rm_name
                FROM tickets t LEFT JOIN csps s ON s.id=t.csp_id LEFT JOIN rms r ON r.id=t.rm_id WHERE t.id=?""",
             (ticket_id,), one=True)
    if not t:
        raise HTTPException(404, "ticket not found")
    check_rm_owns(request, t["rm_id"], "ticket")
    t["details"] = json.loads(t.pop("details_json") or "{}")
    t["events"] = db.q("SELECT * FROM ticket_events WHERE ticket_id=? ORDER BY ts", (ticket_id,))
    t["transcript"] = db.q("SELECT role,text,ts,stt_confidence FROM turns WHERE call_id=? ORDER BY id", (t["call_id"],))
    t["why"] = telemetry.explain_ticket(t)   # who decided, from what, and which details came from unclear speech
    return t


class TicketUpdate(BaseModel):
    status: str | None = None
    rm_category: str | None = None
    note: str | None = None
    summary: str | None = None             # the RM's fix of the agent's summary (kept as a correction)
    details: dict[str, str] | None = None   # the RM's fix of the details the agent captured


@app.patch("/api/tickets/{ticket_id}", dependencies=[Depends(allow("admin", "ops", "rm"))])
def patch_ticket(ticket_id: int, body: TicketUpdate, request: Request):
    if body.status and body.status not in ("open", "in_progress", "resolved", "closed"):
        raise HTTPException(400, "bad status")
    owner = db.q("SELECT rm_id FROM tickets WHERE id=?", (ticket_id,), one=True)
    if not owner:
        raise HTTPException(404, "ticket not found")
    check_rm_owns(request, owner["rm_id"], "ticket")
    try:
        actor = request.state.user["name"]   # audit trail shows who changed the ticket
        return agent.update_ticket(ticket_id, actor, body.status, body.rm_category, body.note,
                                   summary=body.summary, details=body.details)
    except KeyError:
        raise HTTPException(404, "ticket not found")


# ------------------------------------------------------------------ metrics
@app.get("/api/metrics/agent", dependencies=[Depends(allow("admin", "ops", "rm"))])
def m_agent(request: Request, hours: float = 168, rm_id: int | None = None):
    return metrics.agent_metrics(hours, rm_scope(request, rm_id))


@app.get("/api/metrics/model", dependencies=[Depends(allow(*STAFF))])
def m_model(hours: float = 168):
    return metrics.model_metrics(hours)


@app.get("/api/metrics/feedback", dependencies=[Depends(allow(*STAFF))])
def m_feedback(hours: float = 168):
    return metrics.feedback_metrics(hours)


@app.get("/api/metrics/trends", dependencies=[Depends(allow(*STAFF))])
def m_trends(request: Request, hours: float = 168, compare_to: str = "previous",
             rm_id: int | None = None, csp_id: int | None = None, intent: str | None = None,
             prompt_version: str | None = None):
    """Metrics comparison: current period vs previous/baseline with deltas."""
    return metrics.metrics_trends(hours, compare_to, rm_scope(request, rm_id), csp_id, intent, prompt_version)


@app.get("/api/calls/{call_id}/traces", dependencies=[Depends(allow(*STAFF))])
def call_traces(call_id: int):
    """What the engine saw and returned on each turn (prompt, context, raw output)."""
    return telemetry.traces_for_call(call_id)


@app.get("/api/calls/{call_id}/evaluator", dependencies=[Depends(allow(*STAFF))])
def call_evaluator(call_id: int):
    """Phase 1: Evaluator scores for all traces in a call (tier breakdown, quality, etc.)."""
    from . import evaluator
    return {
        "scores": evaluator.scores_for_call(call_id),
        "tier_health": evaluator.tier_health(call_id),
    }


class AnalyzeQuestion(BaseModel):
    question: str


@app.post("/api/calls/{call_id}/analyze", dependencies=[Depends(allow(*STAFF))])
def analyze_call(call_id: int, body: AnalyzeQuestion):
    """Ask Claude questions about call performance, transcription, metrics, etc."""
    import anthropic

    # Fetch traces and metadata
    traces = telemetry.traces_for_call(call_id)
    call = db.q("SELECT * FROM calls WHERE id=?", (call_id,), one=True)

    if not call:
        raise HTTPException(404, "call not found")

    if not traces:
        raise HTTPException(400, "no traces for this call")

    # Format traces for Claude
    trace_summary = []
    for i, t in enumerate(traces):
        turn_data = {
            "turn": i + 1,
            "heard": (t.get("context") or {}).get("heard", ""),
            "intent": (t.get("output") or {}).get("intent", "?"),
            "confidence": (t.get("output") or {}).get("intent_confidence", 0),
            "understood": (t.get("output") or {}).get("understood", False),
            "engine": t.get("engine", "?"),
            "latency_ms": t.get("latency_ms", 0),
            "error": t.get("error"),
        }
        trace_summary.append(turn_data)

    # Create analysis prompt
    system_prompt = """You are an expert debugging assistant for voice agent systems.
You analyze call traces and metrics to identify issues with transcription accuracy,
intent understanding, latency, and behavior patterns.

When analyzing calls:
1. Look for patterns in misunderstood turns or high latency spikes
2. Identify specific turns where things went wrong
3. Suggest root causes (STT issues, prompt clarity, context overflow, etc.)
4. Recommend concrete fixes

Be specific: reference exact turn numbers and provide actionable insights."""

    user_message = f"""Analyze this voice agent call and answer: {body.question}

Call metadata:
- Call ID: {call_id}
- Duration: {call.get('ended_at', 0) - call.get('started_at', 0):.1f}s
- Total turns: {len(traces)}

Turn-by-turn trace:
{json.dumps(trace_summary, indent=2)}

Focus on: specific turns, error patterns, and actionable fixes."""

    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-opus-5-5",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        analysis = response.content[0].text
        return {
            "question": body.question,
            "analysis": analysis,
            "traces_analyzed": len(traces),
        }
    except Exception as e:
        log.exception("Analysis failed")
        raise HTTPException(500, f"Analysis failed: {str(e)}")


@app.get("/api/evaluator/models", dependencies=[Depends(allow(*STAFF))])
def evaluator_models(hours: int = 24):
    """Phase 1: Aggregate model performance (accuracy, latency, token efficiency)."""
    from . import evaluator
    return evaluator.model_performance(hours)


# ------------------------------------------------------------------ approvals (Phase 3)
class ApprovalRequest(BaseModel):
    call_id: int
    turn_id: int
    action: str
    decision: dict
    reason: str | None = None


@app.post("/api/approvals/request", dependencies=[Depends(allow(*STAFF))])
def request_approval(body: ApprovalRequest):
    """Create a new approval request (from harness UI for retroactive approval)."""
    from . import approval_gates

    approval_id = approval_gates.request_approval(
        body.call_id, body.turn_id, body.action, body.decision, body.reason
    )
    return {"approval_id": approval_id, "status": "pending"}


@app.get("/api/approvals/{approval_id}", dependencies=[Depends(allow(*STAFF))])
def get_approval(approval_id: int):
    """Get status of an approval request."""
    from . import approval_gates
    a = approval_gates.get_approval(approval_id)
    if not a:
        raise HTTPException(404, "approval not found")
    if a.get("decision_json"):
        a["decision"] = json.loads(a["decision_json"])
    if a.get("edited_decision_json"):
        a["edited_decision"] = json.loads(a["edited_decision_json"])
    return a


class ApprovalAction(BaseModel):
    approved_by: str | None = None
    denied_by: str | None = None
    denial_reason: str | None = None
    edited_decision: dict | None = None  # If approver modified the decision


@app.post("/api/approvals/{approval_id}/approve", dependencies=[Depends(allow(*STAFF))])
def approve_action(approval_id: int, body: ApprovalAction):
    """Approve a pending action (optionally with edits)."""
    from . import approval_gates
    success = approval_gates.approve(
        approval_id, body.approved_by or "system", body.edited_decision
    )
    if not success:
        raise HTTPException(400, "could not approve (already decided or not found)")
    return {"status": "approved", "approval_id": approval_id}


@app.post("/api/approvals/{approval_id}/deny", dependencies=[Depends(allow(*STAFF))])
def deny_action(approval_id: int, body: ApprovalAction):
    """Deny a pending action."""
    from . import approval_gates
    success = approval_gates.deny(
        approval_id, body.denied_by or "system", body.denial_reason
    )
    if not success:
        raise HTTPException(400, "could not deny (already decided or not found)")
    return {"status": "denied", "approval_id": approval_id}


@app.get("/api/calls/{call_id}/approvals", dependencies=[Depends(allow(*STAFF))])
def call_approvals(call_id: int):
    """Get approval audit trail for a call."""
    from . import approval_gates
    return approval_gates.audit_trail(call_id)


@app.get("/api/approvals/stats", dependencies=[Depends(allow(*STAFF))])
def approvals_stats(hours: int = 24):
    """Approval workflow stats (approval rate, common denials, etc.)."""
    from . import approval_gates
    return approval_gates.approval_stats(hours)


@app.get("/api/tool-registry", dependencies=[Depends(allow(*STAFF))])
def tool_registry():
    """Phase 3: Get tool risk registry (which operations need approval)."""
    from . import approval_gates
    return approval_gates.TOOL_REGISTRY


# ------------------------------------------------------------------ context chips (Phase 4)
@app.get("/api/traces/{trace_id}/chips", dependencies=[Depends(allow(*STAFF))])
def trace_chips(trace_id: int):
    """Phase 4: Get context chips from a trace (CSP, tickets, slots, messages)."""
    from . import context_wipe, telemetry

    trace = db.q("SELECT * FROM traces WHERE id=?", (trace_id,), one=True)
    if not trace:
        raise HTTPException(404, "trace not found")

    # Deserialize
    for k in ("messages_json", "context_json", "output_json"):
        trace[k[:-5]] = json.loads(trace.pop(k)) if trace.get(k) else None

    chips = context_wipe.parse_chips(trace)
    wiped = context_wipe.get_wiped_chips(trace_id)

    return {"chips": chips, "wiped": wiped}


class WipeChipRequest(BaseModel):
    chip_type: str  # ticket | slot | message
    chip_id: str    # ticket_no | slot_key | message_index
    reason: str | None = None


@app.post("/api/traces/{trace_id}/wipe", dependencies=[Depends(allow(*STAFF))])
def wipe_chip(trace_id: int, body: WipeChipRequest, request: Request):
    """Phase 4: Wipe a context chip from a trace."""
    from . import context_wipe

    user_email = request.state.user.get("email", "system") if request.state.user else "system"

    success = context_wipe.wipe_chip(
        trace_id, body.chip_type, body.chip_id, user_email, body.reason
    )
    if not success:
        raise HTTPException(400, "could not wipe chip (trace not found?)")

    return {"status": "wiped", "trace_id": trace_id, "chip": body.chip_id}


@app.get("/api/calls/{call_id}/wipes", dependencies=[Depends(allow(*STAFF))])
def call_wipes(call_id: int):
    """Phase 4: Get wipe audit trail for all traces in a call."""
    from . import context_wipe
    return context_wipe.get_wipe_audit(call_id=call_id)


@app.get("/api/traces/{trace_id}/wipes", dependencies=[Depends(allow(*STAFF))])
def trace_wipes(trace_id: int):
    """Phase 4: Get wipe audit trail for a specific trace."""
    from . import context_wipe
    return context_wipe.get_wipe_audit(trace_id=trace_id)


@app.get("/api/wipes/stats", dependencies=[Depends(allow(*STAFF))])
def wipes_stats(hours: int = 24):
    """Phase 4: Aggregate wipe statistics."""
    from . import context_wipe
    return context_wipe.wipe_stats(hours)


# ------------------------------------------------------------------ drift detection & repair (Phase 5)
@app.get("/api/drifts/pending", dependencies=[Depends(allow("admin", "ops"))])
def get_pending_drifts():
    """Phase 5: Get all pending drift detections awaiting review."""
    from . import drift_repair
    return drift_repair.get_pending_drifts()


class PromptVersionInfo(BaseModel):
    version_hash: str
    prompt_code: str
    created_by: str = "system"


@app.post("/api/prompt-versions", dependencies=[Depends(allow("admin", "ops"))])
def register_prompt_version(body: PromptVersionInfo):
    """Phase 5: Register a new prompt code version."""
    from . import drift_repair, llm_engine

    version_id = drift_repair.register_prompt_version(
        body.version_hash,
        body.prompt_code,
        llm_engine.AGENT_TURN_TOOL,
        body.created_by,
    )
    return {"version_id": version_id, "version_hash": body.version_hash}


@app.get("/api/prompt-versions/{version_id_1}/diff/{version_id_2}", dependencies=[Depends(allow("admin", "ops"))])
def get_diff(version_id_1: int, version_id_2: int):
    """Phase 5: Get diff between two prompt versions by id."""
    from . import drift_repair

    diff = drift_repair.get_prompt_diff(version_id_1, version_id_2)
    if not diff:
        raise HTTPException(404, "one or both versions not found")
    return diff


@app.get("/api/drifts/{drift_id}", dependencies=[Depends(allow("admin", "ops"))])
def get_drift_detail(drift_id: int):
    """Phase 5: Get details of a specific drift."""
    drift = db.q(
        """SELECT pd.*, pv1.version_hash as previous_version_hash, pv2.version_hash as current_version_hash
           FROM prompt_drifts pd
           LEFT JOIN prompt_versions pv1 ON pd.previous_version_id = pv1.id
           LEFT JOIN prompt_versions pv2 ON pd.current_version_id = pv2.id
           WHERE pd.id=?""",
        (drift_id,),
        one=True
    )
    if not drift:
        raise HTTPException(404, "drift not found")

    # Deserialize JSON fields if they exist
    if drift.get("replay_results_json"):
        drift["replay_results"] = json.loads(drift.get("replay_results_json"))
    if drift.get("decision_json"):
        drift["decision"] = json.loads(drift.get("decision_json"))

    return drift


class DriftAction(BaseModel):
    accepted: bool = True
    reason: str = ""


@app.post("/api/drifts/{drift_id}/accept", dependencies=[Depends(allow("admin", "ops"))])
def accept_drift(drift_id: int, request: Request, body: DriftAction):
    """Phase 5: Accept or reject a detected drift."""
    from . import drift_repair

    user_email = request.state.user.get("email", "system") if request.state.user else "system"

    if body.accepted:
        success = drift_repair.accept_drift(drift_id, user_email, body.reason)
        if not success:
            raise HTTPException(400, "could not accept drift")
        return {"status": "accepted", "drift_id": drift_id}
    else:
        success = drift_repair.reject_drift(drift_id, user_email, body.reason)
        if not success:
            raise HTTPException(400, "could not reject drift")
        return {"status": "rejected", "drift_id": drift_id}


@app.get("/api/prompt-versions/{version_hash}/baseline", dependencies=[Depends(allow("admin", "ops"))])
def get_baseline(version_hash: str):
    """Phase 5: Get accepted baseline scores for a prompt version."""
    from . import drift_repair

    baseline = drift_repair.get_baseline_scores(version_hash)
    if not baseline:
        raise HTTPException(404, "no accepted baseline for this version")
    return baseline


# ------------------------------------------------------------------ voice
class Speak(BaseModel):
    text: str
    lang: str = "hi-IN"


@app.post("/api/tts", dependencies=[Depends(allow(*STAFF))])
async def speak(body: Speak):
    text = body.text.strip()[:1000]
    if not text:
        raise HTTPException(400, "empty text")
    try:
        audio = await tts.synthesize(text, body.lang)
    except Exception as e:
        raise HTTPException(502, f"tts failed: {e}")
    return Response(audio, media_type="audio/mpeg")


@app.post("/api/stt", dependencies=[Depends(allow(*STAFF))])
def transcribe(audio: UploadFile = File(...), lang: str = Form("hi-IN")):
    if not stt.available():
        raise HTTPException(503, "Server speech-to-text needs GROQ_API_KEY")
    data = audio.file.read()
    if not data:
        raise HTTPException(400, "empty audio")
    try:
        return {"text": stt.transcribe(data, audio.filename or "speech.webm", lang)}
    except Exception as e:
        raise HTTPException(502, f"stt failed: {e}")


# ------------------------------------------------------------------ call recordings (pilot, app/recordings.py)
def _device(request: Request) -> dict:
    """The uploader app signs in with its upload token: `Authorization: Bearer ekoup_...`."""
    header = request.headers.get("authorization", "")
    dev = recordings.device_for_token(header[7:].strip() if header.lower().startswith("bearer ") else None)
    if not dev:
        raise HTTPException(401, "Upload token is missing, wrong or revoked")
    return dev


@app.get("/api/uploader/ping")
def uploader_ping(device=Depends(_device)):
    """The app's setup screen: mode-specific info for RM/DC/Employee. Only for a valid upload token."""
    mode = device.get("mode", "rm")
    result = {"ok": True, "mode": mode}

    if mode == "rm":
        result.update({
            "rm_id": device.get("rm_id", -1),
            "rm_name": device.get("rm_name", ""),
            "rm_locked": bool(device.get("rm_id")),
            "rms": recordings.rms_for_app()
        })
    elif mode == "dc":
        result.update({
            "dc_id": device.get("dc_id", -1),
            "dc_name": device.get("dc_name", ""),
            "allowed_numbers": recordings.get_allowed_numbers(device.get("dc_id", -1)) if device.get("dc_id") else [],
            "consent_required": not device.get("consent_token")
        })
    elif mode == "employee":
        result.update({
            "employee_id": device.get("employee_id", -1),
            "employee_name": device.get("employee_name", "")
        })

    return result


@app.post("/api/uploader/recordings")
def uploader_upload(audio: UploadFile = File(...), started_at: int | None = Form(None),
                    duration_sec: float | None = Form(None), direction: str = Form("unknown"),
                    other_number: str = Form(""), device_id: str = Form(""), rm_id: int | None = Form(None),
                    mode: str = Form("rm"), consent_token: str | None = Form(None),
                    device=Depends(_device)):
    """Upload a recording. Mode-aware: validates mode-specific constraints."""
    # Validate audio format first (Mansi requirement)
    filename = audio.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in recordings.AUDIO_EXTS:
        raise HTTPException(400, f"Invalid audio format: .{ext}. Accepted: {', '.join(sorted(recordings.AUDIO_EXTS))}")

    # Validate file size (Mansi requirement: max 60 MB)
    data = audio.file.read(recordings.MAX_BYTES + 1)
    if len(data) > recordings.MAX_BYTES:
        max_mb = recordings.MAX_BYTES // (1024 * 1024)
        raise HTTPException(413, f"Recording is over {max_mb} MB limit")
    try:
        # Validate mode matches token
        if mode != device.get("mode", "rm"):
            raise ValueError(f"Token mode is {device.get('mode', 'rm')}, not {mode}")

        # Mode-specific setup
        if mode == "rm":
            device = {**device, "rm_id": recordings.uploader_rm(device, rm_id)}
        elif mode == "dc":
            if not device.get("dc_id"):
                raise ValueError("DC token must have dc_id")
            device = {**device, "consent_token": consent_token or ""}
        elif mode == "employee":
            if not device.get("employee_id"):
                raise ValueError("Employee token must have employee_id")

        return recordings.save_upload(device, data, audio.filename or "", started_at, duration_sec, direction,
                                      other_number, device_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


class UploadTokenBody(BaseModel):
    rm_id: int | None = None          # None: a shared RM token, each RM picks their name in the app
    dc_id: int | None = None          # District Coordinator ID (mutually exclusive with rm_id and employee_id)
    employee_id: int | None = None    # Employee ID (mutually exclusive with rm_id and dc_id)
    label: str = ""


@app.get("/api/uploader/tokens", dependencies=[Depends(allow("admin"))])
def upload_tokens():
    return recordings.list_tokens()


@app.post("/api/uploader/tokens")
def new_upload_token(body: UploadTokenBody, actor=Depends(allow("admin"))):
    try:
        return recordings.create_token(rm_id=body.rm_id, dc_id=body.dc_id, employee_id=body.employee_id,
                                      label=body.label, created_by=actor.get("name") or actor.get("email"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/uploader/tokens/{token_id}", dependencies=[Depends(allow("admin"))])
def revoke_upload_token(token_id: int):
    if not recordings.revoke_token(token_id):
        raise HTTPException(404, "No active token with that id")
    return {"ok": True}


# ------------------------------------------------------------------ DC (District Coordinator) Management
@app.get("/api/dcs", dependencies=[Depends(allow("admin"))])
def list_dcs():
    """List all District Coordinators."""
    return db.q("SELECT id, name, phone, email, region, created_at, active FROM dcs ORDER BY name")


class DCBody(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    region: str | None = None
    active: int = 1


@app.post("/api/dcs", dependencies=[Depends(allow("admin"))])
def create_dc(body: DCBody, actor=Depends(allow("admin"))):
    """Create a new District Coordinator."""
    try:
        dc_id = db.x("""INSERT INTO dcs(name, phone, email, region, created_by, created_at, active)
                        VALUES(?, ?, ?, ?, ?, ?, 1)""",
                     (body.name, body.phone, body.email, body.region, actor.get("email"), time.time()))
        return {"id": dc_id, "name": body.name}
    except sqlite3.IntegrityError as e:
        raise HTTPException(400, f"Phone or email already exists: {e}")


@app.patch("/api/dcs/{dc_id}", dependencies=[Depends(allow("admin"))])
def update_dc(dc_id: int, body: DCBody):
    """Update a District Coordinator."""
    fields = {k: v for k, v in body.dict().items() if v is not None}
    if not fields:
        return {"ok": True}
    fields["updated_at"] = time.time()
    db.update("dcs", dc_id, **fields)
    return db.q("SELECT * FROM dcs WHERE id=?", (dc_id,), one=True)


# ------------------------------------------------------------------ Allowed Numbers Management
@app.get("/api/allowed-numbers", dependencies=[Depends(allow("admin"))])
def list_allowed_numbers(dc_id: int | None = None):
    """List allowed phone numbers. Optionally filter by DC."""
    if dc_id:
        return db.q("SELECT id, dc_id, phone_number, description, added_at FROM allowed_numbers WHERE dc_id=? ORDER BY phone_number",
                   (dc_id,))
    return db.q("SELECT id, dc_id, phone_number, description, added_at FROM allowed_numbers ORDER BY dc_id, phone_number")


@app.get("/api/uploader/allowed-numbers")
def get_allowed_numbers_for_uploader(device=Depends(_device)):
    """Get allowed numbers for a DC (uploader app endpoint, no admin auth required)."""
    if device.get("mode") != "dc":
        raise HTTPException(400, "Only DC mode can access this endpoint")
    dc_id = device.get("dc_id", -1)
    if dc_id < 0:
        raise HTTPException(400, "DC token must have dc_id")
    return {"allowed_numbers": recordings.get_allowed_numbers(dc_id)}


class AllowedNumberBody(BaseModel):
    phone_number: str
    description: str | None = None
    dc_id: int | None = None  # If None, applies to all DCs (shared list)


@app.post("/api/allowed-numbers", dependencies=[Depends(allow("admin"))])
def add_allowed_number(body: AllowedNumberBody, actor=Depends(allow("admin"))):
    """Add a phone number to allowed list."""
    try:
        num_id = db.x("""INSERT INTO allowed_numbers(dc_id, phone_number, description, added_by, added_at)
                        VALUES(?, ?, ?, ?, ?)""",
                     (body.dc_id, body.phone_number, body.description, actor.get("email"), time.time()))
        return {"id": num_id, "phone_number": body.phone_number, "dc_id": body.dc_id}
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"Phone number already in allowed list for this DC")


@app.delete("/api/allowed-numbers/{number_id}", dependencies=[Depends(allow("admin"))])
def remove_allowed_number(number_id: int):
    """Remove a phone number from allowed list."""
    if not db.q("SELECT id FROM allowed_numbers WHERE id=?", (number_id,), one=True):
        raise HTTPException(404, "Number not found")
    db.x("DELETE FROM allowed_numbers WHERE id=?", (number_id,))
    return {"ok": True}


# ------------------------------------------------------------------ Employee Management
@app.get("/api/employees", dependencies=[Depends(allow("admin"))])
def list_employees():
    """List all Employees."""
    try:
        result = db.q("SELECT id, name, phone, email, department, created_at, active FROM employees ORDER BY name")
        log.info(f"list_employees: returned {len(result)} employees")
        return result
    except Exception as e:
        log.error(f"list_employees ERROR: {e}", exc_info=True)
        raise HTTPException(500, str(e))


class EmployeeBody(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    department: str | None = None


@app.post("/api/employees", dependencies=[Depends(allow("admin"))])
def create_employee(body: EmployeeBody, actor=Depends(allow("admin"))):
    """Create a new Employee."""
    try:
        emp_id = db.x("""INSERT INTO employees(name, phone, email, department, created_by, created_at, active)
                        VALUES(?, ?, ?, ?, ?, ?, 1)""",
                     (body.name, body.phone, body.email, body.department, actor.get("email"), time.time()))
        return {"id": emp_id, "name": body.name}
    except sqlite3.IntegrityError as e:
        raise HTTPException(400, f"Phone or email already exists: {e}")


@app.patch("/api/employees/{employee_id}", dependencies=[Depends(allow("admin"))])
def update_employee(employee_id: int, body: EmployeeBody):
    """Update an Employee."""
    fields = {k: v for k, v in body.dict().items() if v is not None}
    if not fields:
        return {"ok": True}
    fields["updated_at"] = time.time()
    db.update("employees", employee_id, **fields)
    return db.q("SELECT * FROM employees WHERE id=?", (employee_id,), one=True)


# ------------------------------------------------------------------ Applicant Numbers Management (Phase 7b)
@app.get("/api/applicant-numbers/status", dependencies=[Depends(allow("admin"))])
def applicant_numbers_status():
    """Get sync status and statistics for applicant numbers."""
    stats = db.q("""
        SELECT
            COUNT(CASE WHEN active=1 THEN 1 END) as total_active,
            COUNT(CASE WHEN active=0 THEN 1 END) as total_inactive,
            MAX(synced_at) as last_sync_api,
            MAX(created_at) as last_upload,
            MAX(CASE WHEN created_by IS NOT NULL THEN created_at END) as last_manual_add
        FROM autogmap_numbers
    """, one=True)

    # Determine sync source based on most recent update
    last_sync_api = stats.get('last_sync_api') or 0
    last_upload = stats.get('last_upload') or 0
    sync_source = "api" if last_sync_api > last_upload else "excel"

    return {
        "total_active": stats.get('total_active', 0),
        "total_inactive": stats.get('total_inactive', 0),
        "last_sync_at": last_sync_api or last_upload or None,
        "sync_source": sync_source
    }


@app.get("/api/applicant-numbers", dependencies=[Depends(allow("admin"))])
def list_applicant_numbers(
    search: str | None = None,
    status: str = "active",
    page: int = 1,
    per_page: int = 50
):
    """List applicant numbers with pagination and filtering.

    Args:
        search: Search by phone or name
        status: Filter by 'active', 'inactive', or 'all'
        page: Page number (1-indexed)
        per_page: Items per page
    """
    # Build query
    where_clauses = []
    params = []

    if status == "active":
        where_clauses.append("active=1")
    elif status == "inactive":
        where_clauses.append("active=0")

    if search:
        where_clauses.append("(phone LIKE ? OR name LIKE ?)")
        search_term = f"%{search}%"
        params.extend([search_term, search_term])

    where_clause = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    # Get total count
    count_sql = f"SELECT COUNT(*) as cnt FROM autogmap_numbers{where_clause}"
    count_result = db.q(count_sql, params, one=True)
    total = count_result.get('cnt', 0) if count_result else 0

    # Get paginated results
    offset = (page - 1) * per_page
    data_sql = f"""
        SELECT id, phone, name, description, active, created_by, created_at, synced_at
        FROM autogmap_numbers
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """
    data_params = params + [per_page, offset]
    records = db.q(data_sql, data_params)

    return {
        "numbers": records,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page
    }


class ApplicantNumberBody(BaseModel):
    phone: str
    name: str | None = None
    description: str | None = None
    active: int = 1


@app.post("/api/applicant-numbers", dependencies=[Depends(allow("admin"))])
def create_applicant_number(body: ApplicantNumberBody, actor=Depends(allow("admin"))):
    """Create a single applicant number."""
    try:
        num_id = db.x("""
            INSERT INTO autogmap_numbers(phone, name, description, created_by, created_at, active)
            VALUES(?, ?, ?, ?, ?, ?)
        """, (body.phone, body.name, body.description, actor.get("email"), time.time(), body.active))
        return {"id": num_id, "phone": body.phone}
    except sqlite3.IntegrityError as e:
        raise HTTPException(400, f"Phone already exists: {e}")


@app.put("/api/applicant-numbers/{number_id}", dependencies=[Depends(allow("admin"))])
def update_applicant_number(number_id: int, body: ApplicantNumberBody):
    """Update an applicant number."""
    # Check if exists
    if not db.q("SELECT id FROM autogmap_numbers WHERE id=?", (number_id,), one=True):
        raise HTTPException(404, "Number not found")

    # Build update fields
    fields = {}
    if body.name is not None:
        fields["name"] = body.name
    if body.description is not None:
        fields["description"] = body.description
    if body.active is not None:
        fields["active"] = body.active

    if fields:
        db.update("autogmap_numbers", number_id, **fields)

    return db.q("SELECT * FROM autogmap_numbers WHERE id=?", (number_id,), one=True)


@app.delete("/api/applicant-numbers/{number_id}", dependencies=[Depends(allow("admin"))])
def delete_applicant_number(number_id: int):
    """Soft delete an applicant number (mark inactive)."""
    if not db.q("SELECT id FROM autogmap_numbers WHERE id=?", (number_id,), one=True):
        raise HTTPException(404, "Number not found")

    db.update("autogmap_numbers", number_id, active=0)
    return {"ok": True}


@app.post("/api/bulk-load/applicant-numbers", dependencies=[Depends(allow("admin"))])
async def bulk_load_applicant_numbers_endpoint(file: UploadFile = File(...), actor=Depends(allow("admin"))):
    """Bulk upload applicant numbers from Excel file."""
    if not file.filename.lower().endswith(('.xlsx', '.xls', '.csv')):
        raise HTTPException(400, "Only Excel files (.xlsx, .xls) are supported")

    try:
        content = await file.read()
        result = bulk_load.bulk_load_applicant_numbers(content, actor.get("email", "unknown"))
        return result
    except Exception as e:
        raise HTTPException(500, f"Upload failed: {str(e)}")


# ------------------------------------------------------------------ Prachi Sync Management (Phase 7d)
@app.get("/api/prachi/sync-status", dependencies=[Depends(allow("admin", "ops"))])
def get_prachi_sync_status():
    """Get Prachi data sync status.

    Returns:
    - sync_source: "api" (PRIMARY: automatic Google Sheets sync)
    - health_status: "OK" | "RECOVERING" | "DEGRADED" (3+ failures)
    - last_sync: timestamp of last sync attempt
    - last_sync_success: timestamp of last successful sync
    - sync_failures: total failure count
    - failure_streak: consecutive failures (3+ = degraded)
    - dcs_count: total active DCs in database
    - officials_count: total active SBI officials in database
    """
    return prachi_sync.get_sync_status()


@app.get("/api/prachi/sync-history", dependencies=[Depends(allow("admin", "ops"))])
def get_prachi_sync_history(limit: int = 50):
    """Get Prachi sync history (audit trail).

    Shows all sync operations: API (primary) and manual Excel uploads (secondary).
    Tracks: success/failed/degraded status, record changes, sync source, timestamps.
    """
    rows = db.q("""
        SELECT id, sync_type, status, records_processed, records_added, records_updated, records_deleted,
               error_message, sync_source, synced_at
        FROM prachi_sync_history
        ORDER BY synced_at DESC
        LIMIT ?
    """, (limit,))

    return {"history": rows, "total": len(rows)}


class PrachiManualUploadBody(BaseModel):
    """Manual Excel upload for Prachi data (secondary, temporary override)."""
    dcs: list[dict] = []  # [{name, phone, region}, ...]
    officials: list[dict] = []  # [{phone, dc_name, description}, ...]


@app.post("/api/prachi/upload-excel", dependencies=[Depends(allow("admin"))])
async def upload_prachi_excel(body: PrachiManualUploadBody, actor=Depends(allow("admin"))):
    """SECONDARY: Manually upload Prachi data from Excel.

    WARNING: This is a temporary override. The next scheduled API sync (every 24 hours)
    will overwrite this data with the latest from Google Sheets.

    Use this only when:
    - Google Sheets API is down
    - You need to make urgent corrections
    - The API data is stale and you have fresher data from another source

    Request body:
    {
        "dcs": [
            {"name": "DC Name", "phone": "9876543210", "region": "North"},
            ...
        ],
        "officials": [
            {"phone": "9876543210", "dc_name": "DC Name", "description": "Officer A"},
            ...
        ]
    }

    Response includes:
    - success: true/false
    - dcs_result: {added, updated, deleted}
    - officials_result: {added, updated, deleted}
    - warning: reminder that API will overwrite on next sync
    """
    try:
        actor_email = actor.get("email", "unknown")
        result = await prachi_sync.manual_excel_upload(body.dcs, body.officials, actor_email)

        if not result.get("success"):
            raise HTTPException(500, f"Upload failed: {result.get('error', 'Unknown error')}")

        return result

    except Exception as e:
        log.exception("Prachi manual Excel upload failed")
        raise HTTPException(500, f"Upload failed: {str(e)}")


@app.get("/api/mansi/recordings")
def mansi_recordings(
    employee_id: int | None = None,
    other_number: str | None = None,
    days: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 100
):
    """Pull-based API for Mansi to query employee recordings.

    Default: Last 7 days of employee recordings.
    Flexible: Customize with date_from/date_to or days parameter.

    Query parameters:
    - employee_id: Filter by specific employee
    - other_number: Filter by caller phone number
    - days: Last N days (default 7, overridden by date_from/date_to)
    - date_from: Start date (ISO: 2026-11-01)
    - date_to: End date (ISO: 2026-11-30)
    - status: Filter by status ('new', 'done', 'failed')
    - skip: Pagination offset
    - limit: Max records per request (default 100, max 500)
    """
    # Validate API key from header if needed (optional for now, can add authentication layer)
    # auth_header = request.headers.get('Authorization', '') if request else ''

    # Set defaults
    if days is None and date_from is None and date_to is None:
        days = 7  # Default: last 7 days

    # Calculate date range
    import datetime
    now = datetime.datetime.utcnow()

    if date_from and date_to:
        # Use explicit date range (overrides days parameter)
        try:
            start_dt = datetime.datetime.fromisoformat(date_from)
            end_dt = datetime.datetime.fromisoformat(date_to)
            # Set end to end of day
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
        except ValueError:
            raise HTTPException(400, "Invalid date format. Use ISO format: 2026-11-01")
        days_param = None
    elif days:
        # Use days parameter
        start_dt = now - datetime.timedelta(days=days)
        end_dt = now
        days_param = days
    else:
        # Fallback to 7 days
        start_dt = now - datetime.timedelta(days=7)
        end_dt = now
        days_param = 7

    start_ts = start_dt.timestamp()
    end_ts = end_dt.timestamp()

    # Build query
    query = "SELECT * FROM recordings WHERE mode='employee' AND uploaded_at >= ? AND uploaded_at <= ?"
    params = [start_ts, end_ts]

    # Add filters
    if employee_id is not None:
        query += " AND employee_id = ?"
        params.append(employee_id)

    if other_number is not None:
        query += " AND other_number = ?"
        params.append(other_number)

    if status is not None:
        query += " AND status = ?"
        params.append(status)

    # Count total before pagination
    count_query = query.replace("SELECT *", "SELECT COUNT(*) as cnt")
    total = db.q(count_query, params, one=True)["cnt"]

    # Add pagination and sorting
    query += " ORDER BY uploaded_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, skip])

    # Fetch results
    recs = db.q(query, params)

    # Format response
    filters_applied = {
        "employee_id": employee_id,
        "other_number": other_number,
        "status": status,
    }

    # Remove None values from filters_applied
    filters_applied = {k: v for k, v in filters_applied.items() if v is not None}

    # Add date info
    if date_from and date_to:
        filters_applied["date_from"] = date_from
        filters_applied["date_to"] = date_to
    else:
        filters_applied["days"] = days_param or 7

    return {
        "recordings": recs,
        "total": total,
        "default_timeframe": "last 7 days" if (date_from is None and date_to is None and days is None) else "custom",
        "filters_applied": filters_applied
    }


@app.get("/api/recordings", dependencies=[Depends(allow("admin", "ops", "rm"))])
def list_recordings(request: Request, status: str | None = None, rm_id: int | None = None, limit: int = 500, call_type: str | None = None, mode: str | None = None, employee_id: int | None = None):
    u = request.state.user
    if u.get("role") == "rm":
        rm_id = u["rm_id"]

    try:
        # Test 1: Can we get counts?
        counts = recordings.summary_counts(rm_id)

        # Test 2: Can we get recordings?
        recs = recordings.list_recordings(status, rm_id, limit, call_type, mode, employee_id)

        # Test 3: Can we add accuracy?
        result = [recordings.add_transcription_accuracy(r) for r in recs]

        # Test 4: Return the response
        return {"counts": counts, "recordings": result}
    except Exception as e:
        import traceback
        error_msg = f"{type(e).__name__}: {str(e)}"
        log.error(f"ERROR in /api/recordings: {error_msg}")
        log.error(traceback.format_exc())
        raise HTTPException(500, error_msg)


def _own_recording(request: Request, rec_id: int) -> dict:
    r = recordings.get_recording(rec_id)
    if not r:
        raise HTTPException(404, "Recording not found")
    check_rm_owns(request, r["rm_id"], "Recording")
    return r


@app.get("/api/recordings/learning", dependencies=[Depends(allow("admin", "ops", "rm"))])
def recordings_learning(request: Request, rm_id: int | None = None):
    """What people's corrections say: speech-to-text accuracy over time, how often the AI's issue was right,
    and the words speech-to-text keeps mishearing."""
    u = request.state.user
    # Admin/Ops: can view metrics for all recordings, or filter to specific RM if requested
    # RM: can only view metrics for their own recordings
    if u.get("role") == "rm":
        rm_id = u["rm_id"]  # RMs always see only their own metrics
    return recordings.learning_stats(rm_id)


class MisheardBlockBody(BaseModel):
    heard: str
    said: str
    blocked: bool = True


@app.post("/api/recordings/misheard/block")
def block_misheard(body: MisheardBlockBody, actor=Depends(allow(*STAFF))):
    """Keep a misheard-word pair out of the AI's prompts (or let it back in)."""
    misheard.set_blocked(body.heard, body.said, body.blocked, _who(actor))
    return {"ok": True}


@app.get("/api/recordings/{rec_id}", dependencies=[Depends(allow("admin", "ops", "rm"))])
def get_recording(rec_id: int, request: Request):
    r = _own_recording(request, rec_id)
    return recordings.add_transcription_accuracy(r)


@app.get("/api/recordings/{rec_id}/audio", dependencies=[Depends(allow("admin", "ops", "rm"))])
def recording_audio(rec_id: int, request: Request):
    _own_recording(request, rec_id)
    row = db.q("SELECT file_path FROM recordings WHERE id=?", (rec_id,), one=True)
    path = recordings.audio_file(row)
    if not os.path.exists(path):
        raise HTTPException(404, "The audio file is missing")
    return FileResponse(path)


@app.post("/api/recordings/upload")
def upload_recordings(audio: list[UploadFile] = File(...), rm_id: int | None = Form(None), started_at: str = Form(""),
                      direction: str = Form("unknown"), other_number: str = Form(""), actor=Depends(allow(*STAFF))):
    """Add recordings by hand (e.g. calls shared on WhatsApp). They go through the same processing as phone uploads.
    started_at: one epoch-ms value per file, comma-separated (the page sends each file's own date)."""
    rm_id = rm_id or None                     # 0 / empty = not an RM call (e.g. a meeting or an interview)
    if rm_id and not db.q("SELECT id FROM rms WHERE id=?", (rm_id,), one=True):
        raise HTTPException(400, "No such RM")
    times = [t.strip() for t in started_at.split(",")]
    results = []
    for i, f in enumerate(audio):
        data = f.file.read(recordings.MAX_BYTES + 1)
        name = f.filename or "recording"
        if len(data) > recordings.MAX_BYTES:
            results.append({"file": name, "error": "Over 100 MB"})
            continue
        t = times[i] if i < len(times) else ""
        try:
            r = recordings.save_upload({"rm_id": rm_id, "id": None}, data, name, int(t) if t.isdigit() else None,
                                       None, direction, other_number, f"manual: {actor.get('name') or ''}"[:64])
            results.append({"file": name, **r})
        except ValueError as e:
            results.append({"file": name, "error": str(e)})
    return {"results": results}


DOWNLOADS = {"transcript.txt": ("transcript_file", "txt", "text/plain; charset=utf-8"),
             "summary.md": ("summary_file", "md", "text/markdown; charset=utf-8"),
             "report.docx": ("docx_file", "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
             "report.doc": ("docx_file", "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}   # old links get the .docx too


@app.get("/api/recordings/{rec_id}/download/{kind}", dependencies=[Depends(allow("admin", "ops", "rm"))])
def download_recording(rec_id: int, kind: str, request: Request):
    """The transcript (.txt), the summary (.md) or both as a Word document (.docx), as a file to save."""
    if kind not in DOWNLOADS:
        raise HTTPException(404, "Choose transcript.txt, summary.md or report.docx")
    r = _own_recording(request, rec_id)
    fn, ext, media = DOWNLOADS[kind]
    name = report.filename(r, ext)
    return Response(getattr(report, fn)(r), media_type=media,
                    headers={"Content-Disposition": f"attachment; filename=\"{name}\"; filename*=UTF-8''{quote(name)}"})


class RecordingEditBody(BaseModel):
    lines: list[dict] | None = None      # every line in order: {"i": index or null, "text", "speaker", "voice", "start", "end"}
    summary: str | None = None           # auto-updated if transcript changes
    report_md: str | None = None
    intent: str | None = None
    slots: dict | None = None            # every detail to keep: {"amount": "5000", ...}
    checked: list[str] = []              # "transcript" / "issue": checked by a person, nothing to change
    based_on: float | None = None        # the transcript's version when the page was opened (stale check)


@app.patch("/api/recordings/{rec_id}")
def edit_recording(rec_id: int, body: RecordingEditBody, request: Request,
                   actor=Depends(allow("admin", "ops", "rm"))):
    """Correct the transcript or the summaries. The RM who made the call may correct their own recordings."""
    _own_recording(request, rec_id)
    try:
        return recordings.save_edits(rec_id, _who(actor), body.lines, body.summary, body.report_md, body.intent,
                                     body.slots, body.checked, body.based_on)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/recordings/{rec_id}/summarize", dependencies=[Depends(allow("admin", "ops", "rm"))])
def summarize_recording(rec_id: int, request: Request):
    """Write the full summary again (it is written by itself after each recording is processed). The RM may,
    for their own recordings: after correcting the transcript they need a summary of the corrected text."""
    r = _own_recording(request, rec_id)
    if not r["transcript"]:
        raise HTTPException(400, "This recording has no transcript yet")
    db.update("recordings", rec_id, report_error=None, report_at=None)
    threading.Thread(target=recordings._write_summary, args=(rec_id,), daemon=True, name="summary").start()
    return {"started": True}


@app.post("/api/recordings/{rec_id}/reprocess", dependencies=[Depends(allow("admin", "ops", "rm"))])
def reprocess_recording(rec_id: int, request: Request):
    """Process a recording again. The RM may, for their own: after correcting the transcript, this updates the
    summaries, issue type and details from the corrected text (it is not transcribed again)."""
    _own_recording(request, rec_id)
    if not recordings.reprocess(rec_id):
        raise HTTPException(404, "Recording not found")
    return {"ok": True}


@app.delete("/api/recordings/{rec_id}", dependencies=[Depends(allow("admin"))])
def delete_recording(rec_id: int):
    if not recordings.delete_recording(rec_id):
        raise HTTPException(404, "Recording not found")
    return {"ok": True}


@app.post("/api/recordings/process", dependencies=[Depends(allow(*STAFF))])
def process_recordings():
    """Process waiting recordings now (normally they are processed as they arrive)."""
    threading.Thread(target=recordings.process_pending, daemon=True, name="recordings-now").start()
    return {"started": True, "waiting": recordings.summary_counts().get("new", 0)}


@app.post("/api/recordings/cleanup")
def cleanup_recordings():
    """Remove non-CSP and short recordings, reset failed ones for reprocessing."""
    threading.Thread(target=recordings.cleanup_invalid_recordings, daemon=True, name="cleanup-recordings").start()
    return {"started": True, "message": "Cleanup running in background"}


# ------------------------------------------------------------------ Prachi API (Phase 7: DC recording submission)

class PrachiRecordingRequest(BaseModel):
    recording_id: int
    dc_id: int
    dc_name: str
    dc_phone: str
    caller_number: str
    recipient_number: str
    call_direction: str
    duration_sec: int
    uploaded_at: str
    transcript: str
    transcript_json: list
    file_path: str
    status: str
    attempts: int


def _validate_phone(phone: str, field_name: str):
    """Validate phone number format (basic check: non-empty, numeric)."""
    if not phone or not isinstance(phone, str):
        raise ValueError(f"Field '{field_name}' must be a non-empty string")
    if not phone.replace(" ", "").replace("-", "").isdigit():
        raise ValueError(f"Field '{field_name}' must contain only digits, spaces, or hyphens")


def _validate_prachi_submission(req: PrachiRecordingRequest) -> dict:
    """Validate Prachi recording submission against spec requirements.
    Returns validation error dict if invalid, empty dict if valid."""

    # Validate recording_id
    if not isinstance(req.recording_id, int) or req.recording_id <= 0:
        return {"status_code": 400, "detail": "Field 'recording_id' must be a positive integer"}

    # Validate dc_id exists
    if not isinstance(req.dc_id, int) or req.dc_id <= 0:
        return {"status_code": 400, "detail": "Field 'dc_id' must be a positive integer"}
    dc = db.q("SELECT id FROM dcs WHERE id=?", (req.dc_id,), one=True)
    if not dc:
        return {"status_code": 400, "detail": f"Field 'dc_id': DC {req.dc_id} does not exist"}

    # Validate dc_name
    if not req.dc_name or not isinstance(req.dc_name, str):
        return {"status_code": 400, "detail": "Field 'dc_name' must be a non-empty string"}

    # Validate phone numbers
    try:
        _validate_phone(req.dc_phone, "dc_phone")
        _validate_phone(req.caller_number, "caller_number")
        _validate_phone(req.recipient_number, "recipient_number")
    except ValueError as e:
        return {"status_code": 400, "detail": str(e)}

    # Validate call_direction
    if req.call_direction not in ("outbound", "inbound"):
        return {"status_code": 400, "detail": "Field 'call_direction' must be 'outbound' or 'inbound'"}

    # Validate duration_sec
    if not isinstance(req.duration_sec, int) or req.duration_sec < 0:
        return {"status_code": 400, "detail": "Field 'duration_sec' must be a non-negative integer"}

    # Validate uploaded_at (ISO 8601 format)
    try:
        # Basic ISO 8601 validation
        if not req.uploaded_at or not isinstance(req.uploaded_at, str):
            raise ValueError()
        # Check basic format: should contain T and Z or +/-
        if "T" not in req.uploaded_at:
            raise ValueError()
    except (ValueError, AttributeError):
        return {"status_code": 400, "detail": "Field 'uploaded_at' must be ISO 8601 format (e.g., 2026-11-11T10:30:00Z)"}

    # Validate transcript (must have at least 10 words)
    if not req.transcript or not isinstance(req.transcript, str):
        return {"status_code": 400, "detail": "Field 'transcript' must be a non-empty string"}
    word_count = len(req.transcript.split())
    if word_count < 10:
        return {"status_code": 422, "detail": f"Failed to process recording: transcript too short (< 10 words, got {word_count})"}

    # Validate transcript_json
    if not req.transcript_json or not isinstance(req.transcript_json, list):
        return {"status_code": 400, "detail": "Field 'transcript_json' must be a non-empty array"}
    for i, entry in enumerate(req.transcript_json):
        if not isinstance(entry, dict):
            return {"status_code": 400, "detail": f"Field 'transcript_json[{i}]' must be an object"}
        if "speaker" not in entry or "text" not in entry:
            return {"status_code": 400, "detail": f"Field 'transcript_json[{i}]' must have 'speaker' and 'text' fields"}

    # Validate file_path
    if not req.file_path or not isinstance(req.file_path, str):
        return {"status_code": 400, "detail": "Field 'file_path' must be a non-empty string"}

    # Validate status (must be "done")
    if req.status != "done":
        return {"status_code": 400, "detail": "Field 'status' must be 'done'"}

    # Validate attempts
    if not isinstance(req.attempts, int) or req.attempts < 1:
        return {"status_code": 400, "detail": "Field 'attempts' must be a positive integer"}

    return {}


@app.post("/api/prachi/recordings")
def prachi_receive_recording(req: PrachiRecordingRequest, request: Request):
    """Receive DC recording submission from Prachi API.

    Phase 7: DC mode recordings are transcribed and submitted here for Prachi's workflow processing.
    Requires API key authentication (admin or service key).

    Returns:
      200: {"ok": true, "recording_id": X, "status": "received", "message": "..."}
      400: Invalid request data
      401: Missing/invalid API key
      409: Duplicate recording_id already received
      422: Processing error (e.g., transcript too short)
    """

    # Check authentication: require API key or admin user
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        # Service API key
        service = integrations.service_for_key(header[7:].strip())
        if not service:
            log.warning("Prachi API: invalid API key attempt")
            return JSONResponse({"detail": "Invalid or missing API key"}, status_code=401)
        request.state.user = service
        log.info(f"Prachi API: authenticated via service API key ({service.get('name')})")
    else:
        # User must be signed in and admin/ops
        user = auth.user_for_token(request.cookies.get(auth.COOKIE))
        if not user or user.get("role") not in ("admin", "ops"):
            log.warning(f"Prachi API: unauthorized access attempt (role={user.get('role') if user else 'none'})")
            return JSONResponse({"detail": "Invalid or missing API key"}, status_code=401)
        request.state.user = user
        log.info(f"Prachi API: authenticated via user ({user.get('email')})")

    try:
        # Validate request
        error = _validate_prachi_submission(req)
        if error:
            log.warning(f"Prachi API: validation error for recording {req.recording_id}: {error['detail']}")
            return JSONResponse({"detail": error["detail"]}, status_code=error["status_code"])

        # Check for duplicate submission (409 Conflict)
        existing = db.q(
            "SELECT prachi_request_id FROM prachi_submissions WHERE recording_id=? ORDER BY created_at DESC LIMIT 1",
            (req.recording_id,),
            one=True
        )
        if existing:
            msg = f"Recording {req.recording_id} already received. Ignoring duplicate."
            log.info(f"Prachi API: {msg}")
            return JSONResponse({"detail": msg}, status_code=409)

        # Store submission record for audit trail
        submission_id = db.x(
            """INSERT INTO prachi_submissions
               (recording_id, dc_id, dc_name, dc_phone, caller_number, recipient_number,
                call_direction, duration_sec, uploaded_at, transcript, transcript_json,
                file_path, status, attempts, received_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                req.recording_id, req.dc_id, req.dc_name, req.dc_phone,
                req.caller_number, req.recipient_number, req.call_direction,
                req.duration_sec, req.uploaded_at, req.transcript,
                json.dumps(req.transcript_json), req.file_path, req.status, req.attempts,
                time.time()
            )
        )

        # Generate prachi_request_id for tracking
        prachi_request_id = f"prachi_{submission_id}_{int(time.time())}"

        # Update submission with request ID
        db.update("prachi_submissions", submission_id, prachi_request_id=prachi_request_id)

        # Log successful reception
        log.info(f"Prachi API: Recording {req.recording_id} received from DC {req.dc_id} "
                f"(req_id={prachi_request_id}, {req.duration_sec}s, attempts={req.attempts})")

        # Return success response
        return {
            "ok": True,
            "recording_id": req.recording_id,
            "status": "received",
            "message": "Recording received and queued for processing"
        }

    except ValueError as e:
        msg = f"Failed to process recording: {str(e)}"
        log.error(f"Prachi API: {msg} for recording {req.recording_id}")
        return JSONResponse({"detail": msg}, status_code=422)
    except Exception as e:
        msg = f"Internal error processing recording {req.recording_id}: {str(e)}"
        log.exception(f"Prachi API: {msg}")
        return JSONResponse({"detail": "Internal error processing recording"}, status_code=500)


# ------------------------------------------------------------------ AutoGMap (Phase 7a: Numbers Sync)
@app.get("/api/autogmap/status", dependencies=[Depends(allow("admin", "ops"))])
def autogmap_status():
    """Get AutoGMap integration status: sync stats, queue depth, upload metrics."""
    sync_stats = autogmap._get_sync().get_stats()
    queue_stats = autogmap.get_upload_queue_stats()

    return {
        "enabled": autogmap.AUTOGMAP_ENABLED,
        "sync": {
            "last_sync": sync_stats.get("last_sync"),
            "last_sync_success": sync_stats.get("last_sync_success"),
            "numbers_count": sync_stats.get("numbers_count", 0),
            "sync_count": sync_stats.get("sync_count", 0),
            "sync_failures": sync_stats.get("sync_failures", 0),
            "failure_streak": sync_stats.get("failure_streak", 0),
        },
        "upload_queue": {
            "max_workers": autogmap.AUTOGMAP_UPLOAD_MAX_WORKERS,
            "max_size": autogmap.AUTOGMAP_UPLOAD_QUEUE_SIZE,
            "current_depth": queue_stats.get("current_queue_depth", 0),
            "queued_total": queue_stats.get("queued", 0),
            "processed_total": queue_stats.get("processed", 0),
            "queue_peak": queue_stats.get("queue_peak", 0),
            "rejections": queue_stats.get("queue_full_rejections", 0),
            "last_queued_at": queue_stats.get("last_queued_at"),
        },
        "status": "OK" if sync_stats.get("failure_streak", 0) < 3 else "ERROR",
    }


# ------------------------------------------------------------------ integrations (app/integrations.py, INTEGRATION.md)
class KeyBody(BaseModel):
    name: str


class WebhookBody(BaseModel):
    url: str
    events: list[str] = ["*"]


def _who(actor: dict) -> str:
    return actor.get("name") or actor.get("email") or ""


@app.get("/api/integrations/keys", dependencies=[Depends(allow("admin"))])
def api_keys():
    return integrations.list_keys()


@app.post("/api/integrations/keys")
def new_api_key(body: KeyBody, actor=Depends(allow("admin"))):
    try:
        return integrations.create_key(body.name, _who(actor))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/integrations/keys/{key_id}", dependencies=[Depends(allow("admin"))])
def revoke_api_key(key_id: int):
    if not integrations.revoke_key(key_id):
        raise HTTPException(404, "No active key with that id")
    return {"ok": True}


@app.get("/api/integrations/webhooks", dependencies=[Depends(allow("admin"))])
def webhooks():
    return {"events": integrations.EVENTS, "webhooks": integrations.list_webhooks()}


@app.post("/api/integrations/webhooks")
def new_webhook(body: WebhookBody, actor=Depends(allow("admin"))):
    try:
        return integrations.create_webhook(body.url, body.events, _who(actor))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/integrations/webhooks/{hook_id}", dependencies=[Depends(allow("admin"))])
def remove_webhook(hook_id: int):
    if not integrations.remove_webhook(hook_id):
        raise HTTPException(404, "No active webhook with that id")
    return {"ok": True}


@app.post("/api/integrations/webhooks/{hook_id}/test", dependencies=[Depends(allow("admin"))])
def test_webhook(hook_id: int):
    if not integrations.send_test(hook_id):
        raise HTTPException(404, "No active webhook with that id")
    return {"queued": True}


@app.get("/api/integrations/deliveries", dependencies=[Depends(allow("admin"))])
def deliveries(webhook_id: int | None = None, limit: int = 100):
    return integrations.list_deliveries(webhook_id, limit)


# ------------------------------------------------------------------ prachi sync

@app.get("/api/prachi/sync-status", dependencies=[Depends(allow("admin"))])
def get_prachi_sync_status():
    """Get current Prachi sync status and statistics."""
    return prachi_sync.get_sync_status()


@app.post("/api/prachi/sync-now", dependencies=[Depends(allow("admin"))])
def trigger_prachi_sync_now():
    """Trigger an immediate Prachi sync (don't wait for daily schedule)."""
    import asyncio
    from threading import Thread

    def run_sync():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(prachi_sync.run_daily_sync())
        finally:
            loop.close()

    # Run in background thread
    thread = Thread(target=run_sync, daemon=True, name="prachi-manual-sync")
    thread.start()

    return {"status": "syncing", "message": "Prachi sync started in background"}


@app.get("/api/prachi/sync-history", dependencies=[Depends(allow("admin"))])
def get_prachi_sync_history(limit: int = 10):
    """Get sync history with details (last N syncs)."""
    try:
        rows = db.q(
            """SELECT id, sync_type, status, records_processed, records_added, records_updated,
                      records_deleted, error_message, synced_at
               FROM prachi_sync_history
               ORDER BY synced_at DESC
               LIMIT ?""",
            (limit,),
        )
        return {
            "count": len(rows),
            "syncs": [
                {
                    "id": row["id"],
                    "sync_type": row["sync_type"],
                    "status": row["status"],
                    "records_processed": row["records_processed"],
                    "records_added": row["records_added"],
                    "records_updated": row["records_updated"],
                    "records_deleted": row["records_deleted"],
                    "error_message": row["error_message"],
                    "synced_at": row["synced_at"],
                }
                for row in rows
            ],
        }
    except Exception as e:
        log.exception("Error fetching Prachi sync history")
        raise HTTPException(500, f"Error fetching history: {e}")


# ------------------------------------------------------------------ monitoring dashboard (Phase 7d)

@app.get("/api/monitor/status", dependencies=[Depends(allow("admin", "ops"))])
def get_monitor_status():
    """Get complete monitoring dashboard status (all metrics in one call)."""
    try:
        autogmap_sync = db.get_autogmap_sync_stats(days=7)
        autogmap_uploads = db.get_autogmap_upload_stats(hours=24)
        prachi_sync_info = db.get_prachi_sync_stats()
        prachi_submissions = db.get_prachi_submission_stats(hours=24)
        system_health = db.get_system_health()
        recent_errors = db.get_recent_errors(limit=10)

        return {
            "timestamp": db.now(),
            "autogmap": {
                "sync": autogmap_sync,
                "uploads": autogmap_uploads
            },
            "prachi": {
                "sync": prachi_sync_info,
                "submissions": prachi_submissions
            },
            "system": system_health,
            "recent_errors": recent_errors
        }
    except Exception as e:
        log.exception("Error fetching monitor status")
        raise HTTPException(500, f"Error fetching monitor status: {str(e)}")


@app.get("/api/monitor/autogmap/stats", dependencies=[Depends(allow("admin", "ops"))])
def get_monitor_autogmap_stats(days: int = 7):
    """Get detailed AutoGMap sync and upload statistics."""
    try:
        sync_stats = db.get_autogmap_sync_stats(days=days)
        upload_stats = db.get_autogmap_upload_stats(hours=days*24)

        # Get historical success rates (last 7 days, by day)
        cutoff = db.now() - (7 * 86400)
        daily_stats = db.q("""
            SELECT
                DATE(synced_at, 'unixepoch') as date,
                COUNT(*) as syncs,
                SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as successful
            FROM prachi_sync_history
            WHERE synced_at > ? AND sync_type IN ('dcs', 'dcs_and_officials')
            GROUP BY DATE(synced_at, 'unixepoch')
            ORDER BY date DESC
        """, (cutoff,))

        return {
            "sync": sync_stats,
            "uploads": upload_stats,
            "daily_history": [
                {
                    "date": row["date"],
                    "syncs": row["syncs"],
                    "successful": row["successful"],
                    "success_rate": round((row["successful"] / row["syncs"] * 100), 2) if row["syncs"] > 0 else 0
                }
                for row in daily_stats
            ]
        }
    except Exception as e:
        log.exception("Error fetching AutoGMap stats")
        raise HTTPException(500, f"Error fetching AutoGMap stats: {str(e)}")


@app.get("/api/monitor/prachi/stats", dependencies=[Depends(allow("admin", "ops"))])
def get_monitor_prachi_stats(hours: int = 24):
    """Get detailed Prachi sync and submission statistics."""
    try:
        sync_info = db.get_prachi_sync_stats()
        submissions = db.get_prachi_submission_stats(hours=hours)

        # Get submission status breakdown
        cutoff = db.now() - (hours * 3600)
        status_breakdown = db.q("""
            SELECT status, COUNT(*) as count
            FROM prachi_submissions
            WHERE received_at > ?
            GROUP BY status
        """, (cutoff,))

        return {
            "sync": sync_info,
            "submissions": submissions,
            "status_breakdown": {row["status"]: row["count"] for row in status_breakdown}
        }
    except Exception as e:
        log.exception("Error fetching Prachi stats")
        raise HTTPException(500, f"Error fetching Prachi stats: {str(e)}")


@app.get("/api/monitor/alerts", dependencies=[Depends(allow("admin", "ops"))])
def get_monitor_alerts(limit: int = 20):
    """Get recent alerts from sync/upload failures."""
    try:
        errors = db.get_recent_errors(limit=limit)

        # Format as alerts
        alerts = []
        for error in errors:
            timestamp = error["synced_at"]
            alert_type = f"{error['sync_type']}_sync"
            message = error["error_message"] or "Unknown error"

            alerts.append({
                "id": error["id"],
                "type": alert_type,
                "severity": "error",
                "message": message,
                "timestamp": timestamp
            })

        return {"alerts": alerts, "count": len(alerts)}
    except Exception as e:
        log.exception("Error fetching alerts")
        raise HTTPException(500, f"Error fetching alerts: {str(e)}")


@app.post("/api/monitor/sync-autogmap", dependencies=[Depends(allow("admin"))])
def trigger_autogmap_sync():
    """Trigger immediate AutoGMap numbers sync."""
    try:
        log.info("Manual AutoGMap sync requested")
        # AutoGMap syncs run on a scheduled interval (every AUTOGMAP_SYNC_INTERVAL_MINUTES)
        # The next sync will pick up any pending work
        return {"status": "queued", "message": "AutoGMap sync queued - will run on next interval"}
    except Exception as e:
        log.exception("Error triggering AutoGMap sync")
        raise HTTPException(500, f"Error triggering sync: {str(e)}")


@app.post("/api/monitor/retry-failed-uploads", dependencies=[Depends(allow("admin"))])
def retry_failed_uploads():
    """Retry failed AutoGMap recording uploads."""
    try:
        # Wake the recordings processing loop to retry uploads
        recordings.wake()
        return {"status": "retrying", "message": "Retry started for failed uploads"}
    except Exception as e:
        log.exception("Error retrying uploads")
        raise HTTPException(500, f"Error retrying uploads: {str(e)}")


# ------------------------------------------------------------------ simulator
class Simulate(BaseModel):
    calls: int = 10
    live: bool = True        # True: calls play out in real time so they appear as "ongoing"
    engine: str = "rules"    # rules = no LLM calls; auto = use the configured LLM if a key is present


@app.post("/api/simulate", dependencies=[Depends(allow(*STAFF))])
def simulate(body: Simulate):
    from .simulator import RealDataError, run_live, run_backfill, _test_csps
    try:
        _test_csps()                       # test CSPs only; refuses when there are none to call
    except RealDataError as e:
        raise HTTPException(409, str(e))
    n = max(1, min(body.calls, 50))
    if body.live:
        threading.Thread(target=run_live, args=(n, body.engine), daemon=True).start()
        return {"started": n, "mode": "live"}
    return run_backfill(n, days=0, engine=body.engine)


# ------------------------------------------------------------------ backup & restore (Phase 8)

@app.get("/api/backup/list", dependencies=[Depends(allow("admin"))])
def list_backups():
    """List all available backups with metadata."""
    from . import backup_restore
    try:
        backups = backup_restore.list_backups()
        return {"backups": backups, "total": len(backups)}
    except Exception as e:
        log.exception("Error listing backups")
        raise HTTPException(500, f"Error listing backups: {str(e)}")


@app.get("/api/backup/export", dependencies=[Depends(allow("admin"))])
def export_backup_endpoint(
    backup_type: str = Query("full", regex="^(full|filtered)$"),
    rm_id: int | None = None,
    dc_id: int | None = None,
    employee_id: int | None = None
):
    """Trigger database export and return ZIP file.

    Query parameters:
    - backup_type: "full" (all data) or "filtered" (mode-specific)
    - rm_id: For filtered exports (RM mode recordings)
    - dc_id: For filtered exports (DC mode recordings)
    - employee_id: For filtered exports (Employee mode recordings)
    """
    from . import backup_restore

    try:
        # Validate that only one mode filter is used
        mode_filters = [rm_id, dc_id, employee_id]
        if backup_type == "filtered" and sum(1 for m in mode_filters if m is not None) != 1:
            raise ValueError("For filtered exports, specify exactly one of: rm_id, dc_id, employee_id")

        # Determine backup type
        if backup_type == "filtered":
            actual_type = "filtered"
        else:
            actual_type = "full"

        result = backup_restore.export_database(
            backup_type=actual_type,
            rm_id=rm_id,
            dc_id=dc_id,
            employee_id=employee_id
        )

        backup_path = result["file_path"]
        filename = result["filename"]

        log.info(f"Backup export complete: {result['backup_id']}, {result['metadata']['compressed_size_mb']} MB")

        return FileResponse(
            backup_path,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    except ValueError as e:
        log.warning(f"Export validation error: {e}")
        raise HTTPException(400, str(e))
    except Exception as e:
        log.exception("Backup export failed")
        raise HTTPException(500, f"Export failed: {str(e)}")


@app.post("/api/backup/restore", dependencies=[Depends(allow("admin"))])
async def restore_backup_endpoint(backup_file: UploadFile = File(...)):
    """Upload and restore from backup file.

    Expected: ZIP file from /api/backup/export
    """
    from . import backup_restore

    if not backup_file.filename.endswith(".zip"):
        raise HTTPException(400, "File must be a .zip backup")

    try:
        file_content = await backup_file.read()

        # Validate before restoring
        validation = backup_restore.restore_database(
            backup_file_obj=io.BytesIO(file_content),
            validate_only=True
        )

        if validation["status"] != "valid":
            raise ValueError("Backup validation failed")

        # Perform actual restore
        result = backup_restore.restore_database(
            backup_file_obj=io.BytesIO(file_content),
            validate_only=False
        )

        log.info(f"Backup restored: {result['backup_id']}, {sum(result['record_counts'].values())} records")

        return result

    except ValueError as e:
        log.warning(f"Restore validation error: {e}")
        raise HTTPException(400, str(e))
    except Exception as e:
        log.exception("Backup restore failed")
        raise HTTPException(500, f"Restore failed: {str(e)}")


@app.get("/api/backup/download/{backup_id}", dependencies=[Depends(allow("admin"))])
def download_backup(backup_id: str):
    """Download a specific backup by ID."""
    from . import backup_restore

    try:
        backup = backup_restore.get_backup_by_id(backup_id)

        if not backup:
            raise HTTPException(404, f"Backup not found: {backup_id}")

        backup_path = backup["filepath"]

        if not os.path.exists(backup_path):
            raise HTTPException(404, "Backup file not found on disk")

        return FileResponse(
            backup_path,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{backup["filename"]}"'}
        )

    except HTTPException:
        raise
    except Exception as e:
        log.exception("Backup download failed")
        raise HTTPException(500, f"Download failed: {str(e)}")


@app.delete("/api/backup/{backup_id}", dependencies=[Depends(allow("admin"))])
def delete_backup_endpoint(backup_id: str):
    """Delete a backup by ID."""
    from . import backup_restore

    try:
        if backup_restore.delete_backup(backup_id):
            return {"ok": True, "message": f"Backup {backup_id} deleted"}
        else:
            raise HTTPException(404, f"Backup not found: {backup_id}")
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Backup deletion failed")
        raise HTTPException(500, f"Deletion failed: {str(e)}")


class BackupExportTableBody(BaseModel):
    table: str
    rm_id: int | None = None
    dc_id: int | None = None
    employee_id: int | None = None


@app.post("/api/backup/export-table", dependencies=[Depends(allow("admin"))])
def export_single_table(body: BackupExportTableBody):
    """Export a single table as JSON for detailed inspection or manual backup.

    Request body:
    {
        "table": "dcs",
        "rm_id": null,
        "dc_id": null,
        "employee_id": null
    }
    """
    from . import backup_restore

    try:
        json_data = backup_restore.export_table_to_json(
            body.table,
            rm_id=body.rm_id,
            dc_id=body.dc_id,
            employee_id=body.employee_id
        )

        # Parse back to get metadata
        records = json.loads(json_data)

        return {
            "table": body.table,
            "record_count": len(records),
            "records": records,
            "exported_at": time.time(),
        }

    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.exception("Table export failed")
        raise HTTPException(500, f"Export failed: {str(e)}")


@app.get("/api/backup/export-table/{table}", dependencies=[Depends(allow("admin"))])
def export_single_table_get(
    table: str,
    rm_id: int | None = None,
    dc_id: int | None = None,
    employee_id: int | None = None
):
    """Export a single table as JSON (GET method for convenience).

    Query parameters:
    - table: Table name (required)
    - rm_id: Optional filter for recordings
    - dc_id: Optional filter for recordings
    - employee_id: Optional filter for recordings
    """
    from . import backup_restore

    try:
        json_data = backup_restore.export_table_to_json(
            table,
            rm_id=rm_id,
            dc_id=dc_id,
            employee_id=employee_id
        )

        # Return as file download
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{table}_{timestamp}.json"

        return Response(
            json_data,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.exception("Table export failed")
        raise HTTPException(500, f"Export failed: {str(e)}")


@app.get("/api/backup/status", dependencies=[Depends(allow("admin"))])
def backup_status():
    """Get backup system status and statistics."""
    from . import backup_restore
    import os

    try:
        backups = backup_restore.list_backups()

        backups_dir = backup_restore.BACKUPS_DIR
        total_size_mb = 0
        if os.path.exists(backups_dir):
            for f in os.listdir(backups_dir):
                path = os.path.join(backups_dir, f)
                if os.path.isfile(path):
                    total_size_mb += os.path.getsize(path) / 1e6

        return {
            "status": "ok",
            "backups_count": len(backups),
            "total_size_mb": round(total_size_mb, 2),
            "backups_dir": backups_dir,
            "latest_backup": backups[0] if backups else None,
            "export_supported_tables": list(backup_restore.EXPORTABLE_TABLES.keys()),
        }

    except Exception as e:
        log.exception("Backup status check failed")
        raise HTTPException(500, f"Status check failed: {str(e)}")
