# Phase 3: authenticated read-only catalogue

Phase 3 adds a read-only FastAPI boundary for retrieving furniture that is
eligible for future recommendations. It does not implement recommendations,
embeddings, image generation, Flutter integration, writes, or migrations.

## Security flow

Both catalogue endpoints require the same Supabase bearer authentication used by
`GET /v1/me`:

```http
Authorization: Bearer <supabase-access-token>
```

FastAPI first verifies the token through Supabase Auth. The verified UUID and the
same access token are retained in a private immutable request context. The token
is excluded from model serialization and representation. The catalogue gateway
then sends these headers to Supabase PostgREST:

```http
apikey: <SUPABASE_PUBLISHABLE_KEY>
Authorization: Bearer <supabase-access-token>
```

Forwarding the user token keeps Supabase Row Level Security active. The gateway
never uses a service-role key, secret key, or unverified identity supplied by the
client. Tokens, keys, configuration values, upstream error bodies, and Supabase
diagnostics are not returned or logged by the application.

## Catalogue eligibility

The PostgREST query explicitly requires every returned product to satisfy:

- `product.lifecycle_state = 'published'`
- `marketplace_party.approval_state = 'approved'`
- `category.is_active = true`
- at least one `product_color.stock_quantity > 0`

Category, seller, and color relationships use inner embedding so their filters
remove ineligible parent products. Only in-stock colors are returned. Enrichment
assignments are filtered to `confirmation_state = 'party_confirmed'` without
requiring a product to have an enrichment assignment. The backend defensively
rechecks all eligibility conditions and removes any `ai_proposed` assignment even
if an upstream response violates the query contract.

The implementation uses one nested request, explicit selected columns, and no
`select=*`. Products are ordered by UUID. Colors are ordered by display order and
UUID; images place primary records first, then use display order and UUID; and
confirmed attributes are ordered by kind, canonical value, and assignment UUID.

## Endpoints

### List products

```http
GET /v1/catalog/products?limit=20&offset=0
```

- `limit`: defaults to `20`; allowed range is `1` through `50`.
- `offset`: defaults to `0`; minimum is `0`.
- The gateway requests `limit + 1` records to calculate `has_more`.

Response shape:

```json
{
  "items": [],
  "limit": 20,
  "offset": 0,
  "has_more": false
}
```

Each product contains only:

- `id`, `name`, `description`
- `price`, `discount_price`
- `width`, `height`, `depth`, `weight`
- `materials`
- `category` with `id` and `name`
- `seller` with `id` and `business_name`
- in-stock `colors` with `id`, `value`, `stock_quantity`, and `display_order`
- `images` with `id`, `url`, `is_primary`, `display_order`, and `color_id`
- confirmed `enrichment_attributes` with `kind` and `value`

UUIDs are JSON strings. Decimal monetary and measurement values are serialized as
JSON strings so their precision is preserved.

### Product detail

```http
GET /v1/catalog/products/20000000-0000-4000-8000-000000000000
```

The response uses the same product shape as a list item. An absent or ineligible
product returns:

```json
{
  "detail": {
    "code": "product_not_found",
    "message": "The product was not found."
  }
}
```

The identical 404 response prevents callers from learning why a product was
excluded.

## Safe upstream errors

PostgREST client errors, malformed JSON, malformed UUIDs, invalid decimals, and
invalid nested data return `502 Bad Gateway`:

```json
{
  "detail": {
    "code": "catalogue_upstream_error",
    "message": "The catalogue could not be loaded."
  }
}
```

Timeouts, connection failures, rate limiting, and PostgREST 5xx responses return
`503 Service Unavailable`:

```json
{
  "detail": {
    "code": "catalogue_service_unavailable",
    "message": "The catalogue is temporarily unavailable."
  }
}
```

Phase 2 authentication errors remain unchanged.

## Run and test

Configure the required Phase 2 variables in `.env` as documented in
`docs/phase-2-supabase-auth.md`, then start the backend with:

```powershell
uv sync
uv run uvicorn app.main:app --reload
```

Run all deterministic tests and style checks with:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Automated tests use HTTPX mock transports and never contact Supabase.

## Relationship verification note

The nested query uses the table relationship names `category`,
`marketplace_party`, `product_color`, `product_image`,
`product_enrichment_assignment`, and `product_enrichment_attribute`. No dedicated
test user access token was available during Phase 3, so those deployed PostgREST
relationship names and the assumed enrichment shape—assignment `value` plus a
related attribute `kind`—were not verified against the live schema. If Supabase
reports an ambiguous relationship, add its foreign-key constraint hint in the
single `CATALOG_SELECT` definition and keep the public response unchanged.
