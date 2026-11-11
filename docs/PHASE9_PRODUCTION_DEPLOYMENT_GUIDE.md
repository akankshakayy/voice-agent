# Production Deployment Guide

Step-by-step guide for deploying Eko Sahayak to production via eko-deploy.

## Prerequisites

- [ ] Docker installed on deployment machine
- [ ] eko-deploy CLI installed
- [ ] Access to indev.eko.in environment
- [ ] All Phase 1-8 completed and tested locally
- [ ] `.env.local` with all production secrets prepared (NOT in git)

## Deployment Steps

### 1. Prepare Secrets (.env.local)

```bash
# Create .env.local with ALL required secrets
cat > .env.local << 'EOF'
ENVIRONMENT=production
APP_BASE_URL=https://indev.eko.in/rm-voice-agent
AUTOGMAP_API_KEY=xxx
PRACHI_RECORDING_SECRET=xxx
ANTHROPIC_API_KEY=xxx
GOOGLE_CLIENT_SECRET=xxx
SMTP_PASSWORD=xxx
ADMIN_EMAILS=admin@eko.co.in
ALLOWED_EMAIL_DOMAINS=eko.co.in,ekosupport.in
TRUST_PROXY=1
COOKIE_SECURE=1
EOF

# Verify secrets file (DO NOT commit)
cat .env.local
```

### 2. Build Docker Image

```bash
# Build production image
docker build -t eko-sahayak:latest .

# Tag for registry (if using private registry)
docker tag eko-sahayak:latest registry.eko.co.in/eko-sahayak:latest
```

### 3. Deploy via eko-deploy

```bash
# Deploy to indev.eko.in
eko-deploy deploy \
  --app rm-voice-agent \
  --image eko-sahayak:latest \
  --env-file .env.local \
  --volumes /data:/app/data \
  --port 8000

# Check deployment status
eko-deploy status rm-voice-agent
```

### 4. Verify Deployment

```bash
# Health check
curl https://indev.eko.in/rm-voice-agent/health

# Expected response:
# {
#   "status": "ok",
#   "version": "1.0.0",
#   "database": "connected"
# }
```

### 5. Verify Database Migration

```bash
# Connect to running container
docker exec -it rm-voice-agent-container bash

# Run migrations
python -m app.db_migrate

# Verify schema
sqlite3 /app/data/eko_agent.db ".tables"
```

### 6. Test Critical Paths

**Test 1: Admin Login**
```bash
# Visit https://indev.eko.in/rm-voice-agent/admin
# Sign in with Google (must be admin email from ADMIN_EMAILS)
# Verify you can access admin panel
```

**Test 2: Recording Upload**
```bash
# POST to /api/uploader/recordings with test file
curl -X POST https://indev.eko.in/rm-voice-agent/api/uploader/recordings \
  -F "audio=@test.ogg" \
  -F "phone=9876543210" \
  -F "mode=dc"
```

**Test 3: AutoGMap Numbers Sync**
```bash
# Verify sync completed
curl https://indev.eko.in/rm-voice-agent/api/autogmap/status

# Expected: {"synced_at": "2026-11-11T...", "numbers_count": 245}
```

**Test 4: Prachi Webhook (if auth resolved)**
```bash
# Send test recording
curl -X POST https://indev.eko.in/sbi-relationship-crm/api/v1/webhooks/recordings \
  -H "X-Recording-Secret: $PRACHI_RECORDING_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"id":"test_001",...}'
```

### 7. Monitor Logs

```bash
# Stream logs
eko-deploy logs rm-voice-agent --follow

# Look for errors
eko-deploy logs rm-voice-agent | grep ERROR

# Check application startup
eko-deploy logs rm-voice-agent | head -50
```

### 8. Setup Monitoring

```bash
# Configure metrics collection
eko-deploy metrics rm-voice-agent enable

# Point Prometheus to: https://indev.eko.in/rm-voice-agent/metrics
# Setup alerts for: error rate, upload failures, API latency
```

## Rollback Procedure

If issues detected:

```bash
# Rollback to previous version
eko-deploy rollback rm-voice-agent --to previous

# Or redeploy with working commit
git checkout <known-good-commit>
docker build -t eko-sahayak:rollback .
eko-deploy deploy --image eko-sahayak:rollback
```

## Volume Setup

Required volumes for persistence:

```
/app/data/              → Production database & recordings
/app/data/logs/         → Application logs (auto-rotated)
/app/data/backups/      → Database backups
```

## Health Checks

Configured in eko-deploy.toml:

```toml
[health_check]
enabled = true
path = "/health"
interval_seconds = 30
timeout_seconds = 5
initial_delay_seconds = 10
```

## Performance Baseline

Expected on indev:
- App startup: < 5 seconds
- /health response: < 100ms
- Recording upload: 2-5 seconds (depends on size)
- AutoGMap sync: 10-30 seconds

## Post-Deployment Tasks

- [ ] Verify health endpoint
- [ ] Test admin panel login
- [ ] Test recording upload
- [ ] Check logs for errors
- [ ] Verify metrics collection
- [ ] Request Mansi to test number sync
- [ ] Request Prachi to verify webhooks
- [ ] Setup monitoring alerts
- [ ] Enable automated backups

## Troubleshooting

**502 Bad Gateway:** App crashed, check logs  
**503 Service Unavailable:** Database not ready, wait 30s  
**Auth failures:** Check GOOGLE_CLIENT_SECRET  
**Upload failures:** Check /app/data volume writable  
**API timeouts:** Check AUTOGMAP_UPLOAD_TIMEOUT_SECONDS
