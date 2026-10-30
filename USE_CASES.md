# Use Cases Tracker

**Last updated:** 2026-10-30  
**Status:** 11 active use cases, integrated with recordings pipeline  
**Tracking:** AI extraction accuracy, RM confirmations, slot completeness

---

## Quick Stats

| Metric | Value | Target |
|--------|-------|--------|
| **Total Use Cases** | 11 | - |
| **High Priority** | 3 | - |
| **Medium Priority** | 6 | - |
| **Low Priority** | 2 | - |
| **Always Escalate** | 1 (fraud_report) | - |
| **Self-Serve** | 1 (ticket_status) | - |

---

## 1. 💰 Money Transfer (DMT) Failed

**ID:** `dmt_failed`  
**Priority:** 🔴 HIGH  
**SLA:** 24 hours  
**Always Escalate?** No  
**Self-Serve?** No  

### Required Details (Slots)
- `txn_id` — Transaction ID
- `amount` — Amount in ₹
- `txn_date` — Date of transaction

### Keywords
dmt, money transfer, transfer, paisa nahi pahuncha, paise nahi pahunche, beneficiary, imps, neft, pending, fail, failed, atak, atka, ट्रांसफर, पैसा नहीं पहुंचा, पैसे नहीं पहुंचे, पेंडिंग, फेल

### Tracking

| Attribute | Value | Notes |
|-----------|-------|-------|
| **Status** | ✅ Active | - |
| **Extraction Rate** | - | To be tracked |
| **Accuracy** | - | Compared with RM confirmations |
| **Common Issues** | - | Add as you discover |
| **Last Review** | - | - |

### Notes
- Most common issue type in pilot phase
- CSPs often provide partial details (amount but no date)
- Need to improve follow-up questions for missing txn_id

---

## 2. 💳 AePS Withdrawal / Biometric Issue

**ID:** `aeps_issue`  
**Priority:** 🔴 HIGH  
**SLA:** 24 hours  
**Always Escalate?** No  
**Self-Serve?** No  

### Required Details (Slots)
- `txn_id` — Transaction ID
- `amount` — Amount in ₹
- `txn_date` — Date of withdrawal
- `bank_name` — Bank name

### Keywords
aeps, aadhaar, aadhar, fingerprint, finger, thumb, anguutha, angootha, withdrawal, nikasi, cash nikala, आधार, अंगूठा, फिंगरप्रिंट, निकासी

### Tracking

| Attribute | Value | Notes |
|-----------|-------|-------|
| **Status** | ✅ Active | - |
| **Extraction Rate** | - | To be tracked |
| **Accuracy** | - | Compared with RM confirmations |
| **Common Issues** | - | Add as you discover |
| **Last Review** | - | - |

### Notes
- Often confused with wallet_topup - need better differentiation
- Biometric failures are common
- Bank name sometimes mispronounced

---

## 3. 📱 Wallet Load / Top-up Not Credited

**ID:** `wallet_topup`  
**Priority:** 🔴 HIGH  
**SLA:** 12 hours  
**Always Escalate?** No  
**Self-Serve?** No  

### Required Details (Slots)
- `amount` — Amount in ₹
- `utr_or_ref` — UTR or reference number
- `txn_date` — Date of transaction
- `payment_mode` — NEFT, IMPS, etc.

### Keywords
wallet, balance, top up, topup, load, e-value, evalue, utr, वॉलेट, बैलेंस, लोड

### Tracking

| Attribute | Value | Notes |
|-----------|-------|-------|
| **Status** | ✅ Active | - |
| **Extraction Rate** | - | To be tracked |
| **Accuracy** | - | Compared with RM confirmations |
| **Common Issues** | - | Add as you discover |
| **Last Review** | - | - |

### Notes
- Shortest SLA (12 hours) - highest priority for resolution
- UTR/reference numbers often mumbled or read digit-by-digit
- Payment mode sometimes unclear

---

## 4. 💼 Commission Not Received / Mismatch

**ID:** `commission`  
**Priority:** 🟡 MEDIUM  
**SLA:** 72 hours  
**Always Escalate?** No  
**Self-Serve?** No  

### Required Details (Slots)
- `month` — Which month (e.g., "October", "Sep 2026")
- `product` — Which product (DMT, AePS, etc.)

### Keywords
commission, kamission, incentive, payout, earning, kamai, कमीशन, इंसेंटिव, कमाई

### Tracking

| Attribute | Value | Notes |
|-----------|-------|-------|
| **Status** | ✅ Active | - |
| **Extraction Rate** | - | To be tracked |
| **Accuracy** | - | Compared with RM confirmations |
| **Common Issues** | - | Add as you discover |
| **Last Review** | - | - |

### Notes
- Less common than DMT/AePS issues
- CSPs often unsure which month they're asking about

---

## 5. 📋 KYC / Onboarding / Account Activation

**ID:** `kyc_onboarding`  
**Priority:** 🟡 MEDIUM  
**SLA:** 48 hours  
**Always Escalate?** No  
**Self-Serve?** No  

### Required Details (Slots)
- `issue_detail` — What part of KYC/onboarding (document, verification, etc.)

### Keywords
kyc, onboarding, activate, activation, document, pan card, verification, account band, id band, केवाईसी, एक्टिवेट, डॉक्यूमेंट, आईडी बंद

### Tracking

| Attribute | Value | Notes |
|-----------|-------|-------|
| **Status** | ✅ Active | - |
| **Extraction Rate** | - | To be tracked |
| **Accuracy** | - | Compared with RM confirmations |
| **Common Issues** | - | Add as you discover |
| **Last Review** | - | - |

### Notes
- Regulatory/compliance-sensitive
- Often requires manual RM intervention
- Document types vary (PAN, Aadhaar, voter ID, etc.)

---

## 6. 📲 App / Login / Device Problem

**ID:** `app_device`  
**Priority:** 🟡 MEDIUM  
**SLA:** 24 hours  
**Always Escalate?** No  
**Self-Serve?** No  

### Required Details (Slots)
- `device_or_screen` — Which device (phone, scanner, etc.) or screen
- `error_message` — What error they see

### Keywords
app, login, password, otp, device, scanner, morpho, mantra, rd service, error, crash, khul nahi, nahi khul, ऐप, लॉगिन, पासवर्ड, स्कैनर, एरर, खुल नहीं

### Tracking

| Attribute | Value | Notes |
|-----------|-------|-------|
| **Status** | ✅ Active | - |
| **Extraction Rate** | - | To be tracked |
| **Accuracy** | - | Compared with RM confirmations |
| **Common Issues** | - | Add as you discover |
| **Last Review** | - | - |

### Notes
- Technical issues, often needs remote support or restart
- CSPs may not know exact error messages
- Device-specific (terminal, scanner, phone app, etc.)

---

## 7. 🧾 Bill Payment / Recharge Failed

**ID:** `bbps_recharge`  
**Priority:** 🟡 MEDIUM  
**SLA:** 24 hours  
**Always Escalate?** No  
**Self-Serve?** No  

### Required Details (Slots)
- `txn_id` — Transaction ID
- `amount` — Amount in ₹
- `biller` — What was being paid (electricity, DTH, etc.)

### Keywords
bill, bijli, electricity, recharge, dth, bbps, fastag, gas, बिल, बिजली, रिचार्ज

### Tracking

| Attribute | Value | Notes |
|-----------|-------|-------|
| **Status** | ✅ Active | - |
| **Extraction Rate** | - | To be tracked |
| **Accuracy** | - | Compared with RM confirmations |
| **Common Issues** | - | Add as you discover |
| **Last Review** | - | - |

### Notes
- Biller information may be unclear
- Many regional variations in terminology

---

## 8. 🔄 Refund Status Enquiry

**ID:** `refund_status`  
**Priority:** 🟡 MEDIUM  
**SLA:** 24 hours  
**Always Escalate?** No  
**Self-Serve?** No  

### Required Details (Slots)
- `txn_id` — Transaction ID (to look up refund)

### Keywords
refund, wapas, vapas, return, रिफंड, वापस

### Tracking

| Attribute | Value | Notes |
|-----------|-------|-------|
| **Status** | ✅ Active | - |
| **Extraction Rate** | - | To be tracked |
| **Accuracy** | - | Compared with RM confirmations |
| **Common Issues** | - | Add as you discover |
| **Last Review** | - | - |

### Notes
- Often paired with other issues (e.g., "why is my DMT refund pending?")
- Agent should look up status from ticket history

---

## 9. ⚠️ Suspected Fraud / Unauthorised Activity

**ID:** `fraud_report`  
**Priority:** 🔴 CRITICAL  
**SLA:** 2 hours  
**Always Escalate?** ✅ **YES - ALWAYS**  
**Self-Serve?** No  

### Required Details (Slots)
- `issue_detail` — What fraud/unauthorized activity occurred

### Keywords
fraud, dhokha, scam, unauthorised, unauthorized, hack, chori, फ्रॉड, धोखा, चोरी

### Tracking

| Attribute | Value | Notes |
|-----------|-------|-------|
| **Status** | ✅ Active | - |
| **Extraction Rate** | - | To be tracked |
| **Accuracy** | - | Compared with RM confirmations |
| **Common Issues** | - | Add as you discover |
| **Last Review** | - | - |

### Notes
- **CRITICAL:** Must always escalate immediately to RM
- 2-hour SLA is strict
- May require regulatory reporting
- No self-serve response acceptable

---

## 10. 🎫 Status of Existing Complaint / Ticket

**ID:** `ticket_status`  
**Priority:** 🟢 LOW  
**SLA:** 0 (self-serve)  
**Always Escalate?** No  
**Self-Serve?** ✅ **YES**  

### Required Details (Slots)
- (None - agent looks up from existing ticket history)

### Keywords
ticket, complaint ka, shikayat, kya hua, status, शिकायत, टिकट, क्या हुआ

### Tracking

| Attribute | Value | Notes |
|-----------|-------|-------|
| **Status** | ✅ Active | - |
| **Extraction Rate** | - | To be tracked |
| **Accuracy** | - | Compared with RM confirmations |
| **Common Issues** | - | Add as you discover |
| **Last Review** | - | - |

### Notes
- Agent answers from existing ticket database
- No new ticket created
- Improves CSP satisfaction by showing we track their issues

---

## 11. ❓ General Query / Other

**ID:** `general_query`  
**Priority:** 🟢 LOW  
**SLA:** 72 hours  
**Always Escalate?** No  
**Self-Serve?** No  

### Required Details (Slots)
- `issue_detail` — What the query is about

### Keywords
(none - catch-all)

### Tracking

| Attribute | Value | Notes |
|-----------|-------|-------|
| **Status** | ✅ Active | - |
| **Extraction Rate** | - | To be tracked |
| **Accuracy** | - | Compared with RM confirmations |
| **Common Issues** | - | Add as you discover |
| **Last Review** | - | - |

### Notes
- Fallback category for anything not covered above
- If pattern emerges, may become its own category
- Lowest priority

---

## Tracking & Updates

### How to Update This File

1. **Add a new use case:** Copy the template below and fill in details
2. **Update metrics:** Add extraction rate, accuracy, common issues as you discover them
3. **Mark status:** ✅ Active, 🔄 In Review, ❌ Deprecated
4. **Add notes:** Document patterns, improvements needed, CSP feedback
5. **Commit to Git:** Changes to USE_CASES.md track taxonomy evolution

### Template for New Use Case

```markdown
## N. [Emoji] [Short Name]

**ID:** `identifier`  
**Priority:** 🔴 HIGH / 🟡 MEDIUM / 🟢 LOW  
**SLA:** X hours  
**Always Escalate?** Yes/No  
**Self-Serve?** Yes/No  

### Required Details (Slots)
- `slot_name` — Human-readable description

### Keywords
keyword1, keyword2, कीवर्ड

### Tracking

| Attribute | Value | Notes |
|-----------|-------|-------|
| **Status** | ✅ Active | - |
| **Extraction Rate** | - | To be tracked |
| **Accuracy** | - | Compared with RM confirmations |
| **Common Issues** | - | Add as you discover |
| **Last Review** | - | - |

### Notes
- Add observations, improvements needed, CSP feedback

```

---

## Related Files

- **Code:** `app/taxonomy.py` — Canonical source of truth for use cases
- **Guide:** `docs/USE_CASES_REVIEW.md` — How to view & review use cases
- **Recording Extraction:** `app/recordings.py` — How use cases are extracted from recordings
- **LLM Engine:** `app/llm_engine.py` — How AI identifies use cases and extracts details

---

## Sync Note

This file (USE_CASES.md) is the **human-readable tracker**.  
The **code source of truth** is `app/taxonomy.py` (CATEGORIES and SLOT_LABELS).

**To add a new use case:**
1. Update `app/taxonomy.py` (the code)
2. Add entry here (this file)
3. Test with sample recordings
4. Commit both files together

