"""SQLite storage. Swap for Postgres later by replacing this module."""
import json
import os
import sqlite3
import threading
import time

# DATA_DIR: the writable, persistent folder the deploy platform gives the app (/data); everything else
# (recordings, voice models, the sign-in secret) is kept next to the database
DB_PATH = os.environ.get("EKO_DB_PATH") or os.path.join(
    os.environ.get("DATA_DIR") or os.path.join(os.path.dirname(__file__), "..", "data"), "eko_agent.db")
_lock = threading.RLock()

def _ensure_schema():
    """Add missing columns to recordings table if they don't exist."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.isolation_level = None  # Autocommit mode
        conn.execute("PRAGMA journal_mode=WAL")

        cols = {c[1] for c in conn.execute("PRAGMA table_info(recordings)").fetchall()}

        # Only add columns that don't exist
        for col, dtype in [("mode", "TEXT DEFAULT 'rm'"), ("dc_id", "INTEGER"), ("employee_id", "INTEGER")]:
            if col not in cols:
                try:
                    conn.execute(f"ALTER TABLE recordings ADD COLUMN {col} {dtype}")
                except sqlite3.OperationalError:
                    pass  # Column might already exist or table doesn't exist yet

        conn.commit()
        conn.close()
    except Exception as e:
        pass  # Silently fail - schema will be created on first use

SCHEMA = """
-- INVARIANT: All recordings and upload_tokens must satisfy mode/ID consistency:
--   mode='rm' => rm_id IS NOT NULL, dc_id IS NULL, employee_id IS NULL
--   mode='dc' => dc_id IS NOT NULL, rm_id IS NULL, employee_id IS NULL
--   mode='employee' => employee_id IS NOT NULL, rm_id IS NULL, dc_id IS NULL
-- This is enforced at the application level, not in the schema (for flexibility during migration).
-- See app/recordings.py and app/main.py for validation.

CREATE TABLE IF NOT EXISTS rms (
    id INTEGER PRIMARY KEY, name TEXT, phone TEXT, region TEXT,
    email TEXT,                -- from the calling sheet; a verified login with this email is linked to the RM
    source TEXT                -- demo (app/seed.py) | kb (imported from Eko's sheets, app/kb_import.py)
);
CREATE TABLE IF NOT EXISTS csps (
    id INTEGER PRIMARY KEY, csp_code TEXT UNIQUE, name TEXT, shop_name TEXT, phone TEXT UNIQUE,
    district TEXT, rm_id INTEGER REFERENCES rms(id),
    shared_phone TEXT,         -- a mobile number several CSPs gave; never used to recognise a caller
    alt_phone TEXT, email TEXT, category TEXT, state TEXT, lho TEXT, population TEXT,
    terminal_status TEXT, active INTEGER DEFAULT 1, source TEXT, import_id INTEGER, updated_at REAL
);
CREATE TABLE IF NOT EXISTS kb_imports (       -- every sheet imported into the knowledge base (app/kb_import.py)
    id INTEGER PRIMARY KEY, file_name TEXT, sha256 TEXT UNIQUE, kind TEXT, rows INTEGER,
    notes TEXT, imported_by TEXT, imported_at REAL
);
CREATE TABLE IF NOT EXISTS csp_monthly (      -- one row per CSP per month: targets, month-to-date achievement, slab
    csp_id INTEGER REFERENCES csps(id), month TEXT,   -- YYYY-MM
    pmjdy REAL, pmjjby REAL, pmsby REAL, apy REAL, slab TEXT,
    target_pmjdy REAL, target_pmjjby REAL, target_pmsby REAL, target_apy REAL, target_slab TEXT,
    txn_count REAL, commission REAL, import_id INTEGER, updated_at REAL,
    PRIMARY KEY (csp_id, month)
);
CREATE TABLE IF NOT EXISTS slabs (            -- the monthly DFS slab table (sheet "Slab")
    slab TEXT PRIMARY KEY, rank INTEGER, pmjdy INTEGER, pmjjby INTEGER, pmsby INTEGER, apy INTEGER,
    incentive_rs REAL, avg_balance_comm REAL, import_id INTEGER
);
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY,
    direction TEXT,            -- inbound | outbound
    purpose TEXT,              -- support | follow_up | activation | ...
    csp_id INTEGER, rm_id INTEGER, caller_phone TEXT,
    status TEXT,               -- ongoing | ended
    outcome TEXT,              -- ticket_raised | escalated | not_understood | resolved_by_agent | dropped | info_only
    intent TEXT, intent_confidence REAL, language TEXT, sentiment TEXT,
    slots_json TEXT DEFAULT '{}',
    misunderstood_streak INTEGER DEFAULT 0, misunderstood_total INTEGER DEFAULT 0,
    turn_count INTEGER DEFAULT 0,
    started_at REAL, ended_at REAL, duration_sec REAL,
    engine TEXT, summary TEXT, ticket_id INTEGER, escalation_reason TEXT
);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY, call_id INTEGER, role TEXT, text TEXT, ts REAL,
    stt_confidence REAL, latency_ms REAL, input_tokens INTEGER, output_tokens INTEGER,
    engine TEXT, intent TEXT, intent_confidence REAL, error TEXT
);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY, ticket_no TEXT UNIQUE, call_id INTEGER, csp_id INTEGER, rm_id INTEGER,
    category TEXT,             -- category predicted by the agent
    rm_category TEXT,          -- category confirmed/corrected by the RM (ground truth for accuracy)
    priority TEXT, status TEXT, -- open | in_progress | resolved | closed
    escalated INTEGER DEFAULT 0, escalation_reason TEXT,
    summary TEXT, details_json TEXT DEFAULT '{}', slot_completeness REAL,
    created_at REAL, updated_at REAL, closed_at REAL, sla_due_at REAL
);
CREATE TABLE IF NOT EXISTS ticket_events (
    id INTEGER PRIMARY KEY, ticket_id INTEGER, ts REAL, actor TEXT, action TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, email TEXT UNIQUE, name TEXT, password_hash TEXT,
    rm_id INTEGER REFERENCES rms(id),   -- set when the user is one of the RMs
    role TEXT,                          -- admin | ops | rm | pending
    created_at REAL, last_login_at REAL,
    email_verified_at REAL, password_changed_at REAL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id), created_at REAL, expires_at REAL,
    last_seen_at REAL, ip TEXT, user_agent TEXT
);
CREATE TABLE IF NOT EXISTS auth_tokens (      -- one-time links sent by email: password reset, email verification
    id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id),
    purpose TEXT,              -- reset | verify
    token_hash TEXT UNIQUE, email TEXT, created_at REAL, expires_at REAL, used_at REAL
);
CREATE TABLE IF NOT EXISTS auth_events (      -- sign-ins, failures, resets, role changes (also drives the lockout)
    id INTEGER PRIMARY KEY, ts REAL, user_id INTEGER, email TEXT, event TEXT, ip TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS dcs (              -- Data Collectors (for DC mode uploader)
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT UNIQUE, email TEXT UNIQUE, region TEXT,
    created_by TEXT, created_at REAL, active INTEGER DEFAULT 1, updated_at REAL
);
CREATE TABLE IF NOT EXISTS employees (        -- Employees (for Employee mode uploader)
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT UNIQUE, email TEXT UNIQUE, department TEXT,
    created_by TEXT, created_at REAL, active INTEGER DEFAULT 1, updated_at REAL
);
CREATE TABLE IF NOT EXISTS allowed_numbers (  -- Phone numbers DCs can upload from
    id INTEGER PRIMARY KEY, dc_id INTEGER REFERENCES dcs(id), phone_number TEXT NOT NULL,
    description TEXT, added_by TEXT, added_at REAL, active INTEGER DEFAULT 1, UNIQUE(dc_id, phone_number)
);
CREATE TABLE IF NOT EXISTS dc_consents (      -- One-time consent tracking for DC mode
    id INTEGER PRIMARY KEY, dc_id INTEGER REFERENCES dcs(id), call_phone TEXT,
    consented_at REAL, consent_token TEXT NOT NULL UNIQUE, expires_at REAL, used_at REAL
);
CREATE TABLE IF NOT EXISTS upload_tokens (   -- one per RM/DC/Employee phone running the uploader app (uploader/)
    id INTEGER PRIMARY KEY, token_hash TEXT UNIQUE, rm_id INTEGER REFERENCES rms(id),
    dc_id INTEGER REFERENCES dcs(id), employee_id INTEGER REFERENCES employees(id),
    mode TEXT DEFAULT 'rm', label TEXT,
    created_by TEXT, created_at REAL, last_used_at REAL, revoked_at REAL
);
CREATE TABLE IF NOT EXISTS recordings (      -- real RM-CSP call recordings from the Eko SIM (app/recordings.py)
    id INTEGER PRIMARY KEY, sha256 TEXT UNIQUE, rm_id INTEGER, dc_id INTEGER, employee_id INTEGER,
    token_id INTEGER, device_id TEXT, mode TEXT DEFAULT 'rm',
    file_path TEXT, orig_name TEXT, size_bytes INTEGER,
    started_at REAL, duration_sec REAL, direction TEXT, other_number TEXT, csp_id INTEGER, uploaded_at REAL,
    status TEXT,               -- new | done | failed
    attempts INTEGER DEFAULT 0, error TEXT, processed_at REAL,
    is_csp_call INTEGER, language TEXT, transcript_json TEXT, issue_segment INTEGER,
    intent TEXT, intent_confidence REAL, slots_json TEXT, sentiment TEXT, resolution TEXT,
    rm_handling TEXT, summary TEXT, model TEXT,
    prachi_api_sent_at REAL, prachi_request_id TEXT,
    mansi_api_sent_at REAL, mansi_request_id TEXT
);
CREATE TABLE IF NOT EXISTS prachi_submissions (  -- DC recordings submitted to Prachi API (Phase 7, app/main.py)
    id INTEGER PRIMARY KEY, recording_id INTEGER UNIQUE, dc_id INTEGER, dc_name TEXT,
    dc_phone TEXT, caller_number TEXT, recipient_number TEXT, call_direction TEXT,
    duration_sec INTEGER, uploaded_at TEXT, transcript TEXT, transcript_json TEXT,
    file_path TEXT, status TEXT, attempts INTEGER,
    prachi_request_id TEXT, received_at REAL, processed_at REAL, error_message TEXT
);
CREATE TABLE IF NOT EXISTS autogmap_numbers (     -- Phase 7a: Cached AutoGMap applicant numbers
    id INTEGER PRIMARY KEY, phone VARCHAR(20) UNIQUE NOT NULL, local VARCHAR(10),
    name TEXT, since TEXT,                       -- since: when they became an applicant (ISO format)
    synced_at REAL,                              -- when we last synced this record
    active INTEGER DEFAULT 1                     -- 0 if they stopped being an applicant
);
CREATE TABLE IF NOT EXISTS api_keys (         -- other systems calling the API (app/integrations.py)
    id INTEGER PRIMARY KEY, key_hash TEXT UNIQUE, name TEXT, role TEXT, created_by TEXT,
    created_at REAL, last_used_at REAL, revoked_at REAL
);
CREATE TABLE IF NOT EXISTS webhooks (         -- other systems told about events (app/integrations.py)
    id INTEGER PRIMARY KEY, url TEXT, events TEXT, secret TEXT, active INTEGER DEFAULT 1, created_by TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS webhook_deliveries (   -- outbox: one row per event per webhook
    id INTEGER PRIMARY KEY, webhook_id INTEGER, event TEXT, payload TEXT,
    status TEXT,               -- pending | delivered | failed
    attempts INTEGER DEFAULT 0, next_attempt_at REAL, last_status_code INTEGER, last_error TEXT,
    created_at REAL, delivered_at REAL
);
CREATE TABLE IF NOT EXISTS approvals (          -- Phase 3: approval workflow audit trail
    id INTEGER PRIMARY KEY, call_id INTEGER, turn_id INTEGER,
    action TEXT,               -- create_ticket, escalate, etc. (from tool registry)
    status TEXT,               -- pending | approved | denied
    reason TEXT,               -- why approval was requested
    decision_json TEXT,        -- the agent's proposed decision
    edited_decision_json TEXT, -- if approver changed it
    created_at REAL, expires_at REAL,
    approved_by TEXT, approved_at REAL,
    denied_by TEXT, denied_at REAL, denial_reason TEXT
);
CREATE TABLE IF NOT EXISTS traces (           -- every engine decision, frozen as it happened (app/telemetry.py)
    id INTEGER PRIMARY KEY, call_id INTEGER, turn_id INTEGER, ts REAL, engine TEXT, model TEXT,
    prompt_version TEXT,       -- fingerprint of the prompt code; metrics are split by it
    system_prompt TEXT, messages_json TEXT,
    context_json TEXT,         -- the CSP data, past tickets and slots put into the prompt
    raw_output_json TEXT,      -- the model's tool call exactly as returned
    output_json TEXT,          -- the decision after cleaning (slots mapped, IDs joined)
    latency_ms REAL, input_tokens INTEGER, output_tokens INTEGER, error TEXT,
    tier_tokens_json TEXT,     -- {"system": N, "context": N, "history": N, "output": N} for accounting
    wiped_chips_json TEXT      -- Phase 4: {"tickets": [ids], "slots": [keys], "messages": [indices]} of wiped context
);
CREATE TABLE IF NOT EXISTS context_wipes (    -- Phase 4: audit trail of context chips removed from traces
    id INTEGER PRIMARY KEY, trace_id INTEGER, ts REAL, wiped_by TEXT,
    chip_type TEXT,            -- ticket | slot | message (what was wiped)
    chip_id TEXT,              -- ticket_no | slot_key | message_index
    chip_value TEXT,           -- the actual value that was wiped (for audit)
    reason TEXT                -- why it was wiped (compliance, redaction, etc.)
);
CREATE TABLE IF NOT EXISTS prompt_versions (  -- Phase 5: track all unique prompt code versions
    id INTEGER PRIMARY KEY, version_hash TEXT UNIQUE,
    prompt_code TEXT,          -- full source code of _system_prompt function
    tool_schema_json TEXT,     -- AGENT_TURN_TOOL dict
    tier_high TEXT,            -- system instructions (frozen core)
    tier_medium_template TEXT, -- template with {csp}, {tickets}, {slots} placeholders
    tier_low_template TEXT,    -- template with {intent}, {confidence}, {history}
    full_prompt TEXT,          -- complete generated prompt (for display/archive)
    created_at REAL, created_by TEXT, notes TEXT,
    status TEXT,               -- draft | baseline | active | deprecated
    git_commit TEXT            -- git SHA if deployed from repo
);
CREATE TABLE IF NOT EXISTS scorecard_baselines (  -- Phase 5: eval results for each version
    id INTEGER PRIMARY KEY, version_hash TEXT,
    eval_timestamp REAL, results_json TEXT,  -- CSV rows as JSON array
    summary_json TEXT,         -- summary.json dict with overall scores
    eval_by TEXT,              -- who ran the eval
    accepted_at REAL, accepted_by TEXT,     -- when the baseline was approved
    FOREIGN KEY (version_hash) REFERENCES prompt_versions(version_hash)
);
CREATE TABLE IF NOT EXISTS prompt_drifts (        -- Phase 5: detected drifts from baseline
    id INTEGER PRIMARY KEY,
    previous_version_id INTEGER, current_version_id INTEGER,
    detected_at REAL, detected_by TEXT,           -- "automatic" or ops email
    drift_type TEXT,           -- code_changed | behavior_diverged | quality_drop
    prompt_diff TEXT,          -- unified diff of tier_high/medium/low

    -- Live metrics (observed in recent traces)
    live_intent_pct REAL, live_action_pct REAL, live_details_pct REAL,
    live_latency_p95 REAL, live_calls_analyzed INTEGER,

    -- Replay results
    replay_status TEXT,        -- pending | in_progress | complete
    replay_results_json TEXT,  -- {baseline: {...}, candidate: {...}, diff: {...}}

    status TEXT,               -- flagged | under_review | approved | rejected
    decision_json TEXT,        -- approver's decision + any edits
    approved_by TEXT, approved_at REAL,
    rejected_by TEXT, rejected_at REAL, rejection_reason TEXT,

    FOREIGN KEY (previous_version_id) REFERENCES prompt_versions(id),
    FOREIGN KEY (current_version_id) REFERENCES prompt_versions(id)
);
CREATE TABLE IF NOT EXISTS test_runs (            -- Phase 5: individual test case results
    prompt_version_id INTEGER, test_case_id TEXT, run_timestamp REAL,
    eval_engine TEXT, eval_model TEXT,
    intent_correct BOOLEAN, action_correct BOOLEAN,
    slots_correct_json TEXT,   -- {slot_key: true/false}
    latency_ms REAL,
    call_id INTEGER,           -- if from a real call
    synthetic BOOLEAN,         -- if from evals replay

    FOREIGN KEY (prompt_version_id) REFERENCES prompt_versions(id),
    PRIMARY KEY (prompt_version_id, test_case_id, run_timestamp)
);
CREATE TABLE IF NOT EXISTS replay_requests (     -- Phase 5: async replay orchestration
    id INTEGER PRIMARY KEY,
    drift_id INTEGER, requested_at REAL, requested_by TEXT,
    baseline_version_id INTEGER, candidate_version_id INTEGER,
    status TEXT,               -- pending | running | complete | failed
    test_count INTEGER, started_at REAL, completed_at REAL,
    results_json TEXT,         -- {baseline: {...}, candidate: {...}, diff: {...}}
    error TEXT,

    FOREIGN KEY (drift_id) REFERENCES prompt_drifts(id),
    FOREIGN KEY (baseline_version_id) REFERENCES prompt_versions(id),
    FOREIGN KEY (candidate_version_id) REFERENCES prompt_versions(id)
);
CREATE TABLE IF NOT EXISTS corrections (      -- a person changed something the agent produced (app/telemetry.py)
    id INTEGER PRIMARY KEY, ts REAL, source TEXT, ref_id INTEGER, call_id INTEGER,
    field TEXT,                -- summary | category | detail:<slot>
    before TEXT, after TEXT, distance INTEGER, delta REAL, actor TEXT, prompt_version TEXT
);
CREATE TABLE IF NOT EXISTS misheard_blocked (  -- misheard-word pairs kept out of the prompts (app/misheard.py)
    heard TEXT, said TEXT, by TEXT, at REAL, PRIMARY KEY (heard, said)
);
CREATE TABLE IF NOT EXISTS prachi_sync_history (  -- Audit trail for Prachi Google Sheets syncs (app/prachi_sync.py)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_type TEXT,             -- 'dcs' | 'sbi_officials' | 'dcs_and_officials'
    status TEXT,                -- 'success' | 'failed' | 'degraded'
    records_processed INTEGER,  -- total records from the sheet
    records_added INTEGER,      -- new records inserted
    records_updated INTEGER,    -- existing records updated
    records_deleted INTEGER,    -- records marked inactive (soft delete)
    error_message TEXT,         -- error details if failed
    sync_source TEXT,           -- 'api' | 'excel' | 'manual' (PRIMARY: api, SECONDARY: excel/manual override)
    synced_at REAL              -- when the sync completed
);
CREATE INDEX IF NOT EXISTS idx_traces_call ON traces(call_id);
CREATE INDEX IF NOT EXISTS idx_context_wipes_trace ON context_wipes(trace_id);
CREATE INDEX IF NOT EXISTS idx_prompt_versions_hash ON prompt_versions(version_hash);
CREATE INDEX IF NOT EXISTS idx_prompt_versions_status ON prompt_versions(status);
CREATE INDEX IF NOT EXISTS idx_prompt_drifts_previous ON prompt_drifts(previous_version_id);
CREATE INDEX IF NOT EXISTS idx_prompt_drifts_current ON prompt_drifts(current_version_id);
CREATE INDEX IF NOT EXISTS idx_prompt_drifts_status ON prompt_drifts(status, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_test_runs_version ON test_runs(prompt_version_id);
CREATE INDEX IF NOT EXISTS idx_test_runs_case ON test_runs(test_case_id);
CREATE INDEX IF NOT EXISTS idx_replay_requests_drift ON replay_requests(drift_id);
CREATE INDEX IF NOT EXISTS idx_replay_requests_status ON replay_requests(status);
CREATE INDEX IF NOT EXISTS idx_corrections_ref ON corrections(source, ref_id);
CREATE INDEX IF NOT EXISTS idx_auth_events_email ON auth_events(email, event, ts);
CREATE INDEX IF NOT EXISTS idx_deliveries_due ON webhook_deliveries(status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_recordings_status ON recordings(status, uploaded_at);
CREATE INDEX IF NOT EXISTS idx_recordings_mode ON recordings(mode, uploaded_at DESC);
CREATE INDEX IF NOT EXISTS idx_recordings_dc ON recordings(dc_id, uploaded_at DESC) WHERE dc_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_recordings_employee ON recordings(employee_id, uploaded_at DESC) WHERE employee_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_recordings_rm ON recordings(rm_id, uploaded_at DESC) WHERE rm_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_allowed_numbers_dc ON allowed_numbers(dc_id, phone_number);
CREATE INDEX IF NOT EXISTS idx_upload_tokens_rm ON upload_tokens(rm_id) WHERE rm_id IS NOT NULL AND mode='rm';
CREATE INDEX IF NOT EXISTS idx_upload_tokens_dc ON upload_tokens(dc_id) WHERE dc_id IS NOT NULL AND mode='dc';
CREATE INDEX IF NOT EXISTS idx_upload_tokens_employee ON upload_tokens(employee_id) WHERE employee_id IS NOT NULL AND mode='employee';
CREATE INDEX IF NOT EXISTS idx_calls_started ON calls(started_at);
CREATE INDEX IF NOT EXISTS idx_turns_call ON turns(call_id);
CREATE INDEX IF NOT EXISTS idx_tickets_rm ON tickets(rm_id, status);
CREATE INDEX IF NOT EXISTS idx_autogmap_phone ON autogmap_numbers(phone);
CREATE INDEX IF NOT EXISTS idx_autogmap_active ON autogmap_numbers(active, synced_at DESC);
CREATE INDEX IF NOT EXISTS idx_prachi_sync_history_status ON prachi_sync_history(status, synced_at DESC);
CREATE INDEX IF NOT EXISTS idx_prachi_sync_history_type ON prachi_sync_history(sync_type, synced_at DESC);
"""

_conn = None


def conn(retry=True) -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=FULL")
        _conn.execute("PRAGMA wal_autocheckpoint=1000")
        try:
            _conn.executescript(SCHEMA)
        except sqlite3.OperationalError as e:
            if "mode" in str(e) or "column" in str(e):
                pass  # Schema issue - columns may not exist yet, will be added below
            else:
                raise
        # Migrations for databases created by older versions
        if "lang" not in {r[1] for r in _conn.execute("PRAGMA table_info(calls)")}:
            _conn.execute("ALTER TABLE calls ADD COLUMN lang TEXT")  # 'ask' | 'hi' | 'en'
            _conn.commit()
        if "touched_at" not in {r[1] for r in _conn.execute("PRAGMA table_info(calls)")}:
            # Real wall-clock time of the last activity (call `ts` can be in the past for simulated calls)
            _conn.execute("ALTER TABLE calls ADD COLUMN touched_at REAL")
            _conn.commit()
        if "model" not in {r[1] for r in _conn.execute("PRAGMA table_info(turns)")}:
            _conn.execute("ALTER TABLE turns ADD COLUMN model TEXT")   # which LLM answered this turn
            _conn.commit()
        if "report_md" not in {r[1] for r in _conn.execute("PRAGMA table_info(recordings)")}:
            for col in ("report_md TEXT", "report_error TEXT", "report_at REAL", "report_s REAL", "report_model TEXT"):
                _conn.execute(f"ALTER TABLE recordings ADD COLUMN {col}")    # the full summary (app/report.py)
            _conn.commit()
        if "timing_json" not in {r[1] for r in _conn.execute("PRAGMA table_info(recordings)")}:
            _conn.execute("ALTER TABLE recordings ADD COLUMN timing_json TEXT")   # how long each step took
            _conn.commit()
        if "stt_json" not in {r[1] for r in _conn.execute("PRAGMA table_info(recordings)")}:
            # Whisper's words and the voice turns, kept so "Process again" doesn't redo the slow, paid parts
            _conn.execute("ALTER TABLE recordings ADD COLUMN stt_json TEXT")
            _conn.commit()
        if "next_try_at" not in {r[1] for r in _conn.execute("PRAGMA table_info(recordings)")}:
            _conn.execute("ALTER TABLE recordings ADD COLUMN next_try_at REAL")   # when a failed one is retried
            _conn.commit()
        if "simulated" not in {r[1] for r in _conn.execute("PRAGMA table_info(calls)")}:
            # Simulated calls send no webhook events. Every call so far was a demo or a console test
            _conn.execute("ALTER TABLE calls ADD COLUMN simulated INTEGER DEFAULT 0")
            _conn.execute("UPDATE calls SET simulated=1")
        # Phase 4+ migrations: mode, dc_id, employee_id for mode-aware recordings
        for col, dtype in [("mode", "TEXT DEFAULT 'rm'"), ("dc_id", "INTEGER"), ("employee_id", "INTEGER")]:
            if col not in {r[1] for r in _conn.execute("PRAGMA table_info(recordings)")}:
                try:
                    _conn.execute(f"ALTER TABLE recordings ADD COLUMN {col} {dtype}")
                    _conn.commit()
                except sqlite3.OperationalError:
                    pass
            _conn.commit()
        if "role" not in {r[1] for r in _conn.execute("PRAGMA table_info(users)")}:
            # Accounts made before roles existed: the first becomes admin, RM-linked ones RMs, the rest ops
            _conn.execute("ALTER TABLE users ADD COLUMN role TEXT")
            _conn.execute("""UPDATE users SET role = CASE WHEN id = (SELECT MIN(id) FROM users) THEN 'admin'
                             WHEN rm_id IS NOT NULL THEN 'rm' ELSE 'ops' END""")
            _conn.commit()
        _add_columns(_conn, "rms", {"email": "TEXT", "source": "TEXT"}, demo_source=True)
        _add_columns(_conn, "csps", {"shared_phone": "TEXT", "alt_phone": "TEXT", "email": "TEXT", "category": "TEXT",
                                     "state": "TEXT", "lho": "TEXT", "population": "TEXT", "terminal_status": "TEXT",
                                     "active": "INTEGER DEFAULT 1", "source": "TEXT", "import_id": "INTEGER",
                                     "updated_at": "REAL"}, demo_source=True)
        _add_columns(_conn, "users", {"email_verified_at": "REAL", "password_changed_at": "REAL",
                                      "google_sub": "TEXT",               # the Google account, for Sign in with Google
                                      "must_verify": "INTEGER DEFAULT 0"})  # password signup not yet confirmed
        # A person's corrections to a recording (app/recordings.py save_edits). agent_* hold the machine's version
        # while a person's text is shown; NULL = the current text is the machine's own
        _add_columns(_conn, "recordings", {"agent_summary": "TEXT", "agent_report_md": "TEXT",
                                           "agent_intent": "TEXT", "agent_slots_json": "TEXT",
                                           "transcript_edited_at": "REAL", "edited_at": "REAL", "edited_by": "TEXT",
                                           "removed_json": "TEXT",       # lines a person removed (nobody said them)
                                           # a person checked the whole transcript: its word errors against theirs
                                           "checked_at": "REAL", "checked_by": "TEXT",
                                           "stt_errors": "INTEGER", "stt_words": "INTEGER",
                                           "issue_checked_at": "REAL", "issue_checked_by": "TEXT",
                                           "stt_confidence": "REAL",     # Whisper's own certainty, 0-1
                                           "call_type": "TEXT DEFAULT 'rm'"})  # 'rm' (RM-CSP) or 'dc' (DC-official)
        if "agent_summary" not in {r[1] for r in _conn.execute("PRAGMA table_info(tickets)")}:
            # The agent's own version of a ticket, kept when an RM edits it (correction delta, acceptance rate)
            _add_columns(_conn, "tickets", {"agent_summary": "TEXT", "agent_details_json": "TEXT",
                                            "reviewed_at": "REAL", "reviewed_by": "TEXT"})
            _conn.execute("UPDATE tickets SET agent_summary=summary, agent_details_json=details_json")
            _conn.commit()
        _add_columns(_conn, "sessions", {"last_seen_at": "REAL", "ip": "TEXT", "user_agent": "TEXT"})
        _add_columns(_conn, "traces", {"tier_tokens_json": "TEXT"})  # Phase 1: context tier accounting
        # Phase 5: Drift detection - handle old prompt_versions that may have prompt_hash instead of version_hash
        try:
            table_exists = _conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='prompt_versions'").fetchone()
            if table_exists:
                cols = {r[1] for r in _conn.execute("PRAGMA table_info(prompt_versions)")}
                if "prompt_hash" in cols and "version_hash" not in cols:
                    _conn.execute("ALTER TABLE prompt_versions RENAME COLUMN prompt_hash TO version_hash")
                    _conn.commit()
                _add_columns(_conn, "prompt_versions", {
                    "prompt_code": "TEXT",
                    "tool_schema_json": "TEXT"
                })
        except Exception as e:
            pass  # May fail if migrations were already applied or table doesn't exist yet
        # Multi-use-case uploader extension: add DC/Employee support
        try:
            _add_columns(_conn, "upload_tokens", {
                "mode": "TEXT DEFAULT 'rm'",
                "dc_id": "INTEGER REFERENCES dcs(id)",
                "employee_id": "INTEGER REFERENCES employees(id)"
            })
            _add_columns(_conn, "recordings", {
                "mode": "TEXT DEFAULT 'rm'",
                "dc_id": "INTEGER REFERENCES dcs(id)",
                "employee_id": "INTEGER REFERENCES employees(id)",
                "prachi_api_sent_at": "REAL",
                "prachi_request_id": "TEXT",
                "mansi_api_sent_at": "REAL",
                "mansi_request_id": "TEXT"
            })
        except Exception as e:
            pass  # Migrations may already be applied or table doesn't exist
        # Phase 7a: AutoGMap integration columns
        try:
            _add_columns(_conn, "recordings", {
                "autogmap_status": "VARCHAR(20)",      # pending | uploaded | failed | not_in_applicants
                "autogmap_sent_at": "REAL",            # when we sent it to AutoGMap
                "autogmap_error": "TEXT",              # error message if failed
                "autogmap_attempts": "INTEGER DEFAULT 0"  # retry count
            })
            _conn.execute("CREATE INDEX IF NOT EXISTS idx_recordings_autogmap ON recordings(autogmap_status, uploaded_at DESC)")
            _conn.commit()
        except Exception as e:
            pass  # Migrations may already be applied or table doesn't exist
        # Phase 7b: Applicant Numbers admin management
        try:
            _add_columns(_conn, "autogmap_numbers", {
                "description": "TEXT",                 # optional notes about the applicant
                "created_by": "TEXT",                  # who uploaded/added this number
                "created_at": "REAL"                   # when it was added to the system
            })
            _conn.execute("CREATE INDEX IF NOT EXISTS idx_autogmap_created ON autogmap_numbers(created_at DESC)")
            _conn.commit()
        except Exception as e:
            pass  # Migrations may already be applied or table doesn't exist
        # Prachi Sync Refactor: Add sync_source column to track API primary vs manual Excel override
        try:
            _add_columns(_conn, "prachi_sync_history", {
                "sync_source": "TEXT"  # 'api' (primary) | 'excel' (manual override)
            })
            _conn.commit()
        except Exception as e:
            pass  # Migration may already be applied or table doesn't exist
    return _conn


def _add_columns(c: sqlite3.Connection, table: str, cols: dict, demo_source: bool = False):
    have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
    for name, kind in cols.items():
        if name not in have:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
            if name == "source" and demo_source:
                c.execute(f"UPDATE {table} SET source='demo'")   # everything before the import was demo data
    c.commit()
    c.execute("PRAGMA wal_checkpoint(RESTART)")


def reset_connection(path: str | None = None):
    """Used by tests to point at a fresh database."""
    global _conn, DB_PATH
    if _conn is not None:
        _conn.close()
    _conn = None
    if path:
        DB_PATH = path


def q(sql: str, args=(), one=False):
    with _lock:
        cur = conn().execute(sql, args)
        rows = [dict(r) for r in cur.fetchall()]
    return (rows[0] if rows else None) if one else rows


def x(sql: str, args=()) -> int:
    with _lock:
        cur = conn().execute(sql, args)
        conn().commit()
        conn().execute("PRAGMA wal_checkpoint(RESTART)")
        return cur.lastrowid


def update(table: str, row_id: int, **fields):
    if not fields:
        return
    for k, v in list(fields.items()):
        if isinstance(v, (dict, list)):
            fields[k] = json.dumps(v, ensure_ascii=False)
    cols = ", ".join(f"{k}=?" for k in fields)
    x(f"UPDATE {table} SET {cols} WHERE id=?", (*fields.values(), row_id))


def now() -> float:
    return time.time()


# ---- MONITORING DASHBOARD HELPERS (Phase 7d) ----

def get_autogmap_sync_stats(days: int = 7) -> dict:
    """Get AutoGMap numbers sync statistics for the last N days."""
    cutoff = now() - (days * 86400)
    syncs = q("""
        SELECT
            COUNT(*) as total_syncs,
            SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as successful_syncs,
            SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed_syncs,
            MAX(synced_at) as last_sync_time
        FROM prachi_sync_history
        WHERE synced_at > ? AND sync_type IN ('dcs', 'dcs_and_officials')
    """, (cutoff,), one=True)

    if not syncs or syncs['total_syncs'] == 0:
        return {
            "last_sync_time": None,
            "status": "UNKNOWN",
            "total_syncs": 0,
            "success_count": 0,
            "failure_count": 0,
            "success_rate": None,
            "numbers_count": 0
        }

    success_rate = (syncs['successful_syncs'] / syncs['total_syncs']) * 100 if syncs['total_syncs'] > 0 else 0
    numbers_count = q("SELECT COUNT(*) as count FROM autogmap_numbers WHERE active=1", one=True)['count']

    # Determine status based on success rate
    if success_rate >= 95:
        status = "OK"
    elif success_rate >= 50:
        status = "DEGRADED"
    else:
        status = "ERROR"

    return {
        "last_sync_time": syncs['last_sync_time'],
        "status": status,
        "total_syncs": syncs['total_syncs'],
        "success_count": syncs['successful_syncs'],
        "failure_count": syncs['failed_syncs'],
        "success_rate": round(success_rate, 2),
        "numbers_count": numbers_count
    }


def get_autogmap_upload_stats(hours: int = 24) -> dict:
    """Get recording upload statistics to AutoGMap for the last N hours."""
    cutoff = now() - (hours * 3600)
    uploads = q("""
        SELECT
            COUNT(*) as total_uploads,
            SUM(CASE WHEN autogmap_status='uploaded' THEN 1 ELSE 0 END) as successful,
            SUM(CASE WHEN autogmap_status='failed' THEN 1 ELSE 0 END) as failed,
            SUM(CASE WHEN autogmap_status='pending' THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN autogmap_status='not_in_applicants' THEN 1 ELSE 0 END) as not_in_applicants,
            AVG(CASE WHEN autogmap_sent_at IS NOT NULL THEN (autogmap_sent_at - uploaded_at) ELSE NULL END) as avg_upload_time_sec,
            MAX(autogmap_sent_at) as last_upload_time
        FROM recordings
        WHERE mode='rm' AND autogmap_status IS NOT NULL AND uploaded_at > ?
    """, (cutoff,), one=True)

    if not uploads or uploads['total_uploads'] == 0:
        return {
            "last_upload_time": None,
            "status": "UNKNOWN",
            "total_uploads": 0,
            "successful": 0,
            "failed": 0,
            "pending": 0,
            "not_in_applicants": 0,
            "success_rate": None,
            "avg_upload_time_sec": None,
            "retry_queue_size": 0
        }

    success_rate = (uploads['successful'] / uploads['total_uploads']) * 100 if uploads['total_uploads'] > 0 else 0
    retry_queue = q("SELECT COUNT(*) as count FROM recordings WHERE autogmap_status='pending' AND uploaded_at > ?", (cutoff,), one=True)['count']

    # Determine status
    if success_rate >= 95:
        status = "OK"
    elif success_rate >= 50:
        status = "DEGRADED"
    else:
        status = "ERROR"

    return {
        "last_upload_time": uploads['last_upload_time'],
        "status": status,
        "total_uploads": uploads['total_uploads'],
        "successful": uploads['successful'],
        "failed": uploads['failed'],
        "pending": uploads['pending'],
        "not_in_applicants": uploads['not_in_applicants'],
        "success_rate": round(success_rate, 2),
        "avg_upload_time_sec": round(uploads['avg_upload_time_sec'], 2) if uploads['avg_upload_time_sec'] else None,
        "retry_queue_size": retry_queue
    }


def get_prachi_sync_stats() -> dict:
    """Get Prachi Google Sheets sync statistics."""
    # Get the last sync for each type
    dcs_sync = q("""
        SELECT status, synced_at, records_added, records_updated, records_deleted, error_message
        FROM prachi_sync_history
        WHERE sync_type IN ('dcs', 'dcs_and_officials')
        ORDER BY synced_at DESC
        LIMIT 1
    """, one=True)

    if not dcs_sync:
        return {
            "last_sync_time": None,
            "status": "UNKNOWN",
            "dcs_count": 0,
            "officials_count": 0,
            "last_changes": {
                "dcs_added": 0,
                "dcs_updated": 0,
                "dcs_deleted": 0,
                "officials_added": 0,
                "officials_updated": 0,
                "officials_deleted": 0
            }
        }

    status = "OK" if dcs_sync['status'] == 'success' else "ERROR"
    dcs_count = q("SELECT COUNT(*) as count FROM dcs WHERE active=1", one=True)['count']
    officials_count = q("SELECT COUNT(*) as count FROM allowed_numbers WHERE active=1", one=True)['count']

    return {
        "last_sync_time": dcs_sync['synced_at'],
        "status": status,
        "dcs_count": dcs_count,
        "officials_count": officials_count,
        "last_changes": {
            "dcs_added": dcs_sync['records_added'] if dcs_sync['records_added'] else 0,
            "dcs_updated": dcs_sync['records_updated'] if dcs_sync['records_updated'] else 0,
            "dcs_deleted": dcs_sync['records_deleted'] if dcs_sync['records_deleted'] else 0,
            "officials_added": 0,
            "officials_updated": 0,
            "officials_deleted": 0
        }
    }


def get_prachi_submission_stats(hours: int = 24) -> dict:
    """Get Prachi API submission statistics for the last N hours."""
    cutoff = now() - (hours * 3600)
    submissions = q("""
        SELECT
            COUNT(*) as total_submissions,
            SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as successful,
            SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed,
            SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending,
            AVG(CASE WHEN processed_at IS NOT NULL THEN (processed_at - received_at) ELSE NULL END) as avg_response_time_sec,
            MAX(received_at) as last_submission_time
        FROM prachi_submissions
        WHERE received_at > ?
    """, (cutoff,), one=True)

    if not submissions or submissions['total_submissions'] == 0:
        return {
            "last_submission_time": None,
            "status": "UNKNOWN",
            "total_submissions": 0,
            "successful": 0,
            "failed": 0,
            "pending": 0,
            "success_rate": None,
            "avg_response_time_sec": None
        }

    success_rate = (submissions['successful'] / submissions['total_submissions']) * 100 if submissions['total_submissions'] > 0 else 0
    status = "OK" if success_rate >= 95 else ("DEGRADED" if success_rate >= 50 else "ERROR")

    return {
        "last_submission_time": submissions['last_submission_time'],
        "status": status,
        "total_submissions": submissions['total_submissions'],
        "successful": submissions['successful'],
        "failed": submissions['failed'],
        "pending": submissions['pending'],
        "success_rate": round(success_rate, 2),
        "avg_response_time_sec": round(submissions['avg_response_time_sec'], 2) if submissions['avg_response_time_sec'] else None
    }


def get_recent_errors(limit: int = 20) -> list:
    """Get recent sync/upload errors from prachi_sync_history."""
    errors = q("""
        SELECT id, sync_type, status, error_message, synced_at
        FROM prachi_sync_history
        WHERE status='failed'
        ORDER BY synced_at DESC
        LIMIT ?
    """, (limit,))

    return errors


def get_system_health() -> dict:
    """Get overall system health status."""
    try:
        # Database connection check
        test = q("SELECT 1", one=True)
        db_status = "OK" if test else "ERROR"
    except:
        db_status = "ERROR"

    # Get recording counts
    recording_counts = q("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as processed,
            SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed,
            SUM(CASE WHEN status='new' THEN 1 ELSE 0 END) as pending
        FROM recordings
    """, one=True)

    # Get DC and RM counts
    dc_count = q("SELECT COUNT(*) as count FROM dcs WHERE active=1", one=True)['count']
    rm_count = q("SELECT COUNT(*) as count FROM rms", one=True)['count']

    return {
        "database": db_status,
        "last_backup": None,  # Would need actual backup tracking
        "database_size_mb": 0,  # Would need file system access
        "recording_counts": {
            "total": recording_counts['total'] or 0,
            "processed": recording_counts['processed'] or 0,
            "failed": recording_counts['failed'] or 0,
            "pending": recording_counts['pending'] or 0
        },
        "dcs_count": dc_count,
        "rms_count": rm_count
    }


# ---- BULK EXPORT/IMPORT HELPERS (Phase 8: Backup & Restore) ----

def bulk_export_table(table: str, where_clause: str = "", args: tuple = ()) -> list[dict]:
    """Export all rows from a table with optional filtering.

    Args:
        table: Table name
        where_clause: Optional WHERE clause (without WHERE keyword)
        args: Arguments for parameterized query

    Returns:
        List of dict records
    """
    sql = f"SELECT * FROM {table}"
    if where_clause:
        sql += f" WHERE {where_clause}"
    sql += " ORDER BY id"
    return q(sql, args)


def bulk_export_with_join(table: str, joins: list[str], select_cols: list[str],
                         where_clause: str = "", args: tuple = ()) -> list[dict]:
    """Export rows from a table with joins for denormalized data.

    Args:
        table: Primary table
        joins: List of JOIN clauses
        select_cols: List of columns to select
        where_clause: Optional WHERE clause
        args: Arguments for parameterized query

    Returns:
        List of dict records
    """
    cols_str = ", ".join(select_cols)
    sql = f"SELECT {cols_str} FROM {table}"
    for join in joins:
        sql += f" {join}"
    if where_clause:
        sql += f" WHERE {where_clause}"
    sql += " ORDER BY " + table + ".id"
    return q(sql, args)


def bulk_import_table(table: str, records: list[dict], skip_duplicates: bool = True) -> dict:
    """Import records into a table.

    Args:
        table: Table name
        records: List of dict records
        skip_duplicates: If True, skip records with duplicate unique constraints

    Returns:
        {"inserted": int, "skipped": int, "errors": list[str]}
    """
    if not records:
        return {"inserted": 0, "skipped": 0, "errors": []}

    inserted = 0
    skipped = 0
    errors = []

    # Get column names from first record
    cols = list(records[0].keys())
    cols_str = ", ".join(cols)
    placeholders = ", ".join(["?"] * len(cols))

    for i, record in enumerate(records):
        try:
            values = [record.get(col) for col in cols]
            x(f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders})", tuple(values))
            inserted += 1
        except sqlite3.IntegrityError as e:
            if skip_duplicates:
                skipped += 1
            else:
                errors.append(f"Row {i}: {str(e)}")
        except Exception as e:
            errors.append(f"Row {i}: {str(e)}")

    return {
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
    }


def table_record_count(table: str, where_clause: str = "", args: tuple = ()) -> int:
    """Get the count of records in a table.

    Args:
        table: Table name
        where_clause: Optional WHERE clause
        args: Arguments for parameterized query

    Returns:
        Record count
    """
    sql = f"SELECT COUNT(*) as cnt FROM {table}"
    if where_clause:
        sql += f" WHERE {where_clause}"
    result = q(sql, args, one=True)
    return result["cnt"] if result else 0


def get_table_schema(table: str) -> list[dict]:
    """Get schema information for a table.

    Returns:
        List of column info dicts: {"cid": int, "name": str, "type": str, "notnull": bool, "dflt_value": any, "pk": bool}
    """
    return q(f"PRAGMA table_info({table})")


def export_to_json(records: list[dict], indent: bool = True) -> str:
    """Convert records to JSON string.

    Args:
        records: List of dict records
        indent: Whether to pretty-print

    Returns:
        JSON string
    """
    return json.dumps(records, indent=2 if indent else None, ensure_ascii=False, default=str)


def import_from_json(json_str: str) -> list[dict]:
    """Parse JSON string into records.

    Args:
        json_str: JSON string

    Returns:
        List of dict records
    """
    try:
        data = json.loads(json_str)
        if not isinstance(data, list):
            raise ValueError(f"Expected list, got {type(data).__name__}")
        return data
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {str(e)}")


# Automatically ensure schema is up-to-date when module is imported
try:
    _ensure_schema()
except Exception as e:
    print(f"⚠️  Warning: Could not ensure database schema: {e}")
