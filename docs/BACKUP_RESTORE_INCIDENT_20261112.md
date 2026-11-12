# Incident Report & Backup Strategy - Nov 12, 2026

## What Happened
**Incident:** 358 real RM call recordings disappeared from production after deployments on Nov 12.

**Root Cause:** 
- Database file at `/home/akanksha/voice_agent/data/eko_agent.db` was deleted without proper backup
- No backup strategy was in place to protect against accidental data loss during deployments
- Database from this morning with 358 recordings was only found in `/tmp/eko_agent.db` as a temporary file

**Timeline:**
- Morning (Nov 12): 358 recordings + real CSP data in production database
- ~13:00-18:00: Multiple deployments (r0062, r0065, r0066)
- Database corrupted due to schema mismatch (mixing old/new schema versions)
- Deleted database to "clean" it
- **LOST DATA** - 358 recordings completely inaccessible

**Recovery:**
- Found backup at `/tmp/eko_agent.db` on server (user-provided location)
- Restored from backup file
- Deployed restored database to `/home/akanksha/voice_agent/data/eko_agent.db`

---

## What We Learned

1. **Database backups must be AUTOMATIC and CENTRALIZED**
2. **Never delete a database without verified backup**
3. **Database schema migrations need backward compatibility**
4. **Production data must have multiple redundant backups**

---

## Backup Strategy Going Forward

### 1. AUTOMATIC DAILY BACKUPS
```bash
# Add to crontab: Run every night at 22:00
22 * * * * cd /home/akanksha/voice_agent && python3 -m app.backup_restore export --full --zip
```

**Location:** `/home/akanksha/voice_agent/data/backups/`
**Retention:** Keep last 30 days of backups

### 2. PRE-DEPLOYMENT BACKUPS
```bash
# ALWAYS run before any eko-deploy command:
cp /home/akanksha/voice_agent/data/eko_agent.db /home/akanksha/voice_agent/data/backups/eko_agent_pre-deploy_$(date +%Y%m%d_%H%M%S).db
```

### 3. DOCKER VOLUME BACKUPS
**Problem:** Docker volume at `/data/eko_agent.db` is ephemeral - restarting container loses data
**Solution:** 
```bash
# After deploying, verify data is backed up:
- /home/akanksha/voice_agent/data/eko_agent.db (primary)
- /home/akanksha/voice_agent/data/backups/ (backup directory)
- /data/eko_agent.db (Docker volume - not reliable for persistence)
```

### 4. CRITICAL FILES TO PROTECT
```
/home/akanksha/voice_agent/data/eko_agent.db          # Main database - 358+ recordings
/home/akanksha/voice_agent/data/backups/              # Backup directory
/tmp/eko_agent.db                                     # Emergency backup (temp - move to permanent)
```

### 5. RECOVERY PROCEDURES

#### If recordings are lost:
```bash
# Step 1: Check /tmp first
ls -lh /tmp/eko_agent.db

# Step 2: Check backups directory
ls -lh /home/akanksha/voice_agent/data/backups/

# Step 3: Choose latest backup
BACKUP_FILE="/home/akanksha/voice_agent/data/backups/eko_agent_restore_20261112.db"

# Step 4: Restore
cp $BACKUP_FILE /home/akanksha/voice_agent/data/eko_agent.db
eko-deploy restart rm-voice-agent

# Step 5: Verify
python3 -c "import sqlite3; db=sqlite3.connect('/home/akanksha/voice_agent/data/eko_agent.db'); print(f'Recordings: {db.execute(\"SELECT COUNT(*) FROM recordings\").fetchone()[0]}')"
```

#### If database is corrupted (schema mismatch):
```bash
# Never delete - restore from backup immediately
# Check /tmp for temporary recovery database
file /tmp/eko_agent.db
cp /tmp/eko_agent.db /home/akanksha/voice_agent/data/eko_agent.db
```

---

## Current State (Nov 12, 2026)

**Restored Database:** `/home/akanksha/voice_agent/data/eko_agent.db`
- ✅ 358 recordings
- ✅ 15 CSPs (demo set - real 535 CSPs pending import)
- ✅ 3 RMs (Vandana, Shiwani, Amuda)

**Backup Created:** `/home/akanksha/voice_agent/data/backups/eko_agent_restore_20261112.db`
- Size: 516 KB
- Contains full 358 recordings + schema

**Deployment:** Running on live server at `https://indev.eko.in/rm-voice-agent/`

---

## Checklist for Future Deployments

- [ ] BEFORE any `eko-deploy` command, create pre-deployment backup:
  ```bash
  cp /home/akanksha/voice_agent/data/eko_agent.db /home/akanksha/voice_agent/data/backups/eko_agent_pre-deploy_$(date +%Y%m%d_%H%M%S).db
  ```

- [ ] NEVER delete `eko_agent.db` without verified backup elsewhere

- [ ] AFTER deployment, verify data integrity:
  ```bash
  python3 -c "import sqlite3; db=sqlite3.connect('/home/akanksha/voice_agent/data/eko_agent.db'); \
  print(f'Recordings: {db.execute(\"SELECT COUNT(*) FROM recordings\").fetchone()[0]}'); \
  print(f'CSPs: {db.execute(\"SELECT COUNT(*) FROM csps\").fetchone()[0]}')"
  ```

- [ ] Keep `/tmp/eko_agent.db` as emergency recovery point (update after each successful deployment)

- [ ] Monthly: Verify backups are being created and are accessible

---

## Prevention Measures

1. **Database Schema Migrations**
   - Use `ALTER TABLE ADD COLUMN IF NOT EXISTS` pattern
   - Never mix old and new schema versions in same container

2. **Error Handling**
   - Log all database operations with before/after record counts
   - Add guards in deployment to prevent data loss

3. **Monitoring**
   - Add database integrity check to health endpoints
   - Alert if recording count drops unexpectedly

4. **Documentation**
   - This incident report serves as runbook for future issues
   - Keep backup procedures updated in team wiki

---

## Key Takeaway
**Always assume production data can be lost. Have 3+ redundant backups at all times.**
- Automatic daily backups
- Pre-deployment backups  
- Backup directory with retention policy
- Immediate recovery procedures

