"""Words that matter in an RM-CSP call: Eko's services, money, banks and IDs, problems and the actions taken.
The call-metrics word lists keep only these (plus words people corrected as misheard), so they show the call's
subject matter and the vocabulary worth training speech-to-text and the review model on, not everyday chatter.

Each word maps to a group shown next to it. Roman and Devanagari spellings are both listed, because Sarvam's
codemix output writes English words in Roman letters but often keeps Hindi ones (and some English) in Devanagari.
The issue keywords in app/taxonomy.py are added automatically under their issue's name.
"""
from .taxonomy import CATEGORIES

GROUPS = {
    "Eko business": """eko csp csps kiosk retailer retailers agent agents distributor slab slabs target targets achieve
        achieved sby transaction transactions txn txns business volume portal service services customer customers
        training onboard dashboard report scheme offer offers bonus
        एको सीएसपी कियोस्क रिटेलर एजेंट डिस्ट्रीब्यूटर स्लैब टारगेट अचीव ट्रांजैक्शन ट्रांजेक्शन ट्रांसेक्शन बिज़नेस बिजनेस
        पोर्टल सर्विस कस्टमर ग्राहक ट्रेनिंग स्कीम ऑफर बोनस""",
    "Money": """paisa paise rupaye rupay rupees rupee rs amount hazaar hazar lakh cash deposit jama credit credited debit
        debited settlement settle limit charge charges fee fees gst tds invoice payment paid due
        पैसा पैसे रुपये रुपए रुपया अमाउंट हज़ार हजार लाख कैश जमा क्रेडिट डेबिट सेटलमेंट लिमिट चार्ज फीस जीएसटी टीडीएस
        इनवॉइस पेमेंट भुगतान""",
    "Banks & IDs": """bank banks account accounts khata ifsc upi sbi pnb hdfc icici axis kotak bob canara airtel paytm fino
        nsdl ippb cms npci pan aadhaar aadhar mobile sim
        बैंक अकाउंट खाता खाते आईएफएससी यूपीआई एसबीआई पीएनबी एचडीएफसी आईसीआईसीआई एक्सिस पैन मोबाइल सिम""",
    "Problems & actions": """complaint complaints problem problems issue issues dikkat pareshani block blocked lock locked
        reversal reverse reversed cancel cancelled stuck deducted kat solve solved resolve resolved escalate
        update mail email callback verify verified approve approved reject rejected
        प्रॉब्लम प्रोब्लम दिक्कत परेशानी समस्या ब्लॉक लॉक रिवर्सल रिवर्स कैंसिल अटका अटक कटा सॉल्व
        अपडेट मेल ईमेल वेरीफाई अप्रूव रिजेक्ट""",
}

ISSUE_GROUPS = {"dmt_failed": "Money transfer", "aeps_issue": "AePS", "wallet_topup": "Wallet", "commission": "Commission",
                "kyc_onboarding": "KYC & onboarding", "app_device": "App & device", "bbps_recharge": "Bills & recharge",
                "refund_status": "Refund", "fraud_report": "Fraud", "ticket_status": "Complaints"}
TOO_COMMON = {"return", "status", "finger", "load", "error", "kya", "hua", "band", "nahi"}   # mean little alone


def _build() -> dict:
    terms = {}
    for cat, group in ISSUE_GROUPS.items():
        for kw in CATEGORIES.get(cat, {}).get("keywords", []):
            for w in kw.lower().split():
                if w not in TOO_COMMON and len(w) > 1:
                    terms.setdefault(w, group)
    for group, words in GROUPS.items():
        for w in words.split():
            terms.setdefault(w.lower(), group)
    return terms


TERMS = _build()


def group_of(word: str, extra: dict | None = None) -> str | None:
    """The word's group, or None if it isn't a domain word. Roman plurals count ("refunds" -> "refund")."""
    w = word.lower()
    for key in (w, w[:-1] if w.endswith("s") and w.isascii() else None):
        if key and key in TERMS:
            return TERMS[key]
        if key and extra and key in extra:
            return extra[key]
    return None
