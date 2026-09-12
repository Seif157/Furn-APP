# Phase 3.2B: Supabase security remediation package

Phase 3.2B converts the live read-only audit evidence into reviewable SQL. No
SQL in this package has been run against Supabase. Another human review and a
live preflight-only confirmation are required; neither migration is approved
for staging or production.

The package contains:

- `sql/phase-3.2b-security-hardening.sql`: core transactional migration.
- `sql/phase-3.2b-security-hardening-preflight.sql`: rollback-scoped copy of the
  core safeguards and exact preflight block, with no migration DDL or DCL.
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

- PostgreSQL version, the exact required roles, and the audited enum inventory.
  The live product enum is `public.product_state`; the preflight also requires
  `public.custom_offering_state` and `public.party_approval_state` and fails if
  the known-absent legacy product enum name resolves.
- Set equality for the exact 34-table inventory using bidirectional `EXCEPT`.
  Array order cannot affect the result. An exception reports exact missing and
  unexpected table names, but no application rows.
- RLS on every reviewed table.
- The eight `marketplace_party` columns, generated ID default, pending approval
  default, the single authenticated INSERT policy, and the exact audited INSERT
  and UPDATE privilege shape.
- The financial view's existence, owner-rights state, postgres owner, and exact
  pre-migration SELECT grantees.
- The exact names, table identities, SELECT command, permissive mode, roles,
  absence of `WITH CHECK`, expected relation/function dependencies, and
  critical predicate ingredients for the six mixed policies being narrowed.
  It rejects helper drift, an unexpected admin dependency, and Boolean
  broadening such as `OR true`.
- The absence of prior `phase32b_` policy artifacts.
- A separate applicable permissive authenticated seller-write policy for every
  child write operation that receives a restrictive guard.
- The exact zero-argument helper signatures, owner, language, volatility,
  security mode, configured search path, and complete deployed bodies. The
  comparison lowercases and removes all whitespace, so harmless formatting
  differences pass while removing `a.is_active` or the approved-state test does
  not.
- The audited postgres-owned default ACLs: public-schema table, sequence, and
  function entries. A global function row was not present and is not required
  by preflight.
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
generate or validate a policy. PostgreSQL reconstructs that text and may change
parentheses, aliases, and qualification, so whitespace-only textual equality is
not a reliable drift check. Preflight instead verifies policy metadata,
dependencies, critical predicate ingredients, and the absence of Boolean
broadening. Each `ALTER POLICY` still explicitly reinstalls its complete
reviewed `USING` predicate while narrowing it to authenticated:

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
unconfirmed assignments. The six retained mixed policies and the four new child
owner-read permissive policies contain no `is_admin()` branch. Existing
`product_select_admin` and `custom_offering_select_admin` policies continue to
provide the audited parent-level administrator reads; Phase 3.2B does not add
administrator reads for draft product colors, images, 3D models, or enrichment
assignments.

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
anon and granted explicitly to authenticated and service roles. Post-migration
checks compare each complete hardened body, not only selected tokens.

## Default privileges and managed-role separation

The live Section 07 audit reported table, sequence, and function default-ACL
rows in `public` for both `postgres` and `supabase_admin`; it reported no global
function row. The core migration changes only the confirmed postgres-owned
scopes:

- Table and sequence defaults are revoked from PUBLIC, anon, and authenticated
  only `IN SCHEMA public`.
- The explicit public-schema function EXECUTE grants are reversed with an
  `IN SCHEMA public` revoke.
- Function EXECUTE defaults are also revoked globally for PUBLIC, anon, and
  authenticated. PostgreSQL grants PUBLIC function EXECUTE from its hard-wired
  global default even when no global `pg_default_acl` row exists; a schema-local
  revoke cannot subtract that global grant.
- Service-role defaults are not changed.

The internal `supabase_admin` defaults are **not fixed by the core migration**.
They are intentionally separated so a lack of managed-role authority cannot
block the critical existing-object fixes.

Run the read-only managed-role diagnostic and have a reviewer confirm every
namespace, object type, grantee, privilege, authority result, and four-scope
effective-privilege result. The optional migration accepts the audited
public-schema table, sequence, and function entries; it does not require a
pre-existing global function row. It applies separate schema-local and global
function revokes and has its own transactional postflight. It must pass a new
human review and live preflight confirmation before staging consideration. Do
not weaken its preflight or combine it with the core migration.

Effective default-ACL calculations deliberately use PostgreSQL's two different
sequence codes: uppercase `S` for `pg_default_acl.defaclobjtype`, and lowercase
`s` as the object-type argument to `pg_catalog.acldefault()`. The core
postflight, Section 11 and its summary, the managed-role diagnostic, and the
optional postflight all keep those values in separate fields.

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
11. Four effective postgres-owned future-object scopes: public tables, public
    sequences, public functions, and global functions. Missing safe catalog rows
    are accepted; schema-local defaults are combined with global defaults.
12. Every reviewed RLS table still has at least one policy.
13. One summary row per verification section with expected, actual, failed, and
    pass counts.

Sections 3 through 6 start from explicit `VALUES` expectations and `LEFT JOIN`
actual metadata. A missing expected policy or view therefore remains visible as
`object_present = false`, `check_passed = false`, and a specific finding code.
The final summary expects four Section 11 results and is safe only when every row
has `failed_count = 0` and `check_passed = true`.

`MAINTAIN` exists only on PostgreSQL 17 and newer. The core migration performs
its effective `MAINTAIN` checks inside a nested version guard using dynamic SQL,
so PostgreSQL 15/16 never parse the unsupported privilege name. The read-only
verification reads `MAINTAIN` from ACL metadata instead of passing it to a
privilege-check function.

## Transactional postflight

Immediately before `COMMIT`, the core migration runs a final fail-closed `DO`
block. It rechecks the exact 34-table/RLS inventory, dangerous effective grants,
the 12-table anonymous allowlist, the marketplace-party grant matrix and seller
INSERT policy, financial-view state, the six retained policies' metadata,
dependencies, and critical predicate ingredients, all expected Phase 3.2B read
policies, child guards and permissive seller paths, complete helper definitions
and grants, anonymous helper
dependencies, and effective postgres defaults across all four scopes. Any
failure raises inside the transaction and rolls back every change. The optional
managed-role migration has an equivalent four-scope default-privilege
postflight. The external verification SQL remains read-only.

## Safe manual review and deployment order

1. Take and validate a restorable backup or Supabase point-in-time recovery
   position. Record recovery instructions outside this repository.
2. Run the helper diagnostic and managed-role default diagnostic one section at
   a time. They return metadata only. Run the dedicated core preflight-only
   artifact separately; it always ends in `ROLLBACK`. Confirm all live
   preflight inputs before either migration is considered further.
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
FastAPI contract, or README is changed by this review package. Another human
review and live preflight confirmation remain mandatory.
