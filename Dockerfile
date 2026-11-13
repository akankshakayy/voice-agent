FROM python:3.12-slim

WORKDIR /app
COPY . /app/

RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user and data directories
RUN useradd -m -u 10001 appuser && \
    mkdir -p /app/data/logs && \
    chown -R 10001:10001 /app && \
    chmod 755 /app && \
    chmod 755 /app/data && \
    find /app -type f -exec chmod 644 {} \; && \
    find /app -type d -exec chmod 755 {} \;

USER 10001

ENV PYTHONUNBUFFERED=1
ENV COOKIE_PATH=/
EXPOSE 8000

# Persistent volumes for database and logs
VOLUME ["/app/data", "/data"]

# Startup script: load env vars from .env.local and start app
RUN echo '#!/bin/bash\nset -e\necho "Starting Eko RM Voice Agent..."\nmkdir -p /app/data/logs\n\necho "Loading environment configuration..."\nif [ -f /app/.env.local ]; then\n  echo "✓ Found /app/.env.local - loading configuration"\n  export $(grep -v "^#" /app/.env.local | xargs)\nelif [ -f /data/.env.local ]; then\n  echo "✓ Found /data/.env.local - loading configuration"\n  export $(grep -v "^#" /data/.env.local | xargs)\nelse\n  echo "⚠ No .env.local found - using environment variables only"\nfi\n\necho "Checking database path..."\nif [ -z "$EKO_DB_PATH" ]; then\n  if [ -f /app/data/eko_agent.db ]; then\n    echo "✓ Found /app/data/eko_agent.db - using mounted volume database"\n    export EKO_DB_PATH=/app/data/eko_agent.db\n  elif [ -f /app/eko_agent.db ]; then\n    echo "✓ Found /app/eko_agent.db - using bundled database"\n    export EKO_DB_PATH=/app/eko_agent.db\n  elif [ -f /data/eko_agent.db ]; then\n    echo "✓ Found /data/eko_agent.db - using from mount"\n    export EKO_DB_PATH=/data/eko_agent.db\n  else\n    echo "⚠ No database found - will use /app/data/eko_agent.db"\n    export EKO_DB_PATH=/app/data/eko_agent.db\n  fi\nelse\n  echo "✓ Using configured EKO_DB_PATH: $EKO_DB_PATH"\nfi\n\necho "Ensuring database directory is writable..."\nDB_DIR=$(dirname "$EKO_DB_PATH")\nmkdir -p "$DB_DIR"\nls -ld "$DB_DIR" || echo "Failed to create/verify $DB_DIR"\n\necho "Checking for database on host mounts..."\nif [ ! -f "$EKO_DB_PATH" ] && [ -f /data/eko_agent.db ]; then\n  echo "Copying database from /data volume mount..."\n  cp /data/eko_agent.db "$EKO_DB_PATH"\n  echo "✓ Database copied to $EKO_DB_PATH"\nfi\n\necho "Configuration loaded:"\necho "  Database: $EKO_DB_PATH"\necho "  DEV_MODE: ${DEV_MODE:-not set}"\necho "  PRACHI_SHEET_ID: ${PRACHI_SHEET_ID:-(not set)}"\necho ""\necho "Starting server..."\nexec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips "*"' > /app/start.sh && \
    chmod +x /app/start.sh

CMD ["/app/start.sh"]
