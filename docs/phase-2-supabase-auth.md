# Phase 2: Supabase authentication boundary

Phase 2 verifies Supabase user access tokens before FastAPI trusts a user ID. It
does not connect Flutter, query application tables, or add recommendation and AI
behavior.

## Required environment variables

Copy the safe template to a local file:

```powershell
Copy-Item .env.example .env
```

Set these values in `.env`:

```env
SUPABASE_URL=https://ijnqccqyqcxqjgglqwzg.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_replace_me
SUPABASE_AUTH_TIMEOUT_SECONDS=5
```

Replace `sb_publishable_replace_me` with the project's real Supabase publishable
key. Obtain it from the Supabase project settings and keep it only in the local
`.env` or the backend deployment environment. The committed `.env.example` must
remain a placeholder. The `.env` file is ignored by Git.

Configuration is rejected at startup when required values are missing or
malformed. `SUPABASE_URL` must use HTTPS, and the authentication timeout must be
greater than zero and no more than 30 seconds.

## Run the backend

Synchronize dependencies and start the development server:

```powershell
uv sync
uv run uvicorn app.main:app --reload
```

The backend reads `.env` from the project root during local development.

## How authentication works

A future Flutter client will authenticate with Supabase and send its user access
token to FastAPI using the standard header:

```http
Authorization: Bearer <supabase-access-token>
```

FastAPI forwards that token and the backend publishable key to:

```http
GET https://ijnqccqyqcxqjgglqwzg.supabase.co/auth/v1/user
```

Only the user UUID returned by Supabase is trusted. FastAPI does not accept user
IDs, profile IDs, roles, or authorization state from request bodies or query
parameters, and it does not decode unverified JWT claims.

## Test `GET /v1/me`

After starting the backend, place a real user access token in a temporary shell
environment variable and make the request:

```powershell
$headers = @{ Authorization = "Bearer $env:SUPABASE_ACCESS_TOKEN" }
Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/me" -Headers $headers
```

Successful response (`200 OK`):

```json
{
  "user_id": "00000000-0000-0000-0000-000000000000",
  "authenticated": true
}
```

Missing or malformed authorization (`401 Unauthorized`, with
`WWW-Authenticate: Bearer`):

```json
{
  "detail": {
    "code": "authentication_required",
    "message": "Authentication is required."
  }
}
```

Invalid or expired token (`401 Unauthorized`, with
`WWW-Authenticate: Bearer`):

```json
{
  "detail": {
    "code": "invalid_access_token",
    "message": "The access token is invalid or expired."
  }
}
```

Supabase timeout or availability failure (`503 Service Unavailable`):

```json
{
  "detail": {
    "code": "authentication_service_unavailable",
    "message": "Authentication is temporarily unavailable."
  }
}
```

Upstream error bodies, access tokens, Supabase metadata, and provider data are
never included in API responses.

## Key safety and deferred Flutter work

Never put a Supabase secret key or service-role key in Flutter. A mobile package
can be inspected by its users, so embedded keys can be recovered. Those privileged
keys can bypass Row Level Security and would give every app installation backend
authority. Flutter will eventually use its normal public client configuration and
send only the signed-in user's short-lived access token to this API.

The real Flutter-to-FastAPI connection is intentionally deferred to a later phase.
