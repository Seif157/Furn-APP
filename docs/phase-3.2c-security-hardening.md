# Phase 3.2C targeted security hardening

Status: **Human security review required; not approved for deployment.**

This is a review-only package. No migration in this package has been run. The SQL is designed to fail closed before DDL/DCL because two required source decisions are not present in the repository: the retained row-by-row audit evidence and an approved furnishing-request withdrawal workflow.

## Preserved baseline

The proposal preserves the verified 34-table public-schema inventory, enabled but unforced RLS, Phase 3.2B catalogue policies, catalogue eligibility semantics, the existing application API, Storage objects and default ACLs, the optional `supabase_admin` migration, fake data, service-role access, and the existing `security_invoker=true` definition of `order_financial_position`.

The SQL does not enable FORCE RLS, change Storage, rewrite Phase 3.2B catalogue policies, change application rows, or recreate the financial view.

## Artifacts and review order

1. Review this document and reconcile both disposition ledgers below with the retained live Phase 3.2C outputs.
2. Review [phase-3.2c-security-hardening.sql](../sql/phase-3.2c-security-hardening.sql).
3. Run [phase-3.2c-security-hardening-preflight.sql](../sql/phase-3.2c-security-hardening-preflight.sql) only after independent approval. It always rolls back.
4. Do not remove the two preflight gates by editing SQL. A reviewed operator may set the documented transaction/session settings only after attaching the corresponding approvals.
5. If the standalone preflight passes, obtain another human security review before considering the core migration.
6. If a reviewed migration is later applied to a fake-data testing branch, run [phase-3.2c-security-hardening-verify.sql](../sql/phase-3.2c-security-hardening-verify.sql), one numbered section at a time.
7. Only then may a reviewer run the interactive acceptance utility described below.

The core and standalone preflight DO blocks are byte-identical. The standalone artifact contains only `BEGIN`, transaction-local safeguards, that preflight block, and `ROLLBACK`.

## Fail-closed review gates

The core and standalone preflights require three external review-record settings:

- `furn_app.phase32c_disposition_evidence=reviewed_19_policies_and_122_findings`
- `furn_app.phase32c_withdrawal_decision=customer_direct_withdrawal_not_approved`
- `furn_app.phase32c_initial_state_decision=customer_insert_draft_only_approved`

These strings are acknowledgements, not authorization controls. They must not be set until the retained live grids are attached, every ordinal below is reconciled to its actual identity, and the withdrawal decision is signed off. With no settings, preflight stops before the first persistent statement.

## Security decisions proposed

### Customer-profile helper

`public.current_customer_profile_id()` retains its UUID contract, postgres owner, SQL language, STABLE volatility, and SECURITY DEFINER mode. Its recreated body uses only `public.customer_profile` and `auth.uid()` with `SET search_path=''`. EXECUTE is revoked from PUBLIC and anon, retained only for authenticated and service_role (plus implicit owner rights). Preflight rejects an anonymous or PUBLIC policy dependency before the revoke.

### Public reviews

Repository inspection found no review endpoint or review SQL consumer in the FastAPI application. The proposal therefore leaves application code unchanged but requires a future Flutter/PostgREST consumer change: anonymous review reads must move from raw `public.review` to `public.public_review`.

Anonymous SELECT on raw `public.review` is revoked. A restrictive authenticated raw-table policy permits an authenticated customer’s own reviews or an administrator. Existing permissive SELECT paths must still exist; the restrictive policy cannot create access by itself. service_role behavior is preserved.

The new view exposes exactly seven columns: `id`, `target_kind`, `target_product_id`, `target_marketplace_party_id`, `rating`, `comment`, and `created_at`. It excludes both `customer_profile_id` and `target_service_request_id`; it contains no service-request branch. Product rows repeat the established published-product, approved-seller, active-category, and positive-stock eligibility rules. Seller rows require an approved marketplace party.

An owner-rights view is proposed deliberately, not casually: revoking anonymous raw-table SELECT means an invoker-rights view could not serve the safe projection. Risk is bounded by a fixed seven-column projection, fixed predicates, a security barrier, UNION ALL non-updatability, postgres ownership, SELECT-only grants, and postflight/verification checks. Reviewers may instead require an equally narrow SECURITY DEFINER RPC, but that is an API decision and must not be substituted without review.

### Service directory

Restrictive anonymous policies require active service types and require both an approved marketplace party and active referenced service type for capabilities. Separate restrictive authenticated guards preserve public eligible rows, an authenticated seller’s own capabilities, and explicit administrator access. Restrictive guards prevent an existing permissive literal-true policy from reopening disallowed rows.

### Furnishing requests

The verified `furnishing_request_write_own` FOR ALL policy is proposed for replacement with operation-specific authenticated policies:

- INSERT requires the current customer and the documented initial `draft` state.
- UPDATE requires the old row to be owned and in `draft` or `open`; WITH CHECK preserves ownership and permits only `draft` or `open`.
- DELETE requires ownership and an existing `draft` or `open` state.
- No SELECT permission is introduced; existing SELECT/admin policies remain authoritative.
- `accepted`, `withdrawn`, and `closed` rows are locked for ordinary customer UPDATE/DELETE.

No repository application code or tests establish the legitimate transition into `withdrawn`, nor independently establish that customer insertion must be draft-only. The conservative proposal uses draft-only insertion and does not permit direct ordinary-customer withdrawal; it cannot pass preflight until both decisions are explicitly approved. If customers must withdraw an open request, a separately reviewed transition mechanism (for example, a narrowly validated RPC) is required. These are deployment blockers, not an invitation to invent a transition graph.

### Financial view

The view definition is not recreated. The proposal preserves `security_invoker=true`, non-updatability, and service_role access. PUBLIC, anon, and authenticated privileges are normalized by revoking all and granting authenticated SELECT only. On supported PostgreSQL versions, the all-privilege revoke also covers MAINTAIN.

## Verification contract

The verifier contains 16 independently runnable, SELECT-only sections. Every section returns `expected_count`, `actual_count`, `failed_count`, and `check_passed`:

1. exact helper definition, security metadata, owner, empty path, body markers, and grants;
2. anonymous raw-review denial;
3. exact public-review columns, predicates, non-updatability, barrier/rights behavior, and grants;
4. absence of a public service-request branch;
5. active-only anonymous service types;
6. approved-party plus active-service anonymous capabilities;
7. seller-own and administrator authenticated directory branches;
8. furnishing operation-specific policy inventory and predicates;
9. accepted/withdrawn/closed update/delete lock predicates;
10. financial view invoker behavior and authenticated SELECT-only grants;
11. unchanged 30-policy Phase 3.2B catalogue inventory (the full Phase 3.2B verifier remains authoritative for complete predicate identity);
12. retained service_role functionality;
13. no client inheritance/elevation;
14. no unexpected PUBLIC privileges on targeted objects;
15. unchanged exact managed Storage default-ACL signature for anon, authenticated, and elevated server-only service_role;
16. verification-section inventory.

Verification is metadata-only and contains no application-row query.

## Live acceptance utility

Do not run [live_phase_3_2c_acceptance.py](../scripts/live_phase_3_2c_acceptance.py) until the proposal has been reviewed and applied to a fake-data testing branch. It reuses the exact Phase 3.2B interactive confirmation and credential handling. It refuses non-TTY input and elevated secret configuration, authenticates the configured customer and seller with the publishable key, keeps tokens/passwords in memory only, and emits only safe labels, actor classes, statuses, HTTP statuses, and error classifications.

Its staged matrix is:

| Actor | Check | Live method |
|---|---|---|
| anonymous | raw review denied | GET must return a safe permission denial |
| anonymous | public product/seller projection and no service reviews | bounded GET plus eligibility cross-check |
| anonymous | active service types and approved-party active capabilities | bounded GET plus parent cross-check |
| customer | own raw review and hardened profile helper | GET/RPC, values retained only in memory |
| customer | draft/open request no-op update | read, exact-value PATCH, read |
| customer | accepted/withdrawn/closed update denial | read, exact-value PATCH, read |
| seller | own capability read | bounded GET scoped by memory-only party identity |
| customer and seller | financial view is a subset of permitted orders | bounded GET comparison |
| runner | DELETE policy | metadata verifier only; no DELETE is issued |

A required missing review, directory, furnishing-state, or financial fixture produces `fixture_precondition_not_met`. The utility never creates fixtures or sends a real DELETE. Product data, reviews, comments, identities, UUIDs, response bodies, URLs, credentials, and tokens are never printed.

## Disposition methodology and limitation

The live result grids containing the 19 policy identities and 122 generated finding rows are not present in the repository or supplied request. Fabricating identity-to-conclusion mappings would be unsafe. The ledgers below therefore give every required ordinal exactly one allowed classification, conservatively defer every unidentified row to the named reconciliation decision, and make deployment fail closed. They are not a claim that 122 vulnerabilities existed: Section 12 produced hypotheses, static signals, and structural observations.

The following topic conclusions are authoritative but cannot safely be attached to a generated `phase32c_NNNN` identifier until the retained result grid is reconciled:

| Topic | Reviewed conclusion | Evidence classification |
|---|---|---|
| category public read | retained behind the Phase 3.2B active-category restrictive guard | accepted with evidence |
| product enrichment attributes | intentional controlled vocabulary unless a schema/content review finds sensitive values | accepted with evidence |
| marketplace-party approval writes | protected by column privileges and successful live denial checks | audit false positive for a policy-only signal |
| FORCE RLS | remains disabled; metadata alone is insufficient approval | accepted with evidence |
| all FOR ALL policies | no mechanical rewrite without operation-level proof | deferred pending a named business decision |

### All 19 FOR ALL policies

The first row is tied to the one verified identity named in the supplied evidence. Rows 02–19 must be replaced with their exact Section 03 schema/table/policy identities before the disposition evidence gate may be acknowledged.

| Item | Audited identity | Classification | Named evidence or decision |
|---|---|---|---|
| for_all_01 | `furnishing_request_write_own` | remediated | Replace the verified mixed write policy with explicit INSERT, UPDATE, and DELETE policies after withdrawal review. |
| for_all_02 | Audit Section 03 row identity not supplied | deferred pending a named business decision | Reconcile this ordinal with the retained Section 03 result and approve its operation-level business authorization. |
| for_all_03 | Audit Section 03 row identity not supplied | deferred pending a named business decision | Reconcile this ordinal with the retained Section 03 result and approve its operation-level business authorization. |
| for_all_04 | Audit Section 03 row identity not supplied | deferred pending a named business decision | Reconcile this ordinal with the retained Section 03 result and approve its operation-level business authorization. |
| for_all_05 | Audit Section 03 row identity not supplied | deferred pending a named business decision | Reconcile this ordinal with the retained Section 03 result and approve its operation-level business authorization. |
| for_all_06 | Audit Section 03 row identity not supplied | deferred pending a named business decision | Reconcile this ordinal with the retained Section 03 result and approve its operation-level business authorization. |
| for_all_07 | Audit Section 03 row identity not supplied | deferred pending a named business decision | Reconcile this ordinal with the retained Section 03 result and approve its operation-level business authorization. |
| for_all_08 | Audit Section 03 row identity not supplied | deferred pending a named business decision | Reconcile this ordinal with the retained Section 03 result and approve its operation-level business authorization. |
| for_all_09 | Audit Section 03 row identity not supplied | deferred pending a named business decision | Reconcile this ordinal with the retained Section 03 result and approve its operation-level business authorization. |
| for_all_10 | Audit Section 03 row identity not supplied | deferred pending a named business decision | Reconcile this ordinal with the retained Section 03 result and approve its operation-level business authorization. |
| for_all_11 | Audit Section 03 row identity not supplied | deferred pending a named business decision | Reconcile this ordinal with the retained Section 03 result and approve its operation-level business authorization. |
| for_all_12 | Audit Section 03 row identity not supplied | deferred pending a named business decision | Reconcile this ordinal with the retained Section 03 result and approve its operation-level business authorization. |
| for_all_13 | Audit Section 03 row identity not supplied | deferred pending a named business decision | Reconcile this ordinal with the retained Section 03 result and approve its operation-level business authorization. |
| for_all_14 | Audit Section 03 row identity not supplied | deferred pending a named business decision | Reconcile this ordinal with the retained Section 03 result and approve its operation-level business authorization. |
| for_all_15 | Audit Section 03 row identity not supplied | deferred pending a named business decision | Reconcile this ordinal with the retained Section 03 result and approve its operation-level business authorization. |
| for_all_16 | Audit Section 03 row identity not supplied | deferred pending a named business decision | Reconcile this ordinal with the retained Section 03 result and approve its operation-level business authorization. |
| for_all_17 | Audit Section 03 row identity not supplied | deferred pending a named business decision | Reconcile this ordinal with the retained Section 03 result and approve its operation-level business authorization. |
| for_all_18 | Audit Section 03 row identity not supplied | deferred pending a named business decision | Reconcile this ordinal with the retained Section 03 result and approve its operation-level business authorization. |
| for_all_19 | Audit Section 03 row identity not supplied | deferred pending a named business decision | Reconcile this ordinal with the retained Section 03 result and approve its operation-level business authorization. |

### All 122 Phase 3.2C findings

These identifiers mirror the audit’s generated identifier shape, but their table/policy/finding identity must be copied from the retained Section 12 results. Each is conservatively classified exactly once.

| Finding | Classification | Named evidence or decision |
|---|---|---|
| phase32c_0001 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0002 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0003 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0004 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0005 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0006 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0007 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0008 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0009 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0010 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0011 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0012 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0013 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0014 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0015 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0016 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0017 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0018 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0019 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0020 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0021 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0022 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0023 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0024 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0025 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0026 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0027 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0028 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0029 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0030 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0031 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0032 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0033 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0034 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0035 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0036 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0037 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0038 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0039 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0040 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0041 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0042 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0043 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0044 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0045 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0046 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0047 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0048 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0049 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0050 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0051 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0052 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0053 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0054 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0055 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0056 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0057 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0058 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0059 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0060 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0061 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0062 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0063 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0064 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0065 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0066 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0067 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0068 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0069 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0070 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0071 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0072 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0073 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0074 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0075 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0076 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0077 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0078 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0079 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0080 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0081 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0082 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0083 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0084 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0085 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0086 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0087 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0088 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0089 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0090 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0091 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0092 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0093 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0094 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0095 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0096 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0097 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0098 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0099 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0100 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0101 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0102 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0103 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0104 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0105 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0106 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0107 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0108 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0109 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0110 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0111 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0112 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0113 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0114 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0115 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0116 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0117 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0118 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0119 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0120 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0121 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |
| phase32c_0122 | deferred pending a named business decision | Reconcile the retained Section 12 row identity and decide the named policy/business question in that row. |

## Unresolved blockers

- The real Section 03 and Section 12 result rows must be attached and reconciled to the ledgers. Counts alone are insufficient.
- Product owners must approve how an ordinary customer legitimately creates a `withdrawn` state, or explicitly approve that no direct customer withdrawal exists.
- Product owners must confirm that the existing initial-state rule is draft-only before acknowledging the initial-state gate.
- Flutter/PostgREST consumers of anonymous reviews must be identified and moved to `public_review`; none exists in this FastAPI repository.
- The exact review enum labels, nine-column raw review inventory, furnishing lifecycle labels, existing initial draft behavior, targeted policy metadata, grants, and dependencies still require the standalone live preflight.
- The owner-rights public review projection requires independent security review.

Final status: **Human security review required; not approved for deployment.**
