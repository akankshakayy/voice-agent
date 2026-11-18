# Production Deployment Instructions

**Date:** Nov 13, 2026  
**Application:** Eko RM Voice Agent  
**Target:** indev.eko.in

## Overview

This guide walks through deploying the fixed version to production with proper persistent storage.

## Prerequisites Checklist

- [ ] Local machine: Docker installed
- [ ] Local machine: .env.local configured (completed)
- [ ] Local machine: Database backed up (367 recordings)
- [ ] Production server: SSH access working
- [ ] Production server: sudo access available
- [ ] eko-deploy: Installed and working

---

## Phase 1: Setup Production Infrastructure

### Step 1A: SSH to Production Server

```bash
ssh -p 2222 akanksha@indev.eko.in
# When prompted, enter your SSH password (kept in the local .env as Password=..., never in git)
```

### Step 1B: Create Persistent Storage Directory

```bash
# On production server:
sudo mkdir -p /data/rm-voice-agent
sudo chmod 777 /data/rm-voice-agent

# Verify:
ls -ld /data/rm-voice-agent
# Should show: drwxrwxrwx ... /data/rm-voice-agent
```

### Step 1C: Exit SSH

```bash
exit
```

---

## Phase 2: Backup Database to Production

**From your LOCAL machine:**

```bash
cd /home/cat/eko-rm-voice-agent

# Copy database to production server
scp -P 2222 data/eko_agent.db akanksha@indev.eko.in:/data/rm-voice-agent/

# Verify it was copied
scp -P 2222 akanksha@indev.eko.in:/data/rm-voice-agent/eko_agent.db /tmp/verify.db
ls -lh /tmp/verify.db
# Should show: 528 KB (367 recordings)
```

---

## Phase 3: Deploy Application

**From your LOCAL machine:**

### Step 3A: Build Docker Image (if not already built)

```bash
cd /home/cat/eko-rm-voice-agent

docker build -t eko-sahayak:latest .
# Should complete successfully
# Image ID should be recent (not from earlier in session)
```

### Step 3B: Run eko-deploy

```bash
# Make sure .env.local exists and has all secrets
cat .env.local | head -5
# Should show your production configuration

# Deploy
eko-deploy deploy \
  --app rm-voice-agent \
  --image eko-sahayak:latest \
  --env-file .env.local \
  --volumes /data/rm-voice-agent:/app/data \
  --volumes /data/rm-voice-agent:/data \
  --port 8000
```

### Step 3C: Wait for Deployment

Monitor the eko-deploy output for:
- ✓ Image pulled/loaded
- ✓ Container started
- ✓ Port 8000 ready
- ✓ Health checks passing

Expected output should show:
```
Deploying rm-voice-agent...
✓ Image ready
✓ Container started
✓ Health check passed
✓ Application ready at https://indev.eko.in/rm-voice-agent
```

---

## Phase 4: Verify Deployment

### Step 4A: Check Container is Running

```bash
# From production server:
ssh -p 2222 akanksha@indev.eko.in
docker ps | grep rm-voice-agent
# Should show the running container
exit
```

### Step 4B: Verify Volume Mounts

```bash
# From production server:
ssh -p 2222 akanksha@indev.eko.in
docker inspect <container_id> | grep -A 10 "Mounts"
# Should show:
#   /data/rm-voice-agent → /app/data
#   /data/rm-voice-agent → /data
exit
```

### Step 4C: Check Health Endpoint

```bash
# From local machine:
curl https://indev.eko.in/rm-voice-agent/health

# Should return:
# {"status": "ok", "database": "connected", ...}
```

### Step 4D: Verify 367 Recordings Accessible

```bash
# From local machine (after signing in via web):
# Visit: https://indev.eko.in/rm-voice-agent/admin
# Check: Recordings page should show 367 records

# Or via API (requires auth):
curl -b cookies.txt https://indev.eko.in/rm-voice-agent/api/recordings
# Should return JSON with 367 recording objects
```

### Step 4E: Test Persistence

```bash
# From production server:
ssh -p 2222 akanksha@indev.eko.in

# Restart container
docker restart <container_id>

# Wait 30 seconds
sleep 30

# Check container is still running
docker ps | grep rm-voice-agent

# Check API still responds
curl http://localhost:8000/health

# Verify data still there (from local machine):
curl https://indev.eko.in/rm-voice-agent/health
# Should still show "database": "connected"

exit
```

---

## Troubleshooting

### Issue: Container Won't Start

**Check logs:**
```bash
docker logs <container_id>
```

**Common causes:**
1. Permission error on /app/data/logs/
   - Fix: `chmod 777 /data/rm-voice-agent` on server

2. Database not found
   - Fix: Copy database: `scp ... akanksha@indev.eko.in:/data/rm-voice-agent/`

3. Environment variables missing
   - Fix: Verify .env.local has all required vars

### Issue: 0 Recordings After Deploy

**Most likely cause:** Database didn't sync to production

**Fix:**
```bash
# From local machine:
scp -P 2222 data/eko_agent.db akanksha@indev.eko.in:/data/rm-voice-agent/

# On production server:
docker restart <container_id>

# Verify:
docker logs <container_id> | grep "Found.*eko_agent.db"
```

### Issue: Can't Write to /app/data

**Fix:**
```bash
# On production server:
sudo chmod 777 /data/rm-voice-agent
ls -ld /data/rm-voice-agent
# Should show: drwxrwxrwx
```

### Issue: Volume Mount Not Working

**Check:**
```bash
# On production server:
docker inspect <container_id> | grep -A 5 "Mounts"
# Should show the volume mounts

# If not showing:
# 1. Verify eko-deploy command had --volumes flags
# 2. Stop container and redeploy with correct flags
# 3. Check eko-deploy documentation
```

---

## Rollback Procedure

If something goes wrong:

```bash
# From local machine:
eko-deploy rollback rm-voice-agent

# Or redeploy with a known-good commit:
git checkout <known_good_commit>
docker build -t eko-sahayak:rollback .
eko-deploy deploy --image eko-sahayak:rollback ...
```

---

## Post-Deployment Checklist

- [ ] Container running without permission errors
- [ ] Health endpoint responds
- [ ] 367 recordings visible in UI
- [ ] Logs being written to /app/data/logs/
- [ ] Logs rotate properly
- [ ] Container restart doesn't lose data
- [ ] Database accessible after restart
- [ ] AutoGMap sync working (check logs)
- [ ] Prachi integration configured (check .env.local)

---

## Ongoing Maintenance

### Regular Backups

```bash
# On production server, periodically:
cp /data/rm-voice-agent/eko_agent.db /backups/eko_agent.db.$(date +%Y%m%d)

# Or use the API backup endpoint:
curl https://indev.eko.in/rm-voice-agent/api/backup/export > backup_$(date +%Y%m%d).zip
```

### Monitor Disk Usage

```bash
# On production server:
du -sh /data/rm-voice-agent
# Watch for growth (recordings being added)
```

### Monitor Logs

```bash
# On production server:
docker logs -f <container_id>
# Watch for errors
```

---

## Support

If deployment fails:

1. Check all prerequisites are complete
2. Review troubleshooting section
3. Check application logs: `docker logs <container_id>`
4. Check eko-deploy logs: `eko-deploy logs rm-voice-agent`
5. Verify /data/rm-voice-agent permissions: `chmod 777 /data/rm-voice-agent`
6. Verify database copied: `ls -lh /data/rm-voice-agent/eko_agent.db`

---

## Summary

**What was fixed:**
- ✅ Dockerfile permissions (chmod 777)
- ✅ eko.yml volume mount configuration
- ✅ Environment variables in .env.local
- ✅ Database restored and ready

**What production needs:**
- [ ] Persistent storage directory created
- [ ] Database backed up to production
- [ ] Proper volume mount flags in eko-deploy
- [ ] Verification that data persists

**Expected outcome:**
- Container runs without permission errors
- 367 recordings accessible
- Data persists after container restart
- Application ready for production use

