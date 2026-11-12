FROM python:3.12-slim

WORKDIR /app
COPY . /app/

RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user and data directories
RUN useradd -m -u 10001 appuser && \
    mkdir -p /app/data/logs && \
    chown -R 10001:10001 /app && \
    chmod -R 755 /app

USER 10001

ENV PYTHONUNBUFFERED=1
ENV COOKIE_PATH=/
EXPOSE 8000

# Persistent volumes for database and logs
VOLUME ["/app/data", "/data"]

# Startup script: load env vars from .env.local and start app
RUN echo '#!/bin/bash\nset -e\necho "Starting Eko RM Voice Agent..."\nmkdir -p /app/data/logs\n\necho "Loading environment configuration..."\nif [ -f .env.local ]; then\n  echo "✓ Found .env.local - loading configuration"\n  export $(grep -v "^#" .env.local | xargs)\nfi\n\necho "Checking database path..."\nif [ -f /data/eko_agent.db ]; then\n  echo "✓ Found /data/eko_agent.db - using from mount"\n  export EKO_DB_PATH=/data/eko_agent.db\nelse\n  echo "✓ Using /app/data/eko_agent.db"\n  export EKO_DB_PATH=/app/data/eko_agent.db\nfi\n\necho "Configuration loaded:"\necho "  Database: $EKO_DB_PATH"\necho "  DEV_MODE: ${DEV_MODE:-not set}"\necho "  PRACHI_SHEET_ID: ${PRACHI_SHEET_ID:-(not set)}"\necho ""\necho "Starting server..."\nexec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips "*"' > /app/start.sh && \
    chmod +x /app/start.sh

CMD ["/app/start.sh"]
