# Deploying the API

Status: **not deployed.** The image builds and starts in CI (the `image` job
in `.github/workflows/ci.yml` checks `/health` and `/v1/meta`); choosing a host
and deploying is a decision for the owner.

## What the server needs

One container from the `Dockerfile`, on any host that runs Docker images and
terminates HTTPS: Render, Railway, Fly.io, Google Cloud Run, or a VPS. The
container listens on `$PORT` (default 8000).

Environment variables, set in the host's dashboard, never committed:

| Variable | Required | Notes |
|---|---|---|
| `SUPABASE_URL` | yes | `https://<project>.supabase.co` |
| `SUPABASE_PUBLISHABLE_KEY` | yes | The publishable key. Never a secret key |
| `SUPABASE_AUTH_TIMEOUT_SECONDS` | yes | `5` |
| `SUPABASE_SECRET_KEY` | for carts | Server only; used solely to create a customer's cart. Mark it secret in the host's dashboard |
| `GEMINI_API_KEY` | for AI | Without it the AI features report `false` in `/v1/meta` |
| `IMAGE_REFERENCE_HOSTS` | for previews | Hosts product photos are fetched from |
| `LOG_LEVEL` | no | `INFO` |
| `RATE_LIMIT_*`, `AI_CACHE_TTL_SECONDS` | no | See `.env.example` |

## Run exactly one instance

Rate limits and the AI cache are held in process memory. Two instances would
each allow the full limit and cache separately. Keep the instance count at 1
until they move to a shared store such as Redis. One instance handles a demo
and early customers comfortably; the slow part is the model, not the server.

Avoid tiers that sleep when idle: the first request after a sleep can take
tens of seconds, which reads as a broken app.

## After deploying

1. `GET https://<host>/health` returns `{"status":"ok",…}`.
2. `GET https://<host>/v1/meta` shows `"search": true` if the Gemini key is set.
3. Rebuild the app with `--dart-define=API_BASE_URL=https://<host>`.
4. Run the signed-in smoke test against the deployed server's configuration.

## Local run of the same image

```bash
docker build -t furn-api .
docker run --env-file .env -p 8000:8000 furn-api
```

`.env` is read at run time only; `.dockerignore` keeps it out of the image.
