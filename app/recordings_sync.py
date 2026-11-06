"""Sync audio recordings from server to local development environment.

This syncs the actual audio files (not just the database) from the production
server to your local /data/recordings directory so transcription can work locally.

Usage:
    python -m app.recordings_sync              # Sync all failed recordings
    python -m app.recordings_sync --all        # Sync all recordings
    python -m app.recordings_sync --limit 10   # Sync first 10
"""
import sqlite3
import sys
from pathlib import Path

# Configuration - matching db_sync.py
LOCAL_DB = Path(__file__).parent.parent / "data" / "eko_agent.db"
SERVER_HOST = "indev.eko.in"
SERVER_PORT = 2222
SERVER_RECORDINGS = "/data/recordings"
LOCAL_RECORDINGS = Path(__file__).parent.parent / "data" / "recordings"

def get_credentials():
    """Extract SSH credentials from .env file."""
    env_path = LOCAL_DB.parent.parent / ".env"
    credentials = {}

    if env_path.exists():
        with open(env_path) as f:
            content = f.read()
            match = re.search(r'Username=(.+)', content)
            if match:
                credentials['username'] = match.group(1).strip()
            match = re.search(r'Password=(.+)', content)
            if match:
                credentials['password'] = match.group(1).strip()

    return credentials

def sync_recordings(status_filter=None, limit=None):
    """Sync audio files from server using SFTP.

    Args:
        status_filter: 'failed', 'pending', or None for all
        limit: Maximum number of files to sync
    """
    try:
        import paramiko
    except ImportError:
        print("Error: paramiko not installed. Run: pip install paramiko")
        return

    conn = sqlite3.connect(LOCAL_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get recordings to sync
    query = "SELECT id, file_path FROM recordings"
    params = []

    if status_filter:
        query += " WHERE status = ?"
        params.append(status_filter)

    if limit:
        query += " LIMIT ?"
        params.append(limit)

    cursor.execute(query, params)
    recordings = cursor.fetchall()
    conn.close()

    if not recordings:
        print(f"No {status_filter or 'any'} recordings found")
        return

    # Get credentials
    creds = get_credentials()
    if 'username' not in creds or 'password' not in creds:
        print("Error: Could not find Username/Password in .env file")
        return

    print(f"Syncing {len(recordings)} recordings from {SERVER_HOST}:{SERVER_RECORDINGS}")
    print(f"To: {LOCAL_RECORDINGS}\n")

    # Ensure local directory exists
    LOCAL_RECORDINGS.mkdir(parents=True, exist_ok=True)

    synced = 0
    failed = 0

    try:
        # Connect via SFTP (like db_sync.py does)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            SERVER_HOST,
            port=SERVER_PORT,
            username=creds['username'],
            password=creds['password'],
            timeout=30
        )

        sftp = client.open_sftp()

        for rec in recordings:
            rec_id = rec['id']
            rel_path = rec['file_path']

            server_path = f"{SERVER_RECORDINGS}/{rel_path}"
            local_path = LOCAL_RECORDINGS / rel_path

            # Create subdirectories
            local_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                # Get file size from server
                stat = sftp.stat(server_path)
                size_mb = stat.st_size / (1024*1024)

                # Download file
                sftp.get(server_path, str(local_path))

                print(f"  OK ID {rec_id}: {rel_path} ({size_mb:.1f} MB)")
                synced += 1

            except (IOError, OSError) as e:
                if "No such file" in str(e):
                    print(f"  SKIP ID {rec_id}: File not found on server")
                else:
                    print(f"  ERROR ID {rec_id}: {str(e)[:80]}")
                failed += 1
            except Exception as e:
                print(f"  ERROR ID {rec_id}: {str(e)[:80]}")
                failed += 1

        sftp.close()
        client.close()

    except Exception as e:
        print(f"Connection error: {str(e)}")
        return

    print(f"\nSynced: {synced}")
    if failed:
        print(f"Failed: {failed}")

    # Check total size
    total_size = 0
    for f in LOCAL_RECORDINGS.rglob("*"):
        if f.is_file():
            try:
                total_size += f.stat().st_size
            except (FileNotFoundError, OSError):
                pass
    total_mb = total_size / (1024*1024)
    print(f"Total recordings size: {total_mb:.1f} MB")

if __name__ == "__main__":
    filter_type = "failed"  # Default: sync failed recordings
    limit = None

    for arg in sys.argv[1:]:
        if arg == "--all":
            filter_type = None
        elif arg == "--pending":
            filter_type = "pending"
        elif arg.startswith("--limit"):
            try:
                limit = int(arg.split("=")[1])
            except (ValueError, IndexError):
                limit = 10

    sync_recordings(status_filter=filter_type, limit=limit)
