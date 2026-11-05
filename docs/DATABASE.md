# Database Architecture & Locations

## Overview

Eko Sahayak uses **SQLite** for data storage. The application has multiple database instances in different environments, and it's critical to keep them synchronized to avoid data loss and inconsistencies.

## Database Locations

### Development Machine (Your Laptop)
- **Path**: `/home/cat/eko-rm-voice-agent/data/eko_agent.db`
- **Size**: ~2-4 MB (test data only)
- **Environment Variable**: `EKO_DB_PATH` (if set, overrides default)
- **Purpose**: Local testing and development
- **Backups**: `/home/cat/eko-rm-voice-agent/data/backups/`

### Server User Copy (indev.eko.in)
- **Path**: `/home/akanksha/voice_agent/data/eko_agent.db`
- **Size**: ~274 KB (usually empty - not used)
- **Status**: ⚠️ **UNUSED** - kept for reference only
- **Note**: This is the old manual setup on port 8010 (no longer active)

### Platform Docker Container (PRODUCTION - indev.eko.in)
- **Path**: `/data/eko_agent.db` (inside container)
- **Size**: ~5-10 MB (actual production data with 358+ recordings)
- **Environment Variable**: `EKO_DB_PATH=/data/eko_agent.db`
- **Host Mount**: Unknown volume (managed by Eko platform)
- **Status**: ✅ **ACTIVE** - serving indev.eko.in/rm-voice-agent
- **Access**: Limited - only via SSH to container or platform API

## Current Issue & Solution

### Problem
- The platform Docker database has **358+ recordings**
- Local development database has only **2 test recordings**
- They're out of sync, making it hard to test data display issues
- When you see "358 recordings" on the server but they don't display, it could be:
  - Database sync issue
  - JOIN failure (missing RMs/CSPs)
  - File path problems
  - API transformation errors

### Solution: Database Synchronization

#### View Database Status
```bash
python -m app.db_sync status
```

Output:
```
📊 Database Status
============================================================

Local Database: /home/cat/eko-rm-voice-agent/data/eko_agent.db
  Size: 1.90 MB
  Recordings: 2
  Upload Tokens: 4

Server Database: indev.eko.in:/home/akanksha/voice_agent/data/eko_agent.db
  Size: 0.26 MB
  Recordings: 0
  Upload Tokens: 4

⚠️  Server has database in Docker volume (not directly accessible)
```

#### Sync from Server to Local
```bash
python -m app.db_sync sync
```

This will:
1. Backup your current local database to `data/backups/eko_agent_YYYYMMDD_HHMMSS.db`
2. Download the server's database
3. Replace your local database with the server version
4. Report any issues

#### Manual SSH Download (if sync fails)
```bash
scp -P 2222 akanksha@indev.eko.in:/home/akanksha/voice_agent/data/eko_agent.db \
    ./data/eko_agent_server_backup.db
```

## Database Schema

### Key Tables
- **recordings**: Call recordings with transcripts, analysis results
- **upload_tokens**: API tokens for the Sahayak uploader app (one per RM phone)
- **rms**: Resource managers (typically 3-5)
- **csps**: CSPs/customers (595+ in production)
- **calls**: Call history/metadata
- **corrections**: Human corrections to transcripts and ML results
- **audit tables**: auth_events, auth_tokens, sessions, etc.

### Important Columns for Debugging

**recordings table:**
- `id`: Unique recording ID
- `rm_id`: FK to RMs (can be NULL for manual uploads)
- `token_id`: FK to upload_tokens (NULL = manual upload)
- `status`: 'new', 'pending', 'done', 'failed'
- `file_path`: Relative path to audio file in `data/recordings/`
- `started_at`: Timestamp when call started (Unix timestamp)
- `uploaded_at`: When it was uploaded to the server
- `transcript_json`: Whisper transcription output
- `summary`: LLM summary of the call

**upload_tokens table:**
- `id`: Token ID
- `token_hash`: SHA256 of the actual token (token never stored in clear)
- `rm_id`: FK to RMs (NULL = shared token)
- `label`: Human-readable name
- `created_at`, `last_used_at`, `revoked_at`: Timestamps

## Debugging Data Issues

### Data Mismatch: Counts ≠ List
If the API shows `{"counts": {"done": 358}, "recordings": []}`:

1. **Check the logs**:
   ```bash
   tail -100 /home/cat/eko-rm-voice-agent/data/logs/eko.log | grep "DATA MISMATCH"
   ```

2. **Check database directly**:
   ```bash
   python3 << 'EOF'
   from app import db
   
   # Total count
   result = db.q("SELECT COUNT(*) as cnt FROM recordings;")
   print(f"Total: {result[0]['cnt']}")
   
   # By status
   result = db.q("SELECT status, COUNT(*) as cnt FROM recordings GROUP BY status;")
   for row in result:
       print(f"  {row['status']}: {row['cnt']}")
   
   # Sample data
   result = db.q("SELECT id, rm_id, status, file_path FROM recordings LIMIT 5;")
   for row in result:
       print(f"  {row['id']}: rm={row['rm_id']}, status={row['status']}, path={row['file_path'][:40]}")
   EOF
   ```

3. **Check for JOIN failures**:
   ```bash
   python3 << 'EOF'
   from app import db
   
   # Raw recording count
   result = db.q("SELECT COUNT(*) as cnt FROM recordings;")
   raw = result[0]['cnt']
   
   # With joins (from list_recordings SQL)
   result = db.q("""
       SELECT COUNT(*) as cnt FROM recordings r 
       LEFT JOIN rms m ON m.id=r.rm_id 
       LEFT JOIN csps c ON c.id=r.csp_id
   """)
   with_joins = result[0]['cnt']
   
   print(f"Raw count: {raw}")
   print(f"With JOINs: {with_joins}")
   
   if raw != with_joins:
       print("⚠️  JOIN issue! Some recordings have invalid FK references")
   EOF
   ```

4. **Check file existence**:
   ```bash
   python3 << 'EOF'
   from app import db, recordings
   import os
   
   result = db.q("SELECT id, file_path FROM recordings;")
   missing = 0
   for row in result:
       path = os.path.join(recordings.storage_dir(), row['file_path'])
       if not os.path.exists(path):
           missing += 1
           print(f"  Missing: {row['file_path']}")
   
   print(f"\nTotal: {len(result)}, Missing files: {missing}")
   EOF
   ```

## Environment Variables

Set these in `.env` to override defaults:

```bash
# Database location (default: app/../data/eko_agent.db)
EKO_DB_PATH=/path/to/eko_agent.db

# Recording files storage (default: same dir as database)
RECORDINGS_DIR=/path/to/recordings

# Server connection for db_sync
SERVER_HOST=indev.eko.in
SERVER_PORT=2222
SERVER_USER=akanksha
```

## Backup Strategy

### Automatic Backups
- Each database sync creates a timestamped backup before overwriting
- Backups stored in: `data/backups/eko_agent_YYYYMMDD_HHMMSS.db`
- Keep for 30 days (manual cleanup needed)

### Manual Backup
```bash
# Backup local database
cp data/eko_agent.db data/backups/eko_agent_manual_$(date +%Y%m%d_%H%M%S).db

# Backup server database
scp -P 2222 akanksha@indev.eko.in:/home/akanksha/voice_agent/data/eko_agent.db \
    ./data/backups/eko_agent_server_$(date +%Y%m%d_%H%M%S).db
```

### Restore from Backup
```bash
cp data/backups/eko_agent_20261105_143022.db data/eko_agent.db
```

## API Logging for Data Issues

The `/api/recordings` endpoint now logs:
- Every API call with user and parameters
- Total counts from `summary_counts()`
- Number of recordings returned by `list_recordings()`
- **WARNING**: If counts ≠ returned items (data mismatch)

Monitor logs for warnings:
```bash
tail -f /home/cat/eko-rm-voice-agent/data/logs/eko.log | grep "DATA MISMATCH\|ERROR"
```

## Best Practices

1. **Always backup before syncing**: `db_sync` does this automatically
2. **Check status regularly**: `python -m app.db_sync status`
3. **Sync before testing features**: If working on data-heavy features
4. **Monitor logs for mismatches**: Set up alerts for "DATA MISMATCH"
5. **Keep backups**: Don't delete them until data is confirmed good
6. **Document schema changes**: Update this file if you add columns/tables

## References

- [[database-persistence-fix]] - Fix for ephemeral /app/data volume
- [[recordings-pilot]] - Recording upload pipeline details
- [[harness-phase-status]] - Current system state including recording count
