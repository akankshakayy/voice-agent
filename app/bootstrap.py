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
