#!/bin/bash
set -e

echo "════════════════════════════════════════════════════════════════════════════════"
echo "🚀 DEPLOYING PRACHI_SHEET_ID TO PRODUCTION"
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""

cd /home/akanksha/voice_agent

echo "Step 1: Pull latest code"
git pull origin main

echo ""
echo "Step 2: Add PRACHI_SHEET_ID to .env.local"
if [ -f .env.local ]; then
  if grep -q "PRACHI_SHEET_ID" .env.local; then
    echo "Already exists, updating..."
    sed -i 's|PRACHI_SHEET_ID=.*|PRACHI_SHEET_ID=1lz7RihRysA10akqcwrxrRUq2fVYw4Mr-w7DclVRApLw|' .env.local
  else
    echo "Adding PRACHI_SHEET_ID..."
    echo "" >> .env.local
    echo "# Prachi Sheet Auto-Sync (Nov 13, 2026)" >> .env.local
    echo "PRACHI_SHEET_ID=1lz7RihRysA10akqcwrxrRUq2fVYw4Mr-w7DclVRApLw" >> .env.local
    echo "PRACHI_SYNC_ENABLED=true" >> .env.local
  fi
else
  echo "Creating .env.local..."
  echo "# Prachi Sheet Configuration (Nov 13, 2026)" > .env.local
  echo "PRACHI_SHEET_ID=1lz7RihRysA10akqcwrxrRUq2fVYw4Mr-w7DclVRApLw" >> .env.local
  echo "PRACHI_SYNC_ENABLED=true" >> .env.local
fi

echo "✓ Configuration added"
echo ""

echo "Step 3: Verify .env.local"
echo "PRACHI configuration:"
grep "PRACHI_SHEET_ID\|PRACHI_SYNC_ENABLED" .env.local || echo "(not found - will be added on deploy)"
echo ""

echo "Step 4: Deploy with eko-deploy"
eko-deploy deploy rm-voice-agent

echo ""
echo "════════════════════════════════════════════════════════════════════════════════"
echo "✅ DEPLOYMENT COMPLETE!"
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""
echo "Prachi auto-sync is now ENABLED:"
echo "  • Runs daily @ 2 AM IST"
echo "  • Syncs DCs from Google Sheets"
echo "  • Syncs SBI Officials from Google Sheets"
echo "  • Updates allowed_numbers table automatically"
echo ""
