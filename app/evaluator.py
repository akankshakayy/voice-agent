"""Harness evaluator: score traces and compare against ground truth.

Evaluates each trace on:
- Intent accuracy vs. corrections
- Slot extraction completeness
- Confidence calibration
- Token efficiency per tier
- Decision quality (error vs. success)
"""
import json
from . import db


def score_trace(trace: dict, call_id: int | None = None) -> dict:
    """Score a single trace against available ground truth (corrections, RM review).

    Returns a dict with:
      - intent_match: 0-1, whether final intent matches RM correction (if any)
      - slots_extracted: 0-1, fraction of expected slots for this category
      - confidence_quality: -1 to 1, whether confidence predicts accuracy
      - token_efficiency: 0-1, tokens used vs. expected for this decision
      - error_state: bool, whether trace has an error
    """
    score = {
        "trace_id": trace.get("id"),
        "engine": trace.get("engine"),
        "intent": trace.get("output", {}).get("intent"),
        "confidence": trace.get("output", {}).get("intent_confidence"),
        "tier_tokens": trace.get("tier_tokens"),
        "total_tokens": (trace.get("input_tokens") or 0) + (trace.get("output_tokens") or 0),
        "latency_ms": trace.get("latency_ms"),
        "has_error": bool(trace.get("error")),
    }

    if trace.get("error"):
        score["quality"] = "error"
        return score

    # Check if this trace was corrected by an RM (ground truth)
    if call_id:
        turn_id = trace.get("turn_id")
        corrections = db.q(
            "SELECT * FROM corrections WHERE call_id=? AND ref_id=? LIMIT 1",
            (call_id, turn_id),
        )
        if corrections:
            c = corrections[0]
            if c.get("field") == "intent":
                agent_intent = trace.get("output", {}).get("intent")
                human_intent = c.get("after")
                score["intent_corrected"] = agent_intent != human_intent
                if agent_intent == human_intent:
                    score["quality"] = "correct"
                else:
                    score["quality"] = "wrong"
            elif c.get("field", "").startswith("detail:"):
                score["slot_corrected"] = True
                score["quality"] = "incomplete"

    if "quality" not in score:
        score["quality"] = "unchecked"

    return score


def scores_for_call(call_id: int) -> list[dict]:
    """Score all traces for a call."""
    traces = db.q("SELECT * FROM traces WHERE call_id=? ORDER BY id", (call_id,))
    for t in traces:
        for k in ("messages_json", "context_json", "raw_output_json", "output_json", "tier_tokens_json"):
            if k in t and t[k]:
                t[k[:-5]] = json.loads(t[k])

    return [score_trace(t, call_id) for t in traces]


def tier_health(call_id: int) -> dict:
    """Analyze token tier usage across a call: which tiers are bloated?

    Returns:
      - by_tier: {system: total, context: total, history: total, output: total}
      - by_tier_pct: percentages of each
      - warnings: [list of tier-specific warnings]
    """
    traces = db.q("SELECT tier_tokens_json FROM traces WHERE call_id=?", (call_id,))
    tiers = {"system": 0, "context": 0, "history": 0, "output": 0}

    for t in traces:
        if t.get("tier_tokens_json"):
            try:
                tt = json.loads(t["tier_tokens_json"])
                for k in tiers:
                    tiers[k] += tt.get(k, 0)
            except (json.JSONDecodeError, TypeError):
                pass

    total = sum(tiers.values())
    pct = {k: round((v / total * 100) if total else 0, 1) for k, v in tiers.items()}

    warnings = []
    if pct.get("history", 0) > 50:
        warnings.append(f"History is {pct['history']}% of tokens - consider trimming past turns")
    if pct.get("context", 0) > 40:
        warnings.append(f"Context (CSP data) is {pct['context']}% of tokens - consider compressing")
    if pct.get("output", 0) > 20:
        warnings.append(f"Output is {pct['output']}% of tokens - consider simplifying response format")

    return {"by_tier": tiers, "by_tier_pct": pct, "total": total, "warnings": warnings}


def model_performance(hours: int = 24, engine: str | None = None) -> dict:
    """Aggregate performance across calls (traces broken down by model/engine)."""
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc).timestamp() - (hours * 3600)
    where = "ts > ?" if engine is None else "ts > ? AND engine = ?"
    args = (since,) if engine is None else (since, engine)

    traces = db.q(
        f"SELECT engine, model, output_json, error, latency_ms, input_tokens, output_tokens "
        f"FROM traces WHERE {where} ORDER BY ts DESC",
        args,
    )

    by_model = {}
    for t in traces:
        key = f"{t.get('engine')}/{t.get('model') or 'unknown'}"
        if key not in by_model:
            by_model[key] = {
                "count": 0,
                "errors": 0,
                "avg_latency_ms": 0,
                "total_tokens": 0,
                "avg_tokens": 0,
            }

        by_model[key]["count"] += 1
        if t.get("error"):
            by_model[key]["errors"] += 1
        by_model[key]["total_tokens"] += (t.get("input_tokens") or 0) + (t.get("output_tokens") or 0)
        by_model[key]["avg_latency_ms"] += t.get("latency_ms") or 0

    for k, v in by_model.items():
        if v["count"] > 0:
            v["avg_latency_ms"] = round(v["avg_latency_ms"] / v["count"], 1)
            v["avg_tokens"] = round(v["total_tokens"] / v["count"], 0)
            v["error_rate"] = round(v["errors"] / v["count"] * 100, 1)

    return by_model
