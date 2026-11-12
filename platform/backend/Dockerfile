# syntax=docker/dockerfile:1
# Build context: repository root (needs ../../rca). See platform/docker-compose.yml.
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY platform/backend/requirements.txt /tmp/requirements.txt
COPY rca /src/rca
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install -r /tmp/requirements.txt \
 && /opt/venv/bin/pip install /src/rca
# Train the RCA model at build time (deterministic seed, ~10 s), so the image is self-contained.
RUN /opt/venv/bin/python -m rca_engine.train --out /opt/rca/rca_model.joblib --seed 42

FROM python:3.12-slim
ENV PATH="/opt/venv/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PLATFORM_DB=/data/platform.db RCA_MODEL_PATH=/opt/rca/rca_model.joblib
RUN groupadd --system --gid 10001 platform \
 && useradd --system --uid 10001 --gid platform --no-create-home --shell /usr/sbin/nologin platform \
 && install -d -o platform -g platform /data
WORKDIR /srv
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/rca /opt/rca
COPY platform/backend/app ./app
USER platform
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
