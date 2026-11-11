# Configuration Reference - All 50+ Environment Variables

Complete guide to all environment variables needed for production deployment.

---

## Database Configuration

```bash
# SQLite database path (local development)
DB_PATH=/app/data/eko_agent.db

# Or for Postgres (future migration)
DATABASE_URL=postgresql://user:pass@localhost:5432/eko_sahayak
```

## Logging

```bash
# Log level: DEBUG, INFO, WARNING, ERROR
LOG_LEVEL=INFO

# Log directory (auto-rotated, 10MB per file, 5 backups)
LOG_DIR=/app/data/logs

# Trace retention (days) - keep telemetry traces this long
TRACE_KEEP_DAYS=180
```

## Authentication & Security

```bash
# Google OAuth
GOOGLE_CLIENT_ID=xxx
GOOGLE_CLIENT_SECRET=xxx

# Email domains allowed to sign up
ALLOWED_EMAIL_DOMAINS=eko.co.in,ekosupport.in

# Admin email addresses (no approval needed, auto-admin on first login)
ADMIN_EMAILS=admin1@eko.co.in,admin2@eko.co.in

# Session configuration
SESSION_IDLE_HOURS=12
SESSION_EXPIRE_DAYS=7

# Password hashing (scrypt)
SCRYPT_N=16384
SCRYPT_R=8
SCRYPT_P=1
```

## Email (SMTP)

```bash
# SMTP server for password resets and confirmations
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=noreply@eko.co.in
SMTP_PASSWORD=xxx

# From address in emails
SMTP_FROM=noreply@eko.co.in

# Required for email links (used in password reset, confirmation)
APP_BASE_URL=https://indev.eko.in/rm-voice-agent

# Trust proxy (set to 1 if behind nginx/load balancer)
TRUST_PROXY=1

# Cookie security (set to 1 for HTTPS only)
COOKIE_SECURE=1
```

## LLM Configuration

```bash
# LLM Provider: auto, claude, groq, gemini, openai
LLM_PROVIDER=auto

# Claude (Anthropic)
ANTHROPIC_API_KEY=xxx

# Groq (free tier)
GROQ_API_KEY=xxx

# Gemini (Google)
GEMINI_API_KEY=xxx

# OpenAI (fallback)
OPENAI_API_KEY=xxx

# Prompt version fingerprint (for metric tracking)
PROMPT_VERSION=p-abc123def456
```

## Speech & Audio

```bash
# Speech-to-Text (Whisper via Groq)
WHISPER_TIMEOUT_SECONDS=30

# Text-to-Speech (Microsoft Edge TTS)
TTS_VOICE_HI=hi-IN-SwaraNeural
TTS_VOICE_EN=en-US-AriaNeural

# Demo mode (use synthetic CSPs)
DEMO_DATA=0
```

## AutoGMap Integration (Phase 7a)

```bash
# AutoGMap API configuration
AUTOGMAP_ENABLED=true
AUTOGMAP_API_KEY=xxx

# Endpoints
AUTOGMAP_NUMBERS_URL=https://indev.eko.in/autogmap/api/v1/call-recorder/numbers
AUTOGMAP_RECORDINGS_URL=https://indev.eko.in/autogmap/api/v1/call-recorder/recordings

# Sync interval (minutes) - fetch applicant numbers every 15 min
AUTOGMAP_SYNC_INTERVAL_MINUTES=15

# Timeouts
AUTOGMAP_SYNC_TIMEOUT_SECONDS=30
AUTOGMAP_UPLOAD_TIMEOUT_SECONDS=60

# Retry configuration
AUTOGMAP_UPLOAD_RETRY_MAX=3
AUTOGMAP_UPLOAD_RETRY_BACKOFF=60,300,900

# Rate limiting for uploads
AUTOGMAP_MAX_CONCURRENT_UPLOADS=2
AUTOGMAP_UPLOAD_QUEUE_SIZE=1000
```

## Prachi Integration (Phase 7b)

```bash
# Prachi webhook configuration
PRACHI_WEBHOOK_ENABLED=true
PRACHI_WEBHOOK_URL=https://indev.eko.in/sbi-relationship-crm/api/v1/webhooks/recordings

# Authentication
PRACHI_RECORDING_SECRET=xxx

# Webhook timeouts and retries
PRACHI_WEBHOOK_TIMEOUT_SECONDS=30
PRACHI_WEBHOOK_RETRY_MAX=3
PRACHI_WEBHOOK_RETRY_BACKOFF=300,3600,86400

# Batch configuration
PRACHI_MAX_BATCH_SIZE=50
```

## Google Sheets Sync (Phase 7d)

```bash
# Prachi DC list from Google Sheets
PRACHI_SHEET_ID=1lz7RihRysA10akqcwrxrRUq2fVYw4Mr-w7DclVRApLw
PRACHI_SYNC_ENABLED=true

# Schedule: hour of day (0-23, UTC)
PRACHI_SYNC_SCHEDULE_HOUR=2

# Timeouts and retries
PRACHI_SYNC_TIMEOUT_SECONDS=60
PRACHI_SYNC_RETRY_MAX=3

# Google Sheets API (if using auth instead of public access)
GOOGLE_SHEETS_API_KEY=xxx
```

## Recording Storage

```bash
# Recording files directory
RECORDINGS_DIR=/app/data/recordings

# Max file size for uploads (bytes, default 60MB)
MAX_RECORDING_SIZE=62914560

# Supported formats
ALLOWED_AUDIO_FORMATS=ogg,mp4,wav,m4a

# Daily processing schedule (instead of real-time)
RECORDINGS_DAILY_AT=21:00
```

## Admin Panel Configuration

```bash
# Admin UI endpoints
ADMIN_PANEL_ENABLED=true
ADMIN_API_PREFIX=/api/admin

# Pagination defaults
ADMIN_PAGE_SIZE=50
ADMIN_MAX_PAGE_SIZE=200
```

## Development Mode

```bash
# Development mode (no real CSP calls)
DEV_MODE=0

# Demo data (use synthetic CSPs)
DEMO_DATA=0

# Database path override for testing
EKO_DB_PATH=data/eko_agent.db
```

## Performance Tuning

```bash
# Request timeouts
DEFAULT_REQUEST_TIMEOUT=30

# Connection pool size (if using Postgres)
DB_POOL_MIN_SIZE=5
DB_POOL_MAX_SIZE=20

# Trace queue size
TRACE_QUEUE_SIZE=5000

# Cache settings
CACHE_ENABLED=true
CACHE_TTL_SECONDS=300
```

## Feature Flags

```bash
# Enable/disable major features
FEATURE_AUTOGMAP_ENABLED=true
FEATURE_PRACHI_ENABLED=true
FEATURE_BACKUP_RESTORE=true

# Real CSP calls (NEVER true in production until ready)
REAL_CSP_CALLS=0
```

## Monitoring & Observability

```bash
# Health check endpoints
HEALTH_CHECK_PORT=8000
HEALTH_CHECK_PATH=/health

# Metrics collection
METRICS_ENABLED=true
METRICS_PORT=9090

# Error tracking (Sentry)
SENTRY_DSN=https://YOUR_SENTRY_KEY@sentry.io/123456
SENTRY_ENVIRONMENT=production
```

## Deployment Environment

```bash
# Environment name
ENVIRONMENT=production

# App version
APP_VERSION=1.0.0

# Platform
PLATFORM=eko-deploy
```

---

## .env.local Template

```bash
# === CRITICAL SECRETS (NOT IN GIT) ===
AUTOGMAP_API_KEY=xxx
PRACHI_RECORDING_SECRET=xxx
GOOGLE_CLIENT_SECRET=xxx
ANTHROPIC_API_KEY=xxx
GROQ_API_KEY=xxx
SMTP_PASSWORD=xxx

# === REQUIRED FOR PRODUCTION ===
ENVIRONMENT=production
APP_BASE_URL=https://indev.eko.in/rm-voice-agent
ALLOWED_EMAIL_DOMAINS=eko.co.in,ekosupport.in
ADMIN_EMAILS=admin@eko.co.in
SMTP_HOST=smtp.gmail.com
SMTP_FROM=noreply@eko.co.in
TRUST_PROXY=1
COOKIE_SECURE=1

# === OPTIONAL (DEFAULTS OK) ===
LOG_LEVEL=INFO
TRACE_KEEP_DAYS=180
AUTOGMAP_SYNC_INTERVAL_MINUTES=15
PRACHI_SYNC_SCHEDULE_HOUR=2
```

---

## Validation Checklist

- [ ] All API keys set in `.env.local`
- [ ] `ENVIRONMENT=production` (NOT development)
- [ ] `REAL_CSP_CALLS=0` (NEVER 1 in production)
- [ ] `TRUST_PROXY=1` (if behind nginx)
- [ ] `COOKIE_SECURE=1` (HTTPS only)
- [ ] Email configured (SMTP or disabled)
- [ ] Database path writable
- [ ] Logs directory writable
- [ ] Recording storage directory writable
- [ ] All secrets in `.env.local` (NOT in git)

---

## Troubleshooting

**Connection refused:** Check API keys and URLs  
**Rate limited:** Adjust retry backoff values  
**Memory issues:** Reduce `TRACE_QUEUE_SIZE` or `DB_POOL_MAX_SIZE`  
**Slow uploads:** Check `AUTOGMAP_UPLOAD_TIMEOUT_SECONDS`
