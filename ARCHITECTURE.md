# Sahayak Database & Storage Architecture

## Overview

Sahayak is a voice agent for Eko Relationship Managers (RMs) handling CSP support calls. This document describes:
- Database schema and current data
- Recording storage strategy
- Scalability analysis
- Archive/migration plans

## Current Setup (Pilot Phase)

### Data Inventory
- **CSPs:** 595 real records (from Eko sheets)
- **RMs:** 3 (Amuda, Shiwani, Vandana)
- **Monthly data:** 4,162 rows (targets & achievement per month)
- **Database size:** 1.8 MB (SQLite)

### Storage Layout

**Laptop (Local Development):**
```
data/eko_agent.db (1.8 MB)
├─ CSPs: 595 rows
├─ RMs: 3
├─ Monthly data: 4,162 rows
├─ Calls: 155 test calls logged
├─ Traces: 468 (from test calls)
├─ Recordings: 2 files
└─ Tickets: 145 support tickets
```

**Server (indev.eko.in - Docker):**
```
/data/ (persistent Docker volume)
├─ eko_agent.db (synced from laptop)
├─ recordings/ (RM phone uploads via /api/recordings/upload)
└─ models/ (71 MB - TTS/STT models)
```

## Database Schema (SQLite)

### Core Tables

| Table | Rows | Purpose |
|-------|------|---------|
| `rms` | 3 | Relationship Managers (email, phone, region) |
| `csps` | 595 | Customers (bank details, slab level, rm_id) |
| `csp_monthly` | 4,162 | Monthly targets & achievement |
| `calls` | 155 | Call metadata (status, outcome, intent) |
| `turns` | 1,144 | Conversation turns (STT conf, latency, tokens) |
| `tickets` | 145 | Support tickets (category, priority, SLA) |
| `recordings` | N | Audio file metadata (sha256, file_path, status) |
| `traces` | 468 | LLM decision logs (context tiers, tokens spent) |
| `upload_tokens` | N | RM phone auth for recording upload |
| `users` | 4 | Admin/Ops login accounts |

### Key Relationships
```
rms (1) ──→ (N) csps ──→ (N) calls ──→ (N) turns
                    ↓
                csp_monthly
                    
calls ──→ tickets ──→ ticket_events
       ──→ traces
       ──→ recordings
```

## Recording Storage & Load Analysis

### How Recordings Flow
```
RM Phone (Uploader App)
  ↓ Calls /api/recordings/upload with upload_token
  ↓ Sends audio file + metadata (rm_id, csp_id, duration)
Server /app/recordings.py
  ↓ Receives file, computes SHA256 (dedup)
  ↓ Stores in /data/recordings/{date}/{filename}
  ↓ Sends to Whisper for transcription
Database 'recordings' table
  ↓ Stores metadata + file_path + status
  ↓ status: new → transcribing → done
```

### Storage Load Estimates

#### Pilot (3 RMs, 10 calls/day each)
```
Per call:     5-10 min audio ≈ 7.5 MB average
Per RM/day:   10 calls × 7.5 MB = 75 MB/day
All RMs/day:  3 × 75 MB = 225 MB/day
Monthly:      ~6.75 GB
Server disk:  Typically 50-100 GB

Status: ✅ TOTALLY SAFE for 6+ months
```

#### Medium Scale (10 RMs, 10 calls/day)
```
Daily:    750 MB
Monthly:  22.5 GB
Status:   ⚠️ Manageable, monitor disk
```

#### Full Rollout (50+ RMs)
```
Daily:    3-5 GB
Monthly:  90-150 GB
Status:   ❌ Fills disk in weeks → Need archive strategy
```

## Current Bottlenecks

1. **SQLite:** Fine for 595 CSPs, but slow at 10K+ (no indexes, no connection pooling)
2. **Single Server Volume:** `/data` is not replicated or backed up
3. **No Recording Cleanup:** Audio files keep growing indefinitely
4. **No Automated Backups:** Database and recordings need manual backups
5. **Network Upload:** Each 10 MB upload can strain bandwidth at scale

## Scaling Strategy

### Phase 3.5: Recording Archive (After Phase 4)
```
Goal: Keep server disk free during pilot expansion

Actions:
• Delete local recording files after transcription
• Keep audio metadata in database (sha256, duration, status)
• Compress audio to opus/AAC (10 MB → 1-2 MB)
• Set 30-day retention for active recordings
```

### Phase 5-6: Database Migration (20+ RMs)
```
Goal: Share database across multiple servers

Current:  SQLite (each server has its own copy)
Target:   PostgreSQL (all servers share one database)

Benefits:
• Automatic backups & replication
• Connection pooling (handle 100+ concurrent calls)
• Full-text search on turns/tickets
• Ready for 10K+ CSPs
• Transactions with rollback
• Per-user audit trail

Timeline: Before expanding beyond 20 RMs
```

### Phase 7: Cloud Archive (50+ RMs)
```
Goal: Unlimited recording storage

Actions:
• Upload processed recordings to S3/GCS
• Delete from server /data after 30 days
• Keep metadata in PostgreSQL
• Search/playback via database queries

Timeline: Before full rollout
```

## Storage Breakdown (Current)

```
data/: 109 MB total
├─ Models (TTS/STT):     71 MB  (65%) ← Included in Docker build
├─ Recordings:            31 MB  (28%) ← Grows with calls
├─ Database:              1.8 MB (1.7%) ← Structured data
├─ Backups:               7 MB   (6%) ← Manual backups
└─ KB docs:               1.6 MB (1.5%) ← Imported CSP sheets
```

## Monitoring

### For Pilot (3 RMs)

**Weekly checks:**
```bash
# SSH to server
ssh -p 2222 akanksha@indev.eko.in

# Check disk usage
du -sh /data/

# Database size
ls -lh /data/eko_agent.db

# Recording count
ls -1 /data/recordings/ | wc -l
```

**Alert thresholds:**
- Disk > 50%: Start archiving plan
- DB > 50 MB: Schema optimization needed
- Uploads failing: Check network

### For Scale (10+ RMs)

**Daily monitoring:**
- Disk usage trend (should be linear)
- Upload success rate (target: 99%+)
- Transcription latency (should be <2x audio duration)
- DB query performance (100ms max)

## Emergency Procedures

### Disk Full
```bash
# 1. Stop accepting new recordings
# 2. Archive oldest 7 days to external storage
# 3. Delete from /data/recordings/
# 4. Check cleanup scripts
# 5. Resume uploads
```

### Database Corruption
```bash
# 1. Stop app container
# 2. Restore from backup: cp backup-*.db /data/eko_agent.db
# 3. Restart container
# 4. Verify with: eko-deploy report rm-voice-agent
```

### PostgreSQL Migration
```bash
# Pre-migration:
# 1. Export SQLite schema to PostgreSQL
# 2. Migrate data (can be done live during maintenance window)
# 3. Test all queries on new DB
# 4. Switch app to new connection string
# 5. Keep SQLite as read-only backup for 1 week
```

## Decisions Made

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| SQLite for pilot | Simple, zero ops, fast to test | No scaling beyond 10K CSPs |
| Local recordings until Phase 7 | Faster iteration, lower complexity | Need archive plan |
| Single server /data volume | Fast deployment | Need backup strategy |
| SHA256 for recording dedup | Prevent duplicates from reuploads | Minimal (dedup rarely happens) |
| No cleanup until Phase 3.5 | Focus on agent quality first | Disk growth, monitor closely |

## FAQ

**Q: Will recordings fill the server disk during pilot?**
A: No. 3 RMs generating 225 MB/day fits comfortably in 50-100 GB server disk for 6+ months.

**Q: When do we need PostgreSQL?**
A: At 20+ RMs or 10K+ CSPs. For pilot of 3-5 RMs, SQLite is fine.

**Q: What if we need to migrate mid-pilot?**
A: PostgreSQL export works live. Zero downtime possible with connection pooling.

**Q: Can RMs run their own uploader apps offline?**
A: Yes, uploader works offline, syncs when network returns. Metadata queued locally.

**Q: How often should we backup?**
A: Daily automated backups (planned for Phase 3.5). Current: manual backup after major changes.

## References

- Schema definition: `app/db.py` (SCHEMA variable)
- Recording upload: `app/recordings.py`
- KB import: `app/kb_import.py`
- Uploader app: `uploader/` directory
- Deployment: `eko-deploy deploy rm-voice-agent`
