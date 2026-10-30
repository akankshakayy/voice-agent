"""Aggregations for the dashboards."""
import json
import os
import statistics
from collections import Counter

from . import db, telemetry
from .taxonomy import STT_CONFIDENCE_MIN, INTENT_CONFIDENCE_MIN, label

PRICE_IN = float(os.environ.get("LLM_PRICE_INPUT_PER_M", "1.0"))    # USD per 1M input tokens
PRICE_OUT = float(os.environ.get("LLM_PRICE_OUTPUT_PER_M", "5.0"))  # USD per 1M output tokens
USD_INR = float(os.environ.get("USD_INR", "84"))


def _pct(a, b):
    return round(100 * a / b, 1) if b else 0.0


def _p(values, q):
    if not values:
        return None
    values = sorted(values)
    k = max(0, min(len(values) - 1, round(q * (len(values) - 1))))
    return round(values[k], 1)


def agent_metrics(hours: float = 24 * 7, rm_id: int | None = None):
    since = db.now() - hours * 3600
    rm_sql, rm_args = ("AND c.rm_id=?", (rm_id,)) if rm_id else ("", ())
    calls = db.q(f"""SELECT c.*, s.name csp_name, s.csp_code, r.name rm_name, t.ticket_no, t.status ticket_status,
                     t.closed_at ticket_closed_at
                     FROM calls c LEFT JOIN csps s ON s.id=c.csp_id LEFT JOIN rms r ON r.id=c.rm_id
                     LEFT JOIN tickets t ON t.id=c.ticket_id
                     WHERE c.started_at>=? {rm_sql} ORDER BY c.started_at DESC""", (since, *rm_args))
    ended = [c for c in calls if c["status"] == "ended"]
    live = db.q(f"""SELECT c.id, c.direction, c.started_at, c.intent, c.turn_count, s.name csp_name, s.csp_code,
                    r.name rm_name FROM calls c LEFT JOIN csps s ON s.id=c.csp_id LEFT JOIN rms r ON r.id=c.rm_id
                    WHERE c.status='ongoing' {rm_sql} ORDER BY c.started_at""", rm_args)
    durations = [c["duration_sec"] for c in ended if c["duration_sec"] is not None]
    outcomes = Counter(c["outcome"] for c in ended)
    intents = Counter(c["intent"] or "unknown" for c in calls)

    # time series
    bucket = 3600 if hours <= 48 else 86400
    series = Counter()
    for c in calls:
        series[int(c["started_at"] // bucket * bucket)] += 1
    start = int(since // bucket * bucket)
    timeline = [{"t": t, "calls": series.get(t, 0)} for t in range(start, int(db.now()) + 1, bucket)]

    tickets = db.q(f"""SELECT * FROM tickets t WHERE created_at>=? {rm_sql.replace('c.', 't.')}""", (since, *rm_args))
    tstatus = Counter(t["status"] for t in tickets)
    res_hours = [(t["closed_at"] - t["created_at"]) / 3600 for t in tickets if t["closed_at"]]
    now = db.now()
    breached = sum(1 for t in tickets if (t["closed_at"] or now) > t["sla_due_at"])

    dur_buckets = [("<30s", 0, 30), ("30-60s", 30, 60), ("1-2m", 60, 120), ("2-3m", 120, 180),
                   ("3-5m", 180, 300), (">5m", 300, 1e9)]
    hist = [{"bucket": n, "count": sum(1 for d in durations if lo <= d < hi)} for n, lo, hi in dur_buckets]

    n_end = len(ended)
    handled_by_agent = outcomes["ticket_raised"] + outcomes["resolved_by_agent"] + outcomes["info_only"]
    return {
        "window_hours": hours,
        "totals": {
            "calls": len(calls), "inbound": sum(c["direction"] == "inbound" for c in calls),
            "outbound": sum(c["direction"] == "outbound" for c in calls), "ongoing": len(live), "ended": n_end,
            "avg_duration_sec": round(statistics.mean(durations), 1) if durations else 0,
            "median_duration_sec": round(statistics.median(durations), 1) if durations else 0,
            "ticket_raise_rate": _pct(sum(1 for c in ended if c["ticket_id"]), n_end),
            "escalation_rate": _pct(outcomes["escalated"], n_end),
            "not_understood_rate": _pct(outcomes["not_understood"], n_end),
            "agent_handled_rate": _pct(handled_by_agent, n_end),
            "self_resolved": outcomes["resolved_by_agent"],
        },
        "outcomes": dict(outcomes),
        "intents": [{"intent": k, "label": label(k) if k != "unknown" else "Unknown", "count": v}
                    for k, v in intents.most_common()],
        "timeline": timeline, "bucket_sec": bucket,
        "duration_hist": hist,
        "tickets": {
            "total": len(tickets), "open": tstatus["open"], "in_progress": tstatus["in_progress"],
            "resolved": tstatus["resolved"], "closed": tstatus["closed"],
            "escalated": sum(t["escalated"] for t in tickets),
            "avg_resolution_hours": round(statistics.mean(res_hours), 1) if res_hours else None,
            "sla_breached": breached,
        },
        "live_calls": live,
        "recent_calls": [{k: c[k] for k in ("id", "direction", "purpose", "started_at", "duration_sec", "status",
                                            "outcome", "intent", "intent_confidence", "csp_name", "csp_code",
                                            "rm_name", "ticket_no", "ticket_status", "ticket_closed_at",
                                            "escalation_reason", "turn_count", "engine", "sentiment")}
                         for c in calls[:60]],
    }


def model_metrics(hours: float = 24 * 7):
    since = db.now() - hours * 3600
    turns = db.q("""SELECT t.* FROM turns t JOIN calls c ON c.id=t.call_id WHERE c.started_at>=? AND t.role='csp'""",
                 (since,))
    nlu = [t for t in turns if t["engine"] not in ("guard", "system", None)]
    llm = [t for t in nlu if t["engine"] != "rules"]
    lat = [t["latency_ms"] for t in nlu if t["latency_ms"] is not None]
    llm_lat = [t["latency_ms"] for t in llm if t["latency_ms"] is not None]
    stt = [t["stt_confidence"] for t in turns if t["stt_confidence"] is not None]
    conf = [t["intent_confidence"] for t in nlu if t["intent_confidence"] is not None]
    tin = sum(t["input_tokens"] or 0 for t in turns)
    tout = sum(t["output_tokens"] or 0 for t in turns)
    paid = [t for t in turns if t["engine"] == "claude"]  # Groq / Gemini free tiers cost nothing
    cost_usd = (sum(t["input_tokens"] or 0 for t in paid) / 1e6 * PRICE_IN
                + sum(t["output_tokens"] or 0 for t in paid) / 1e6 * PRICE_OUT)
    errors = [t for t in turns if t["error"]]
    stt_errors = [t for t in turns if t["stt_confidence"] is not None and t["stt_confidence"] < STT_CONFIDENCE_MIN]

    calls = db.q("SELECT * FROM calls WHERE started_at>=? AND status='ended'", (since,))
    tickets = db.q("SELECT category, rm_category, slot_completeness FROM tickets WHERE created_at>=?", (since,))
    labelled = [t for t in tickets if t["rm_category"]]
    correct = sum(1 for t in labelled if t["rm_category"] == t["category"])
    confusions = Counter((t["category"], t["rm_category"]) for t in labelled if t["rm_category"] != t["category"])
    per_intent = {}
    for t in labelled:
        d = per_intent.setdefault(t["rm_category"], {"n": 0, "correct": 0})
        d["n"] += 1
        d["correct"] += t["rm_category"] == t["category"]
    completeness = [t["slot_completeness"] for t in tickets if t["slot_completeness"] is not None]
    misunderstood = sum(c["misunderstood_total"] or 0 for c in calls)

    # latency per day for trend
    lat_series = {}
    for t in nlu:
        if t["latency_ms"] is None:
            continue
        day = int(t["ts"] // 86400 * 86400)
        lat_series.setdefault(day, []).append(t["latency_ms"])
    lat_trend = [{"t": d, "p50": _p(v, .5), "p95": _p(v, .95)} for d, v in sorted(lat_series.items())]

    return {
        "engine_mix": dict(Counter(t["engine"] for t in turns)),
        "nlu_turns": len(nlu),
        "latency_ms": {"p50": _p(lat, .5), "p95": _p(lat, .95), "max": _p(lat, 1.0),
                       "llm_p50": _p(llm_lat, .5), "llm_p95": _p(llm_lat, .95)},
        "latency_trend": lat_trend,
        "tokens": {"input": tin, "output": tout,
                   "avg_per_call": round((tin + tout) / len(calls)) if calls else 0},
        "cost": {"usd": round(cost_usd, 4), "inr": round(cost_usd * USD_INR, 2),
                 "inr_per_call": round(cost_usd * USD_INR / len(calls), 3) if calls else 0},
        "stt": {"avg_confidence": round(statistics.mean(stt), 3) if stt else None,
                "accuracy_pct": round(100 * (1 - len(stt_errors) / len(stt)), 1) if stt else None,
                "low_conf_pct": _pct(sum(1 for s in stt if s < STT_CONFIDENCE_MIN), len(stt)),
                "low_conf_count": len(stt_errors),
                "samples": len(stt)},
        "intent": {"avg_confidence": round(statistics.mean(conf), 3) if conf else None,
                   "low_conf_pct": _pct(sum(1 for c in conf if c < INTENT_CONFIDENCE_MIN), len(conf)),
                   "accuracy_pct": _pct(correct, len(labelled)) if labelled else None,
                   "labelled_tickets": len(labelled),
                   "per_intent": [{"intent": k, "label": label(k), "n": v["n"],
                                   "accuracy_pct": _pct(v["correct"], v["n"])} for k, v in per_intent.items()],
                   "top_confusions": [{"predicted": label(a), "actual": label(b), "count": n}
                                      for (a, b), n in confusions.most_common(5)]},
        "slot_completeness_pct": round(100 * statistics.mean(completeness), 1) if completeness else None,
        "misunderstood_turn_pct": _pct(misunderstood, len(turns)),
        "avg_turns_per_call": round(statistics.mean([c["turn_count"] for c in calls]), 1) if calls else 0,
        "errors": {"count": len(errors), "fallback_pct": _pct(len(errors), len(turns)),
                   "recent": [{"ts": e["ts"], "error": e["error"]} for e in errors[-5:]]},
    }


def feedback_metrics(hours: float = 24 * 7):
    """How much RMs had to change what the agent wrote (app/telemetry.py).

    A ticket counts once an RM has saved it (reviewed). It is *accepted* when the RM kept the agent's
    summary, details and category as they were. The correction delta is the edit distance between the
    agent's text and the final text, as a share of its length (0 = untouched, 100% = rewritten)."""
    since = db.now() - hours * 3600
    tickets = db.q("""SELECT t.id, t.call_id, t.category, t.rm_category, t.summary, t.agent_summary, t.details_json,
                             t.agent_details_json, t.reviewed_at FROM tickets t
                      WHERE t.created_at>=? AND t.reviewed_at IS NOT NULL""", (since,))
    versions = {r["call_id"]: r["prompt_version"] for r in db.q(
        """SELECT call_id, prompt_version FROM traces WHERE id IN (SELECT MAX(id) FROM traces GROUP BY call_id)
           AND ts>=?""", (since,))}
    per_field = Counter()
    rows = []
    for t in tickets:
        old, new = json.loads(t["agent_details_json"] or "{}"), json.loads(t["details_json"] or "{}")
        changed = [f"detail:{k}" for k in set(old) | set(new) if str(old.get(k, "")) != str(new.get(k, ""))]
        if t["agent_summary"] is not None and (t["summary"] or "") != (t["agent_summary"] or ""):
            changed.append("summary")
        if t["rm_category"] and t["rm_category"] != t["category"]:
            changed.append("category")
        per_field.update({"details" if f.startswith("detail:") else f for f in changed})   # tickets, not edits
        text_before = (t["agent_summary"] or "") + "\n" + json.dumps(old, sort_keys=True, ensure_ascii=False)
        text_after = (t["summary"] or "") + "\n" + json.dumps(new, sort_keys=True, ensure_ascii=False)
        rows.append({"version": versions.get(t["call_id"], "unknown"), "accepted": not changed,
                     "delta": telemetry.delta(text_before, text_after) if t["agent_summary"] is not None else 0.0,
                     "chars": telemetry.edit_distance(text_before, text_after) if changed else 0})

    def summary(rs):
        return {"reviewed": len(rs), "acceptance_pct": _pct(sum(r["accepted"] for r in rs), len(rs)) if rs else None,
                "correction_delta_pct": round(100 * statistics.mean(r["delta"] for r in rs), 1) if rs else None,
                "avg_chars_changed": round(statistics.mean(r["chars"] for r in rs), 1) if rs else None}

    # Tokens per call by prompt version: context-window efficiency
    tok = db.q("""SELECT prompt_version v, COUNT(DISTINCT call_id) calls, COUNT(*) turns,
                         SUM(COALESCE(input_tokens,0)) tin, SUM(COALESCE(output_tokens,0)) tout
                  FROM traces WHERE ts>=? GROUP BY prompt_version""", (since,))
    by_version = {r["v"]: {"version": r["v"], "calls": r["calls"], "turns": r["turns"],
                           "tokens_per_call": round((r["tin"] + r["tout"]) / r["calls"]) if r["calls"] else 0,
                           "input_tokens_per_turn": round(r["tin"] / r["turns"]) if r["turns"] else 0}
                  for r in tok}
    for v in {r["version"] for r in rows}:
        by_version.setdefault(v, {"version": v})
        by_version[v].update(summary([r for r in rows if r["version"] == v]))
    recent = db.q("""SELECT ts, ref_id ticket_id, field, before, after, delta, actor FROM corrections
                     WHERE source='ticket' AND ts>=? ORDER BY delta DESC, ts DESC LIMIT 10""", (since,))
    return {**summary(rows), "fields_changed": dict(per_field), "by_prompt_version": list(by_version.values()),
            "biggest_corrections": recent, "current_prompt_version": telemetry.prompt_version()}


def _delta(current, previous):
    """Compute absolute and percentage change between two values."""
    if previous is None or previous == 0:
        return None, None
    abs_delta = current - previous
    pct_delta = round(100 * abs_delta / abs(previous), 1) if previous != 0 else None
    return round(abs_delta, 1), pct_delta


def metrics_trends(current_hours: float = 24 * 7, compare_to: str = "previous", rm_id: int | None = None,
                   csp_id: int | None = None, intent: str | None = None, prompt_version: str | None = None):
    """Compare metrics across two time periods (current vs previous/baseline).

    compare_to: 'previous' (same period ago) | 'baseline' (the deployed baseline)
    Returns: current metrics, previous metrics, deltas, and trend analysis
    """
    current_m = agent_metrics(current_hours, rm_id)
    model_m = model_metrics(current_hours)
    feedback_m = feedback_metrics(current_hours)

    # Get comparison metrics - compare current vs previous period
    if compare_to == "previous":
        since_current = db.now() - current_hours * 3600
        since_previous = db.now() - (current_hours * 2) * 3600
        previous_calls = db.q(f"""SELECT c.* FROM calls c
                             WHERE c.started_at>=? AND c.started_at<? ORDER BY c.started_at DESC""",
                            (since_previous, since_current))
        # Compute previous period metrics
        if previous_calls:
            previous_ended = [c for c in previous_calls if c["status"] == "ended"]
            durations = [c["duration_sec"] for c in previous_ended if c["duration_sec"] is not None]
            previous_totals = {
                "calls": len(previous_calls),
                "avg_duration_sec": round(statistics.mean(durations), 1) if durations else 0,
                "ticket_raise_rate": _pct(sum(1 for c in previous_ended if c["ticket_id"]), len(previous_ended)) if previous_ended else 0,
                "escalation_rate": _pct(sum(1 for c in previous_ended if c["outcome"] == "escalated"), len(previous_ended)) if previous_ended else 0,
                "not_understood_rate": _pct(sum(1 for c in previous_ended if c["outcome"] == "not_understood"), len(previous_ended)) if previous_ended else 0,
                "agent_handled_rate": _pct(sum(1 for c in previous_ended if c["outcome"] in ("ticket_raised", "resolved_by_agent", "info_only")), len(previous_ended)) if previous_ended else 0,
            }
        else:
            previous_totals = {k: 0 for k in ["calls", "avg_duration_sec", "ticket_raise_rate", "escalation_rate", "not_understood_rate", "agent_handled_rate"]}
    else:
        previous_totals = {}

    # Compute deltas
    agent_deltas = {}
    for k in ["calls", "avg_duration_sec", "ticket_raise_rate", "escalation_rate", "not_understood_rate", "agent_handled_rate"]:
        agent_deltas[k] = _delta(current_m["totals"].get(k, 0), previous_totals.get(k, 0))

    # Model metrics deltas
    model_deltas = {}
    model_deltas["intent_accuracy"] = (model_m["intent"]["accuracy_pct"], None) if model_m["intent"]["accuracy_pct"] is not None else (None, None)
    model_deltas["stt_confidence"] = (round(model_m["stt"]["avg_confidence"] * 100, 1) if model_m["stt"]["avg_confidence"] else None, None)
    model_deltas["intent_confidence"] = (round(model_m["intent"]["avg_confidence"] * 100, 1) if model_m["intent"]["avg_confidence"] else None, None)
    model_deltas["latency_p50"] = (model_m["latency_ms"]["p50"], None)
    model_deltas["cost_per_call"] = (model_m["cost"]["inr_per_call"], None)

    # Feedback metrics
    feedback_deltas = {}
    feedback_deltas["acceptance_rate"] = (feedback_m["acceptance_pct"], None) if feedback_m["acceptance_pct"] is not None else (None, None)
    feedback_deltas["correction_delta"] = (feedback_m["correction_delta_pct"], None) if feedback_m["correction_delta_pct"] is not None else (None, None)

    # Determine improving/degrading metrics
    all_deltas = {**agent_deltas, **model_deltas, **feedback_deltas}
    improving = []
    degrading = []
    for k, (d, p) in all_deltas.items():
        if d is None:
            continue
        # For rate metrics, lower is often better (e.g., escalation_rate, not_understood_rate)
        # For accuracy/acceptance/confidence, higher is better
        if k in ("escalation_rate", "not_understood_rate", "correction_delta"):
            if d < 0: improving.append(k)
            elif d > 0: degrading.append(k)
        else:
            if d > 0: improving.append(k)
            elif d < 0: degrading.append(k)

    return {
        "period": {"current_hours": current_hours, "compare_to": compare_to},
        "current": {
            "agent": current_m,
            "model": model_m,
            "feedback": feedback_m,
        },
        "previous": {
            "agent": {"totals": previous_totals} if previous_totals else {},
        },
        "deltas": {
            "agent": agent_deltas,
            "model": model_deltas,
            "feedback": feedback_deltas,
        },
        "summary": {
            "improving": improving,
            "degrading": degrading,
        }
    }
