# Phase 3.2B: Supabase security remediation package

Phase 3.2B converts the live read-only audit evidence into reviewable SQL. No
SQL in this package has been run against Supabase. The core migration is ready
for another human review, not yet approved for staging or production.

The package contains:

- `sql/phase-3.2b-security-hardening.sql`: core transactional migration.
- `sql/phase-3.2b-security-hardening-verify.sql`: read-only post-migration
  verification, including a final section summary.
- `sql/phase-3.2b-helper-function-definitions.sql`: read-only helper diagnostic.
- `sql/phase-3.2b-supabase-admin-default-privileges-diagnostic.sql`: read-only
  managed-role default-ACL and authority diagnostic.
- `sql/phase-3.2b-supabase-admin-default-privileges-optional.sql`: isolated,
  optional managed-role migration. It must not be bundled with the core change.

## Confirmed findings

- **Critical - seller self-approval:** `authenticated` had table-level INSERT
  on all eight `marketplace_party` columns. Its only applicable INSERT policy
  checked `user_id = auth.uid()` but did not force pending approval or a null
  state reason.
- **Critical - broad direct writes:** `anon` had direct write and dangerous
  maintenance privileges across all 34 public base tables.
- **Critical - financial view:** `order_financial_position` was postgres-owned,
  used owner-rights behavior, and was selectable by anonymous callers.
- **High - catalogue exposure:** public category, product, enrichment, and child
  policies did not collectively enforce all active, published, approved-seller,
  and party-confirmed conditions.
- **High - mixed policies:** anonymous and seller-owner access shared policies
  that called security-definer helpers.
- **High - helper hardening:** the three audited security-definer helpers used
  `search_path = public, pg_temp` and were executable by PUBLIC and anon.
- **High - future defaults:** postgres and the managed `supabase_admin` role had
  client-facing default privileges. Their scopes and operational ownership must
  be handled separately.

All 34 public base tables have RLS enabled and at least one policy. None has
FORCE RLS. Nineteen unrelated policies use `FOR ALL`; their operation-specific
semantics remain deferred to Phase 3.2C.

## Fail-closed preflight

The core migration performs every preflight check before its first DDL or DCL
statement. It verifies:

- PostgreSQL version and the exact required roles.
- Set equality for the exact 34-table inventory using bidirectional `EXCEPT`.
  Array order cannot affect the result. An exception reports exact missing and
  unexpected table names, but no application rows.
- RLS on every reviewed table.
- The eight `marketplace_party` columns, generated ID default, pending approval
  default, the single authenticated INSERT policy, and the exact audited INSERT
  and UPDATE privilege shape.
- The financial view's existence, owner-rights state, postgres owner, and exact
  pre-migration SELECT grantees.
- The exact names, SELECT command, permissive mode, roles, and required predicate
  shape for the six mixed policies being narrowed.
- The absence of prior `phase32b_` policy artifacts.
- A separate applicable permissive authenticated seller-write policy for every
  child write operation that receives a restrictive guard.
- The exact zero-argument helper signatures, owner, language, volatility,
  security mode, configured search path, and normalized deployed bodies.
- Only the postgres-owned default-ACL scopes changed by the core migration:
  public-schema tables and sequences, and global functions.
- The executor's authority for postgres-owned operations. Core deployment does
  not require or assume authority over `supabase_admin`.

Any drift aborts before changes. The migration is deliberately one transaction.

## Operational timeouts

Immediately after `BEGIN`, the core and optional migrations set transaction-local
safeguards:

```sql
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '5min';
SET LOCAL idle_in_transaction_session_timeout = '5min';
```

Any timeout rolls back the transaction. Investigate lock contention, statement
behavior, deployment authority, or schema drift before retrying. Never bypass a
timeout by directly increasing it in production.

## Exact existing-object grants

The core migration uses explicit reviewed table lists; it does not use an
uncontrolled `ON ALL TABLES` operation.

For all 34 tables it removes INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES,
TRIGGER, and, on PostgreSQL 17 or newer, MAINTAIN from PUBLIC and anon. It removes
TRUNCATE, REFERENCES, TRIGGER, and MAINTAIN from authenticated. Service-role
privileges are not changed.

PUBLIC and anon SELECT are removed from the inventory before SELECT is granted
back explicitly to this 12-table anonymous allowlist:

- `category`, `custom_offering`, `marketplace_party`, `party_capability`
- `product`, `product_3d_model`, `product_color`
- `product_enrichment_assignment`, `product_enrichment_attribute`
- `product_image`, `review`, `service_type`

The other 22 tables remain private to anonymous callers.

## Marketplace-party writes

The migration revokes authenticated table-level INSERT and UPDATE, then revokes
column-level INSERT and UPDATE over all eight reviewed columns before regranting.

Authenticated INSERT is granted only on:

- `user_id`
- `business_name`
- `business_description`
- `logo_url`
- `coverage_area`

Authenticated UPDATE is granted only on:

- `business_name`
- `business_description`
- `logo_url`
- `coverage_area`

INSERT remains denied on `id`, `approval_state`, and `state_reason`. UPDATE
remains denied on `id`, `user_id`, `approval_state`, and `state_reason`. The
single seller INSERT policy is retained by name discovered in preflight and its
`WITH CHECK` is hardened to require the caller's user ID, pending approval, and
a null reason. PUBLIC and anon receive no marketplace-party writes. Service-role
access is preserved.

## Financial view

`public.order_financial_position` loses PUBLIC and anon SELECT, retains explicit
SELECT for authenticated and service roles, and becomes `security_invoker`.
Authenticated access therefore also depends on grants and RLS for
`purchase_order`, `order_line_item`, and `payment`.

## Explicit public and owner policy split

The migration does not use regular-expression replacement of `pg_get_expr()` to
generate a policy. Preflight checks exactly these audited mixed policies and the
migration explicitly narrows only them to authenticated:

- `custom_offering.custom_offering_select_published_or_own`
- `product.product_select_published_or_own`
- `product_color.product_color_select`
- `product_image.product_image_select`
- `product_3d_model.product_3d_model_select`
- `product_enrichment_assignment.product_enrichment_assignment_select`

The custom-offering anonymous policy and its restrictive defense-in-depth guard
both use this reviewed predicate:

```sql
publication_state = 'published'::public.custom_offering_state
```

No anonymous policy calls `is_admin()`, `current_marketplace_party_id()`, or
`current_party_is_approved()`. A schema-wide check aborts before helper EXECUTE
is revoked if any PUBLIC- or anon-facing policy still calls one.

Public products require published lifecycle state, an approved seller, and an
active category. Product child reads follow the parent product without making a
product policy query its children, avoiding product/child RLS recursion. Public
enrichment assignments additionally require `party_confirmed`.

Authenticated sellers retain owner read policies for their own drafts and
unconfirmed assignments. Existing read-side admin behavior is preserved.

## Child-write semantics

Each INSERT, UPDATE, and DELETE path on product colors, images, 3D models, and
enrichment assignments receives a restrictive approved-owner guard. The guard
requires both `current_party_is_approved()` and ownership through
`current_marketplace_party_id()`.

A restrictive policy does not grant access; it only limits rows admitted by an
applicable permissive policy. The preflight and verification therefore confirm
that a separate permissive authenticated seller-write policy remains available
for every guarded operation.

The guards do not contain `OR is_admin()` and do not claim to grant admin write
access. Phase 3.2B preserves the audited behavior: approved owning sellers can
write when their existing permissive policy allows it, and `service_role`
continues to bypass RLS. New admin write authorization requires a separately
confirmed business requirement and is not introduced here.

## Helper functions

The migration preserves the three exact caller-bound behaviors while changing
their bodies to use an empty search path and fully qualified references:

- `public.is_admin()`
- `public.current_marketplace_party_id()`
- `public.current_party_is_approved()`

Names, zero-argument signatures, return types, postgres owner, `LANGUAGE sql`,
`STABLE`, and `SECURITY DEFINER` remain unchanged. The approved comparison uses
`'approved'::public.party_approval_state`. EXECUTE is revoked from PUBLIC and
anon and granted explicitly to authenticated and service roles.

## Default privileges and managed-role separation

The core migration changes only confirmed postgres-owned scopes:

- Table and sequence defaults are revoked from PUBLIC, anon, and authenticated
  only `IN SCHEMA public`.
- Function EXECUTE defaults are revoked globally for PUBLIC, anon, and
  authenticated. PostgreSQL grants PUBLIC function EXECUTE implicitly at the
  global level; a schema-local default revoke cannot subtract that global grant.
- Service-role defaults are not changed.

The internal `supabase_admin` defaults are **not fixed by the core migration**.
They are intentionally separated so a lack of managed-role authority cannot
block the critical existing-object fixes.

Run the read-only managed-role diagnostic and have a reviewer confirm every
namespace, object type, grantee, privilege, and authority result. The optional
migration only accepts public-schema table/sequence defaults and global function
defaults. It aborts on any other client-facing scope. It must pass in staging
under the intended deployment role before separate production consideration.
Do not weaken its preflight or combine it with the core migration.

This follows PostgreSQL default-privilege semantics and Supabase's function
guidance:

- [PostgreSQL `ALTER DEFAULT PRIVILEGES`](https://www.postgresql.org/docs/current/sql-alterdefaultprivileges.html)
- [PostgreSQL privileges](https://www.postgresql.org/docs/current/ddl-priv.html)
- [Supabase database functions](https://supabase.com/docs/guides/database/functions)
- [Supabase API security](https://supabase.com/docs/guides/api/securing-your-api)

## Verification

Run `sql/phase-3.2b-security-hardening-verify.sql` one numbered SELECT at a time.
It reads metadata only.

1. Exact public-table RLS state.
2. Complete marketplace-party table/column INSERT and UPDATE matrix for anon,
   authenticated, and service roles.
3. Exactly one hardened marketplace-party INSERT policy.
4. Financial-view presence, owner, security mode, and exact SELECT grants.
5. Thirty expected original, public, owner, and restrictive read policies.
6. Twelve restrictive child-write guards plus their independent permissive
   seller-write paths.
7. Three hardened helper functions and effective EXECUTE grants.
8. No anonymous policy dependency on restricted helpers.
9. No dangerous PUBLIC, anon, or authenticated existing-object grants.
10. Exact 34-table inventory and 12-table anon SELECT classification.
11. Three exact postgres-owned default-ACL scopes changed by the core migration.
12. Every reviewed RLS table still has at least one policy.
13. One summary row per verification section with expected, actual, failed, and
    pass counts.

Sections 3 through 6 start from explicit `VALUES` expectations and `LEFT JOIN`
actual metadata. A missing expected policy or view therefore remains visible as
`object_present = false`, `check_passed = false`, and a specific finding code.
The final summary is safe only when every row has `failed_count = 0` and
`check_passed = true`.

## Safe manual review and deployment order

1. Take and validate a restorable backup or Supabase point-in-time recovery
   position. Record recovery instructions outside this repository.
2. Run the helper diagnostic and managed-role default diagnostic one section at
   a time. They return metadata only.
3. Have a second reviewer compare the exact inventory, grants, policy names,
   predicates, helper bodies, view ACL, default scopes, and timeout settings with
   the live audit evidence.
4. In an isolated staging clone, restore-test the backup before changing SQL.
5. Run the core migration manually in staging using the intended deployment
   role. A preflight error or timeout means the entire transaction rolls back.
6. Run all 13 verification sections. Require all summary rows to pass.
7. Test anonymous catalogue reads, seller drafts, seller writes, service-role
   workflows, and financial-view access. Run:

   ```powershell
   uv run python -u -m scripts.live_catalog_smoke
   ```

8. Review the managed-role diagnostic separately. Only if its exact output and
   deployment authority match the optional migration should that migration be
   tested as a distinct staging change.
9. Obtain explicit approval before either production deployment. Monitor locks
   and API errors, rerun verification, and retain the recovery position.

## Deferred to Phase 3.2C

- Operation-by-operation review of the remaining nineteen `FOR ALL` policies.
- FORCE RLS, pending owner-job and administrative workflow validation.
- New administrator write permissions for catalogue children.
- Any managed-role default scope not exactly accepted by the separate optional
  preflight.

No application data, schema migration, seed data, authentication behavior,
FastAPI contract, or README is changed by this review package.
