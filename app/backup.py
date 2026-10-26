"""Move a Sahayak's data to another Sahayak (e.g. from a laptop to the server).

  python -m app.backup make [out.tar.gz]     # on the machine that has the data

makes one file with the database and the recordings. An admin then uploads it on the new site
(Users page, "Move data here"). The upload is only accepted while that site is still empty - no calls,
no recordings, at most one account - so it can't overwrite real data; the replaced database is kept
next to the new one anyway (eko_agent.db.before-restore-<time>).

What is left out of the copy: sign-in sessions and one-time email links (everyone signs in again),
and accounts outside the company email domains lose their access (role 'pending'; an admin can change it).
The voice models aren't copied: the new site downloads them when it first needs them.
"""
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time

from . import auth, db, recordings

DB_NAME = "eko_agent.db"
NEEDED_TABLES = {"users", "rms", "csps", "calls", "tickets", "recordings"}


# ---------------------------------------------------------------- making the backup
def _snapshot(dest: str):
    """A consistent copy of the live database, even while the app is writing to it."""
    src = db.conn()
    out = sqlite3.connect(dest)
    with db._lock:
        src.backup(out)
    out.close()


def _clean(path: str) -> dict:
    """Strip what must not travel: sessions, one-time links; non-company accounts lose access."""
    c = sqlite3.connect(path)
    c.execute("DELETE FROM sessions")
    c.execute("DELETE FROM auth_tokens")
    domains = auth.allowed_domains()
    blocked = []
    if domains:
        for uid, email in c.execute("SELECT id, email FROM users").fetchall():
            if (email or "").rsplit("@", 1)[-1].lower() not in domains:
                blocked.append(email)
                c.execute("UPDATE users SET role='pending' WHERE id=?", (uid,))
    c.commit()
    c.execute("VACUUM")
    c.close()
    return {"accounts_without_access": blocked}


def make(out_path: str | None = None) -> dict:
    out_path = out_path or os.path.join(os.path.dirname(os.path.abspath(db.DB_PATH)),
                                        f"sahayak-backup-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz")
    with tempfile.TemporaryDirectory() as tmp:
        snap = os.path.join(tmp, DB_NAME)
        _snapshot(snap)
        info = _clean(snap)
        files = [r["file_path"] for r in db.q("SELECT file_path FROM recordings WHERE file_path IS NOT NULL")]
        store = recordings.storage_dir()
        with tarfile.open(out_path, "w:gz") as tar:
            tar.add(snap, arcname=DB_NAME)
            for rel in files:
                full = os.path.join(store, rel)
                if os.path.isfile(full):
                    tar.add(full, arcname=f"recordings/{rel}")
    return {"file": out_path, "size_mb": round(os.path.getsize(out_path) / 1e6, 1), "recordings": len(files), **info}


# ---------------------------------------------------------------- restoring it on the new site
def site_is_empty() -> bool:
    return not db.q("SELECT 1 FROM calls LIMIT 1", one=True) and not db.q("SELECT 1 FROM recordings LIMIT 1", one=True) \
        and db.q("SELECT COUNT(*) n FROM users", one=True)["n"] <= 1


def restore(fileobj) -> dict:
    if not site_is_empty():
        raise ValueError("This site already has data, so it can't be replaced by a backup")
    data_dir = os.path.dirname(os.path.abspath(db.DB_PATH))
    work = tempfile.mkdtemp(prefix="restore-", dir=data_dir)    # same disk as the database: moves are instant
    try:
        try:
            tar = tarfile.open(fileobj=fileobj, mode="r:gz")
        except (tarfile.TarError, OSError):
            raise ValueError("That isn't a Sahayak backup file (.tar.gz)")
        with tar:
            for m in tar.getmembers():
                if not (m.name == DB_NAME or m.name.startswith("recordings/")) or not (m.isfile() or m.isdir()):
                    raise ValueError(f"Unexpected item in the backup: {m.name[:80]}")
            tar.extractall(work, filter="data")     # no absolute paths, no "..", no links
        new_db = os.path.join(work, DB_NAME)
        if not os.path.isfile(new_db):
            raise ValueError("The backup has no database in it")
        try:
            c = sqlite3.connect(new_db)
            ok = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            c.close()
        except sqlite3.DatabaseError:
            ok, tables = False, set()
        if not ok or not NEEDED_TABLES <= tables:
            raise ValueError("The database in the backup is damaged or isn't a Sahayak database")

        stamp = time.strftime("%Y%m%d-%H%M%S")
        with db._lock:
            db.reset_connection()                                   # close it; reopened on next use
            for ext in ("", "-wal", "-shm"):
                if os.path.exists(db.DB_PATH + ext):
                    os.replace(db.DB_PATH + ext, f"{db.DB_PATH}.before-restore-{stamp}{ext}")
            os.replace(new_db, db.DB_PATH)
            src = os.path.join(work, "recordings")
            if os.path.isdir(src):
                dest = recordings.storage_dir()
                for root, _, names in os.walk(src):
                    for n in names:
                        target = os.path.join(dest, os.path.relpath(os.path.join(root, n), src))
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        shutil.move(os.path.join(root, n), target)
            db.conn()                                               # reopen and run any newer migrations
        counts = {t: db.q(f"SELECT COUNT(*) n FROM {t}", one=True)["n"]
                  for t in ("users", "rms", "csps", "calls", "tickets", "recordings")}
        return {"restored": counts, "previous_database": f"{os.path.basename(db.DB_PATH)}.before-restore-{stamp}"}
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "make":
        print(make(sys.argv[2] if len(sys.argv) > 2 else None))
    else:
        print(__doc__)
