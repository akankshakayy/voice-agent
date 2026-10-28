"""Phase 5: Drift detection & repair.

Track prompt code versions, store scorecard baselines, detect behavior drift,
and allow operators to accept new versions as correct.
"""
import json
import time
from . import db


def register_prompt_version(version_hash: str, prompt_code: str, tool_schema: dict, created_by: str) -> int:
    """Register a new prompt code version in the database.

    Args:
        version_hash: SHA1 hash from telemetry.prompt_version()
        prompt_code: Full source code of _system_prompt function
        tool_schema: AGENT_TURN_TOOL dict
        created_by: user email or "system"

    Returns:
        row id
    """
    # Check if already exists
    existing = db.q(
        "SELECT id FROM prompt_versions WHERE version_hash=?",
        (version_hash,),
        one=True
    )
    if existing:
        return existing["id"]

    # Register new version
    db.x(
        """INSERT INTO prompt_versions(version_hash, prompt_code, tool_schema_json, created_at, created_by)
           VALUES(?, ?, ?, ?, ?)""",
        (
            version_hash,
            prompt_code,
            json.dumps(tool_schema, ensure_ascii=False, default=str),
            time.time(),
            created_by,
        ),
    )
    return db.q("SELECT id FROM prompt_versions WHERE version_hash=?", (version_hash,), one=True)["id"]


def store_scorecard_baseline(
    version_hash: str,
    results_csv: str,
    summary: dict,
    eval_by: str = "system",
) -> int:
    """Store a scorecard baseline for a prompt version.

    Args:
        version_hash: prompt version hash
        results_csv: full results.csv as string
        summary: summary.json dict
        eval_by: who ran the eval

    Returns:
        row id
    """
    # Convert CSV to JSON rows for storage
    results_json = {}
    try:
        import csv
        import io
        reader = csv.DictReader(io.StringIO(results_csv))
        results_json = [row for row in reader]
    except Exception:
        results_json = {"raw": results_csv[:1000]}  # fallback

    db.x(
        """INSERT INTO scorecard_baselines(version_hash, eval_timestamp, results_json, summary_json, eval_by)
           VALUES(?, ?, ?, ?, ?)""",
        (
            version_hash,
            time.time(),
            json.dumps(results_json, ensure_ascii=False, default=str),
            json.dumps(summary, ensure_ascii=False, default=str),
            eval_by,
        ),
    )
    return db.q(
        "SELECT id FROM scorecard_baselines WHERE version_hash=? ORDER BY id DESC LIMIT 1",
        (version_hash,),
        one=True
    )["id"]


def get_baseline_scores(version_hash: str) -> dict | None:
    """Get the accepted baseline scorecard for a version."""
    baseline = db.q(
        "SELECT summary_json FROM scorecard_baselines WHERE version_hash=? AND accepted_at IS NOT NULL ORDER BY accepted_at DESC LIMIT 1",
        (version_hash,),
        one=True
    )
    if baseline and baseline.get("summary_json"):
        try:
            return json.loads(baseline["summary_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def detect_drift(
    previous_version_id: int,
    current_version_id: int,
    live_scores: dict,
    detected_by: str = "system",
) -> int | None:
    """Detect drift between two prompt versions based on live call metrics.

    Args:
        previous_version_id: database id of previous version
        current_version_id: database id of current version
        live_scores: dict with live_intent_pct, live_action_pct, live_details_pct, live_latency_p95, live_calls_analyzed
        detected_by: who detected it ("automatic" or ops email)

    Returns:
        drift id if drift detected, None if no significant drift
    """
    # Check if drift already exists
    existing = db.q(
        "SELECT id FROM prompt_drifts WHERE previous_version_id=? AND current_version_id=? AND status='flagged'",
        (previous_version_id, current_version_id),
        one=True
    )
    if existing:
        return existing["id"]

    # Store drift record (initially flagged, awaiting review)
    db.x(
        """INSERT INTO prompt_drifts(previous_version_id, current_version_id, detected_at, detected_by,
                                     live_intent_pct, live_action_pct, live_details_pct, live_latency_p95, live_calls_analyzed,
                                     drift_type, status)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            previous_version_id,
            current_version_id,
            time.time(),
            detected_by,
            live_scores.get("live_intent_pct"),
            live_scores.get("live_action_pct"),
            live_scores.get("live_details_pct"),
            live_scores.get("live_latency_p95"),
            live_scores.get("live_calls_analyzed"),
            live_scores.get("drift_type", "code_changed"),
            "flagged",
        ),
    )

    return db.q(
        "SELECT id FROM prompt_drifts WHERE previous_version_id=? AND current_version_id=? ORDER BY detected_at DESC LIMIT 1",
        (previous_version_id, current_version_id),
        one=True
    )["id"]


def get_pending_drifts() -> list[dict]:
    """Get all pending drift detections awaiting operator review."""
    return db.q(
        """SELECT pd.*, pv1.version_hash as previous_hash, pv2.version_hash as current_hash
           FROM prompt_drifts pd
           LEFT JOIN prompt_versions pv1 ON pd.previous_version_id = pv1.id
           LEFT JOIN prompt_versions pv2 ON pd.current_version_id = pv2.id
           WHERE pd.status IN ('flagged', 'under_review')
           ORDER BY pd.detected_at DESC"""
    )


def accept_drift(drift_id: int, accepted_by: str, reason: str = "") -> bool:
    """Accept a detected drift and mark the new version as approved.

    Args:
        drift_id: the drift to accept
        accepted_by: operator email
        reason: why they accepted it

    Returns:
        True if successful
    """
    drift = db.q("SELECT * FROM prompt_drifts WHERE id=?", (drift_id,), one=True)
    if not drift or drift["status"] not in ("flagged", "under_review"):
        return False

    # Mark drift as approved
    db.x(
        """UPDATE prompt_drifts SET status='approved', approved_by=?, approved_at=?, decision_json=?
           WHERE id=?""",
        (
            accepted_by,
            time.time(),
            json.dumps({"reason": reason, "accepted_at": time.time()}),
            drift_id,
        ),
    )

    return True


def reject_drift(drift_id: int, rejected_by: str, reason: str = "") -> bool:
    """Reject a detected drift (keep using old version)."""
    drift = db.q("SELECT * FROM prompt_drifts WHERE id=?", (drift_id,), one=True)
    if not drift or drift["status"] not in ("flagged", "under_review"):
        return False

    db.x(
        """UPDATE prompt_drifts SET status='rejected', rejected_by=?, rejected_at=?, rejection_reason=?
           WHERE id=?""",
        (rejected_by, time.time(), reason, drift_id),
    )

    return True


def get_prompt_diff(version_id_1: int, version_id_2: int) -> dict | None:
    """Get the diff between two prompt versions by id."""
    v1 = db.q("SELECT version_hash, prompt_code FROM prompt_versions WHERE id=?", (version_id_1,), one=True)
    v2 = db.q("SELECT version_hash, prompt_code FROM prompt_versions WHERE id=?", (version_id_2,), one=True)

    if not v1 or not v2 or not v1.get("prompt_code") or not v2.get("prompt_code"):
        return None

    # Simple diff: show lines that changed
    import difflib
    diff_lines = list(difflib.unified_diff(
        v1["prompt_code"].splitlines(keepends=True),
        v2["prompt_code"].splitlines(keepends=True),
        fromfile=f"prompt-{v1['version_hash'][:8]}",
        tofile=f"prompt-{v2['version_hash'][:8]}",
        lineterm="",
    ))

    return {
        "from_version_id": version_id_1,
        "to_version_id": version_id_2,
        "from_hash": v1["version_hash"],
        "to_hash": v2["version_hash"],
        "diff_lines": diff_lines[:100],  # First 100 lines
        "total_lines": len(diff_lines),
    }


def export_prompt_version(version_hash: str) -> str | None:
    """Export a versioned prompt as Python code."""
    version = db.q("SELECT prompt_code FROM prompt_versions WHERE version_hash=?", (version_hash,), one=True)
    if not version:
        return None

    # Wrap in exportable Python function
    code = f'''# Exported prompt version: {version_hash}
# Generated at {time.strftime("%Y-%m-%d %H:%M:%S")}

def _system_prompt_v{version_hash[:8]}(state: dict):
    """Versioned prompt code."""
    {version["prompt_code"]}
'''
    return code
