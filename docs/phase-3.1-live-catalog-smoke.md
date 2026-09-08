# Phase 3.1: secure live catalogue smoke test

The live smoke utility verifies Supabase password authentication, Supabase user
verification, and both authenticated catalogue endpoints without storing or
printing credentials, tokens, identifiers, or product content.

## Prerequisites

The existing local `.env` must define:

```env
SUPABASE_URL=<project HTTPS URL>
SUPABASE_PUBLISHABLE_KEY=<low-privilege publishable key>
SUPABASE_AUTH_TIMEOUT_SECONDS=5.0
```

Do not add an email, password, access token, refresh token, secret key, or
service-role key to `.env`.

Run the utility from an interactive terminal in the project root:

```powershell
uv run python -m scripts.live_catalog_smoke
```

The utility intentionally displays no credential prompts that might echo user
data. Enter the test user's email first and press Enter. After the
`email_input` check passes, enter the password and press Enter; the password is
read with `getpass` and is not displayed.

If stdin or stderr is not attached to a secure terminal, the utility exits before
making an authentication request. It does not fall back to visible password
input.

## Checks performed

The utility validates:

- Supabase password authentication.
- `GET /health`.
- Supabase `/auth/v1/user` through `GET /v1/me`.
- `GET /v1/catalog/products?limit=20&offset=0`.
- Public catalogue shape, pagination bounds, positive stock, and absence of
  internal fields.
- Approved seller, active category, published state, and confirmed enrichment
  using the internal validated upstream models.
- Product detail when at least one eligible product exists.
- The safe 404 response for a random missing product UUID.

When the eligible catalogue is empty, four read-only HEAD requests report only
aggregate counts for published products, approved sellers, active categories,
and positive-stock colors. No database rows are returned or changed.

Output is limited to check names, passed or failed status, HTTP status, returned
counts, and safe error classifications. A failed run exits with status code 1.
