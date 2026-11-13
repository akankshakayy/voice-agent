#!/bin/bash
# PRODUCTION DEPLOYMENT SCRIPT
# Run this on the production server (indev.eko.in)
# Date: Nov 13, 2026

set -e

echo "================================================================================"
echo "EKO RM VOICE AGENT - PRODUCTION DEPLOYMENT"
echo "================================================================================"

# STEP 1: Set up persistent storage
echo ""
echo "STEP 1: Setting up persistent storage directory"
echo "-----------------------------------------------"
sudo mkdir -p /data/rm-voice-agent
echo "✓ Created /data/rm-voice-agent"

sudo chmod 777 /data/rm-voice-agent
echo "✓ Set permissions to 777 (world-writable)"

ls -ld /data/rm-voice-agent
echo ""

# STEP 2: Verify storage is ready
echo "STEP 2: Verifying storage"
echo "-----------------------------------------------"
if [ -d /data/rm-voice-agent ]; then
    echo "✓ Directory exists and is accessible"
    df -h /data/rm-voice-agent
else
    echo "✗ ERROR: Directory not created!"
    exit 1
fi
echo ""

# STEP 3: Wait for database backup
echo "STEP 3: Waiting for database backup"
echo "-----------------------------------------------"
echo "From your local machine, run:"
echo ""
echo "scp -P 2222 /home/cat/eko-rm-voice-agent/data/eko_agent.db \\"
echo "    akanksha@indev.eko.in:/data/rm-voice-agent/"
echo ""
echo "Checking for database file..."

max_wait=300  # 5 minutes
elapsed=0
while [ ! -f /data/rm-voice-agent/eko_agent.db ] && [ $elapsed -lt $max_wait ]; do
    echo -n "."
    sleep 5
    elapsed=$((elapsed + 5))
done

if [ -f /data/rm-voice-agent/eko_agent.db ]; then
    echo ""
    echo "✓ Database file received!"
    ls -lh /data/rm-voice-agent/eko_agent.db
else
    echo ""
    echo "✗ Database file not received within timeout"
    echo "  Continuing anyway - deployment can proceed"
fi
echo ""

# STEP 4: Pull Docker image (or check if already available)
echo "STEP 4: Docker image"
echo "-----------------------------------------------"
if docker images | grep -q "eko-sahayak:latest"; then
    echo "✓ Docker image eko-sahayak:latest is available"
    docker images | grep eko-sahayak
else
    echo "⚠ Docker image not found locally"
    echo "  It will be pulled during deployment"
fi
echo ""

# STEP 5: Ready for deployment
echo "STEP 5: Ready for deployment!"
echo "-----------------------------------------------"
echo ""
echo "✓ Persistent storage configured"
echo "✓ Directory permissions set (chmod 777)"
if [ -f /data/rm-voice-agent/eko_agent.db ]; then
    echo "✓ Database backup in place"
else
    echo "⚠ Database backup still pending"
fi
echo ""

echo "NEXT STEP: Run eko-deploy deployment command"
echo "================================================================================"
echo ""
echo "From your LOCAL machine, run:"
echo ""
echo "cd /home/cat/eko-rm-voice-agent"
echo ""
echo "eko-deploy deploy \\"
echo "  --app rm-voice-agent \\"
echo "  --image eko-sahayak:latest \\"
echo "  --env-file .env.local \\"
echo "  --volumes /data/rm-voice-agent:/app/data \\"
echo "  --volumes /data/rm-voice-agent:/data \\"
echo "  --port 8000"
echo ""
echo "================================================================================"
