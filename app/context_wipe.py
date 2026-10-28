"""Phase 4: Context chips + wipe-from-context.

Operators can view individual pieces of context that were included in a trace and
wipe (redact) specific chips for compliance or data minimization. Audit trail tracks
all wipes.
"""
import json
import time
from . import db


def parse_chips(trace: dict) -> dict:
    """Extract individual context chips from a trace.

    Returns:
        {
            "csp": {"code": "...", "name": "...", "rm": "..."},
            "tickets": [{"id": "T123", "category": "...", "status": "...", "summary": "..."}],
            "slots": [{"key": "amount", "value": "10000"}, ...],
            "messages": [{"idx": 0, "role": "user", "text": "..."}, ...]
        }
    """
    context = trace.get("context") or {}
    messages = trace.get("messages") or []
    output = trace.get("output") or {}

    # CSP context chips
    csp_chips = {
        "code": context.get("csp", {}).get("csp_code", ""),
        "name": context.get("csp", {}).get("name", ""),
        "rm": context.get("rm_name", ""),
    }

    # Ticket chips
    ticket_chips = []
    for ticket in context.get("past_tickets", []):
        ticket_chips.append({
            "id": ticket.get("ticket_no", ""),
            "category": ticket.get("category", ""),
            "status": ticket.get("status", ""),
            "summary": ticket.get("summary", ""),
        })

    # Slot chips (extracted details)
    slot_chips = []
    for key, value in output.get("slots", {}).items():
        if not key.startswith("_"):
            slot_chips.append({
                "key": key,
                "value": str(value),
            })

    # Message chips (conversation turns)
    message_chips = []
    for idx, msg in enumerate(messages):
        message_chips.append({
            "idx": idx,
            "role": msg.get("role", "user"),
            "text": msg.get("content", "")[:100],  # Truncate for display
            "full_text": msg.get("content", ""),
        })

    return {
        "csp": csp_chips,
        "tickets": ticket_chips,
        "slots": slot_chips,
        "messages": message_chips,
    }


def wipe_chip(trace_id: int, chip_type: str, chip_id: str, wiped_by: str, reason: str | None = None) -> bool:
    """Mark a context chip as wiped and record audit trail.

    Args:
        trace_id: the trace to wipe from
        chip_type: "ticket" | "slot" | "message"
        chip_id: ticket number | slot key | message index
        wiped_by: user email or "system"
        reason: optional reason for wiping

    Returns:
        True if successful
    """
    trace = db.q("SELECT * FROM traces WHERE id=?", (trace_id,), one=True)
    if not trace:
        return False

    # Get the actual value for audit
    try:
        chips = parse_chips(trace)
        chip_value = ""

        if chip_type == "ticket":
            for t in chips["tickets"]:
                if t["id"] == chip_id:
                    chip_value = t["summary"]
                    break
        elif chip_type == "slot":
            for s in chips["slots"]:
                if s["key"] == chip_id:
                    chip_value = s["value"]
                    break
        elif chip_type == "message":
            for m in chips["messages"]:
                if str(m["idx"]) == chip_id:
                    chip_value = m["text"]
                    break
    except Exception:
        chip_value = chip_id

    # Record wipe audit
    db.x(
        """INSERT INTO context_wipes(trace_id, ts, wiped_by, chip_type, chip_id, chip_value, reason)
           VALUES(?, ?, ?, ?, ?, ?, ?)""",
        (trace_id, time.time(), wiped_by, chip_type, chip_id, chip_value, reason),
    )

    # Update traces.wiped_chips_json
    wiped = trace.get("wiped_chips_json")
    if wiped:
        try:
            wiped = json.loads(wiped)
        except (json.JSONDecodeError, TypeError):
            wiped = {}
    else:
        wiped = {}

    # Ensure structure
    if chip_type not in wiped:
        wiped[chip_type] = []

    # Add to wiped list if not already there
    if chip_id not in wiped[chip_type]:
        wiped[chip_type].append(chip_id)

    db.update(
        "traces",
        trace_id,
        wiped_chips_json=json.dumps(wiped, ensure_ascii=False),
    )

    return True


def get_wiped_chips(trace_id: int) -> dict:
    """Get list of chips that have been wiped from a trace."""
    trace = db.q("SELECT wiped_chips_json FROM traces WHERE id=?", (trace_id,), one=True)
    if not trace or not trace.get("wiped_chips_json"):
        return {}

    try:
        return json.loads(trace["wiped_chips_json"])
    except (json.JSONDecodeError, TypeError):
        return {}


def get_wipe_audit(trace_id: int | None = None, call_id: int | None = None) -> list[dict]:
    """Get wipe audit trail for a trace or all traces in a call.

    Args:
        trace_id: specific trace ID, or None for all traces in call_id
        call_id: call ID (ignored if trace_id given)

    Returns:
        List of wipe events
    """
    if trace_id:
        return db.q("SELECT * FROM context_wipes WHERE trace_id=? ORDER BY ts DESC", (trace_id,))

    if call_id:
        return db.q(
            """SELECT cw.* FROM context_wipes cw
               JOIN traces t ON cw.trace_id = t.id
               WHERE t.call_id = ? ORDER BY cw.ts DESC""",
            (call_id,),
        )

    return []


def unparse_chips(trace: dict, wiped_chips: dict) -> dict:
    """Remove wiped chips from a trace's context before sending to UI/API.

    Args:
        trace: the full trace dict
        wiped_chips: result from get_wiped_chips()

    Returns:
        Modified trace with wiped content redacted
    """
    trace = dict(trace)  # Shallow copy
    context = dict(trace.get("context") or {})
    output = dict(trace.get("output") or {})
    messages = list(trace.get("messages") or [])

    # Wipe tickets
    if "ticket" in wiped_chips:
        tickets = []
        for t in context.get("past_tickets", []):
            if t.get("ticket_no") not in wiped_chips["ticket"]:
                tickets.append(t)
        context["past_tickets"] = tickets

    # Wipe slots
    if "slot" in wiped_chips:
        slots = dict(output.get("slots", {}))
        for key in wiped_chips["slot"]:
            slots.pop(key, None)
        output["slots"] = slots

    # Wipe messages
    if "message" in wiped_chips:
        wiped_indices = set(int(i) for i in wiped_chips["message"])
        messages = [m for i, m in enumerate(messages) if i not in wiped_indices]

    trace["context"] = context
    trace["output"] = output
    trace["messages"] = messages
    trace["wiped_chips"] = wiped_chips

    return trace


def wipe_stats(hours: int = 24) -> dict:
    """Aggregate wipe statistics (frequency by chip type, top wipers, etc.)."""
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc).timestamp() - (hours * 3600)

    # Total wipes
    total = db.q("SELECT COUNT(*) cnt FROM context_wipes WHERE ts > ?", (since,))
    total_count = total[0]["cnt"] if total else 0

    # By chip type
    by_type = db.q(
        """SELECT chip_type, COUNT(*) cnt FROM context_wipes WHERE ts > ?
           GROUP BY chip_type ORDER BY cnt DESC""",
        (since,),
    )

    # By actor
    by_actor = db.q(
        """SELECT wiped_by, COUNT(*) cnt FROM context_wipes WHERE ts > ?
           GROUP BY wiped_by ORDER BY cnt DESC""",
        (since,),
    )

    # Reasons
    by_reason = db.q(
        """SELECT reason, COUNT(*) cnt FROM context_wipes WHERE ts > ? AND reason IS NOT NULL
           GROUP BY reason ORDER BY cnt DESC""",
        (since,),
    )

    return {
        "total_wipes": total_count,
        "by_chip_type": by_type,
        "by_actor": by_actor,
        "by_reason": by_reason,
    }
