FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

# Non-root user. /app/data is the persistent volume (declared in eko-deploy.toml);
# the bundled /app/eko_agent.db only seeds it on first boot (see start.sh).
RUN useradd -m -u 10001 appuser && \
    mkdir -p /app/data/logs && \
    chown -R 10001:10001 /app/data && \
    chmod +x /app/start.sh

USER 10001

ENV PYTHONUNBUFFERED=1 \
    COOKIE_PATH=/ \
    EKO_DB_PATH=/app/data/eko_agent.db \
    DATA_DIR=/app/data

EXPOSE 8000
VOLUME ["/app/data"]

CMD ["/app/start.sh"]
