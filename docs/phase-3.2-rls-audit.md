# Phase 3.2A: read-only Supabase security audit

Phase 3.2A inventories the security posture of every table, view, materialized
view, policy, relevant grant, state-protection trigger, and requested helper
function in the exposed `public` schema. It does not change the database or the
FastAPI application and does not propose a hardening migration.

The audit script is [`sql/phase-3.2-rls-audit.sql`](../sql/phase-3.2-rls-audit.sql).
Every statement reads PostgreSQL catalog metadata only. It never selects rows
from an application table and therefore does not retrieve customer, seller,
address, cart, order, payment, offer, review, saved-space, administrative, or
catalogue data.

## How to run the audit

Use the Supabase SQL Editor with an administrative database role that can read
PostgreSQL catalogs. Run one numbered section at a time, in numeric order:

1. Select only the SQL beneath one numbered comment.
2. Run that statement and save its result table with the section number.
3. Confirm the result contains catalog metadata, not application rows.
4. Continue with the next section.

Do not use a client access token to run this audit, do not paste credentials into
the editor, and do not modify any result before retaining the original audit
copy. Do not run a migration based only on an automated `risk_finding`; policy
composition and trigger behavior require review together.

All twelve result tables are designed to be safe to send for migration planning.
They contain schema object names, privilege booleans, policy expressions,
trigger definitions, function properties, and risk labels only. The script does
not emit function bodies. When sharing results, export or copy only the result
grid; omit browser chrome, project URLs, SQL Editor history, and unrelated query
tabs.

## Severity guide

- **Critical**: plausible unauthorized write, sensitive-data exposure, privilege
  escalation, or an unsafe security-definer boundary. Treat as an immediate
  blocker for the hardening design.
- **High**: a client-visible or client-writable boundary lacks an expected guard
  and could expose or alter data. Resolve before expanding client integration.
- **Medium**: defense-in-depth, policy completeness, or availability concern that
  is not by itself proof of unauthorized access.
- **Low**: hygiene or clarity issue with limited direct security impact.
- **Review**: the metadata identifies a boundary that needs human interpretation;
  it is not automatically a vulnerability.

Risk labels produced by the SQL are conservative review aids. PostgreSQL
permissive policies combine with `OR`, restrictive policies combine with `AND`,
and grants, RLS predicates, helper functions, and triggers must be evaluated as
one authorization path.

## Numbered audit sections


### 01. Public tables and RLS state

**Why:** establishes the complete table inventory, including ordinary,
partitioned, and foreign tables, and reports both `ENABLE ROW LEVEL SECURITY` and
`FORCE ROW LEVEL SECURITY` state.

**Safe result:** every application table appears exactly once and has
`rls_enabled = true`. `rls_forced = true` is stronger defense for table owners;
`false` is not automatically client exposure because API roles should not own
tables or have `BYPASSRLS`, but it deserves defense-in-depth review.

**Risk:** RLS disabled is critical or high when Section 02 shows client access.
Missing expected tables is medium because it may indicate an incomplete schema
inventory or a different exposed schema.


### 02. Effective table privileges for API roles

**Why:** reports direct grants, grants inherited from `PUBLIC`, and effective
privileges for `anon`, `authenticated`, and `service_role` across every public
table. Effective checks include role membership and `PUBLIC` access.

**Safe result:** `anon` and `authenticated` possess only the operations required
by an explicitly reviewed RLS policy. Broad `service_role` access is expected,
but that role must never be used by the client application. A missing standard
role is a high configuration issue.

**Risk:** unexpected client writes are critical; unexpected reads of customer,
address, order, payment, administrative, or other private tables are critical.
Unneeded client reads of nonsensitive tables are high or medium depending on the
data domain.


### 03. Complete RLS policy definitions

**Why:** lists every policy with its roles, command, permissive/restrictive mode,
`USING`, and `WITH CHECK` expressions. Metadata review flags call attention to:

- published-product reads without seller-approval enforcement;
- inactive-category reads;
- reads of non-confirmed enrichment assignments;
- product color, image, or enrichment writes without an approved-party guard;
- marketplace-party writes that require separate column or trigger protection.

**Safe result:** policies are operation-specific, narrowly role-scoped, and use
both row ownership and required lifecycle/approval predicates. Public product
reads require a published product and an approved seller; category reads require
active categories; enrichment reads require `party_confirmed`; child writes
require an approved current marketplace party.

**Risk:** any permissive client policy that independently grants broader access
is critical or high. A regex-generated finding is a review signal: an equivalent
guard may be encapsulated in another securely implemented helper function.


### 04. Marketplace-party column write privileges

**Why:** RLS protects rows, not individual columns. This section checks both
table-level and column-effective `INSERT`/`UPDATE` privileges for every
`marketplace_party` column, with explicit attention to `approval_state` and
`state_reason`. The query resolves roles, the table, and columns through
PostgreSQL catalog OIDs and calls `has_table_privilege` and
`has_column_privilege` directly. It does not concatenate or expand mixed ACL
arrays, avoiding the SQL Editor error `ACL arrays must be one-dimensional`.

**Safe result:** `anon` cannot insert or update marketplace parties. The safest
authenticated configuration denies effective writes to both protected state
columns while allowing only the profile fields sellers must manage.

**Risk:** authenticated or anonymous effective access to `approval_state` or
`state_reason` is high and becomes critical if neither Section 03 nor Section 05
proves that unauthorized values are rejected. An insertion policy alone does not
provide column protection.


### 05. Marketplace-party state-protection triggers

**Why:** inventories every non-internal trigger on `marketplace_party`, its
enabled state, trigger function, execution context, definition, and whether the
trigger implementation references both protected state columns. The function
body is inspected only to calculate booleans and is not returned.

**Safe result:** an enabled `BEFORE INSERT OR UPDATE` trigger protects both
`approval_state` and `state_reason`, rejects unauthorized changes, and uses a
secure function boundary. The result label still requests manual logic review
because mentioning a column does not prove correct enforcement.

**Risk:** no enabled trigger candidate covering both protected columns is
critical when clients have effective state-column writes. Disabled or unrelated
triggers do not make the boundary safe merely because they exist. A
security-definer protection function without a controlled search path is
critical and should also be considered during the migration.


### 06. Public views and materialized views

**Why:** identifies all public views, whether regular views use
`security_invoker`, whether clients can select them, and which relations they
reference with each dependency's RLS state. Materialized views are explicitly
identified because their stored rows do not re-evaluate underlying RLS during a
client read.

**Safe result:** client-readable regular views are `security_invoker` and depend
only on intentionally accessible relations. Materialized views containing
protected data are not client-readable, or their access is separately and
explicitly secured.

**Risk:** a client-readable owner-rights view or materialized view over protected
tables is high or critical because it may bypass underlying table RLS. A view
with an incomplete dependency list requires manual review before it is treated
as safe.


### 07. Default privileges

**Why:** reports altered default ACLs that can automatically grant access to
future tables, sequences, functions, types, or schemas. Section 07 now reports
every namespace scope, including `public`, `<all_schemas>`, `storage`, and any
other schema. The earlier `public`/global filter concealed reviewed Supabase
storage defaults and was an audit blind spot. The first focused follow-up also
filtered grantees to PUBLIC, `anon`, and `authenticated`, concealing
`service_role`. Section 07 now has no grantee filter: it reports those four
identities and any unexpected additional grantee.

**Safe result:** every row has an identified owner, namespace, object type,
grantee, privilege, and grant-option state. Application-controlled client
defaults are limited to reviewed scopes. Supabase-managed defaults such as the
exact reviewed `postgres`/`storage` signature are reported visibly and assessed
separately rather than hidden or automatically classified as an application
hardening failure. An empty result means no altered defaults exist, not that
every PostgreSQL built-in default is revoked. Function execution is checked
again for the three helpers in Section 09. For the currently reviewed storage
signature, `anon` and `authenticated` are client roles; `service_role` is a
managed elevated server role. It bypasses RLS and must remain server-only.

**Risk:** an unreviewed namespace, owner, grantee, privilege, object type, or
grant option is high or critical depending on the access. Automatic application
client writes to new tables are critical; automatic reads and broad future
function execution are high. Managed-schema rows require exact-signature review
before they are accepted.


### 08. Helper-function inventory

**Why:** verifies that `is_admin`, `current_marketplace_party_id`, and
`current_party_is_approved` exist in `public`, and shows their overloads,
arguments, result types, language, and object kind.

**Safe result:** all three functions are present with only the expected
signatures and return types. Unexpected overloads require review because policy
resolution or exposed RPC behavior may differ by signature.

**Risk:** a missing helper used by a policy is critical. Unexpected overloads or
wrong result types are high.


### 09. Helper-function security properties

**Why:** reports owner, security-definer/invoker mode, volatility, configured
`search_path`, and effective execute privileges for `PUBLIC` and all three API
roles.

**Safe result:** security-invoker functions execute with least privilege. Any
necessary security-definer function has a fixed minimal `search_path`, a trusted
owner, schema-qualified object references, and execute grants limited to roles
that genuinely require it. `service_role` access alone is not client exposure.

**Risk:** a security-definer function without a fixed `search_path` is critical.
Public execution of a security-definer function is high or critical depending on
its behavior. Excessive client execution of an invoker helper is medium unless it
exposes data through RPC.


### 10. Client grants with RLS disabled

**Why:** produces the direct exception report requested by the audit: any public
table where `anon` or `authenticated` has effective CRUD access while RLS is
disabled. It flags names associated with profiles, customers, addresses, carts,
orders, payments, offers, reviews, saved spaces, or administration.

**Safe result:** zero rows.

**Risk:** client writes with RLS disabled are critical. Client reads of sensitive
domains with RLS disabled are critical; other unintended client reads are high.


### 11. RLS enabled with no policies

**Why:** finds tables placed behind RLS but lacking any policy. PostgreSQL denies
ordinary client access in this state, which is normally safe from disclosure but
may indicate an unfinished authorization design.

**Safe result:** zero rows for tables meant to be client-accessible. Rows are
acceptable for deliberately service-only tables when client denial is intended
and documented.

**Risk:** usually medium for availability or configuration completeness, not an
exposure by itself. Reassess if a privileged or owner-based access path exists.


### 12. `FOR ALL` policies

**Why:** lists policies whose command is `ALL`. One predicate rarely expresses
the correct semantics for select, insert, update, and delete, and broad policies
are harder to review safely.

**Safe result:** zero rows, or a small set of rigorously justified restrictive
administrative policies. Operation-specific policies are preferred.

**Risk:** a permissive `FOR ALL` policy targeting `PUBLIC`, `anon`, or
`authenticated` is high and may be critical when it affects sensitive or
administrative data. A restrictive service-only policy is generally low or
medium.

## Known-risk coverage map

| Risk to verify | Primary sections |
| --- | --- |
| Seller supplies `approval_state` during insertion | 03, 04, 05 |
| Seller updates `approval_state` or `state_reason` | 03, 04, 05 |
| Published products from rejected/suspended sellers are readable | 03 |
| Inactive categories are readable | 03 |
| `ai_proposed` enrichment assignments are readable | 03 |
| Unapproved/suspended sellers modify colors, images, or assignments | 03, 08, 09 |
| Customer, order, payment, admin, or address table lacks RLS | 01, 02, 10, 11 |
| Public view bypasses underlying RLS | 06 |
| Future objects receive unsafe automatic grants | 07 |

## Handoff for migration planning

Return the twelve result tables labeled `01` through `12`. Empty results are
meaningful for Sections 06, 07, 10, 11, and 12 and should be reported explicitly
as empty rather than omitted. Migration design must wait for these real results;
this phase intentionally contains no `ALTER`, `GRANT`, `REVOKE`, policy, trigger,
function, or migration statement.

## Reference basis

The audit interpretation follows PostgreSQL's documentation for
[row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html),
[view execution behavior](https://www.postgresql.org/docs/current/sql-createview.html),
[default privileges](https://www.postgresql.org/docs/current/sql-alterdefaultprivileges.html),
and safely configured
[`SECURITY DEFINER` functions](https://www.postgresql.org/docs/current/sql-createfunction.html#SQL-CREATEFUNCTION-SECURITY).
