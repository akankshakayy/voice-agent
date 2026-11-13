# Next Steps - Deployment Action Items

**Status:** All code fixes complete ✅ | Infrastructure setup pending ⏳

---

## What Was Done ✅

### Code Fixes Committed (4 commits)
1. ✅ **Permission Fix** - Dockerfile chmod 755 → 777
2. ✅ **Volume Config** - eko.yml updated to standard paths
3. ✅ **Environment** - .env.local complete with all production secrets
4. ✅ **Documentation** - Deployment instructions and scripts added

### Testing Completed ✅
- ✅ Database verified: 367 recordings in `/home/cat/eko-rm-voice-agent/data/eko_agent.db`
- ✅ Docker image built and tested with volume mounts
- ✅ Container starts without permission errors
- ✅ Application runs successfully

### What's Ready ✅
- ✅ Code is production-ready
- ✅ Docker image: `eko-sahayak:latest` (built Nov 13)
- ✅ Configuration: `.env.local` with all secrets
- ✅ Database: 367 recordings backed up locally

---

## What's Still Needed ⏳

### Phase 1: Production Server Setup (30 min)
**Who:** DevOps/Sysadmin  
**What:** Create persistent storage directory

```bash
# SSH to indev.eko.in
ssh -p 2222 akanksha@indev.eko.in

# Run (with sudo if needed):
mkdir -p /data/rm-voice-agent
chmod 777 /data/rm-voice-agent

# Verify:
ls -ld /data/rm-voice-agent
# Output: drwxrwxrwx ... /data/rm-voice-agent

exit
```

**Or:** Run the automated script:
```bash
bash PRODUCTION_DEPLOYMENT_SCRIPT.sh
```

### Phase 2: Database Backup (5 min)
**Who:** You (from local machine)  
**What:** Copy database to production

```bash
cd /home/cat/eko-rm-voice-agent

# Copy database
scp -P 2222 data/eko_agent.db akanksha@indev.eko.in:/data/rm-voice-agent/

# Verify (should be ~528 KB)
scp -P 2222 akanksha@indev.eko.in:/data/rm-voice-agent/eko_agent.db /tmp/test.db
ls -lh /tmp/test.db
```

### Phase 3: Deploy (10 min)
**Who:** You (from local machine)  
**What:** Run eko-deploy with proper volume mount flags

```bash
cd /home/cat/eko-rm-voice-agent

# Ensure Docker image is built
docker images | grep eko-sahayak:latest
# If not there: docker build -t eko-sahayak:latest .

# Deploy
eko-deploy deploy \
  --app rm-voice-agent \
  --image eko-sahayak:latest \
  --env-file .env.local \
  --volumes /data/rm-voice-agent:/app/data \
  --volumes /data/rm-voice-agent:/data \
  --port 8000
```

### Phase 4: Verify (10 min)
**Who:** You  
**What:** Check everything works

```bash
# 1. Health check
curl https://indev.eko.in/rm-voice-agent/health
# Should return: {"status": "ok", "database": "connected"}

# 2. Check container running
ssh -p 2222 akanksha@indev.eko.in
docker ps | grep rm-voice-agent
exit

# 3. Check data persists
ssh -p 2222 akanksha@indev.eko.in
docker restart <container_id>
sleep 10
exit

curl https://indev.eko.in/rm-voice-agent/health
# Should still work

# 4. Check recordings
# Visit: https://indev.eko.in/rm-voice-agent/admin
# Sign in and check Recordings page
# Should show 367 records
```

---

## Timeline

| Step | Duration | Who | Status |
|------|----------|-----|--------|
| Create /data/rm-voice-agent | 5 min | DevOps | ⏳ Pending |
| Copy database backup | 5 min | You | ⏳ Pending |
| Run eko-deploy | 10 min | You | ⏳ Pending |
| Verify deployment | 10 min | You | ⏳ Pending |
| **Total** | **30 min** | - | - |

---

## Quick Reference

### Important Directories/Files

**Local Development:**
- Database: `/home/cat/eko-rm-voice-agent/data/eko_agent.db` (367 recordings)
- Config: `/home/cat/eko-rm-voice-agent/.env.local` (production secrets - DO NOT COMMIT)
- Docker image: `eko-sahayak:latest`
- Deployment scripts: `DEPLOYMENT_INSTRUCTIONS.md`, `PRODUCTION_DEPLOYMENT_SCRIPT.sh`

**Production Server:**
- Persistent storage: `/data/rm-voice-agent/` (needs to be created)
- Database will be: `/data/rm-voice-agent/eko_agent.db`
- Container mounts: `/app/data` → `/data/rm-voice-agent` (for app) + `/data` → `/data/rm-voice-agent` (for logs)
- Logs: `/data/rm-voice-agent/logs/eko.log`
- Application URL: `https://indev.eko.in/rm-voice-agent`

### Essential Git Commits

```bash
git log --oneline | head -10
# 8b5c93e docs: Add production deployment instructions
# 943d102 chore: Ignore .env.local
# 4a6ac9e fix: Resolve volume mount permission issues
# 9e65bab refactor: Simplify eko.yml volume format
# d39a8e2 fix: Update eko-deploy volume mount path
```

### Commands Cheat Sheet

**Local:**
```bash
# Build image
docker build -t eko-sahayak:latest .

# Test locally
docker run -v /home/cat/eko-rm-voice-agent/data:/app/data \
           -v /home/cat/eko-rm-voice-agent/data:/data \
           --env-file .env.local \
           eko-sahayak:latest

# Copy database to production
scp -P 2222 data/eko_agent.db akanksha@indev.eko.in:/data/rm-voice-agent/

# Deploy
eko-deploy deploy --app rm-voice-agent --image eko-sahayak:latest \
  --env-file .env.local \
  --volumes /data/rm-voice-agent:/app/data \
  --volumes /data/rm-voice-agent:/data \
  --port 8000
```

**Production Server:**
```bash
# SSH
ssh -p 2222 akanksha@indev.eko.in

# Setup storage
sudo mkdir -p /data/rm-voice-agent && sudo chmod 777 /data/rm-voice-agent

# Check status
docker ps | grep rm-voice-agent
docker logs <container_id>

# Inspect mounts
docker inspect <container_id> | grep -A 10 Mounts
```

---

## Troubleshooting Quick Links

See `DEPLOYMENT_INSTRUCTIONS.md` for detailed troubleshooting:

- Container won't start → Check logs, permissions, database
- 0 recordings after deploy → Copy database, restart container
- Can't write to /app/data → chmod 777 /data/rm-voice-agent
- Volume mount not working → Verify eko-deploy command flags

---

## Success Criteria

✅ Deployment is successful when:

1. Container running without errors
2. Health endpoint returns `{"status": "ok"}`
3. Admin panel accessible at `https://indev.eko.in/rm-voice-agent/admin`
4. 367 recordings visible in Recordings page
5. Restarting container doesn't lose data
6. Logs being written to `/app/data/logs/eko.log`
7. AutoGMap integration initializing (check logs)

---

## Next Immediate Actions

1. **[Action] Send this to DevOps:**
   - Ask them to run `PRODUCTION_DEPLOYMENT_SCRIPT.sh` OR
   - Manually create `/data/rm-voice-agent` with chmod 777

2. **[You] When /data/rm-voice-agent ready:**
   - Copy database: `scp ... /data/rm-voice-agent/eko_agent.db`
   - Run eko-deploy with --volumes flags
   - Verify all 4 success criteria above

3. **[You] After deployment:**
   - Check production health endpoint
   - Verify 367 recordings in admin panel
   - Monitor logs for errors

---

## Files You Need

Copy these to reference while deploying:

1. `DEPLOYMENT_INSTRUCTIONS.md` - Detailed step-by-step guide
2. `PRODUCTION_DEPLOYMENT_SCRIPT.sh` - Automated setup script
3. `.env.local` - Production configuration (keep secure!)
4. `data/eko_agent.db` - Database with 367 recordings

---

## Important Reminders

⚠️ **SECURITY:**
- `.env.local` contains production secrets - NEVER commit to git
- Database backup contains real data - keep secure
- `/data/rm-voice-agent` should only be accessible to app

⚠️ **DATA:**
- 367 recordings ONLY exist locally right now
- They MUST be copied to production or they'll be lost
- Verify copy succeeded before deployment

⚠️ **VOLUMES:**
- Without `--volumes` flags in eko-deploy, data will be ephemeral
- Container restart = data loss (if volumes not mounted)
- Always use both volume mount flags:
  - `--volumes /data/rm-voice-agent:/app/data`
  - `--volumes /data/rm-voice-agent:/data`

---

## Questions?

Refer to:
- `DEPLOYMENT_INSTRUCTIONS.md` for step-by-step details
- `comprehensive-diagnosis-nov13.md` (in memory) for technical details
- `PRODUCTION_DEPLOYMENT_SCRIPT.sh` for automated setup

---

**Status Summary:**
- Code: ✅ Ready
- Database: ✅ Backed up (367 recordings)
- Config: ✅ Complete (.env.local)
- Infrastructure: ⏳ Pending (create /data/rm-voice-agent)
- Deployment: ⏳ Pending (run eko-deploy)
- Verification: ⏳ Pending (check success criteria)

**Estimated time to production:** 30 minutes
**Current blocker:** Need `/data/rm-voice-agent` created on production server

