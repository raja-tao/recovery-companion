# Single-service image for Render (or any PaaS): the API also serves the built web app on the same origin.
# Local stack uses backend.Dockerfile + frontend.Dockerfile (nginx) instead.

FROM node:20-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/backend STATIC_DIR=/app/static
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY backend ./backend
COPY ai ./ai
COPY agents ./agents
COPY rag ./rag
COPY rules ./rules
COPY integrations ./integrations
COPY scripts ./scripts
COPY knowledge ./knowledge
COPY --from=web /web/dist ./static
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser
EXPOSE 10000
# Render sets PORT (default 10000).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips='*'"]
