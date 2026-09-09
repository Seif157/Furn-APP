# Phase 3.2B: Supabase security remediation package

Phase 3.2B turns the confirmed Phase 3.2A findings into reviewable SQL. No SQL
in this package has been run against Supabase, no migration has been applied,
and no application rows or credentials were used. The FastAPI endpoints and
their response contracts are unchanged.

The package consists of:

- [`phase-3.2b-security-hardening.sql`](../sql/phase-3.2b-security-hardening.sql),
  the transactional forward migration draft;
- [`phase-3.2b-security-hardening-verify.sql`](../sql/phase-3.2b-security-hardening-verify.sql),
  numbered, metadata-only post-migration checks;
- [`phase-3.2b-helper-function-definitions.sql`](../sql/phase-3.2b-helper-function-definitions.sql),
  the read-only query required before changing deployed helper functions; and
- [`test_phase_3_2b_security_sql.py`](../tests/test_phase_3_2b_security_sql.py),
  deterministic local regression tests for the SQL package.

## Confirmed findings

The supplied audit evidence confirms:

- **Critical — seller self-approval:** `authenticated` has table-level INSERT
  across `marketplace_party`; the INSERT policy only binds `user_id` to
  `auth.uid()`. A seller can explicitly submit `approval_state` and
  `state_reason`, and no state-protection trigger exists.
- **Critical/high — excessive client grants:** `anon` has direct INSERT, UPDATE,
  DELETE, TRUNCATE, REFERENCES, and TRIGGER privileges on all 34 public tables.
  `authenticated` also has unnecessary structural/maintenance privileges.
- **Critical — financial view boundary:** `order_financial_position` is owned by
  `postgres`, uses owner-rights behavior, reads order/payment relations, and is
  selectable by `anon` and `authenticated`.
- **High — catalogue disclosure:** public category access does not require an
  active category; product access does not require an approved seller; and
  enrichment-assignment access does not require `party_confirmed`.
- **Critical/high — catalogue child writes:** seller write policies on colors,
  images, 3D models, and enrichment assignments do not require an approved
  marketplace party.
- **High — unsafe future defaults:** objects created by `postgres` or
  `supabase_admin` automatically acquire client table/sequence privileges or
  function execution.
- **High — broad helper execution:** the three requested helpers are
  `STABLE SECURITY DEFINER`, use `search_path = public, pg_temp`, and are
  executable by PUBLIC and client roles.

The audit also confirms two positive controls: all 34 public tables have RLS and
at least one policy. None uses FORCE RLS; this is not direct client exposure
because client roles are not expected to own tables or bypass RLS.

## Remediation decisions

### Seller approval

The migration removes table-level INSERT from `authenticated`, then grants only
`user_id`, `business_name`, `business_description`, `logo_url`, and
`coverage_area`. It explicitly denies INSERT on `id`, `approval_state`, and
`state_reason`, leaving the database-generated UUID default intact. It locates
the single audited authenticated INSERT policy by catalog metadata and changes
its `WITH CHECK` to require the authenticated user, `pending` state, and a null
reason. Existing authenticated UPDATE column grants are not broadened or
rewritten. Anonymous marketplace-party writes are removed, while `service_role`
is untouched.

Column grants and RLS are independent controls. RLS alone is not treated as
column protection.

### Financial view

The migration removes PUBLIC/anonymous SELECT, keeps explicit authenticated and
service-role SELECT, and sets `security_invoker = true`. Underlying table grants
and RLS are therefore evaluated as the caller. The verification script checks
both the reloption and effective grants.

### Catalogue policies

New restrictive policies constrain the existing permissive policies:

- categories require `is_active = true` for client-public reads;
- public products require `published`, an approved seller, and an active
  category;
- authenticated sellers receive an explicit permissive path for their own
  draft/unpublished products;
- enrichment assignments require `party_confirmed` for public reads while their
  owning seller may inspect unconfirmed assignments;
- color, image, 3D-model, and assignment reads require a parent product visible
  under the public/owner/admin product rules; and
- INSERT, UPDATE, and DELETE on the four child relations add restrictive
  approved-owner-or-admin checks.

The product policy queries only the seller and category parent relations. It
never queries a product child. Child policies query the parent product, so the
policy dependency direction remains one-way and does not create product/child
RLS recursion. Admin branches remain explicit. `service_role` grants and bypass
behavior are not reduced.

The FastAPI query still applies the Phase 3.1 eligibility filters independently;
RLS is the database security boundary, not a replacement for the API contract.

### Grants and future defaults

The final migration must explicitly list all 34 reviewed public base tables.
For those existing tables it removes anon write/structural/maintenance grants
and authenticated TRUNCATE, REFERENCES, TRIGGER, and MAINTAIN. Audit Sections 02
and 03 must also be used to form an explicit list of tables that do not have an
intentional anonymous read surface; anon SELECT is removed from that list and
retained only for the reviewed public tables. The migration must not use
`ON ALL TABLES IN SCHEMA`, because an unreviewed or extension-owned future
relation could otherwise be changed silently.

For future objects created by both `postgres` and `supabase_admin`, the draft
removes automatic client privileges on tables and sequences and automatic
function execution. A creating migration must grant only what its workflow
needs. Both global and `public`-specific default ACL entries are removed because
a schema-specific REVOKE cannot cancel a grant inherited from global defaults.
The forward migration preflight fails clearly unless its executor can alter
defaults for both owner roles.

## Required preflight blockers

The forward file is intentionally non-deployable in its current review state.
Its executable stop occurs before all DDL/DCL and therefore rolls the transaction
back without changes.

Two metadata inputs are absent from the repository and supplied evidence:

1. **Exact 34-table and anon-read lists.** Run Sections 01, 02, and 03 of
   [`phase-3.2-rls-audit.sql`](../sql/phase-3.2-rls-audit.sql). Copy only the
   `table_name` values for public base/partitioned tables into the first two
   explicit REVOKE statements described at the blocker. Confirm there are
   exactly 34 and review every name. Build the third explicit list from tables
   that lack an intentional anon SELECT policy. Remove the blocking `DO` only
   after both reviews.
2. **Exact helper bodies.** Run
   [`phase-3.2b-helper-function-definitions.sql`](../sql/phase-3.2b-helper-function-definitions.sql).
   The result contains only function metadata/source, not application rows.
   Review the exact three definitions before writing a separate follow-up.

Do not replace either missing input with inferred table names or invented
function behavior.

## Helper-function follow-up

The migration intentionally does not replace `is_admin()`,
`current_marketplace_party_id()`, or `current_party_is_approved()`, and it does
not revoke their existing execution grants. Once exact definitions are
available, a follow-up must:

1. preserve each signature, return type, `STABLE` property, and caller-bound
   authorization semantics;
2. schema-qualify every referenced relation, function, operator-sensitive type,
   and object;
3. use an empty fixed `search_path` only after the fully qualified body is
   proven valid;
4. verify the bodies do not bypass intended RLS or cause recursive policy
   evaluation;
5. prove no anon-facing policy still calls a helper before removing anon/PUBLIC
   EXECUTE; and
6. grant EXECUTE only to `authenticated` and `service_role` where required.

Post-migration Verification Section 07 deliberately remains a failed sign-off
until that follow-up is applied.

## Deferred to Phase 3.2C

The nineteen unrelated `FOR ALL` policies are not rewritten here. Their SELECT,
INSERT, UPDATE, and DELETE semantics affect customer profiles, addresses, carts,
orders, payments, offers, reviews, saved spaces, services, and administrative
workflows. Each requires an operation-by-operation business review. Only the
catalogue child operations needed for the confirmed Phase 3.2B risks receive
new restrictive guards.

FORCE RLS is also not enabled blindly. Table-owner jobs, administrative
functions, and operational workflows must be assessed before changing owner
bypass behavior.

## Safe manual deployment order

1. Take a Supabase-managed backup or point-in-time recovery checkpoint. Also
   export a schema-only snapshot containing grants, policies, views, functions,
   triggers, and default privileges. Verify restoration in a non-production
   environment.
2. Run Phase 3.2A Sections 01, 03, 04, 06, 07, 08, 09, and 12 one section at a
   time. Retain the unmodified metadata result grids.
3. Resolve both blockers above. Have a second reviewer compare the 34 explicit
   names with Section 01 and review the exact helper-body follow-up.
4. Run the completed migration first in a staging database with the same schema.
   Any preflight exception is a hard stop; investigate rather than bypass it.
5. Run every numbered statement in
   `phase-3.2b-security-hardening-verify.sql` separately. Sections 08, 09, and 10
   must be empty. Every returned `check_passed` must be true. Section 05 must
   return all nine named read guards and Section 06 all twelve write guards.
6. Exercise anonymous catalogue reads, an authenticated seller's own drafts,
   admin access, marketplace-party creation, and affected seller write workflows
   in staging. Attempting to provide protected approval fields must fail.
7. Apply the independently reviewed transaction in production during a monitored
   window, then repeat all verification statements.
8. Run the application regression suite and:

   ```powershell
   uv run python -u -m scripts.live_catalog_smoke
   ```

   The live smoke output must remain sanitized and the Phase 3.1 catalogue list,
   eligibility, detail, and safe-not-found checks must pass.

There is no automatic rollback file. Restoring the broad prior grants or the
owner-rights financial view would deliberately recreate confirmed
vulnerabilities. If an operational rollback is required, design a narrow,
time-bounded response from the schema-only backup and incident evidence.

## Verification interpretation

The post-migration file contains metadata only:

1. all public base tables retain RLS;
2. marketplace-party column privileges match the insert/update boundary;
3. seller INSERT policy contains all three checks;
4. the financial view is invoker-rights and not anonymous;
5. all required catalogue read guards exist;
6. all twelve child write guards require approval and ownership/admin;
7. helper security and grants reach the hardened target after the follow-up;
8. dangerous existing client privileges are gone;
9. unsafe client default privileges are gone; and
10. no RLS-enabled table lost all policies.

The policy checks expose full metadata expressions for human review. Regular
expressions are regression aids, not a proof of semantic security.

This design follows PostgreSQL's documented policy composition, where
permissive policies combine with `OR` and restrictive policies combine with
`AND`, and its documented `security_invoker` view behavior. The relevant
references are the PostgreSQL documentation for
[CREATE POLICY](https://www.postgresql.org/docs/current/sql-createpolicy.html),
[CREATE VIEW](https://www.postgresql.org/docs/current/sql-createview.html), and
[ALTER DEFAULT PRIVILEGES](https://www.postgresql.org/docs/current/sql-alterdefaultprivileges.html).
