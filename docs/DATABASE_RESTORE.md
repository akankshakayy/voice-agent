# Database Restoration Guide

## Problem
When deploying to a fresh container, the database may be empty even though data exists on the host. This happens because database files (`.db`) are in `.gitignore` to prevent committing production data.

## Solution: Use the `/api/admin/restore` Endpoint

### Step 1: Create a Database Backup
On the machine with the data:
```bash
python3 -m app.backup make pilot-database-backup.tar.gz
```

This creates a `.tar.gz` file with the database and recordings.

### Step 2: Upload via Admin Panel
1. Navigate to: `https://<your-server>/rm-voice-agent/admin`
2. Go to Users page → "Move data here" section
3. Upload the backup file

**Note**: The restore endpoint only works if the site is empty (no data). If you have existing data, download the current backup first.

### Step 3: Verify
- Refresh the page
- DCs, allowed numbers, and other data should appear
- The app will create the database tables automatically on first run

## Preventing This Issue in Future Deployments

### Option A: Store Backup in Git
For pilot/demo environments, store a snapshot backup:
```bash
# On host with data
python3 -m app.backup make deploy/pilot-backup.tar.gz
git add deploy/pilot-backup.tar.gz
git commit -m "pilot: Include database backup for deployment"
```

Then add initialization to Dockerfile:
```dockerfile
# At startup, restore if database is empty
if [ ! -f "$EKO_DB_PATH" ]; then
  tar -xzf /app/deploy/pilot-backup.tar.gz
  cp eko_agent.db "$EKO_DB_PATH"
fi
```

### Option B: Use Environment-Specific Backups
Store backups separately per environment:
- `backups/dev-snapshot.tar.gz` - for development
- `backups/staging-snapshot.tar.gz` - for staging
- Production uses live data only (no backup in repo)

### Option C: Database Initialization Script
Create a startup migration that populates test data if database is empty:
```python
# app/migrations.py
def init_empty_database():
    """Populate default data on first run"""
    if db.q("SELECT COUNT(*) FROM dcs", one=True)["COUNT(*)"] == 0:
        # Load from JSON file or SQL script
        seed_dcs()
        seed_allowed_numbers()
```

## For Production Deployments

1. **Always backup before deploying**: Use the backup feature to snapshot production data
2. **Store backups in secure location**: Not in git (use S3, encrypted storage, etc.)
3. **Document the data source**: Keep track of which backup corresponds to which deployment
4. **Test restoration**: Regularly test restoring from backup to verify integrity

## Troubleshooting

### "Database is not empty"
The restore endpoint only works on empty databases. To restore:
1. Create a new deployment/container
2. Or delete the database file and restart
3. Then use the restore endpoint

### Backup file corrupted
Check file size and integrity:
```bash
tar -tzf pilot-database-backup.tar.gz
```

### Data missing after restore
1. Check admin panel for data (DCs, allowed numbers, etc.)
2. Refresh browser cache
3. Check browser console for API errors
4. Verify backup file contained the data: `tar -tzf backup.tar.gz`

## API Reference

### GET /api/admin/restore
Check if restore is allowed (database must be empty):
```bash
curl https://<server>/rm-voice-agent/api/admin/restore
# Response: {"allowed": true/false}
```

### POST /api/admin/restore
Upload and restore from backup:
```bash
curl -F "backup_file=@pilot-database-backup.tar.gz" \
  https://<server>/rm-voice-agent/api/admin/restore
```
