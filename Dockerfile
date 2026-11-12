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
EXPOSE 8000

# Persistent volumes for database and logs
VOLUME ["/app/data", "/data"]

# Startup script: set database path and initialize
RUN echo '#!/bin/bash\nset -e\necho "Setting up Eko RM Voice Agent..."\nmkdir -p /app/data/logs\necho "Checking for host database in /data mount..."\nif [ -f /data/eko_agent.db ]; then\n  echo "✅ Found /data/eko_agent.db - using from mount"\n  export EKO_DB_PATH=/data/eko_agent.db\nelse\n  echo "⚠️  No /data/eko_agent.db - using /app/data/eko_agent.db"\n  export EKO_DB_PATH=/app/data/eko_agent.db\nfi\necho "Database path: $EKO_DB_PATH"\necho "Starting Eko RM Voice Agent..."\nexec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips "*"' > /app/start.sh && \
    chmod +x /app/start.sh

CMD ["/app/start.sh"]
