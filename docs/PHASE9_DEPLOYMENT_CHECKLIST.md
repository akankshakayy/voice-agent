# Pre-Deployment & Production Rollout Checklist

Complete checklist for shipping Eko Sahayak to production.

---

## Phase 1: Pre-Deployment Validation (48 hours before)

### Code Quality
- [ ] All tests passing (pytest tests/ -v)
- [ ] Code review completed
- [ ] No uncommitted changes (git status clean)
- [ ] No secrets in git (grep API_KEY, SECRET)
- [ ] Linting passed (if configured)
- [ ] Type checking passed (mypy)

### Documentation
- [ ] PHASE9_UNIFIED_API_REFERENCE.md complete
- [ ] PHASE9_CONFIGURATION_REFERENCE.md complete
- [ ] PHASE9_PRODUCTION_DEPLOYMENT_GUIDE.md complete
- [ ] PHASE9_TROUBLESHOOTING_RUNBOOK.md complete
- [ ] PHASE9_TEAM_ONBOARDING.md complete
- [ ] API examples tested manually
- [ ] All edge cases documented

### Dependencies
- [ ] requirements.txt up to date
- [ ] No security vulnerabilities (pip audit)
- [ ] All external services reachable
- [ ] API keys provisioned and tested

### Configuration
- [ ] .env.example complete and documented
- [ ] .env.local prepared (NOT in git)
- [ ] All required secrets present
- [ ] Database path writable (/app/data)
- [ ] Logs directory writable (/app/data/logs)
- [ ] Recording storage writable (/app/data/recordings)

### Credentials & Secrets
- [ ] Google OAuth credentials configured
- [ ] AUTOGMAP_API_KEY verified working
- [ ] PRACHI_RECORDING_SECRET verified working
- [ ] ANTHROPIC_API_KEY set and valid
- [ ] SMTP credentials for email working
- [ ] All secrets in .env.local (not in code)

---

## Phase 2: Staging Deployment (24 hours before)

### Staging Environment
- [ ] Docker image builds successfully
- [ ] Staging deployment succeeds
- [ ] Health check endpoint responding (202 OK)
- [ ] Database migrations run automatically
- [ ] Logs flowing to /app/data/logs

### Staging Validation
- [ ] Admin login works (Google + email)
- [ ] Recording upload endpoint responds
- [ ] AutoGMap numbers sync runs
- [ ] Prachi webhook reachable (if auth ready)
- [ ] All API endpoints accessible
- [ ] Database queries fast (< 100ms)
- [ ] No errors in logs
- [ ] Memory usage reasonable (< 500MB)

### Staging Testing
- [ ] Manual upload test (recording appears in DB)
- [ ] Admin panel CRUD operations work
- [ ] Number sync completes successfully
- [ ] Rate limiting enforces 2 req/sec
- [ ] Backup/restore functionality works
- [ ] Error handling graceful (no 500s)

### Staging Performance
- [ ] App startup: < 5 seconds
- [ ] Health check: < 100ms
- [ ] Recording upload: 2-5 seconds
- [ ] API latency: < 1 second
- [ ] Database latency: < 100ms

### Staging Sign-Off
- [ ] Dev team sign-off: ✅
- [ ] Product team sign-off: ✅
- [ ] Security review: ✅
- [ ] Operations team review: ✅

---

## Phase 3: Production Deployment (< 6 hours)

### Pre-Production Setup
- [ ] Production secrets prepared (.env.local)
- [ ] Deployment window scheduled
- [ ] Rollback plan reviewed
- [ ] Team notified of deployment window
- [ ] On-call team standing by

### Deployment Execution
- [ ] Docker image tagged with version
- [ ] eko-deploy deployment command prepared
- [ ] Backup of current database taken
- [ ] Deployment started
- [ ] Deployment completion confirmed (status: running)
- [ ] No deploy errors in logs

### Post-Deployment Verification
- [ ] Health check passing
- [ ] Admin login working
- [ ] Recording upload endpoint responding
- [ ] Database connectivity verified
- [ ] Logs being written to /app/data/logs
- [ ] Metrics being collected
- [ ] No error spikes in logs

### Post-Deployment Testing
- [ ] Manual upload test (small recording)
- [ ] Manual upload test (large recording)
- [ ] Admin panel accessible
- [ ] Number sync completed
- [ ] API latency acceptable
- [ ] Database performance acceptable
- [ ] Error rate normal

### Post-Deployment Notifications
- [ ] Notify dev team: deployment complete
- [ ] Notify product team: features available
- [ ] Notify Mansi: ready for testing
- [ ] Notify Prachi: ready for webhook testing (if auth resolved)

---

## Phase 4: Production Stabilization (24 hours after)

### Monitoring
- [ ] Error rate stable (< 0.1%)
- [ ] API latency stable (< 1s avg)
- [ ] Upload success rate > 99%
- [ ] Database queries fast
- [ ] Memory usage stable
- [ ] Disk usage growth rate normal

### Issue Response
- [ ] Any issues escalated immediately
- [ ] Root cause analysis for each incident
- [ ] Fix deployed if needed
- [ ] Post-mortem scheduled if critical issue

### User Testing
- [ ] Mansi team testing AutoGMap integration
- [ ] Prachi team testing webhook delivery (if auth ready)
- [ ] Admin panel tested by admins
- [ ] Recording uploads tested by sample users

### Data Validation
- [ ] Recordings being uploaded successfully
- [ ] Recording counts match expectations
- [ ] AutoGMap numbers syncing correctly
- [ ] No data corruption observed
- [ ] Backup/restore tested

---

## Phase 5: Production Stabilization (72 hours after)

### Long-Term Monitoring
- [ ] Error rate remains stable
- [ ] Upload queue staying empty (not backed up)
- [ ] Database size within expectations
- [ ] Backup retention working
- [ ] Logs rotating correctly

### Team Readiness
- [ ] Support team trained
- [ ] Troubleshooting runbook reviewed
- [ ] Escalation path clear
- [ ] On-call setup working

### Feature Validation
- [ ] All 3 upload modes working
- [ ] All API integrations functional
- [ ] Admin panel fully operational
- [ ] Real-world usage data flowing in

---

## Rollback Criteria

Deploy will be **rolled back immediately** if:

- [ ] Health check failing for > 5 minutes
- [ ] Upload success rate drops below 95%
- [ ] Error rate exceeds 5%
- [ ] Database becomes inaccessible
- [ ] Memory usage exceeds 1GB
- [ ] Critical security issue discovered

### Rollback Steps

```bash
# If critical issue detected:
1. Notify team immediately
2. Execute rollback command:
   eko-deploy rollback rm-voice-agent --to previous
3. Verify previous version is running
4. Document incident for post-mortem
5. Schedule emergency meeting with team
```

---

## Sign-Off Template

After production deployment completes and stabilizes:

```
DEPLOYMENT COMPLETE ✅
Date: 2026-11-XX
Version: X.X.X
Deployed by: [Name]

Staging testing: PASSED
Production deployment: PASSED
Post-deployment monitoring: PASSED

Issues encountered: [None / List any]
Rollback needed: [No / Yes - if yes, describe]

Approvals:
- Dev Team: ___________
- Ops Team: ___________
- Product: ___________

Next steps: [Continue monitoring / Schedule retrospective]
```

---

## Post-Deployment Handbook

### For On-Call

**Issue: Upload failing**
1. Check logs: `grep ERROR /app/data/logs/eko.log`
2. If AutoGMap timeout: Increase AUTOGMAP_UPLOAD_TIMEOUT_SECONDS
3. If queue full: Check if rate limiting is causing bottleneck
4. Escalate if not resolved in 15 minutes

**Issue: API returning 502**
1. Check app status: `eko-deploy status rm-voice-agent`
2. Check health: `curl https://indev.eko.in/rm-voice-agent/health`
3. Restart if unhealthy: `eko-deploy restart rm-voice-agent`
4. If persistent, rollback

**Issue: Database locked**
1. Check active connections: `sqlite3 /app/data/eko_agent.db ".connections"`
2. Wait 30 seconds (auto-recovery)
3. If persists, restart app
4. If still locked, escalate to DBAs

### For Product

**Feature not working**
1. Check error logs
2. Verify configuration is correct
3. File bug report with: error message, logs, steps to reproduce

**Need new feature**
1. Create feature branch
2. Code review required
3. Staging test required
4. Include in next deployment window

---

## Success Criteria

Deployment is **successful** when:

✅ All automated tests passing  
✅ All manual tests passing  
✅ No critical errors in logs  
✅ Performance within baseline  
✅ All team sign-offs complete  
✅ Monitoring stable for 24 hours  
✅ Users can upload recordings successfully  
✅ AutoGMap integration working  
✅ Admin panel fully functional  

**Go/No-Go Decision:** All criteria must be met before full rollout.

---

## Questions?

- Deployment guide: See PHASE9_PRODUCTION_DEPLOYMENT_GUIDE.md
- Troubleshooting: See PHASE9_TROUBLESHOOTING_RUNBOOK.md
- Config help: See PHASE9_CONFIGURATION_REFERENCE.md
- API questions: See PHASE9_UNIFIED_API_REFERENCE.md
