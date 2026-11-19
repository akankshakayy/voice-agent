import os
import tempfile
import time

import pytest

os.environ["AGENT_ENGINE"] = "rules"
os.environ["COOKIE_PATH"] = "/"


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    from app import db
    from app.seed import seed
    d = tempfile.mkdtemp()
    monkeypatch.setenv("RECORDINGS_DIR", os.path.join(d, "recordings"))
    db.reset_connection(os.path.join(d, "t.db"))
    seed()
    yield


def _phone():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def _dc(allowed=("9876543210",)):
    from app import db, recordings
    dc_id = db.x("INSERT INTO dcs(name, phone, created_at) VALUES(?,?,?)", ("Asha DC", "9000011111", time.time()))
    for n in allowed:
        db.x("INSERT INTO allowed_numbers(dc_id, phone_number, added_at) VALUES(?,?,?)", (dc_id, n, time.time()))
    return dc_id, recordings.create_token(dc_id=dc_id)["token"]


def _employee():
    from app import db, recordings
    emp_id = db.x("INSERT INTO employees(name, phone, created_at) VALUES(?,?,?)", ("Ravi", "9000022222", time.time()))
    return emp_id, recordings.create_token(employee_id=emp_id)["token"]


def _upload(c, token, mode, number, data=b"audio bytes", **form):
    return c.post("/api/uploader/recordings", files={"audio": ("call.m4a", data)},
                  data={"mode": mode, "other_number": number, "started_at": "1792560000000", **form},
                  headers={"Authorization": f"Bearer {token}"})


def test_dc_ping_asks_for_consent_and_lists_numbers():
    dc_id, tok = _dc()
    p = _phone().get("/api/uploader/ping", headers={"Authorization": f"Bearer {tok}"}).json()
    assert p["mode"] == "dc" and p["dc_id"] == dc_id and p["consent_required"] is True
    assert p["allowed_numbers"] == ["9876543210"]


def test_dc_upload_needs_server_issued_consent():
    _, tok = _dc()
    c = _phone()
    assert _upload(c, tok, "dc", "+91 98765 43210").status_code == 403                       # no consent
    assert _upload(c, tok, "dc", "+919876543210", consent_token="made-up").status_code == 403  # app-made code
    consent = c.post("/api/uploader/consent", headers={"Authorization": f"Bearer {tok}"}).json()["consent_token"]
    r = _upload(c, tok, "dc", "+91 98765 43210", consent_token=consent)
    assert r.status_code == 200, r.text
    r2 = _upload(c, tok, "dc", "09876543210", data=b"second call", consent_token=consent)   # consent is reusable
    assert r2.status_code == 200, r2.text


def test_dc_consent_is_only_for_its_own_dc():
    _, tok_a = _dc()
    from app import db, recordings
    other = db.x("INSERT INTO dcs(name, phone, created_at) VALUES(?,?,?)", ("Other DC", "9000033333", time.time()))
    db.x("INSERT INTO allowed_numbers(dc_id, phone_number, added_at) VALUES(?,?,?)", (other, "9876543210", time.time()))
    tok_b = recordings.create_token(dc_id=other)["token"]
    c = _phone()
    consent_a = c.post("/api/uploader/consent", headers={"Authorization": f"Bearer {tok_a}"}).json()["consent_token"]
    assert _upload(c, tok_b, "dc", "9876543210", consent_token=consent_a).status_code == 403


def test_dc_number_not_allowed_is_rejected():
    _, tok = _dc()
    c = _phone()
    consent = c.post("/api/uploader/consent", headers={"Authorization": f"Bearer {tok}"}).json()["consent_token"]
    r = _upload(c, tok, "dc", "9111111111", consent_token=consent)
    assert r.status_code == 400 and "allowed" in r.json()["detail"]


def test_consent_endpoint_refuses_rm_and_employee_and_bad_tokens():
    from app import recordings
    c = _phone()
    _, emp_tok = _employee()
    rm_tok = recordings.create_token(rm_id=1)["token"]
    for tok in (emp_tok, rm_tok):
        assert c.post("/api/uploader/consent", headers={"Authorization": f"Bearer {tok}"}).status_code == 400
    assert c.post("/api/uploader/consent").status_code == 401
    assert c.post("/api/uploader/consent", headers={"Authorization": "Bearer ekoup_wrong"}).status_code == 401


def test_employee_upload_needs_no_consent():
    emp_id, tok = _employee()
    c = _phone()
    p = c.get("/api/uploader/ping", headers={"Authorization": f"Bearer {tok}"}).json()
    assert p["mode"] == "employee" and p["employee_id"] == emp_id and "consent_required" not in p
    r = _upload(c, tok, "employee", "9123456789")
    assert r.status_code == 200, r.text


def test_rm_upload_unchanged():
    from app import recordings
    tok = recordings.create_token(rm_id=1)["token"]
    r = _upload(_phone(), tok, "rm", "9000000101", rm_id="1")
    assert r.status_code == 200, r.text


def test_shared_rm_token_can_be_created_and_used():
    from app import recordings
    t = recordings.create_token()
    assert t["mode"] == "rm" and t["rm_id"] is None
    c = _phone()
    p = c.get("/api/uploader/ping", headers={"Authorization": f"Bearer {t['token']}"}).json()
    assert p["rm_locked"] is False and p["rms"]
    assert _upload(c, t["token"], "rm", "9000000101", rm_id=str(p["rms"][0]["id"])).status_code == 200


def test_token_mode_must_match():
    _, tok = _employee()
    assert _upload(_phone(), tok, "dc", "9876543210").status_code == 400


def test_allowed_number_matching_ignores_prefixes():
    from app import recordings
    dc_id, _ = _dc(allowed=("+91 98765 43210",))
    for n in ("9876543210", "+919876543210", "09876543210", "98765-43210"):
        assert recordings.is_allowed_number(dc_id, n), n
    assert not recordings.is_allowed_number(dc_id, "9876543211")
    assert not recordings.is_allowed_number(dc_id, "")
