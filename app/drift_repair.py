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
    old_version: str,
    new_version: str,
    old_summary: dict,
    new_summary: dict,
    detected_by: str = "system",
) -> int | None:
    """Detect drift between two prompt versions based on scorecard differences.

    Args:
        old_version: previous prompt version hash
        new_version: current prompt version hash
        old_summary: previous scorecard summary
        new_summary: current scorecard summary
        detected_by: who detected it

    Returns:
        drift id if drift detected, None if no significant drift
    """
    # Simple heuristic: check if understanding scores dropped significantly
    old_understanding = old_summary.get("understanding_from_audio", {}).get("details_pct", 100)
    new_understanding = new_summary.get("understanding_from_audio", {}).get("details_pct", 100)

    # Flag drift if understanding dropped by >5% or latency increased >10%
    understanding_drop = (old_understanding or 100) - (new_understanding or 100)
    old_latency = old_summary.get("timing_s", {}).get("heard_llm_s", {}).get("p50")
    new_latency = new_summary.get("timing_s", {}).get("heard_llm_s", {}).get("p50")
    latency_increase = 0
    if old_latency and new_latency:
        latency_increase = ((new_latency - old_latency) / old_latency * 100)

    is_drift = understanding_drop > 5 or latency_increase > 10

    if not is_drift:
        return None

    # Create diff summary
    diff_summary = f"Understanding: {old_understanding}% → {new_understanding}% ({understanding_drop:+.1f}%)"
    if latency_increase:
        diff_summary += f" | Latency: +{latency_increase:.1f}%"

    # Store drift record
    db.x(
        """INSERT INTO prompt_drifts(from_version, to_version, detected_at, detected_by, diff_summary,
                                     previous_baseline_json, current_scores_json, status)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            old_version,
            new_version,
            time.time(),
            detected_by,
            diff_summary,
            json.dumps(old_summary, ensure_ascii=False, default=str),
            json.dumps(new_summary, ensure_ascii=False, default=str),
            "detected",
        ),
    )

    return db.q(
        "SELECT id FROM prompt_drifts WHERE from_version=? AND to_version=? ORDER BY detected_at DESC LIMIT 1",
        (old_version, new_version),
        one=True
    )["id"]


def get_pending_drifts() -> list[dict]:
    """Get all pending drift detections awaiting operator review."""
    return db.q(
        "SELECT * FROM prompt_drifts WHERE status='detected' ORDER BY detected_at DESC"
    )


def accept_drift(drift_id: int, accepted_by: str, reason: str = "") -> bool:
    """Accept a detected drift and update baseline to new version.

    Args:
        drift_id: the drift to accept
        accepted_by: operator email
        reason: why they accepted it

    Returns:
        True if successful
    """
    drift = db.q("SELECT * FROM prompt_drifts WHERE id=?", (drift_id,), one=True)
    if not drift or drift["status"] != "detected":
        return False

    # Mark drift as accepted
    db.update(
        "prompt_drifts",
        drift_id,
        status="accepted",
        accepted_at=time.time(),
        accepted_by=accepted_by,
        acceptance_reason=reason,
    )

    # Accept the new baseline scores
    new_summary = json.loads(drift["current_scores_json"])
    db.update(
        "scorecard_baselines",
        db.q(
            "SELECT id FROM scorecard_baselines WHERE version_hash=? ORDER BY eval_timestamp DESC LIMIT 1",
            (drift["to_version"],),
            one=True
        )["id"],
        accepted_at=time.time(),
        accepted_by=accepted_by,
        accepted_reason=reason,
    )

    return True


def reject_drift(drift_id: int, rejected_by: str, reason: str = "") -> bool:
    """Reject a detected drift (keep using old version)."""
    drift = db.q("SELECT * FROM prompt_drifts WHERE id=?", (drift_id,), one=True)
    if not drift or drift["status"] != "detected":
        return False

    db.update(
        "prompt_drifts",
        drift_id,
        status="rejected",
        accepted_at=time.time(),  # reuse field for rejection time
        accepted_by=rejected_by,
        acceptance_reason=reason,
    )

    return True


def get_prompt_diff(version1_hash: str, version2_hash: str) -> dict | None:
    """Get the diff between two prompt versions."""
    v1 = db.q("SELECT prompt_code FROM prompt_versions WHERE version_hash=?", (version1_hash,), one=True)
    v2 = db.q("SELECT prompt_code FROM prompt_versions WHERE version_hash=?", (version2_hash,), one=True)

    if not v1 or not v2:
        return None

    # Simple diff: show lines that changed
    import difflib
    diff = list(difflib.unified_diff(
        v1["prompt_code"].splitlines(keepends=True),
        v2["prompt_code"].splitlines(keepends=True),
        fromfile=f"prompt-{version1_hash[:8]}",
        tofile=f"prompt-{version2_hash[:8]}",
        lineterm="",
    ))

    return {
        "from_version": version1_hash,
        "to_version": version2_hash,
        "diff_lines": diff[:100],  # First 100 lines
        "total_lines": len(diff),
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
