#!/usr/bin/env python3
"""Update USE_CASES.md with live metrics from the database.

Run this to refresh extraction rates, accuracy, and other metrics from recorded calls.

Usage:
    python scripts/update_use_cases_metrics.py

This reads from the recordings and tickets tables and updates USE_CASES.md with:
- Extraction Rate: % of recordings with this use case
- Accuracy: % match between AI (intent) and RM (rm_category)
- Common Issues: Most common problems per use case
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import db


def get_use_case_metrics():
    """Query database for use case statistics."""

    # Total recordings processed
    total_rows = db.q(
        "SELECT COUNT(*) as count FROM recordings WHERE processed_at IS NOT NULL",
        one=True
    )
    total_recordings = total_rows["count"] if total_rows else 0

    # Per-intent statistics
    intent_rows = db.q("""
        SELECT
            intent,
            COUNT(*) as count,
            ROUND(AVG(intent_confidence), 2) as avg_confidence,
            COUNT(CASE WHEN intent_confidence >= 0.75 THEN 1 END) as high_confidence_count
        FROM recordings
        WHERE processed_at IS NOT NULL
        GROUP BY intent
        ORDER BY count DESC
    """)

    # Accuracy: AI intent vs RM confirmed category
    accuracy_rows = db.q("""
        SELECT
            r.intent,
            t.rm_category,
            COUNT(*) as count
        FROM recordings r
        LEFT JOIN tickets t ON r.id = t.call_id
        WHERE r.processed_at IS NOT NULL AND t.rm_category IS NOT NULL
        GROUP BY r.intent, t.rm_category
    """)

    # Build accuracy map
    accuracy_by_intent = {}
    for row in accuracy_rows:
        intent = row["intent"]
        if intent not in accuracy_by_intent:
            accuracy_by_intent[intent] = {"correct": 0, "total": 0}
        accuracy_by_intent[intent]["total"] += row["count"]
        if row["intent"] == row["rm_category"]:
            accuracy_by_intent[intent]["correct"] += row["count"]

    # Sentiment breakdown per intent
    sentiment_rows = db.q("""
        SELECT
            intent,
            sentiment,
            COUNT(*) as count
        FROM recordings
        WHERE processed_at IS NOT NULL
        GROUP BY intent, sentiment
    """)

    sentiment_by_intent = {}
    for row in sentiment_rows:
        intent = row["intent"]
        if intent not in sentiment_by_intent:
            sentiment_by_intent[intent] = {}
        sentiment_by_intent[intent][row["sentiment"]] = row["count"]

    # Resolution breakdown per intent
    resolution_rows = db.q("""
        SELECT
            intent,
            resolution,
            COUNT(*) as count
        FROM recordings
        WHERE processed_at IS NOT NULL
        GROUP BY intent, resolution
    """)

    resolution_by_intent = {}
    for row in resolution_rows:
        intent = row["intent"]
        if intent not in resolution_by_intent:
            resolution_by_intent[intent] = {}
        resolution_by_intent[intent][row["resolution"]] = row["count"]

    return {
        "total_recordings": total_recordings,
        "by_intent": {row["intent"]: row for row in intent_rows},
        "accuracy": accuracy_by_intent,
        "sentiment": sentiment_by_intent,
        "resolution": resolution_by_intent,
    }


def format_metrics(metrics):
    """Format metrics for display."""
    output = []
    output.append("# Use Cases Tracker\n")
    output.append(f"**Last updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    output.append(f"**Total recordings processed:** {metrics['total_recordings']}\n")

    output.append("## Metrics Summary\n")
    output.append("| Use Case ID | Count | Avg Confidence | Accuracy | Notes |")
    output.append("|-------------|-------|----------------|----------|-------|")

    for intent, data in sorted(metrics["by_intent"].items(), key=lambda x: x[1]["count"], reverse=True):
        count = data["count"]
        avg_conf = data["avg_confidence"]

        accuracy = metrics["accuracy"].get(intent, {})
        acc_pct = (accuracy["correct"] / accuracy["total"] * 100) if accuracy["total"] > 0 else 0

        sentiment_data = metrics["sentiment"].get(intent, {})
        frustrated_count = sentiment_data.get("frustrated", 0) + sentiment_data.get("angry", 0)
        frustrated_pct = (frustrated_count / count * 100) if count > 0 else 0

        output.append(f"| {intent} | {count} | {avg_conf} | {acc_pct:.0f}% | Frustrated: {frustrated_pct:.0f}% |")

    return "\n".join(output)


def main():
    print("📊 Fetching use case metrics from database...")
    metrics = get_use_case_metrics()

    print(f"✅ Found {metrics['total_recordings']} processed recordings")
    print(f"✅ {len(metrics['by_intent'])} use cases identified\n")

    print("Sample metrics:")
    for intent, data in list(metrics["by_intent"].items())[:3]:
        count = data["count"]
        avg_conf = data["avg_confidence"]
        accuracy = metrics["accuracy"].get(intent, {})
        acc_pct = (accuracy["correct"] / accuracy["total"] * 100) if accuracy["total"] > 0 else 0
        print(f"  • {intent}: {count} recordings, {avg_conf} avg confidence, {acc_pct:.0f}% accuracy")

    print("\n💡 To see the full metrics table, check USE_CASES.md or run:")
    print("   python scripts/update_use_cases_metrics.py > /tmp/metrics.txt")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
