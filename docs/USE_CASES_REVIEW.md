# Viewing & Reviewing Use Cases & Subcases

## Database Storage

### Table: `recordings` (one row per uploaded call recording)
**Where use cases are extracted from transcribed calls:**

```sql
SELECT 
  id, 
  rm_id,
  csp_id,
  status,                    -- new | done | failed
  processed_at,
  intent,                    -- ✓ USE CASE (e.g., "dmt_failed", "aeps_issue")
  intent_confidence,         -- ✓ Confidence 0-1
  slots_json,                -- ✓ SUBCASES (details as JSON)
  sentiment,                 -- positive | neutral | frustrated | angry
  resolution,                -- resolved_on_call | follow_up_promised | escalated | no_issue | unclear
  summary,                   -- Text summary
  transcript_json,           -- Full transcription with timings
  issue_segment,             -- Which part of recording has the issue
  language,                  -- Language of call
FROM recordings;
```

### Table: `tickets` (one row per ticket created)
**Ground truth: what the RM confirmed:**

```sql
SELECT
  id,
  ticket_no,
  call_id,
  csp_id,
  category,                  -- ✓ USE CASE (what agent predicted)
  rm_category,               -- ✓ USE CASE (what RM confirmed - GROUND TRUTH)
  details_json,              -- ✓ SUBCASES (JSON of confirmed details)
  slot_completeness,         -- 0-1: how complete was extraction
  priority,
  status,
  created_at
FROM tickets;
```

---

## 4 Ways to View & Review

### **1. 🖥️ Web Dashboard (Easiest)**

**URL:** `http://localhost:8000/recordings` (or `https://indev.eko.in/rm-voice-agent/recordings`)

**Access:** Login as admin/ops/rm

**Shows:**
- ✅ List of all processed recordings
- ✅ Filters by status (new, done, failed), RM, date range
- ✅ Click on any recording to see:
  - Audio file (play it)
  - Full transcription with speaker identification
  - Extracted use case + confidence score
  - Extracted subcases (slots/details)
  - CSP sentiment & mood
  - How it ended (resolution)
  - Summary

**Features:**
- Edit extracted use case and subcases if wrong
- Listen to audio and mark sections
- Export recordings as CSV
- See learning metrics (STT accuracy, intent accuracy over time)

---

### **2. 🔌 API Endpoints** (for programmatic access)

**List all recordings with use cases:**
```bash
GET /api/recordings?status=done&limit=100&rm_id=2

Response:
{
  "counts": {
    "new": 5,
    "done": 42,
    "failed": 3
  },
  "recordings": [
    {
      "id": 123,
      "rm_id": 2,
      "csp_id": 567,
      "intent": "dmt_failed",
      "intent_confidence": 0.87,
      "slots_json": "{\"txn_id\": \"412398765432\", \"amount\": \"10000\", \"txn_date\": \"2026-10-28\"}",
      "sentiment": "frustrated",
      "resolution": "escalated",
      "summary": "Money transfer failed, escalated to RM team",
      "transcript_json": "[{\"start\": 0.5, \"end\": 3.2, \"text\": \"...\", \"speaker\": \"csp\"}...]",
      "processed_at": 1698652345.123
    },
    ...
  ]
}
```

**Get one recording with all details:**
```bash
GET /api/recordings/123
```

**Get learning stats (how often AI was right):**
```bash
GET /api/recordings/learning?rm_id=2

Response:
{
  "intent_accuracy": 0.89,        # % of predictions matching RM corrections
  "stt_accuracy": 0.92,           # % of transcript words correct
  "mishearing_rate": 0.08,        # Common misheard words
  "completion_rate": 0.85         # % of details successfully extracted
}
```

---

### **3. 📊 Direct Database Query** (for analysis)

**Query all use cases:**
```sql
SELECT 
  id, 
  intent, 
  intent_confidence,
  slots_json,
  sentiment,
  resolution,
  summary
FROM recordings 
WHERE processed_at IS NOT NULL
ORDER BY processed_at DESC
LIMIT 100;
```

**Group by use case:**
```sql
SELECT 
  intent,
  COUNT(*) as count,
  ROUND(AVG(intent_confidence), 2) as avg_confidence,
  COUNT(CASE WHEN resolution='escalated' THEN 1 END) as escalated_count
FROM recordings
WHERE processed_at IS NOT NULL
GROUP BY intent
ORDER BY count DESC;
```

**Find recordings with low confidence:**
```sql
SELECT id, intent, intent_confidence, summary
FROM recordings
WHERE intent_confidence < 0.6 AND processed_at IS NOT NULL
ORDER BY intent_confidence;
```

**Compare AI vs RM (accuracy):**
```sql
SELECT 
  r.intent as ai_intent,
  t.rm_category as rm_intent,
  COUNT(*) as count
FROM recordings r
LEFT JOIN tickets t ON r.id = t.call_id
WHERE r.processed_at IS NOT NULL
GROUP BY r.intent, t.rm_category;
```

---

### **4. 📁 CSV Export** (for analysis in Excel/Sheets)

**From the web UI:**
1. Go to `/recordings`
2. Click **"Export as CSV"** button
3. Downloads all recordings with:
   - Recording ID, RM name, CSP code
   - Use case (intent)
   - Subcases (slots as JSON)
   - Confidence scores
   - Sentiment, resolution, summary

**Via CLI command:**
```bash
cd /home/cat/eko-rm-voice-agent
python -m app.recordings list

# Output:
#  ID   When      RM Name        Status   Intent            Summary
#   42  30 Oct  Shiwani         done    dmt_failed        Money transfer failed, ₹10000, UTR 412398765432
#   41  30 Oct  Priya           done    aeps_issue        Fingerprint not working, biometric failure
#  ...
```

---

## 11 Use Cases (Categories)

| Use Case | ID | Required Subcases |
|----------|----|----|
| 💰 Money Transfer Failed | `dmt_failed` | txn_id, amount, txn_date |
| 💳 AePS Withdrawal | `aeps_issue` | txn_id, amount, txn_date, bank_name |
| 📱 Wallet Load | `wallet_topup` | amount, utr_or_ref, txn_date, payment_mode |
| 💼 Commission Issue | `commission` | month, product |
| 📋 KYC/Onboarding | `kyc_onboarding` | issue_detail |
| 📲 App/Device/Login | `app_device` | device_or_screen, error_message |
| 🧾 Bill Payment | `bbps_recharge` | txn_id, amount, biller |
| 🔄 Refund Status | `refund_status` | txn_id |
| ⚠️ Fraud Report | `fraud_report` | issue_detail (ALWAYS escalate) |
| 🎫 Complaint Status | `ticket_status` | (answer from existing tickets) |
| ❓ General Query | `general_query` | issue_detail |

---

## Quality Metrics to Track

**In the learning stats (GET `/api/recordings/learning`):**

1. **Intent Accuracy** (0-1) — % of times the AI's use case matched what the RM confirmed
   - Target: > 0.85

2. **Slot Completeness** (0-1) — % of required details extracted
   - Target: > 0.80 for high-priority issues

3. **STT Confidence** (0-1) — % of words transcribed correctly
   - Target: > 0.90

4. **Escalation Rate** — % of calls escalated to humans
   - Target: < 0.15 (only for real issues)

5. **Average Confidence** — Model's self-reported certainty (0-1)
   - Target: > 0.75

---

## Common Issues & Fixes

### "Use case shows 'unknown'"
- Intent confidence too low (< 0.55)
- Issue doesn't match any category
- **Fix:** Manually edit in UI, or add new category if pattern repeats

### "Some subcases missing"
- CSP didn't mention them
- AI forgot to ask
- **Fix:** Review and manually add missing details in the tickets page

### "AI keeps getting intent wrong"
- Check the mishearing stats (`/api/recordings/learning`)
- Block common misheard words
- Improve the prompt in `llm_engine.py`

### "Want to improve AI accuracy"
- Review low-confidence predictions
- Compare AI vs RM corrections
- Share pattern with team to improve system prompts

---

## Next Steps

1. **Review Dashboard** — Check `/recordings` for processed calls
2. **Check Accuracy** — Compare AI intents vs RM confirmations
3. **Find Patterns** — Use SQL to see which use cases are struggling
4. **Improve Model** — Share feedback loop: corrections help next call
