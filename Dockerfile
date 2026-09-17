# Spellforge in one container: the built frontend served by the Python game server.
# Used by the Hugging Face Space (see docs/deploy.md); works on any Docker host.
#
#   docker build -t spellforge .
#   docker run -p 7860:7860 -e ANTHROPIC_API_KEY=... -e SPELLFORGE_ACCESS_CODE=... spellforge
#
# Secrets are never baked into the image: pass them as environment variables at run time.

# ---- 1. build the frontend ----------------------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2. the server ------------------------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Hugging Face runs containers as uid 1000; run as that unprivileged user everywhere.
RUN useradd --create-home --uid 1000 spellforge
WORKDIR /app

COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/spellforge backend/spellforge
RUN pip install ./backend

COPY --from=frontend /app/frontend/dist /app/static

USER spellforge
ENV HOST=0.0.0.0 \
    PORT=7860 \
    SPELLFORGE_STATIC_DIR=/app/static \
    SPELLFORGE_DAILY_BUDGET_USD=5 \
    SPELLFORGE_MAX_SESSIONS=20
EXPOSE 7860
CMD ["python", "-m", "spellforge.server"]
