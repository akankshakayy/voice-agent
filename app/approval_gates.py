"""Phase 3: Approval workflow for risky operations.

When an agent wants to execute a tool marked as "high-risk" (create_ticket, escalate, etc.),
the system pauses and waits for Ops/Admin approval before proceeding.

Operations are gated based on:
- Tool risk level (high, medium, low)
- Agent confidence
- Context state (if tokens are tight, more things need approval)
"""
import json
import time
from . import db


# Tool registry: which operations need approval
TOOL_REGISTRY = {
    "create_ticket": {
        "name": "Create Ticket",
        "risk": "high",
        "requires_approval": True,
        "description": "Submit CSP issue as a ticket to the RM",
        "timeout_sec": 300,  # 5 min to approve
    },
    "escalate": {
        "name": "Escalate to RM",
        "risk": "high",
        "requires_approval": True,
        "description": "Hand call to RM for direct assistance",
        "timeout_sec": 300,
    },
    "resolved_by_agent": {
        "name": "Mark Resolved",
        "risk": "medium",
        "requires_approval": False,
        "description": "Answer from ticket history without creating new one",
        "timeout_sec": 60,
    },
    "continue": {
        "name": "Continue",
        "risk": "low",
        "requires_approval": False,
        "description": "Ask another clarifying question",
        "timeout_sec": 30,
    },
    "end_call": {
        "name": "End Call",
        "risk": "low",
        "requires_approval": False,
        "description": "End the call gracefully",
        "timeout_sec": 30,
    },
}


def needs_approval(action: str, decision: dict, context_state: dict | None = None) -> bool:
    """Check if an action needs approval based on risk level and context.

    Args:
        action: tool name (create_ticket, escalate, etc.)
        decision: the agent's decision dict with intent_confidence, etc.
        context_state: optional state (tokens used, etc.)

    Returns:
        True if approval is required before executing this action
    """
    tool = TOOL_REGISTRY.get(action)
    if not tool:
        return False  # Unknown tool, allow through

    # Base risk check
    if tool["requires_approval"]:
        return True

    # Additional context-based checks
    confidence = decision.get("intent_confidence", 0)
    # If confidence is very low and it's a risky action, require approval
    if tool["risk"] == "medium" and confidence < 0.5:
        return True

    return False


def request_approval(
    call_id: int,
    turn_id: int,
    action: str,
    decision: dict,
    reason: str | None = None,
) -> int:
    """Create an approval request and return its ID.

    Args:
        call_id: the call this decision is for
        turn_id: the turn within the call
        action: tool name (create_ticket, escalate, etc.)
        decision: the agent's full decision dict
        reason: optional reason why approval is needed

    Returns:
        approval_id
    """
    tool = TOOL_REGISTRY.get(action)
    if not tool:
        raise ValueError(f"Unknown action: {action}")

    approval_id = db.x(
        """INSERT INTO approvals(call_id, turn_id, action, status, reason, decision_json,
                                created_at, expires_at)
           VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            call_id,
            turn_id,
            action,
            "pending",
            reason,
            json.dumps(decision, ensure_ascii=False, default=str),
            time.time(),
            time.time() + tool["timeout_sec"],
        ),
    )
    return approval_id


def get_approval(approval_id: int) -> dict | None:
    """Fetch an approval request."""
    return db.q("SELECT * FROM approvals WHERE id=?", (approval_id,), one=True)


def approve(approval_id: int, approved_by: str, edited_decision: dict | None = None) -> bool:
    """Approve an action (optionally with edits).

    Args:
        approval_id: the approval to approve
        approved_by: actor (user email or ID)
        edited_decision: if the approver edited the decision, provide the new one

    Returns:
        True if approval was successful
    """
    approval = get_approval(approval_id)
    if not approval:
        return False

    if approval["status"] != "pending":
        return False  # Already decided

    db.update(
        "approvals",
        approval_id,
        status="approved",
        approved_by=approved_by,
        approved_at=time.time(),
        edited_decision_json=json.dumps(edited_decision, ensure_ascii=False, default=str)
        if edited_decision
        else None,
    )
    return True


def deny(approval_id: int, denied_by: str, reason: str | None = None) -> bool:
    """Deny an action.

    Args:
        approval_id: the approval to deny
        denied_by: actor (user email or ID)
        reason: why it was denied

    Returns:
        True if denial was successful
    """
    approval = get_approval(approval_id)
    if not approval:
        return False

    if approval["status"] != "pending":
        return False  # Already decided

    db.update(
        "approvals",
        approval_id,
        status="denied",
        denied_by=denied_by,
        denied_at=time.time(),
        denial_reason=reason,
    )
    return True


def audit_trail(call_id: int, approval_id: int | None = None) -> list[dict]:
    """Get approval audit trail for a call (or specific approval).

    Returns:
        List of approval decisions with actor, timestamp, what changed
    """
    if approval_id:
        return db.q("SELECT * FROM approvals WHERE id=? ORDER BY created_at", (approval_id,))
    return db.q(
        "SELECT * FROM approvals WHERE call_id=? ORDER BY created_at DESC",
        (call_id,),
    )


def approval_stats(hours: int = 24) -> dict:
    """Aggregate approval stats (approval rate, common denials, etc.)."""
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc).timestamp() - (hours * 3600)

    # Total approvals
    total = db.q("SELECT COUNT(*) cnt FROM approvals WHERE created_at > ?", (since,))
    total_count = total[0]["cnt"] if total else 0

    # By status
    by_status = db.q(
        """SELECT status, COUNT(*) cnt FROM approvals WHERE created_at > ?
           GROUP BY status""",
        (since,),
    )
    status_counts = {r["status"]: r["cnt"] for r in by_status}

    # By action
    by_action = db.q(
        """SELECT action, COUNT(*) cnt, SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) approved
           FROM approvals WHERE created_at > ? GROUP BY action ORDER BY cnt DESC""",
        (since,),
    )

    # Avg approval time
    times = db.q(
        """SELECT AVG(approved_at - created_at) avg_sec FROM approvals
           WHERE created_at > ? AND status='approved' AND approved_at IS NOT NULL""",
        (since,),
    )
    avg_approval_time = times[0]["avg_sec"] if times and times[0]["avg_sec"] else 0

    return {
        "total_requests": total_count,
        "by_status": status_counts,
        "by_action": by_action,
        "avg_approval_time_sec": round(avg_approval_time, 1),
        "approval_rate": (
            (status_counts.get("approved", 0) / total_count * 100) if total_count else 0
        ),
    }
