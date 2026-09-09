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

## Catalogue 502 investigation (2026-09-09)

A real password-authenticated run verified `GET /health` and `GET /v1/me` with
HTTP 200, then received the public HTTP 502 `catalogue_upstream_error` contract
from `GET /v1/catalog/products`. The first staged PostgREST request failed with
HTTP 400 and PostgreSQL code `42703` (`undefined_column`) while selecting only
root `product` fields.

The verified table schema showed that the query's `width`, `height`, `depth`, and
`weight` references do not exist. Their physical columns are `width_cm`,
`height_cm`, `depth_cm`, and `weight_kg`. The production select now uses
PostgREST response aliases:

- `width:width_cm`
- `height:height_cm`
- `depth:depth_cm`
- `weight:weight_kg`

This preserves the existing strict upstream and public models without changing
the database schema or transformation logic. The root lifecycle filter still
uses the verified `lifecycle_state` column, root ordering still uses the verified
`id` column, and `limit`/`offset` remain pagination parameters rather than column
references.

A follow-up live run confirmed every root probe, the complete root query, and
the category, marketplace-party, product-color, and product-image relationships.
The next `enrichment_assignment_relationship` stage failed with HTTP 400 and
PostgreSQL code `42703`.

The assignment table has the composite primary key `(product_id, attribute_id)`
and no independent `id` or `value` column. The failing projection selected both
nonexistent fields and its embedded ordering also referenced `id`. The related
attribute table owns `attribute_kind` and `attribute_value`. The corrected
production embedding is therefore:

```text
enrichment_assignments:product_enrichment_assignment!
product_enrichment_assignment_product_fk(
  attribute_id,
  confirmation_state,
  attribute:product_enrichment_attribute!
  product_enrichment_assignment_attribute_fk(
    id,
    kind:attribute_kind,
    value:attribute_value
  )
)
```

The confirmed-only filter remains
`enrichment_assignments.confirmation_state=eq.party_confirmed`. Embedded
assignment ordering now uses `attribute_id.asc`, never a fabricated assignment
ID. The internal model retains `attribute_id` as a foreign-key field, while the
public attribute value comes from the nested attribute row. `proposed_at` is not
selected or probed because production does not use it.

The production request selects explicit root product columns and these embedded
response aliases:

- `category:category!inner(...)`
- `seller:marketplace_party!inner(...)`
- `colors:product_color!inner(...)`
- `images:product_image(...)`
- `enrichment_assignments:product_enrichment_assignment(...)`
- nested `attribute:product_enrichment_attribute(...)`

Its embedded filters use those response aliases: `seller.approval_state`,
`category.is_active`, `colors.stock_quantity`, and
`enrichment_assignments.confirmation_state`. Root products are restricted to
`lifecycle_state=published`. Root ordering is `id.asc`; colors, images, and
assignments use their respective embedded `.order` parameters. List pagination
uses `limit + 1` and `offset`; product detail uses `id=eq.<uuid>` and `limit=1`.
The strict upstream model expects category and seller objects plus arrays of
colors, images, and assignments, with each assignment containing an attribute
object.

### Safe staged diagnosis

When the public catalogue request returns HTTP 502 with
`catalogue_upstream_error`, the smoke utility now sends cumulative, read-only
PostgREST requests with the same in-memory user bearer token. Every diagnostic
request has `limit=1`, has no offset, and never performs a write.

| Stage | Relationship candidate |
| --- | --- |
| `root_product.<column>` | cumulative physical root columns, added one at a time |
| `root_product` | complete root projection with measurement response aliases |
| `category_relationship` | `category!product_category_fk` |
| `marketplace_party_relationship` | `marketplace_party!product_party_fk` |
| `product_color_relationship` | `product_color!product_color_product_fk` |
| `product_image_relationship` | `product_image!product_image_product_fk` |
| `enrichment_assignment_relationship` | relationship with `product_id` only |
| `enrichment_assignment_attribute_id` | adds assignment `attribute_id` |
| `enrichment_assignment_confirmation_state` | adds assignment `confirmation_state` |
| `enrichment_assignment_filter` | adds the confirmed-only embedded alias filter |
| `enrichment_attribute_relationship` | nested relationship with no selected attribute field |
| `enrichment_attribute_id` | adds nested `id` |
| `enrichment_attribute_attribute_kind` | adds nested `attribute_kind` |
| `enrichment_attribute_attribute_value` | adds nested `attribute_value` |
| `production_filters_and_ordering` | exact current production select, aliases, filters, and ordering |

The root probes now add each selected physical column independently, so another
`42703` identifies the exact candidate in the stage name without exposing the
raw database message. Relationship-isolation stages use explicit constraint
hints without changing parent eligibility. The final stage uses the exact
production query, including the existing `!inner` embeddings where a related row
must exist. This separates a root-column failure, missing or ambiguous
relationship, and production filter or ordering error.

Diagnostic output contains only the stage, passed/failed state, HTTP status,
PostgREST error code when present, and a sanitized relationship candidate or
constraint name. `PGRST100` identifies query parsing, `PGRST108` identifies a
filter on an embedded alias absent from `select`, `PGRST200` identifies a missing
relationship in the schema cache (which can also mean a stale cache), and
`PGRST201` identifies an ambiguous embedding. No raw response body, row data,
UUID, product name, image URL, token, password, or key is printed.

If all staged HTTP requests pass, the utility validates the final body with the
same strict `UpstreamProduct` model used by the gateway and then runs the normal
transformer. A model failure reports only its field path and expected/received
JSON types. A transformer failure reports only the transformation stage as
failed; values are never printed.

## Final live verification

Phase 3.1 is live-verified. A secure interactive run completed successfully with
password authentication, health, current-user authentication, catalogue list,
catalogue eligibility, product detail, and the safe missing-product response all
passing. The catalogue returned four eligible products. No credentials,
identities, tokens, UUIDs, product content, project URLs, or image URLs are
recorded here.
