"""RM voiceprints decide which voice in a recorded call is the RM (app/voiceprint.py)."""
import json
import os
import tempfile
import time

import pytest

os.environ["AGENT_ENGINE"] = "rules"

LINES = [{"start": 0, "end": 2, "text": "हाँ Madam, बोलिए", "voice": "A"},
         {"start": 2, "end": 5, "text": "Sanjay Shah का क्या update है?", "voice": "B"}]


@pytest.fixture(autouse=True)
def fresh_db():
    from app import db
    from app.seed import seed
    db.reset_connection(os.path.join(tempfile.mkdtemp(), "t.db"))
    seed()
    yield


def _stored(rm_id=1):
    from app import voiceprint
    voiceprint.save(rm_id, {"model": voiceprint.MODEL_FILE, "vec": [1.0, 0.0], "seconds": 45}, "admin@eko.co.in")


def test_the_clearly_closer_voice_is_the_rm_otherwise_none():
    from app import voiceprint
    assert voiceprint.decide({"A": 0.23, "B": 0.51}) == ("B", 0.28)
    assert voiceprint.decide({"A": 0.30, "B": 0.33})[0] is None
    assert voiceprint.decide({"A": 0.6}) == (None, 0.0)


def test_voiceprint_from_another_model_is_ignored_and_status_hides_the_numbers():
    from app import db, voiceprint
    assert voiceprint.get(1) is None
    db.x("UPDATE rms SET voiceprint_json=? WHERE id=1", (json.dumps({"model": "old.onnx", "vec": [1]}),))
    assert voiceprint.get(1) is None
    _stored()
    assert voiceprint.get(1)["seconds"] == 45
    row = next(r for r in voiceprint.status() if r["id"] == 1)
    assert row["has_voiceprint"] and row["by"] == "admin@eko.co.in" and "vec" not in json.dumps(row)
    voiceprint.remove(1)
    assert voiceprint.get(1) is None


def test_review_follows_the_voiceprint_over_the_ai(monkeypatch):
    from app import recordings
    seen = {}

    def ask(system, user, tool):
        seen["user"] = user
        return {"voice_roles": {"A": "rm", "B": "csp"}, "speakers": ["rm", "csp"], "summary": "s"}, "m"
    monkeypatch.setattr(recordings, "_ask", ask)
    out, _ = recordings.review_call(LINES, "B")
    assert out["speakers"] == ["csp", "rm"] and out["ai_voice_roles"] == {"A": "rm", "B": "csp"}
    assert "Voice B is the RM" in seen["user"]
    out, _ = recordings.review_call(LINES)
    assert out["speakers"] == ["rm", "csp"]


def _process(monkeypatch, tmp_path, match, rm_id=1, mode="rm"):
    from app import db, llm_engine, recordings, sarvam, voiceprint
    monkeypatch.setenv("SARVAM_API_KEY", "k")
    monkeypatch.setattr(recordings, "storage_dir", lambda: str(tmp_path))
    (tmp_path / "x.m4a").write_bytes(b"audio")
    monkeypatch.setattr(sarvam, "transcribe", lambda path: LINES)
    monkeypatch.setattr(llm_engine, "provider", lambda: "groq")
    monkeypatch.setattr(recordings, "_write_summary", lambda rid: None)
    monkeypatch.setattr(voiceprint, "match", match)
    monkeypatch.setattr(recordings, "_ask", lambda *a: ({"voice_roles": {"A": "rm", "B": "csp"}, "speakers": ["rm", "csp"],
                                                        "is_csp_call": False, "summary": "s"}, "m"))
    rid = db.x("""INSERT INTO recordings(sha256, rm_id, mode, file_path, orig_name, size_bytes, status, uploaded_at, duration_sec, attempts)
                  VALUES(?, ?, ?, 'x.m4a', 'x.m4a', 5, 'new', ?, 60, 0)""", (f"h{time.time_ns()}", rm_id, mode, time.time()))
    recordings.process_one(db.q("SELECT * FROM recordings WHERE id=?", (rid,), one=True))
    return recordings.get_recording(rid)


def test_processing_labels_the_rm_by_voice_and_notes_the_ai_disagreed(monkeypatch, tmp_path):
    from app import voiceprint
    _stored()
    calls = []

    def match(path, lines, rm_id):
        calls.append(rm_id)
        return {"rm_voice": "B", "scores": {"A": 0.23, "B": 0.51}, "margin": 0.28, "model": voiceprint.MODEL_FILE,
                "min_margin": voiceprint.MIN_MARGIN}
    r = _process(monkeypatch, tmp_path, match)
    assert [l["speaker"] for l in r["transcript"]] == ["csp", "rm"]
    assert r["timing"]["voiceprint"]["rm_voice"] == "B" and r["timing"]["voiceprint"]["ai_agreed"] is False
    assert calls == [1]


def test_unclear_match_or_no_voiceprint_keeps_the_ai_guess(monkeypatch, tmp_path):
    from app import voiceprint
    unclear = lambda p, l, rm: {"rm_voice": None, "scores": {"A": 0.3, "B": 0.32}, "margin": 0.02,
                                "model": voiceprint.MODEL_FILE, "min_margin": voiceprint.MIN_MARGIN}
    r = _process(monkeypatch, tmp_path, lambda *a: pytest.fail("no voiceprint stored: must not match"))
    assert [l["speaker"] for l in r["transcript"]] == ["rm", "csp"] and "voiceprint" not in r["timing"]
    _stored()
    r = _process(monkeypatch, tmp_path, unclear)
    assert [l["speaker"] for l in r["transcript"]] == ["rm", "csp"] and r["timing"]["voiceprint"]["rm_voice"] is None


def test_a_failed_match_never_fails_the_recording(monkeypatch, tmp_path):
    _stored()

    def boom(*a):
        raise RuntimeError("model download failed")
    r = _process(monkeypatch, tmp_path, boom)
    assert r["status"] == "done" and [l["speaker"] for l in r["transcript"]] == ["rm", "csp"]


def test_only_admins_upload_samples_and_short_ones_are_refused(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main, voiceprint
    c = TestClient(main.app)
    assert c.post("/api/rms/1/voice-sample", files={"file": ("s.m4a", b"x")}).status_code in (401, 403, 303, 307)
    with pytest.raises(ValueError, match="at least 20 seconds"):
        monkeypatch.setattr(voiceprint, "_load", lambda p: __import__("numpy").zeros(16000 * 5, dtype="float32"))
        voiceprint.from_sample("short.m4a")
