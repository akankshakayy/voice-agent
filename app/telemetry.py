"""What the agent saw, what it said, and what a person changed afterwards.

Two records feed the self-improving loop:

- traces: one row per engine decision (each CSP turn). The exact system prompt, the messages, the
  CSP data and past tickets put into the prompt, and the model's raw output, frozen as they were.
  Live data changes; a trace still explains last week's answer.
- corrections: one row per field a person changed on something the agent produced (a ticket's
  summary, a detail, the category), with the edit distance between the agent's text and the final text.

Traces are written by a background thread so a slow disk never slows a call down.
Corrections are written in the request that makes them (they are small and rare).
"""
import hashlib
import inspect
import json
import os
import queue
import threading
import time

from . import db

KEEP_DAYS = float(os.environ.get("TRACE_KEEP_DAYS", "180"))
_q: queue.Queue = queue.Queue(maxsize=5000)
_worker = None
_worker_lock = threading.Lock()
_last_purge = 0.0
_version = None


# ---------------------------------------------------------------- prompt version
def prompt_version() -> str:
    """Short fingerprint of the prompt code and the tool schema. It changes whenever either changes,
    so every metric can be split by the prompt that produced it without anyone bumping a number."""
    global _version
    if _version is None:
        from . import llm_engine
        src = inspect.getsource(llm_engine._system_prompt) + inspect.getsource(llm_engine._build_messages) \
            + json.dumps(llm_engine.AGENT_TURN_TOOL, sort_keys=True)
        _version = os.environ.get("PROMPT_VERSION") or "p-" + hashlib.sha1(src.encode()).hexdigest()[:8]
    return _version


# ---------------------------------------------------------------- traces
def record_trace(call_id: int, turn_id: int | None, ts: float, decision: dict, heard: str, state: dict,
                 error: str | None = None):
    """Queue one engine decision. Never raises: telemetry must not break a call."""
    try:
        tr = decision.get("trace") or {}
        csp = state.get("csp") or {}
        context = {
            "heard": heard,                                    # the caller's words as the engine read them
            "csp": {k: csp.get(k) for k in ("id", "csp_code", "name", "district", "state", "category")} if csp else None,
            "rm_name": state.get("rm_name"),
            "past_tickets": [t.get("ticket_no") for t in state.get("csp_tickets") or []],
            "intent_before": state.get("intent"),
            "slots_before": {k: v for k, v in (state.get("slots") or {}).items() if not k.startswith("_")},
            "history_turns": len(state.get("history") or []),
        }
        output = {k: decision.get(k) for k in ("reply", "understood", "language", "intent", "intent_confidence",
                                               "slots", "sentiment", "action", "escalation_reason", "summary")}
        row = (call_id, turn_id, ts, decision.get("engine"), decision.get("model"),
               prompt_version() if decision.get("engine") not in ("rules", None) else "rules",
               tr.get("system"), json.dumps(tr.get("messages"), ensure_ascii=False) if tr.get("messages") else None,
               json.dumps(context, ensure_ascii=False, default=str),
               json.dumps(tr.get("raw"), ensure_ascii=False, default=str) if tr.get("raw") is not None else None,
               json.dumps(output, ensure_ascii=False, default=str),
               decision.get("latency_ms"), decision.get("input_tokens"), decision.get("output_tokens"), error)
        _start()
        _q.put_nowait(row)
    except Exception:
        pass   # a full queue or a bad value loses one trace, never the call


def _start():
    global _worker
    if _worker and _worker.is_alive():
        return
    with _worker_lock:
        if not (_worker and _worker.is_alive()):
            _worker = threading.Thread(target=_run, name="telemetry", daemon=True)
            _worker.start()


def _run():
    while True:
        row = _q.get()
        try:
            db.x("""INSERT INTO traces(call_id,turn_id,ts,engine,model,prompt_version,system_prompt,messages_json,
                    context_json,raw_output_json,output_json,latency_ms,input_tokens,output_tokens,error)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", row)
            _purge()
        except Exception:
            pass
        finally:
            _q.task_done()


def _purge():
    """Old traces hold full prompts (CSP names, numbers); keep them only TRACE_KEEP_DAYS."""
    global _last_purge
    if KEEP_DAYS <= 0 or time.time() - _last_purge < 86400:
        return
    _last_purge = time.time()
    db.x("DELETE FROM traces WHERE ts < ?", (time.time() - KEEP_DAYS * 86400,))


def flush(timeout: float = 5.0):
    """Wait until queued traces are written (tests, shutdown)."""
    end = time.time() + timeout
    while _q.unfinished_tasks and time.time() < end:
        time.sleep(0.01)


def traces_for_call(call_id: int) -> list[dict]:
    rows = db.q("SELECT * FROM traces WHERE call_id=? ORDER BY id", (call_id,))
    for r in rows:
        for k in ("messages_json", "context_json", "raw_output_json", "output_json"):
            r[k[:-5]] = json.loads(r.pop(k)) if r.get(k) else None
    return rows


# ---------------------------------------------------------------- corrections
def edit_distance(a: str, b: str, cap: int = 4000) -> int:
    """Levenshtein distance (characters inserted, deleted or replaced)."""
    a, b = (a or "")[:cap], (b or "")[:cap]
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def delta(a: str, b: str) -> float:
    """Edit distance as a share of the longer text: 0 = untouched, 1 = completely rewritten."""
    a, b = a or "", b or ""
    longest = max(len(a), len(b))
    return round(edit_distance(a, b) / longest, 4) if longest else 0.0


def record_correction(source: str, ref_id: int, field: str, before, after, actor: str | None,
                      call_id: int | None = None, ts: float | None = None):
    before, after = "" if before is None else str(before), "" if after is None else str(after)
    if before == after:
        return
    last = db.q("SELECT prompt_version FROM traces WHERE call_id=? ORDER BY id DESC LIMIT 1", (call_id,),
                one=True) if call_id else None
    db.x("""INSERT INTO corrections(ts,source,ref_id,call_id,field,before,after,distance,delta,actor,prompt_version)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
         (ts or db.now(), source, ref_id, call_id, field, before, after, edit_distance(before, after),
          delta(before, after), actor, last["prompt_version"] if last else None))


# ---------------------------------------------------------------- why the agent did what it did
UNSURE_BELOW = float(os.environ.get("WHY_UNSURE_BELOW", "0.75"))   # amber in the UI below this confidence
_RULE_REASONS = ("Suspected fraud", "CSP sounded angry", "Call exceeded max turns", "CSP asked to speak to RM",
                 "Not understood", "Call dropped")


def explain_ticket(t: dict) -> dict:
    """What the RM sees under "Why": who decided (a safety rule or the model), what the agent was given,
    and for each detail the caller's words it came from, marked unsure when the speech or the model was."""
    from .taxonomy import INTENT_CONFIDENCE_MIN
    call = db.q("SELECT intent, intent_confidence, engine FROM calls WHERE id=?", (t["call_id"],), one=True) or {}
    turns = db.q("SELECT id, role, text, stt_confidence, engine FROM turns WHERE call_id=? ORDER BY id",
                 (t["call_id"],))
    by_id = {x["id"]: x for x in turns}
    traces = traces_for_call(t["call_id"]) if t.get("call_id") else []

    def unsure(conf):
        return conf is not None and conf < UNSURE_BELOW

    # Where each detail first appeared: the turn whose decision added or changed it
    source = {}
    for tr in traces:
        before = (tr.get("context") or {}).get("slots_before") or {}
        for k, v in ((tr.get("output") or {}).get("slots") or {}).items():
            if not k.startswith("_") and before.get(k) != v:
                source[k] = tr
    details = []
    for k, v in json.loads(t.get("agent_details_json") or t.get("details_json") or "{}").items():
        tr = source.get(k)
        turn = by_id.get(tr["turn_id"]) if tr else None
        conf = turn["stt_confidence"] if turn else None
        details.append({"slot": k, "value": v, "heard": turn["text"] if turn else None, "speech_confidence": conf,
                        "unsure": unsure(conf)})

    reason = t.get("escalation_reason") or ""
    last_csp = next((x for x in reversed(turns) if x["role"] == "csp"), None)
    by_rule = bool(reason) and (reason.startswith(_RULE_REASONS) or (last_csp or {}).get("engine") == "guard")
    last = traces[-1] if traces else None
    ctx = (last or {}).get("context") or {}
    conf = call.get("intent_confidence")
    return {
        "decided_by": "safety rule" if by_rule else ("rules engine" if (last or {}).get("engine") == "rules"
                                                     else "AI model" if last else "unknown"),
        "rule": reason if by_rule else None,
        "model": (last or {}).get("model"), "prompt_version": (last or {}).get("prompt_version"),
        "intent": call.get("intent"), "intent_confidence": conf,
        "intent_unsure": conf is not None and conf < max(INTENT_CONFIDENCE_MIN, UNSURE_BELOW),
        "context": {"csp_code": (ctx.get("csp") or {}).get("csp_code"), "rm_name": ctx.get("rm_name"),
                    "past_tickets": ctx.get("past_tickets") or [], "turns_seen": len(traces)},
        "details": details,
        "unsure_turns": [x["text"] for x in turns if x["role"] == "csp" and unsure(x["stt_confidence"])],
        "unsure_below": UNSURE_BELOW,
        "traced": bool(traces),
    }
