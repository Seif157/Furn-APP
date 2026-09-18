# Getting started with the Furniture AI API

The backend for Furn-APP, a furniture marketplace. FastAPI in front of
Supabase (auth, PostgreSQL, row-level security), with an AI layer on Google
Gemini for natural-language search and room planning.

One rule shapes everything: **the model reads the customer's words; it never
supplies a marketplace fact.** Products, prices, stock and sizes always come
from the catalogue, read with the customer's own token so row-level security
decides what they can see. Ranking, comparison and budgeting are ordinary,
deterministic code. `CLAUDE.md` is the full plan and project state.

The top-level `README.md` is still the Phase 1 text. It is kept byte-identical
because the Phase 3.2C and 3.2D security packages pin it, and those packages
are pending human review; this file is the current overview until then.

## Endpoints

Every `/v1` route requires `Authorization: Bearer <Supabase access token>`,
except `/v1/meta`, `/v1/search/vocabulary`, `/v1/search/examples` and
`/v1/reviews/public`, which describe the server or public data.

| Route | What it does | Model call |
|---|---|---|
| `GET /v1/meta` | Switched-on features and limits | no |
| `GET /v1/search/vocabulary` | Categories, colours, materials with both labels | no |
| `GET /v1/search/examples` | Sentences known to work, per language | no |
| `GET /v1/reviews/public` | A product's or seller's public reviews | no |
| `GET /health` | Liveness | no |
| `GET /v1/me` | The signed-in user's id | no |
| `GET /v1/catalog/products` | A page of products the caller may buy | no |
| `GET /v1/catalog/products/{id}` | One product | no |
| `GET /v1/catalog/products/{id}/similar` | Real products of the same kind that share facts with it | no |
| `POST /v1/compare` | 2 to 4 products side by side | no |
| `POST /v1/search` | One sentence, Arabic or English, to ranked real products | yes |
| `POST /v1/rooms/plan` | One sentence to a room of real products within budget | yes |
| `POST /v1/rooms/image` | A labelled AI preview of a planned room | yes (image) |

The three model-backed routes are rate limited per user (429 with
`Retry-After`) and cache identical requests. Every response carries an
`X-Request-ID` that matches one line in the server log.

Search and room planning accept `history`, the customer's earlier messages,
so a follow-up refines the previous answer instead of starting over.

The Flutter developer starts at `docs/flutter-integration.md`; request and
response shapes, error codes and a Dart client are in
`docs/flutter-search-contract.md`; `docs/openapi.json` describes every
endpoint and is checked against the code. Deployment: `docs/deploy.md`.

## Setup

Requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/). From the project
root:

```powershell
uv sync
Copy-Item .env.example .env   # then fill in the real values
```

`.env` is git-ignored. Never commit a key, and never give the Gemini key or any
Supabase secret key to the mobile app: the app needs only the Supabase URL, the
publishable key, and this API's address. With no `GEMINI_API_KEY` the service
still starts and only the model-backed routes refuse.

## Run

```powershell
uv run python -m scripts.serve                  # http://127.0.0.1:8000
uv run python -m scripts.serve --host 0.0.0.0   # reachable from a phone on the same Wi-Fi
```

`uv run uvicorn ...` also works on machines without Windows Application
Control; on this project's development machine the `uvicorn.exe` shim is
blocked, which is why `scripts/serve.py` exists. Swagger UI is at `/docs`.

## Check

```powershell
uv run python -m pytest
uv run ruff check .
uv run ruff format --check .
```

The test suite never contacts Supabase or Gemini. CI
(`.github/workflows/ci.yml`) runs the same checks with no secrets.

Scripts under `scripts/live_*` do reach live systems and refuse to run without
`--i-have-authorization`. Several need a signed-in account and an interactive
terminal.

## Status

Built and verified locally and against the live services: search (Arabic and
English), grounded reasons, nearest alternatives, room planning with per-piece
and whole-room budgets and upgrade suggestions, AI room previews, comparison,
similar products.

Before real customers:

1. The row-level security hardening packages (Phases 3.2C and 3.2D, SQL in
   `sql/`) need human security review, then a controlled migration. They have
   **not** been applied.
2. The fake demo catalogue must be removed from the live project with
   `seed/phase-5-fake-catalogue-remove.sql`.
3. Rate limits and caches live in process memory, which is right for one
   server; a second server needs a shared store.
