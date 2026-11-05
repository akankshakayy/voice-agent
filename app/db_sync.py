"""Database synchronization and backup utilities.

Keeps local dev database in sync with server database and handles backups.
Database location: /home/cat/eko-rm-voice-agent/data/eko_agent.db
Server location: /home/akanksha/voice_agent/data/eko_agent.db
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Configuration
LOCAL_DB = Path(__file__).parent.parent / "data" / "eko_agent.db"
SERVER_HOST = "indev.eko.in"
SERVER_PORT = 2222
SERVER_USER = "akanksha"
SERVER_DB = "/home/akanksha/voice_agent/data/eko_agent.db"
BACKUP_DIR = LOCAL_DB.parent / "backups"

def get_db_info(db_path: str) -> dict:
    """Get database info: size, table count, recording count."""
    if not os.path.exists(db_path):
        return {"exists": False}

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM recordings;")
        recording_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM upload_tokens;")
        token_count = cursor.fetchone()[0]
        conn.close()

        size_mb = os.path.getsize(db_path) / (1024*1024)
        return {
            "exists": True,
            "size_mb": round(size_mb, 2),
            "recordings": recording_count,
            "tokens": token_count,
        }
    except Exception as e:
        return {"exists": True, "error": str(e)}

def sync_from_server() -> bool:
    """Sync database from server to local machine.

    Returns True if successful, False otherwise.
    """
    print(f"\n📡 Syncing database from {SERVER_HOST}:{SERVER_PORT}...")
    print(f"   Local: {LOCAL_DB}")
    print(f"   Server: {SERVER_DB}")

    # Create backup of current local database
    if LOCAL_DB.exists():
        backup_path = backup_local_db()
        print(f"   ✓ Backed up local to: {backup_path}")

    # Download from server using SCP
    try:
        cmd = [
            "scp",
            "-P", str(SERVER_PORT),
            f"{SERVER_USER}@{SERVER_HOST}:{SERVER_DB}",
            str(LOCAL_DB)
        ]

        # Set up password auth via SSH_ASKPASS
        env = os.environ.copy()

        # Create temp script for password
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            # Read password from .env if available
            env_path = LOCAL_DB.parent.parent / ".env"
            if env_path.exists():
                with open(env_path) as ef:
                    for line in ef:
                        if line.startswith("Password="):
                            password = line.split("=", 1)[1].strip()
                            f.write(f"#!/bin/bash\necho '{password}'\n")
                            break
            f.flush()
            os.chmod(f.name, 0o700)

            # Try SCP with password
            env['SSH_ASKPASS'] = f.name
            env['SSH_ASKPASS_REQUIRE'] = 'force'
            env['DISPLAY'] = ':0'  # Required for SSH_ASKPASS

            result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
            os.unlink(f.name)

        if result.returncode != 0:
            print(f"   ✗ SCP failed: {result.stderr}")
            return False

        # Verify the download
        local_info = get_db_info(str(LOCAL_DB))
        print(f"   ✓ Downloaded successfully")
        print(f"   ✓ Local DB now has {local_info.get('recordings', 0)} recordings")
        return True

    except subprocess.TimeoutExpired:
        print(f"   ✗ SCP timeout")
        return False
    except Exception as e:
        print(f"   ✗ Error: {e}")
        return False

def backup_local_db() -> str:
    """Backup the local database."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"eko_agent_{timestamp}.db"
    shutil.copy2(LOCAL_DB, backup_path)
    return str(backup_path)

def status() -> None:
    """Print database status for local and server."""
    print("\n📊 Database Status")
    print("="*60)

    # Local
    local_info = get_db_info(str(LOCAL_DB))
    print(f"\nLocal Database: {LOCAL_DB}")
    if local_info.get("exists"):
        print(f"  Size: {local_info.get('size_mb', 0)} MB")
        print(f"  Recordings: {local_info.get('recordings', 0)}")
        print(f"  Upload Tokens: {local_info.get('tokens', 0)}")
        if "error" in local_info:
            print(f"  ⚠️  Error: {local_info['error']}")
    else:
        print(f"  Not found")

    # Server
    print(f"\nServer Database: {SERVER_HOST}:{SERVER_DB}")
    server_info = get_db_info(f"ssh://{SERVER_USER}@{SERVER_HOST}:{SERVER_PORT}{SERVER_DB}")
    if server_info.get("exists"):
        print(f"  Size: {server_info.get('size_mb', 0)} MB")
        print(f"  Recordings: {server_info.get('recordings', 0)}")
        print(f"  Upload Tokens: {server_info.get('tokens', 0)}")
        if "error" in server_info:
            print(f"  ⚠️  Error: {server_info['error']}")
    else:
        print(f"  Not accessible (may be in Docker volume)")

    # Sync needed?
    local_recs = local_info.get('recordings', 0)
    server_recs = server_info.get('recordings', 0)
    if server_recs > local_recs:
        diff = server_recs - local_recs
        print(f"\n⚠️  Server has {diff} more recordings than local")
        print(f"   Run: python -m app.db_sync sync")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "sync":
        sync_from_server()
    else:
        status()
