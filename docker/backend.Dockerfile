FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/backend
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
# Application packages (monorepo layout: backend + shared ai/agents/rag/rules/integrations)
COPY backend ./backend
COPY ai ./ai
COPY agents ./agents
COPY rag ./rag
COPY rules ./rules
COPY integrations ./integrations
COPY tests ./tests
COPY scripts ./scripts
COPY knowledge ./knowledge
COPY pytest.ini ./pytest.ini
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
