"""Recordings are transcribed by Sarvam only; per-call tokens, cost, words, voices and top words (app/call_metrics.py)."""
import json
import os
import tempfile
import time

import pytest

os.environ["AGENT_ENGINE"] = "rules"


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    from app import db
    from app.seed import seed
    monkeypatch.delenv("LLM_PRICES_USD", raising=False)
    monkeypatch.setenv("SARVAM_INR_PER_HOUR", "45")
    monkeypatch.setenv("USD_TO_INR", "85")
    db.reset_connection(os.path.join(tempfile.mkdtemp(), "t.db"))
    seed()
    yield


def _rec(lines, duration=120, review=None, summary=None, sarvam=True, mode="rm", rm_id=1, started=None):
    from app import db
    stt = {"provider": "sarvam|saaras:v4|codemix|hi-IN|2", "stt": "Sarvam", "lines": lines} if sarvam else {"model": "whisper"}
    return db.x("""INSERT INTO recordings(sha256, rm_id, mode, file_path, orig_name, size_bytes, status, uploaded_at,
                   started_at, duration_sec, transcript_json, stt_json, review_usage_json, summary_usage_json, is_csp_call)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                (f"h{time.time_ns()}", rm_id, mode, "x.m4a", "x.m4a", 1, "done", time.time(), started or time.time(),
                 duration, json.dumps(lines, ensure_ascii=False), json.dumps(stt),
                 json.dumps(review) if review is not None else None, json.dumps(summary) if summary is not None else None))


RM_CSP = [{"start": 0, "end": 3, "text": "नमस्कार Sir, वंदना बात कर रही हूँ। slab achieve कीजिए", "voice": "A", "speaker": "rm"},
          {"start": 3, "end": 6, "text": "हाँ जी, slab achieve करेंगे, mera number [PHONE] hai", "voice": "B", "speaker": "csp"},
          {"start": 6, "end": 9, "text": "slab achieve slab achieve slab", "voice": "A", "speaker": "rm"}]


def test_one_call_counts_words_voices_people_tokens_and_cost():
    from app import call_metrics
    rid = _rec(RM_CSP, duration=3600, review={"openai/gpt-oss-120b": {"input": 1000, "output": 200, "requests": 1}},
               summary={"openai/gpt-oss-120b": {"input": 500, "output": 300, "requests": 2}})
    from app.recordings import get_recording
    m = get_recording(rid)["metrics"]
    assert m["voices"] == 2 and m["rm_found"] and m["csp_found"]
    assert m["words"] == 10 + 8 + 5                                 # [PHONE] is not a word
    assert m["tokens"] == 2000 and m["tokens_in"] == 1500 and m["usage"]["openai/gpt-oss-120b"]["requests"] == 3
    assert m["stt_cost_inr"] == 45.0 and m["llm_cost_inr"] == 0 and m["cost_inr"] == 45.0   # an hour; Groq free tier


def test_llm_prices_and_unknown_claude_price(monkeypatch):
    from app import call_metrics
    use = {"claude-haiku-4-5": {"input": 1_000_000, "output": 100_000}}
    assert call_metrics.llm_cost_inr(use) is None                     # never guess a Claude price
    monkeypatch.setenv("LLM_PRICES_USD", '{"claude-haiku": [1, 5]}')
    assert call_metrics.llm_cost_inr(use) == pytest.approx((1 + 0.5) * 85)


def test_summary_over_calls_in_view():
    from app import call_metrics
    _rec(RM_CSP, review={"m": {"input": 100, "output": 10, "requests": 1}})
    _rec([{"start": 0, "end": 5, "text": "hello hello कोई है", "voice": "A", "speaker": "rm"}])   # one voice, no tokens kept
    _rec(RM_CSP, rm_id=2)
    _rec(RM_CSP, mode="employee")
    d = call_metrics.summary("rm", rm_id=1)
    assert d["calls"] == 2 and d["voices"]["two_or_more"] == 1 and d["voices"]["one"] == 1
    assert d["roles"]["both"] == 1 and d["roles"]["rm_only"] == 1
    assert d["tokens"]["calls"] == 1 and d["tokens"]["total"] == 110
    top = {w["word"]: w for w in d["top_words"]}
    assert top["slab"]["count"] == 5 and top["slab"]["calls"] == 1 and "जी" not in top and "hello" not in top
    assert {"word": "slab", "calls": 1, "group": "Eko business"} in d["repeated_in_call"]
    assert d["top_phrases"][0]["phrase"] == "slab achieve"
    assert d["top_words_rm"][0]["word"] == "slab" and any(w["word"] == "achieve" for w in d["top_words_csp"])
    assert "करेंगे" not in top and "वंदना" not in top                 # not domain words: left out
    assert d["word_counts"]["top_words"] == {"distinct": 2, "uses": 9} and d["word_counts"]["top_words_rm"]["distinct"] == 2
    assert top["slab"]["group"] == "Eko business" and {"group": "Eko business", "count": 9} in d["groups"]
    assert call_metrics.summary("rm")["calls"] == 3 and call_metrics.summary("employee")["calls"] == 1
    assert call_metrics.summary("rm", date_from=time.time() + 3600)["calls"] == 0


def test_usage_is_counted_only_inside_count_usage():
    from app import llm_engine
    llm_engine.record_usage("m", 5, 5)                               # outside: ignored
    with llm_engine.count_usage() as used:
        llm_engine.record_usage("m", 10, 2)
        llm_engine.record_usage("m", 1, 1)
    assert used == {"m": {"input": 11, "output": 3, "requests": 2}}


def test_recordings_wait_without_a_sarvam_key(monkeypatch):
    from app import recordings
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    res = recordings.process_pending()
    assert res["stopped"] == "SARVAM_API_KEY is not set" and res["processed"] == 0
    with pytest.raises(ValueError, match="Sarvam only"):
        recordings._transcribe({"id": 1, "stt_json": None}, "x.m4a")


def test_review_tokens_are_stored_with_the_recording(monkeypatch, tmp_path):
    from app import db, llm_engine, recordings, sarvam
    monkeypatch.setenv("SARVAM_API_KEY", "k")
    monkeypatch.setattr(recordings, "storage_dir", lambda: str(tmp_path))
    (tmp_path / "x.m4a").write_bytes(b"audio")
    lines = [{"start": 0, "end": 2, "text": "Haan ji bataiye", "voice": "A"}, {"start": 2, "end": 4, "text": "DMT fail hua", "voice": "B"}]
    monkeypatch.setattr(sarvam, "transcribe", lambda path: lines)
    monkeypatch.setattr(llm_engine, "provider", lambda: "groq")
    monkeypatch.setattr(recordings, "_write_summary", lambda rid: None)

    def ask(system, user, tool):
        llm_engine.record_usage("openai/gpt-oss-120b", 700, 90)
        return {"speakers": ["rm", "csp"], "is_csp_call": True, "intent": "unknown", "summary": "s"}, "openai/gpt-oss-120b"
    monkeypatch.setattr(recordings, "_ask", ask)
    rid = db.x("""INSERT INTO recordings(sha256, rm_id, mode, file_path, orig_name, size_bytes, status, uploaded_at, duration_sec, attempts)
                  VALUES('h', 1, 'rm', 'x.m4a', 'x.m4a', 5, 'new', ?, 60, 0)""", (time.time(),))
    recordings.process_one(db.q("SELECT * FROM recordings WHERE id=?", (rid,), one=True))
    r = recordings.get_recording(rid)
    assert r["status"] == "done" and r["timing"]["stt"].startswith("Sarvam")
    assert r["metrics"]["tokens"] == 790 and r["metrics"]["audio_s"] == 60 and r["metrics"]["stt_cost_inr"] == 0.75


def test_domain_words_and_misheard_corrections_are_kept():
    from app import domain_terms
    assert domain_terms.group_of("Refunds") == "Refund" and domain_terms.group_of("कमीशन") == "Commission"
    assert domain_terms.group_of("बैंक") == "Banks & IDs" and domain_terms.group_of("status") is None
    assert domain_terms.group_of("वंदना") is None and domain_terms.group_of("zyx", {"zyx": "Corrected as misheard"})


def _backfill_env(monkeypatch, tmp_path, transcribe):
    from app import llm_engine, recordings, sarvam
    monkeypatch.setenv("SARVAM_API_KEY", "k")
    monkeypatch.setattr(recordings, "BACKFILL", True)
    monkeypatch.setattr(recordings, "storage_dir", lambda: str(tmp_path))
    monkeypatch.setattr(sarvam, "transcribe", transcribe)
    monkeypatch.setattr(llm_engine, "provider", lambda: "groq")
    monkeypatch.setattr(recordings, "_write_summary", lambda rid: None)
    monkeypatch.setattr(recordings, "_ask", lambda *a: ({"speakers": ["rm"], "is_csp_call": True, "summary": "new"}, "m"))

    def no_handoff(*a):
        raise AssertionError("an old recording redone must not be sent again")
    monkeypatch.setattr(recordings.integrations, "recording_processed", no_handoff)


def _old(tmp_path, name, **cols):
    from app import db
    (tmp_path / name).write_bytes(b"audio")
    rid = _rec([{"start": 0, "end": 2, "text": "whisper text", "speaker": "rm"}], sarvam=cols.pop("sarvam", False))
    db.update("recordings", rid, file_path=name, attempts=1, **cols)
    return rid


def test_old_recordings_are_redone_by_sarvam_in_batches(monkeypatch, tmp_path):
    from app import db, recordings
    _backfill_env(monkeypatch, tmp_path, lambda path: [{"start": 0, "end": 2, "text": "Sarvam ne suna", "voice": "A"}])
    a = _old(tmp_path, "a.m4a")
    b = _old(tmp_path, "b.m4a", status="failed")
    _old(tmp_path, "c.m4a", checked_at=time.time())                 # a person checked it: kept
    _old(tmp_path, "d.m4a", mode="employee")                        # not transcribed at all
    _old(tmp_path, "e.m4a", sarvam=True)                            # already Sarvam
    db.update("recordings", _old(tmp_path, "f.m4a"), file_path="gone.m4a")   # audio missing
    assert {r["id"] for r in recordings.backfill_candidates()} == {a, b}
    assert recordings.backfill_status()["left"] == 2
    assert recordings.backfill_batch(1)["redone"] == 1                  # one batch of one
    assert recordings.backfill_status()["left"] == 1
    assert recordings.backfill_batch()["redone"] == 1
    for rid in (a, b):
        r = recordings.get_recording(rid)
        assert r["status"] == "done" and r["transcript"][0]["text"] == "Sarvam ne suna" and r["summary"] == "new"
    assert recordings.backfill_status()["left"] == 0


def test_a_failed_redo_keeps_the_old_transcript_and_gives_up_after_three(monkeypatch, tmp_path):
    from app import recordings, sarvam
    def broken(path):
        raise sarvam.SarvamError("bad file", 400)
    _backfill_env(monkeypatch, tmp_path, broken)
    rid = _old(tmp_path, "a.m4a")
    for _ in range(3):
        assert recordings.backfill_batch()["failed"] == 1
    r = recordings.get_recording(rid)
    assert r["status"] == "done" and r["transcript"][0]["text"] == "whisper text"
    assert recordings.backfill_candidates() == []


def test_new_uploads_go_before_the_redo(monkeypatch, tmp_path):
    from app import db, recordings
    _backfill_env(monkeypatch, tmp_path, lambda path: [])
    _old(tmp_path, "a.m4a")
    db.update("recordings", _old(tmp_path, "b.m4a"), status="new")
    assert recordings.backfill_batch() == {"redone": 0, "failed": 0, "stopped": "new uploads waiting"}
