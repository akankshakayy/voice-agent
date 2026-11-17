FROM python:3.12-slim

WORKDIR /app
COPY . /app/
# Explicitly copy database file even though it's in git
COPY eko_agent.db /app/

RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user and data directories
# Note: When volumes are mounted, host UIDs may not match container UIDs
# Solution: Use 777 permissions on mounted directories so any UID can write
RUN useradd -m -u 10001 appuser && \
    mkdir -p /app/data/logs && \
    mkdir -p /data/logs && \
    chown -R 10001:10001 /app && \
    chmod 755 /app && \
    chmod 777 /app/data && \
    chmod 777 /app/data/logs && \
    chmod 777 /data && \
    find /app -type f -exec chmod 644 {} \; && \
    find /app -type d -exec chmod 755 {} \;

# Fix /app/data and /data permissions again for mounted volumes
RUN chmod 777 /app/data /app/data/logs /data 2>/dev/null || true

USER 10001

ENV PYTHONUNBUFFERED=1
ENV COOKIE_PATH=/
EXPOSE 8000

# Persistent volumes for database and logs
VOLUME ["/app/data", "/data"]

# Ensure database is in the expected location (/app/data/)
RUN if [ -f /app/eko_agent.db ]; then cp /app/eko_agent.db /app/data/eko_agent.db && echo "✓ Database copied to /app/data/"; fi

# Startup script: load env vars from .env.local and start app
RUN echo '#!/bin/bash\nset -e\necho "Starting Eko RM Voice Agent..."\nmkdir -p /app/data/logs\n\necho "Loading environment configuration..."\nif [ -f /app/.env.local ]; then\n  echo "✓ Found /app/.env.local - loading configuration"\n  export $(grep -v "^#" /app/.env.local | xargs)\nelif [ -f /data/.env.local ]; then\n  echo "✓ Found /data/.env.local - loading configuration"\n  export $(grep -v "^#" /data/.env.local | xargs)\nelse\n  echo "⚠ No .env.local found - using environment variables only"\nfi\n\necho "Checking database path..."\nif [ -z "$EKO_DB_PATH" ]; then\n  if [ -f /app/eko_agent.db ]; then\n    echo "✓ Found /app/eko_agent.db - using bundled database"\n    export EKO_DB_PATH=/app/eko_agent.db\n  elif [ -f /app/data/eko_agent.db ]; then\n    echo "✓ Found /app/data/eko_agent.db - using mounted volume database"\n    export EKO_DB_PATH=/app/data/eko_agent.db\n  elif [ -f /data/eko_agent.db ]; then\n    echo "✓ Found /data/eko_agent.db - using from mount"\n    export EKO_DB_PATH=/data/eko_agent.db\n  else\n    echo "⚠ No database found - will use /app/data/eko_agent.db"\n    export EKO_DB_PATH=/app/data/eko_agent.db\n  fi\nelse\n  echo "✓ Using configured EKO_DB_PATH: $EKO_DB_PATH"\nfi\n\necho "Ensuring database directory is writable..."\nDB_DIR=$(dirname "$EKO_DB_PATH")\nmkdir -p "$DB_DIR"\nls -ld "$DB_DIR" || echo "Failed to create/verify $DB_DIR"\n\necho "Checking for database on host mounts..."\nif [ ! -f "$EKO_DB_PATH" ] && [ -f /data/eko_agent.db ]; then\n  echo "Copying database from /data volume mount..."\n  cp /data/eko_agent.db "$EKO_DB_PATH"\n  echo "✓ Database copied to $EKO_DB_PATH"\nfi\n\necho "Checking if database needs data..."\nif [ "$EKO_DB_PATH" = "/app/data/eko_agent.db" ] && [ -f /app/eko_agent.db ]; then\n  # If using /app/data/eko_agent.db but it'\''s empty, copy from bundled /app/eko_agent.db\n  if [ ! -s "$EKO_DB_PATH" ] || ! sqlite3 "$EKO_DB_PATH" "SELECT COUNT(*) FROM dcs;" 2>/dev/null | grep -qE "[1-9]"; then\n    echo "⚠ Volume database is empty - copying from bundled database"\n    cp /app/eko_agent.db "$EKO_DB_PATH"\n    echo "✓ Database initialized with bundled data"\n  fi\nelif [ ! -f "$EKO_DB_PATH" ] || [ ! -s "$EKO_DB_PATH" ]; then\n  echo "⚠ Database missing or empty - app will initialize fresh schema on startup"\nfi\n\necho "Configuration loaded:"\necho "  Database: $EKO_DB_PATH"\necho "  DEV_MODE: ${DEV_MODE:-not set}"\necho "  PRACHI_SHEET_ID: ${PRACHI_SHEET_ID:-(not set)}"\necho ""\necho "Starting server..."\nexec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips "*"' > /app/start.sh && \
    chmod +x /app/start.sh

CMD ["/app/start.sh"]
