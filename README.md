# Furniture AI API

Phase 1 provides a minimal FastAPI service and verifies that the backend can start
and answer health checks. It intentionally contains no database, authentication,
recommendation, AI, image-generation, CORS, migration, or deployment integration.

## Prerequisites

- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/)

Run all commands from the project root.

## Install dependencies

Create or update the local virtual environment and synchronize all locked runtime
and development dependencies:

```powershell
uv sync
```

## Start the development server

```powershell
uv run uvicorn app.main:app --reload
```

The health endpoint is available at <http://127.0.0.1:8000/health>.

## Open Swagger documentation

With the development server running, open Swagger UI in the default browser:

```powershell
Start-Process "http://127.0.0.1:8000/docs"
```

Swagger UI is available at <http://127.0.0.1:8000/docs>.

## Run tests

```powershell
uv run pytest
```

## Run Ruff checks

Run lint checks:

```powershell
uv run ruff check .
```

Verify formatting without modifying files:

```powershell
uv run ruff format --check .
```
