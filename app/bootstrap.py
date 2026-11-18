"""Bootstrap: Auto-migrate data from /tmp if /data is empty"""
import os
import shutil
import sqlite3
from pathlib import Path

def migrate_db_if_needed():
    """
    If /data/eko_agent.db is empty or missing, check for migration file in /tmp
    This allows platform users to:
    1. Upload file to /tmp
    2. Restart container
    3. Auto-migration happens
    """
    data_dir = Path(os.environ.get("DATA_DIR", "data"))
    db_path = data_dir / "eko_agent.db"
    tmp_source = Path("/tmp/eko_agent.db")

    # Check if migration file exists
    if not tmp_source.exists():
        return

    # If dest exists and has data, skip
    if db_path.exists():
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM csps")
            count = c.fetchone()[0]
            conn.close()
            if count > 100:  # Has real data already
                return
        except:
            pass

    # Migrate
    print(f"🔄 Bootstrap: Migrating database from {tmp_source} → {db_path}")
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tmp_source, db_path)

        # Verify
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM csps")
        csps = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM rms")
        rms = c.fetchone()[0]
        conn.close()

        print(f"✅ Bootstrap: Migrated {csps} CSPs, {rms} RMs")

        # Clean up source
        tmp_source.unlink()
        print(f"✅ Bootstrap: Cleaned up {tmp_source}")

    except Exception as e:
        print(f"⚠️ Bootstrap: Migration failed: {e}")
        raise

if __name__ == "__main__":
    migrate_db_if_needed()


# Reference tables that are copied from the bundled database when the live one has none.
SEED_TABLES = ("dcs", "allowed_numbers")


def seed_reference_data(seed_path: str | None = None) -> dict:
    """Copy DCs and allowed numbers from the bundled database into the live one, table by table,
    ONLY when the live table is empty. Every other table (recordings, users, ...) is never touched.
    Safe to run on every start: once a table has rows it is skipped.
    Returns {table: rows_copied} (0 = skipped)."""
    import logging
    from . import db

    log = logging.getLogger("eko.bootstrap")
    seed_path = seed_path or os.environ.get("SEED_DB_PATH", "/app/eko_agent.db")
    result = {t: 0 for t in SEED_TABLES}
    if not os.path.exists(seed_path):
        log.info("Seed: no bundled database at %s - nothing to seed", seed_path)
        return result
    if os.path.abspath(seed_path) == os.path.abspath(db.DB_PATH):
        return result  # the live database IS the bundled one

    # immutable=1: read without creating -wal/-shm files (the image filesystem is read-only)
    src = sqlite3.connect(f"file:{seed_path}?mode=ro&immutable=1", uri=True)
    try:
        live = db.conn()
        with db._lock:
            for table in SEED_TABLES:
                if live.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]:
                    continue
                live_cols = {r[1] for r in live.execute(f"PRAGMA table_info({table})")}
                cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})") if r[1] in live_cols]
                if not cols:
                    continue
                rows = src.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
                live.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", rows)
                result[table] = len(rows)
            live.commit()
    finally:
        src.close()
    log.info("Seed from %s: %s", seed_path, result)
    print(f"Seed reference data from {seed_path}: {result}", flush=True)
    return result
