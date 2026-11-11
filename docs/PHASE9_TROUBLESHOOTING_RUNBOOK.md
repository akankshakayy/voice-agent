# Troubleshooting Runbook

Common issues, root causes, and resolution steps for production support.

## Recording Upload Failures

### Symptom
Users report uploads failing with error messages.

### Diagnosis
```bash
# Check logs for upload errors
tail -f /app/data/logs/eko.log | grep -i "upload\|recording"

# Look for patterns:
# - "File size exceeds 60MB"
# - "Format not supported (not .ogg/.mp4/.wav)"
# - "Failed to connect to AutoGMap"
# - "Queue full, rejecting upload"
```

### Solutions

**Issue: File too large**
- Fix: Ensure Eko SIM call recording < 60MB
- Check device storage: Eko SIM may not have recorded correctly

**Issue: Unsupported format**
- Fix: Verify recording format is OGG, MP4, or WAV
- Check: Device's call recording app settings

**Issue: AutoGMap API timeout**
- Fix: Increase AUTOGMAP_UPLOAD_TIMEOUT_SECONDS
- Check: AutoGMap service status
- Retry: Server auto-retries with backoff

**Issue: Queue full (1000 recordings pending)**
- Fix: May indicate upload bottleneck
- Check: Network bandwidth
- Monitor: Upload rate vs incoming rate

---

## API Timeout Issues

### Symptom
API calls return 504 Gateway Timeout

### Diagnosis
```bash
# Check request logs
grep "504\|timeout" /app/data/logs/eko.log

# Monitor API latency
curl -w "@curl_latency.txt" https://indev.eko.in/rm-voice-agent/health

# Check external API status
# AutoGMap: https://autogmap.eko.co.in/status
# Prachi: https://sbi-relationship-crm.indev.eko.in/health
```

### Solutions

**High latency to AutoGMap:**
- Increase: AUTOGMAP_UPLOAD_TIMEOUT_SECONDS (default 60s → 90s)
- Check: Network connectivity to AutoGMap
- Check: AutoGMap server load

**High latency to Prachi:**
- Increase: PRACHI_WEBHOOK_TIMEOUT_SECONDS (default 30s → 45s)
- Check: Prachi server status
- Verify: X-Recording-Secret header is correct

**Database locks:**
- Symptom: /api calls slow, timeout
- Cause: Too many concurrent uploads
- Fix: Increase DB_POOL_MAX_SIZE or reduce uploads

---

## Database Lock Scenarios

### Symptom
Database locked errors in logs

### Diagnosis
```bash
# Check active connections
sqlite3 /app/data/eko_agent.db "SELECT COUNT(*) FROM pragma_database_list;"

# Check for long-running queries
sqlite3 /app/data/eko_agent.db "PRAGMA query_only=true;"
```

### Solutions

**High concurrent upload load:**
- Increase AUTOGMAP_MAX_CONCURRENT_UPLOADS (default 2)
- Reduce upload queue size to prevent bottleneck
- Monitor: Is rate limiting being triggered?

**Telemetry thread conflict:**
- Already fixed: telemetry thread exits on DB close
- If issue persists: Check telemetry.shutdown() is called

**Backup/export interfering:**
- Don't run backups during peak upload times
- Schedule backups: 2-4 AM (off-peak)

---

## Webhook Retry Failures

### Symptom
Recordings stuck in retry queue, not delivered to Prachi

### Diagnosis
```bash
# Check Prachi submission status
sqlite3 /app/data/eko_agent.db << 'EOF'
SELECT id, dc_id, prachi_api_sent_at, prachi_request_id, error 
FROM recordings 
WHERE mode='dc' AND prachi_api_sent_at IS NOT NULL 
ORDER BY updated_at DESC LIMIT 10;
EOF

# Check for 401 errors
grep "Prachi.*401\|Invalid.*secret" /app/data/logs/eko.log
```

### Solutions

**Authentication failed (401):**
- Verify: PRACHI_RECORDING_SECRET is correct
- Check: Has Prachi configured this secret on their end?
- Resolution: Regenerate secret with Prachi team

**Payload validation failed (400):**
- Check: All required fields present (id, dc_number, other_number, direction, started_at, duration, audio_url)
- Verify: Phone numbers are 10-digit format
- Check: Timestamp is ISO 8601 with timezone

**Prachi server error (5xx):**
- Auto-retry will continue (24h window)
- Monitor: Check Prachi server status
- Escalate: Contact Prachi team if repeated failures

**Timeout (30s):**
- Increase: PRACHI_WEBHOOK_TIMEOUT_SECONDS
- Check: Network connectivity to Prachi
- Verify: Is Prachi server responding?

---

## Sync Failures

### AutoGMap Numbers Sync Failure

**Symptom:** Numbers not updating

```bash
# Check last sync time
curl https://indev.eko.in/rm-voice-agent/api/autogmap/status

# Check logs
grep "AutoGMap.*sync\|applicant.*numbers" /app/data/logs/eko.log
```

**Solutions:**
- Verify: AUTOGMAP_API_KEY is correct
- Check: AUTOGMAP_NUMBERS_URL is accessible
- Increase: AUTOGMAP_SYNC_TIMEOUT_SECONDS if slow network
- Retry: Sync runs every 15 minutes automatically

### Google Sheets Sync Failure

**Symptom:** DC list not updating from Prachi sheet

**Solutions:**
- Verify: PRACHI_SHEET_ID is correct
- Check: Google Sheets API accessible
- Verify: Sheet is public (anyone with link)
- Increase: PRACHI_SYNC_TIMEOUT_SECONDS
- Schedule: Runs daily at 2 AM UTC (PRACHI_SYNC_SCHEDULE_HOUR=2)

---

## Log Parsing Guide

### Find Errors

```bash
# All errors
grep "ERROR\|CRITICAL" /app/data/logs/eko.log

# Recording errors
grep "recording.*error\|upload.*failed" /app/data/logs/eko.log

# API errors
grep "401\|403\|500\|502\|503\|504" /app/data/logs/eko.log

# Database errors
grep "database\|sql\|lock" /app/data/logs/eko.log

# Prachi errors
grep "prachi\|webhook" /app/data/logs/eko.log

# AutoGMap errors
grep "autogmap\|applicant" /app/data/logs/eko.log
```

### Log Format

```
2026-11-11 10:30:00 | INFO  | eko.recordings    | Recording 365 uploaded successfully
2026-11-11 10:30:05 | ERROR | eko.prachi        | Prachi API rejected: 401 Invalid secret
2026-11-11 10:30:10 | WARN  | eko.autogmap      | Sync timeout after 30s, will retry
```

### Common Log Patterns

| Pattern | Meaning | Action |
|---------|---------|--------|
| `201 Created` | Upload success | Good! |
| `422 Unprocessable` | Invalid data | Check payload |
| `401 Unauthorized` | Auth failed | Check API key/secret |
| `500 Internal Error` | Server error | Wait, auto-retry |
| `timeout` | Slow response | Increase timeout |
| `queue full` | Too many uploads | Reduce concurrent |
| `database locked` | Concurrency conflict | Reduce load |

---

## Performance Tuning

### High Upload Latency

```bash
# Baseline check
time curl -X POST https://indev.eko.in/rm-voice-agent/api/uploader/recordings \
  -F "audio=@10MB_test.ogg"

# Should be: 2-5 seconds

# If slow:
# 1. Check network: ping -c 5 indev.eko.in
# 2. Check disk: iostat -x 1
# 3. Increase timeout: AUTOGMAP_UPLOAD_TIMEOUT_SECONDS=90
# 4. Reduce concurrency: AUTOGMAP_MAX_CONCURRENT_UPLOADS=1
```

### High Memory Usage

```bash
# Monitor memory
docker stats rm-voice-agent-container

# If high:
# 1. Reduce queue size: AUTOGMAP_UPLOAD_QUEUE_SIZE=500
# 2. Reduce trace queue: TRACE_QUEUE_SIZE=2000
# 3. Restart app: eko-deploy restart rm-voice-agent
```

### Database Size

```bash
# Check database file size
ls -lh /app/data/eko_agent.db

# If > 500MB:
# 1. Archive old traces: TRACE_KEEP_DAYS=30
# 2. Run VACUUM: sqlite3 /app/data/eko_agent.db VACUUM
# 3. Export/purge old data
```

---

## Escalation Path

**Tier 1 (Self-service):**
- Check logs
- Restart service
- Increase timeouts
- Check external service status

**Tier 2 (Team):**
- Email: dev-team@eko.co.in
- Include: Error message, logs (last 100 lines), steps taken

**Tier 3 (External):**
- AutoGMap issues → api-support@eko.co.in
- Prachi issues → prachi@eko.co.in
- Google Sheets → tech-support@google.com
