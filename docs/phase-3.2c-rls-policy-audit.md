# Phase 3.2C RLS policy audit

Status: **audit package ready for human review**. This phase contains no
remediation migration and performs no database change. The Phase 3.2B core and
optional `supabase_admin` SQL packages remain unchanged.

## Scope and safety

`sql/phase-3.2c-rls-policy-audit.sql` contains 13 independently runnable,
SELECT-only PostgreSQL metadata statements. They inspect system catalogs and do
not select application rows. The audit dynamically discovers the current public
base tables and policies; it does not carry forward the historical `FOR ALL`
policy count.

Run one numbered statement at a time in the Supabase SQL Editor. Review and
export that result before moving to the next statement. Do not run the whole
file as a remediation script, and do not add transaction, procedural, dynamic,
or mutation statements. This package was not run against Supabase while being
created.

Metadata returned by these queries is safe to send for policy-review planning:

- schema, table, view, policy, role, function, type, and constraint names;
- owner, RLS, FORCE RLS, role-inheritance, ACL, and function-security metadata;
- complete policy `USING` and `WITH CHECK` expressions;
- query-produced risk classifications, counts, and pass/fail summaries.

Do not supplement the result with application rows, customer or seller
identifiers, order or payment contents, credentials, tokens, project addresses,
or raw API responses.

## Numbered SQL sections

1. **Public base-table inventory** — returns the exact current ordinary and
   partitioned table set, owners, RLS state, FORCE state, and relation kind. A
   missing expected table, RLS-disabled table, or unexpected relation kind is a
   review finding; the query itself does not assume a table count.
2. **Complete policy inventory** — returns every current public policy without
   role, command, name, or expression filtering. Both complete predicate fields
   remain visible.
3. **Dynamic `FOR ALL` inventory** — lists current `FOR ALL` policies and always
   emits a summary row. If none exist, the summary explicitly says
   `no_current_for_all_policies`.
4. **`FOR ALL` effective operations** — expands each policy into SELECT, INSERT,
   UPDATE, and DELETE, then shows raw and effective predicates and structural
   predicate coverage.
5. **Operation predicate review** — expands all policies by effective operation
   and emits conservative signals for missing predicates, literal true,
   tautologies, ownership-only insertion checks, state-transition gaps,
   approval manipulation, cross-principal access, unexpected roles/admin
   branches, and overlapping permissive policies. It returns every expanded
   policy; a filter cannot conceal a policy expression.
6. **Policy dependencies** — reports relation, function, enum/type, column, and
   other recorded `pg_depend` entries for every policy. It identifies recorded
   normal self-relation dependencies and SECURITY DEFINER function metadata.
7. **Effective policy/grant matrix** — covers PUBLIC, `anon`, `authenticated`,
   and `service_role` across SELECT, INSERT, UPDATE, DELETE, TRUNCATE,
   REFERENCES, TRIGGER, and version-aware MAINTAIN. ACL and inherited-role paths
   are evaluated without passing MAINTAIN to a privilege-check function. The
   sequence-default metadata calculation maps `pg_default_acl.defaclobjtype`
   uppercase `S` to lowercase `s` for `acldefault()`.
8. **Role inheritance** — follows inherited membership paths from the three real
   API roles and flags any client path to a superuser, BYPASSRLS role, or the
   elevated server-only `service_role`.
9. **FORCE RLS suitability** — returns one row per table with owner-bypass
   materiality, recorded SECURITY DEFINER dependencies, service-role access,
   the missing background-job evidence, and a candidate classification.
10. **Financial and administrative review** — separately inventories the nine
    named sensitive tables and `order_financial_position`, including owner,
    policies, direct ACL metadata, RLS/FORCE state, and view invoker behavior.
11. **Parent-child directions** — inventories every public foreign key and both
    directions of recorded policy dependencies, with mutual and self-reference
    review flags.
12. **Prioritized findings** — combines structural findings and clearly labeled
    static hypotheses into the requested severity/decision table. A
    `phase32c_none` row explicitly represents an empty finding set.
13. **Audit-completeness summary** — reports expected checks, actual checks,
    failed checks, and pass/fail status for Sections 1–12. Passing this summary
    means the audit coverage is complete; it does not mean the policies are
    secure or approved.

## `FOR ALL` semantics

A PostgreSQL `FOR ALL` policy applies to all four row operations. Its `USING`
predicate controls rows visible to SELECT and rows eligible for UPDATE or
DELETE. Its `WITH CHECK` predicate controls new rows for INSERT and resulting
rows for UPDATE. For `ALL` and `UPDATE`, PostgreSQL uses the `USING` expression
as the implicit `WITH CHECK` when an explicit check is absent.

Permissive policies applicable to the same role and operation are combined with
Boolean OR. Restrictive policies are combined with Boolean AND around the
permissive result. Consequently, reviewing one policy in isolation cannot prove
the effective authorization result. Section 5 flags overlapping permissive
paths but does not claim that overlap is automatically unsafe.

## Proven findings versus hypotheses

The audit distinguishes these evidence classes:

- `proven_structural_finding`: directly established by catalog state, such as a
  missing required operation predicate, RLS disabled on a public base table, an
  unexpected assigned role, or a non-invoker financial view;
- `static_risk_signal`: syntax-based evidence such as a simple tautology or an
  administrator branch outside an explicitly named administrator policy;
- `layered_control_hypothesis`: a policy-layer gap that may be safely constrained
  by independently verified column grants or triggers;
- `business_semantics_hypothesis`: a possible owner, state transition,
  cross-principal, or overlapping-policy issue that requires workflow evidence.

Dependency presence proves only that PostgreSQL recorded a catalog dependency.
It does not prove Boolean correctness, and procedural or dynamically resolved
function bodies may not expose every business dependency through `pg_depend`.

## FORCE RLS tradeoffs

Without FORCE RLS, a table owner normally bypasses row policies. FORCE RLS can
reduce that owner-bypass path, but it can also break migrations, background
jobs, SECURITY DEFINER helpers, administrative workflows, billing settlement,
and operational repair procedures that intentionally run as an owner.
`service_role` separately has BYPASSRLS and remains an elevated server-only
role; FORCE RLS does not make it a client-safe role.

Section 9 therefore does not mechanically recommend enabling FORCE RLS. Its
classifications mean:

- `force_candidate`: sufficient reviewed workflow evidence may support a later
  proposal, but no audit-only query assigns this automatically;
- `force_not_recommended`: a verified owner workflow conflicts with FORCE RLS;
- `requires_business_decision`: sensitive/service/helper workflows must be
  resolved by owners and security reviewers;
- `insufficient_evidence`: catalog metadata alone cannot support a decision.

No global FORCE RLS recommendation is made.

## Result-return template

Return each result separately using this template. Attach only the metadata
grid produced by that numbered SELECT.

```text
Phase 3.2C section:
Execution timestamp:
Statement completed: yes/no
Result row count:
Empty-result sentinel present: yes/no/not applicable
Failed-check count (Section 13 only):
Metadata grid attached: yes/no
Reviewer notes (no application data or identifiers):
```

For Section 12, preserve `finding_id`, severity, table, policy, finding,
evidence, recommended decision, `migration_required`,
`human_business_decision_required`, and evidence classification. For Section 13,
preserve every expected/actual/failed/status row. Do not collapse or filter role
arrays, expressions, dependencies, zero counts, or unexpected rows.

## Local limitations and next decision

Static SQL cannot determine whether a policy's business semantics are correct,
whether an owner or background job is operationally required, or whether an
unrecorded dynamic function reference exists. ACL calculations show database
privilege paths, while RLS policy combination and BYPASSRLS behavior remain
separate authorization layers.

No Phase 3.2C remediation migration exists. Migration planning must wait for all
13 result sets, human classification of each finding versus hypothesis, explicit
business decisions for state transitions and owner workflows, and a second
security review. The Phase 3.2B core migration and separate optional
`supabase_admin` package must not be changed or applied as part of this audit.
