"""Tests for Prachi API integration (Phase 7b - DC Mode)."""
import json
import os
import tempfile
import time

import pytest



@pytest.fixture(autouse=True)
def fresh_db():
    from app import db
    from app.seed import seed

    path = os.path.join(tempfile.mkdtemp(), "t.db")
    db.reset_connection(path)
    seed()
    yield


class _Resp:
    def __init__(self, code, body=None):
        self.status_code, self._body, self.text = code, body or {}, json.dumps(body or {})

    def json(self):
        return self._body


def _feed_on(monkeypatch, since="2026-11-25"):
    monkeypatch.setenv("PRACHI_RECORDING_SECRET", "s3cret")
    monkeypatch.setenv("PRACHI_SEND_FROM", since)
    monkeypatch.setenv("APP_BASE_URL", "https://indev.eko.in/rm-voice-agent")
    from app import recordings
    monkeypatch.setitem(recordings._prachi, "paused", "")


def _rec(mode="rm", uploaded_at=None, direction="outgoing", other="+91 98765 43210"):
    from app import db
    rm = db.q("SELECT id FROM rms WHERE phone IS NOT NULL AND phone<>'' LIMIT 1", one=True)["id"]
    dc = db.x("INSERT INTO dcs(name, phone, created_at) VALUES(?,?,?)", ("DC", f"90000{int(time.time()*1e6) % 100000:05d}", time.time()))
    t = uploaded_at or 1795600000.0          # 2026-11-26, after the switch-on date
    return db.x("""INSERT INTO recordings(sha256, mode, rm_id, dc_id, file_path, started_at, duration_sec, direction,
                   other_number, uploaded_at, status) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (f"sha{time.time_ns()}", mode, rm if mode == "rm" else None, dc if mode == "dc" else None,
                 "x.m4a", t - 100, 95.4, direction, other, t, "new"))


class TestPrachiHandoff:
    def test_off_until_switched_on(self, monkeypatch):
        from app import recordings
        monkeypatch.delenv("PRACHI_SEND_FROM", raising=False)
        monkeypatch.setenv("PRACHI_RECORDING_SECRET", "s3cret")
        _rec()
        assert "off" in recordings.send_to_prachi(now=1795600100)

    def test_rm_and_dc_records_and_per_record_results(self, monkeypatch):
        from app import db, recordings
        _feed_on(monkeypatch)
        rm_id, dc_id = _rec("rm"), _rec("dc", direction="inbound")
        old = _rec("rm", uploaded_at=1795000000.0)      # before the switch-on date: never sent
        emp = _rec("employee")
        sent = []

        def post(records):
            sent.extend(records)
            return _Resp(202, {"received": 2, "accepted": 1, "results": [
                {"id": str(rm_id), "status": "queued", "reason": ""},
                {"id": str(dc_id), "status": "skipped", "reason": "official_not_in_crm"}]})
        monkeypatch.setattr(recordings, "post_to_prachi", post)
        assert recordings.send_to_prachi(now=1795600100)["sent"] == 2
        by_id = {r["id"]: r for r in sent}
        rm, dc = by_id[str(rm_id)], by_id[str(dc_id)]
        assert "rm_number" in rm and "dc_number" not in rm and rm["direction"] == "outbound"
        assert "dc_number" in dc and "rm_number" not in dc and dc["direction"] == "inbound"
        assert rm["started_at"].endswith("+05:30") and rm["duration"] == 95
        assert rm["audio_url"].startswith("https://indev.eko.in/rm-voice-agent/api/prachi/recordings/")
        st = {r["id"]: r for r in db.q("SELECT id, prachi_status, prachi_reason FROM recordings")}
        assert st[rm_id]["prachi_status"] == "queued"
        assert (st[dc_id]["prachi_status"], st[dc_id]["prachi_reason"]) == ("skipped", "official_not_in_crm")
        assert st[old]["prachi_status"] is None and st[emp]["prachi_status"] is None
        assert recordings.send_to_prachi(now=1795600200) == {"sent": 0}   # nothing sent twice

    def test_unknown_direction_is_left_out(self, monkeypatch):
        from app import db, recordings
        _feed_on(monkeypatch)
        rec = recordings.prachi_record(db.q("SELECT * FROM recordings WHERE id=?", (_rec(direction=None),), one=True))
        assert "direction" not in rec

    def test_timeout_and_5xx_retry_401_pauses(self, monkeypatch):
        import requests
        from app import db, recordings
        _feed_on(monkeypatch)
        rid = _rec()

        def timeout(records):
            raise requests.Timeout("slow")
        monkeypatch.setattr(recordings, "post_to_prachi", timeout)
        assert "retry" in recordings.send_to_prachi(now=1795600100)
        monkeypatch.setattr(recordings, "post_to_prachi", lambda r: _Resp(503))
        assert "retry" in recordings.send_to_prachi(now=1795600100)
        assert db.q("SELECT prachi_status FROM recordings WHERE id=?", (rid,), one=True)["prachi_status"] is None
        calls = []
        monkeypatch.setattr(recordings, "post_to_prachi", lambda r: calls.append(r) or _Resp(401))
        assert "401" in recordings.send_to_prachi(now=1795600100)["off"]
        recordings.send_to_prachi(now=1795600100)
        assert len(calls) == 1                         # a wrong secret is not retried

    def test_gives_up_after_a_day(self, monkeypatch):
        from app import db, recordings
        _feed_on(monkeypatch)
        rid = _rec()
        monkeypatch.setattr(recordings, "post_to_prachi", lambda r: (_ for _ in ()).throw(AssertionError("sent")))
        recordings.send_to_prachi(now=1795600000 + 86400 + 10)
        assert db.q("SELECT prachi_status FROM recordings WHERE id=?", (rid,), one=True)["prachi_status"] == "gave_up"

    def test_signed_audio_link(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient
        from app import db, recordings
        from app.main import app
        _feed_on(monkeypatch)
        rid = _rec()
        audio = tmp_path / "a.m4a"
        audio.write_bytes(b"audio")
        monkeypatch.setattr(recordings, "audio_file", lambda row: str(audio))
        url = recordings.prachi_audio_url(rid).replace("https://indev.eko.in/rm-voice-agent", "")
        c = TestClient(app, client=("10.1.2.3", 5000))   # not localhost: no dev sign-in shortcut
        assert c.get(url).content == b"audio"
        assert c.get(url.replace("sig=", "sig=0")).status_code == 403
        expired = recordings.prachi_audio_url(rid, now=time.time() - 7200).replace("https://indev.eko.in/rm-voice-agent", "")
        assert c.get(expired).status_code == 403



class TestPrachiRecordingTracking:
    """Test database tracking of Prachi submissions."""

    def test_prachi_submission_status_tracking(self):
        """Test that Prachi submission status is tracked correctly."""
        from app import db

        # Create a prachi submission record
        sid = db.x(
            """INSERT INTO prachi_submissions(recording_id, dc_id, dc_name, dc_phone,
                                             caller_number, recipient_number, call_direction,
                                             duration_sec, uploaded_at, status, attempts)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                123,
                1,
                "DC Name",
                "9876543210",
                "9999999999",
                "9111111111",
                "inbound",
                120,
                "2025-01-15T10:00:00Z",
                "submitted",
                1,
            ),
        )

        # Verify submission was created
        sub = db.q("SELECT * FROM prachi_submissions WHERE id=?", (sid,), one=True)
        assert sub["recording_id"] == 123
        assert sub["status"] == "submitted"
        assert sub["attempts"] == 1
        assert sub["prachi_request_id"] is None

        # Update with request ID
        db.update("prachi_submissions", sid, prachi_request_id="prachi_req_456", status="processed")

        # Verify update
        sub = db.q("SELECT * FROM prachi_submissions WHERE id=?", (sid,), one=True)
        assert sub["prachi_request_id"] == "prachi_req_456"
        assert sub["status"] == "processed"
