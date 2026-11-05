#!/bin/bash
# Troubleshoot Recording Display Issues
# Usage: ./troubleshoot-recordings.sh

set -e

echo "📋 Recording Display Troubleshooter"
echo "==================================="
echo ""

cd "$(dirname "$0")"

# 1. Check database status
echo "1️⃣  Database Status"
echo "   -----------"
python3 -m app.db_sync status
echo ""

# 2. Check for API data mismatches in logs
echo "2️⃣  Recent API Activity (last 20 lines with 'recordings')"
echo "   -------"
if [ -f "data/logs/eko.log" ]; then
    grep -i "recordings\|DATA MISMATCH" data/logs/eko.log | tail -20 || echo "   (no matches found)"
else
    echo "   (log file not found)"
fi
echo ""

# 3. Direct database check
echo "3️⃣  Direct Database Check"
echo "   -------"
python3 << 'PYEOF'
from app import db, recordings

# Get counts
result = db.q("SELECT COUNT(*) as cnt FROM recordings;")
total = result[0]["cnt"] if result else 0

# Get status distribution
result = db.q("SELECT status, COUNT(*) as cnt FROM recordings GROUP BY status;")
print(f"Total recordings: {total}")
print("By status:")
for row in result:
    print(f"  {row['status']}: {row['cnt']}")

# Check summary_counts (what API returns)
counts = recordings.summary_counts()
print(f"\nAPI summary_counts(): {counts}")
print(f"Sum of counts: {sum(counts.values())}")

# Check if list_recordings returns anything
recs = recordings.list_recordings()
print(f"list_recordings() returned: {len(recs)} items")

if total > 0 and len(recs) == 0:
    print("\n⚠️  DATA MISMATCH DETECTED!")
    print("    Counts show recordings but list_recordings returns none")
    print("    Possible causes:")
    print("    - Database sync issue (try: python -m app.db_sync sync)")
    print("    - JOIN failure (missing RMs or CSPs)")
    print("    - File path problems")
    print("    - See docs/DATABASE.md for debugging help")
elif total == 0 and sum(counts.values()) > 0:
    print("\n⚠️  COUNTS MISMATCH DETECTED!")
    print("    Counts show data but table is empty")
    print("    Try: python -m app.db_sync sync")
else:
    print("\n✅ Database appears consistent")
PYEOF

echo ""

# 4. Check token upload counts
echo "4️⃣  Upload Token Status"
echo "   -------"
python3 << 'PYEOF'
from app import db

result = db.q("""
    SELECT label,
           (SELECT COUNT(*) FROM recordings WHERE token_id = id) as uploads
    FROM upload_tokens
    ORDER BY uploads DESC
""")

total_uploads = 0
for row in result:
    label = row['label'] or "(no label)"
    print(f"  {label}: {row['uploads']} uploads")
    total_uploads += row['uploads']

print(f"\nTotal from tokens: {total_uploads}")
PYEOF

echo ""

# 5. Recommendation
echo "5️⃣  Recommendations"
echo "   -------"
python3 << 'PYEOF'
from app import db, recordings

result = db.q("SELECT COUNT(*) as cnt FROM recordings;")
local_total = result[0]["cnt"] if result else 0

result = db.q("SELECT COUNT(*) as cnt FROM upload_tokens;")
token_count = result[0]["cnt"] if result else 0

print(f"Local database has: {local_total} recordings from {token_count} tokens")

if local_total < 10:
    print("\n  💡 Recommendation: Sync server database")
    print("     Command: python -m app.db_sync sync")
    print("     This will pull 358+ recordings from production")
else:
    print("\n  ✅ Local database has plenty of test data")

print("\n  📖 For more info: cat docs/DATABASE.md")
PYEOF

echo ""
echo "Done! ✨"
