# Production image for the Furniture AI API.
#
#   docker build -t furn-api .
#   docker run --env-file .env -p 8000:8000 furn-api
#
# Configuration comes only from the environment at run time. Nothing secret is
# copied into the image: .env is excluded by .dockerignore, and the hosting
# platform supplies SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, GEMINI_API_KEY and
# the rest as environment variables.

FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first, from the lock file only, so code changes reuse this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY app ./app

# Run as an unprivileged user.
RUN useradd --system --no-create-home --uid 10001 api
USER api

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'), timeout=4)"

# Most platforms (Render, Railway, Fly.io, Cloud Run) set PORT. The proxy flags
# make the app see the real scheme behind the platform's HTTPS terminator.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
