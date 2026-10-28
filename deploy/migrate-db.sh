#!/bin/bash
# Migrate database from laptop to server
# Run this on the server as admin/root

set -e

echo "=== Sahayak Database Migration Script ==="
echo "This script syncs real CSP data (595 CSPs, 3 RMs) from laptop to server"
echo ""

# Expect the file to be in /tmp (uploaded via SCP from laptop)
DB_SOURCE="/tmp/eko_agent.db"
DB_DEST="/data/eko_agent.db"
CONTAINER_ID=$(docker ps --format "{{.ID}}" | head -1)

if [ ! -f "$DB_SOURCE" ]; then
    echo "❌ Error: Database file not found at $DB_SOURCE"
    echo "   On laptop, run: scp -P 2222 data/eko_agent.db akanksha@indev.eko.in:/tmp/"
    exit 1
fi

if [ -z "$CONTAINER_ID" ]; then
    echo "❌ Error: No running Docker container found"
    echo "   Container must be running to mount volumes"
    exit 1
fi

echo "✅ Found database at $DB_SOURCE"
echo "✅ Found container: $CONTAINER_ID"
echo ""

# Backup existing db if it exists
if [ -f "$DB_DEST" ]; then
    BACKUP_FILE="$DB_DEST.backup.$(date +%Y%m%d-%H%M%S)"
    echo "📦 Backing up existing database..."
    sudo cp "$DB_DEST" "$BACKUP_FILE"
    echo "   Saved to: $BACKUP_FILE"
    echo ""
fi

# Copy to /data
echo "📋 Copying database to /data..."
sudo cp "$DB_SOURCE" "$DB_DEST"
sudo chown 10001:10001 "$DB_DEST"
sudo chmod 644 "$DB_DEST"
echo "✅ Database copied to $DB_DEST"
echo ""

# Verify in container
echo "🔍 Verifying database in container..."
docker exec $CONTAINER_ID python3 << 'PYEOF'
import sqlite3
try:
    conn = sqlite3.connect('/data/eko_agent.db')
    c = conn.cursor()

    c.execute('SELECT COUNT(*) FROM csps')
    csps = c.fetchone()[0]

    c.execute('SELECT COUNT(*) FROM rms')
    rms = c.fetchone()[0]

    c.execute('SELECT id, name FROM rms')
    rm_list = c.fetchall()

    print(f"✅ Database verification successful!")
    print(f"   CSPs: {csps}")
    print(f"   RMs: {rms}")
    for rm_id, rm_name in rm_list:
        print(f"     - {rm_name} (ID: {rm_id})")

    conn.close()
except Exception as e:
    print(f"❌ Verification failed: {e}")
    exit(1)
PYEOF

if [ $? -ne 0 ]; then
    echo "❌ Database verification failed"
    exit 1
fi

echo ""
echo "=== Migration Complete ==="
echo "Real data is now on the server!"
echo ""
echo "Next step: Generate upload tokens for RM phones"
echo "  Run: python3 -m app.commands gen-upload-token --rm-id <id>"
