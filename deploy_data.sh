#!/bin/bash

# Deployment script to push database to production

USERNAME="akanksha"
# Password is read from the local .env (never commit it): Password=...
PASSWORD="${SSH_PASSWORD:-$(grep -m1 '^Password=' .env 2>/dev/null | cut -d= -f2- | tr -d "\"'")}"
if [ -z "$PASSWORD" ]; then echo "Set SSH_PASSWORD or add Password=... to .env"; exit 1; fi
PORT="2222"
HOSTNAME="indev.eko.in"
SOURCE_DB="data/eko_agent.db"
DEST_DB="/data/eko_agent.db"

echo "=========================================="
echo "Deploying database to production"
echo "=========================================="
echo ""
echo "Source: $SOURCE_DB"
echo "Destination: $HOSTNAME:$DEST_DB"
echo ""

# Use SSH with password-based authentication
export SSHPASS="$PASSWORD"
sshpass -e scp -P $PORT "$SOURCE_DB" "$USERNAME@$HOSTNAME:$DEST_DB" && {
    echo ""
    echo "✅ Database deployed successfully!"
    echo ""
    echo "Now restart the Docker container:"
    echo "  ssh -p $PORT $USERNAME@$HOSTNAME"
    echo "  docker restart rm-voice-agent"
} || {
    echo ""
    echo "❌ Deployment failed. Try manually:"
    echo "  scp -P $PORT data/eko_agent.db akanksha@indev.eko.in:/data/eko_agent.db"
}
