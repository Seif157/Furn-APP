# Phase 3.2B live RLS acceptance

Status: **passed on the reviewed fake-data testing branch**. Every staged check
passed after the Phase 3.2B core migration and verification completed
successfully. This evidence is limited to that testing branch and is not
approval for staging or production.

## Purpose and safety boundary

`scripts/live_rls_acceptance.py` performs a staged, low-privilege acceptance
check of the Phase 3.2B RLS behavior. It authenticates only the designated
fake-data customer and seller fixtures, using the configured publishable/anon
key and passwords entered through a secure terminal.

The runner:

- refuses redirected or otherwise non-interactive input;
- requires the exact confirmation `FAKE-DATA TESTING BRANCH` before accepting a
  password;
- refuses known service-role, secret-key, and JWT-secret environment variables;
- keeps passwords and access/refresh tokens in secret-bearing in-memory objects;
- disables HTTP client logging and emits only fixed check names, actor classes,
  pass/fail state, HTTP status codes, and safe error classifications;
- never emits UUIDs, response bodies, row values, credentials, tokens, keys,
  product data, or target URLs;
- uses GET for PostgREST reads and read-only helper RPC calls;
- uses PATCH only for exact-value no-op probes with
  `return=representation,count=exact`;
- contains no database POST, DELETE, SQL, mutating RPC, service-role request, or
  fixture creation/removal path. The sole POST is the password-authentication
  request required by Supabase Auth.

The utility discovers and validates every identity, ownership relationship,
child record, and exact comparison value before the first PATCH. A missing or
ambiguous prerequisite stops the run with `fixture_precondition_not_met`.

## Exact acceptance matrix

| Actor | Check | Expected result |
| --- | --- | --- |
| Anonymous | Read all 12 intentional anonymous catalogue tables | GET succeeds; zero or one bounded row is accepted |
| Anonymous | Read the other 22 public tables and `order_financial_position` | Permission denial or an empty RLS result; any returned row fails |
| Anonymous | Call `is_admin`, `current_marketplace_party_id`, and `current_party_is_approved` | 401 or 403 |
| Customer | Read an eligible published catalogue product | At least one row through the production-equivalent eligibility predicates |
| Customer | `is_admin()` | `false` |
| Customer | `current_marketplace_party_id()` | `null` |
| Customer | `current_party_is_approved()` | `false` |
| Customer | No-op PATCH of the sampled seller party profile | 401/403 or exactly zero affected rows |
| Customer | No-op PATCH of the sampled seller product | 401/403 or exactly zero affected rows |
| Customer | Read `order_financial_position` | Every returned order identifier is in the customer's directly readable `purchase_order` scope |
| Approved seller | Resolve own marketplace party | Exactly one matching party, retained only as a secret in memory |
| Approved seller | `is_admin()` | `false` |
| Approved seller | `current_party_is_approved()` | `true` |
| Approved seller | No-op PATCH of own `business_description` | Exactly one represented row and unchanged before/after business values |
| Approved seller | No-op PATCH of own `approval_state` | 401/403 or exactly zero affected rows |
| Approved seller | No-op PATCH of own `state_reason` | 401/403 or exactly zero affected rows |
| Approved seller | No-op PATCH of own product `description` | Exactly one represented row and unchanged before/after business values |
| Approved seller | No-op PATCH of another seller's product `description` | 401/403 or exactly zero affected rows |
| Approved seller | No-op PATCH of own `product_color.color_value` | Exactly one represented row and unchanged before/after business values |
| Approved seller | No-op PATCH of another seller's `product_color.color_value` | 401/403 or exactly zero affected rows |
| Approved seller | Read `order_financial_position` | Every returned order identifier is in the seller's directly readable `purchase_order` scope |

The 12-table anonymous catalogue allowlist is `category`, `custom_offering`,
`marketplace_party`, `party_capability`, `product`, `product_3d_model`,
`product_color`, `product_enrichment_assignment`,
`product_enrichment_attribute`, `product_image`, `review`, and `service_type`.
The enrichment-assignment read correctly uses its composite key
`product_id,attribute_id`; it does not assume an `id` column.

## No-op PATCH proof

Each probe reads the complete bounded business snapshot immediately before the
PATCH. The request body contains one column with its exact current JSON value.
An allowed write must return exactly one row and an affected count of one. A
denied write must return 401/403 or HTTP 200 with an empty representation and an
affected count of zero. A represented row from a forbidden write is a failure.

The same complete snapshot is read immediately after every PATCH attempt,
including timeout, malformed-response, and unexpected-permission paths. Any
value difference, missing row, extra row, malformed body, or failed cleanup read
fails closed. Because the submitted value is already current, no restoration
write is needed or permitted.

## Required fake fixtures

All of these fixtures must already exist. The runner will not create them:

- at least one product satisfying the public catalogue eligibility rules;
- one approved marketplace party owned by the designated fake-data seller and
  readable by the designated customer under the intended public policy;
- one published seller-owned product with a positive-stock `product_color`, both
  also readable by the customer for exact-value denial probes;
- one published product owned by a different approved seller with a
  positive-stock `product_color`, both readable by the customer;
- for both customer and seller, at least one and at most 100 directly readable
  `purchase_order` rows and at least one corresponding
  `order_financial_position` row;
- a financial-view order-reference field named `purchase_order_id`, `order_id`,
  or `id` whose UUIDs are a subset of the actor's directly readable order IDs.

If either financial role has no suitable order/view fixture, if more than 100
rows would need comparison, or if the order-reference shape is not recognizable,
the utility reports `fixture_precondition_not_met`. Do not add data merely to
make this acceptance run pass; review the fake fixture set first.

## Human-run procedure

1. Confirm the configured target is the fake-data testing branch. Do not run
   against staging or production.
2. Ensure only `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, and
   `SUPABASE_AUTH_TIMEOUT_SECONDS` provide Supabase configuration. Do not expose
   a service-role or secret key to this process.
3. Start the utility from an interactive terminal:

   ```text
   uv run python -u -m scripts.live_rls_acceptance
   ```

4. Enter the exact testing-branch confirmation when prompted, then enter the
   customer and seller passwords through the hidden prompts.
5. Retain only the redacted check output. Stop and review any failed check; do
   not paste credentials, upstream bodies, row data, identifiers, or the target
   URL into an issue or review record.

## Local verification scope

`tests/test_live_rls_acceptance.py` uses deterministic HTTPX transports. It
covers TTY and branch confirmation, credential/token redaction, forbidden
elevated configuration, fixed ownership distinctions, approval-column denial,
zero-row denials, forbidden-write detection, before/after equality, network and
malformed responses, cleanup reads, fixture insufficiency, and the absence of
PostgREST POST/DELETE or mutating RPC/SQL paths.

Local mocks prove runner behavior only. The later human-operated run passed on
the reviewed fake-data testing branch. That result does not establish that
service-role access is RLS-protected; the service role is elevated, bypasses
RLS, and must remain server-only. Phase 3.2C and any deployment decision still
require human review.
