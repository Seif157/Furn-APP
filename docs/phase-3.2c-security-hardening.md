# Phase 3.2C targeted security hardening

Status: **Human security review required; not approved for deployment.**

This correction is review-only. No migration or live acceptance utility has been run. The package reconciles the supplied Phase 3.2C evidence exactly and removes the earlier owner-rights review view design.

## Evidence contract

The local verifier treats these user-supplied files as immutable inputs:

- `docs/evidence/phase-3.2c/section-03-for-all.csv`
- `docs/evidence/phase-3.2c/section-12-findings.csv`

Section 03 has the audit’s exact nine-column schema, 19 unique `policy` rows, and one canonical summary row reporting 19. Section 12 has the audit’s exact ten-column schema and 122 unique finding rows. Tests reject missing files, header drift, malformed Boolean/count fields, missing values, duplicate full rows, duplicate identities, truncation, extra rows, and bidirectional source/ledger differences.

The ledger classifications are exactly: `remediated`, `accepted_with_evidence`, `audit_false_positive`, or `deferred_with_named_blocker`. “Finding” means an audit hypothesis or static signal, not proof that a vulnerability existed.

## Review projection architecture

The owner-rights `public_review` view has been removed from the design. The corrected migration explicitly requires that no such view exists.

Anonymous review access uses two independent controls on raw `public.review`:

1. Table-level SELECT is revoked from PUBLIC and anon. Anon receives SELECT only on the seven safe columns: `id`, `target_kind`, `target_product_id`, `target_marketplace_party_id`, `rating`, `comment`, and `created_at`.
2. The permissive policy `phase32c_review_anon_safe_read` applies only to anon. Product reviews require a published product, approved seller, active category, and positive-stock color. Marketplace-party reviews require an approved party. Both branches reject conflicting target columns and require `target_service_request_id IS NULL`.

Anon receives no column grant for `customer_profile_id` or `target_service_request_id`. The former PUBLIC literal-true review policy is removed. A restrictive authenticated guard limits raw authenticated reads to the current customer’s reviews or an explicit administrator policy; the anonymous policy does not apply to authenticated.

No view or SECURITY DEFINER review reader is used. Consequently, review-table RLS cannot be bypassed by projection ownership.

### Future public API contract

No review consumer exists in this FastAPI repository. A future backend endpoint is required: `GET /v1/reviews/public`. It must query Supabase with the anonymous role, select exactly the seven safe columns, use a strict public response model, and preserve the RLS result without requesting either sensitive column. Flutter must use that backend endpoint and must never query sensitive raw review columns directly. This contract is documented only; application behavior is unchanged in this phase.

## Furnishing-request architecture

### Sanitized live diagnostic

A read-only live catalog diagnostic confirmed 13 deployed columns, in the order below. It also confirmed no identity or generated columns. Effective anon INSERT/UPDATE was denied on every column; authenticated and service_role each had effective INSERT/UPDATE on every column. No endpoint, credential, identity, UUID, default-generated value, or application row was recorded. The authenticated privileges were broader than the approved customer design and are the target of this package.

### Exact deployed inventory

| # | Column | PostgreSQL type | Nullability | Default |
|---:|---|---|---|---|
| 1 | `id` | `uuid` | NOT NULL | `gen_random_uuid()` |
| 2 | `customer_profile_id` | `uuid` | NOT NULL | none |
| 3 | `address_id` | `uuid` | NOT NULL | none |
| 4 | `title` | `text` | NOT NULL | none |
| 5 | `requirements_description` | `text` | NOT NULL | none |
| 6 | `reference_image_urls` | `text[]` | nullable | none |
| 7 | `budget_min` | `numeric(12,2)` | nullable | none |
| 8 | `budget_max` | `numeric(12,2)` | nullable | none |
| 9 | `requested_timing` | `text` | nullable | none |
| 10 | `offer_deadline` | `timestamp with time zone` | nullable | none |
| 11 | `lifecycle_state` | `public.furnishing_request_state` | NOT NULL | `'draft'` |
| 12 | `created_at` | `timestamp with time zone` | NOT NULL | `now()` |
| 13 | `coarse_location` | `text` | nullable | none |

The preflight compares ordinal, name, type OID, type modifier, formatted type, nullability, canonical default expression, identity marker, and generated marker with bidirectional `EXCEPT`. It separately validates the live-confirmed effective privilege baseline for all 13 columns and all three roles.

### Approved authenticated column privileges

Before granting either allowlist, the migration revokes authenticated table-level INSERT and UPDATE and explicitly revokes column-level INSERT and UPDATE across all 13 columns. This prevents historical column ACLs from surviving.

Authenticated INSERT is granted only on:

- `customer_profile_id`
- `address_id`
- `title`
- `requirements_description`
- `reference_image_urls`
- `budget_min`
- `budget_max`
- `requested_timing`
- `offer_deadline`
- `coarse_location`

Authenticated INSERT remains denied on the database-controlled `id`, `lifecycle_state`, and `created_at` columns. Their defaults therefore generate the identifier, initial draft state, and creation timestamp.

Authenticated UPDATE is granted only on:

- `address_id`
- `title`
- `requirements_description`
- `reference_image_urls`
- `budget_min`
- `budget_max`
- `requested_timing`
- `offer_deadline`
- `coarse_location`

Direct authenticated UPDATE remains denied on immutable `id`, `customer_profile_id`, `lifecycle_state`, and `created_at`. Anon remains denied INSERT/UPDATE on every column. The migration issues no anon or service_role furnishing privilege statement, and postflight verifies that service_role retains effective INSERT/UPDATE on all 13 columns.

### RLS and address ownership

INSERT is owner-scoped and draft-only. Its `WITH CHECK` also requires `address_id` to identify an address whose `customer_profile_id` equals `current_customer_profile_id()`. UPDATE is owner-scoped to existing draft/open rows, preserves owner and draft/open state in `WITH CHECK`, and repeats the same address-ownership condition. A foreign key by itself would not prevent a customer from referencing another customer’s address.

DELETE remains owner-scoped and is permitted only while the existing row is draft or open. Automated and live acceptance tests perform no DELETE.

### Lifecycle transition matrix

| Existing state | Requested customer action | Result |
|---|---|---|
| draft | `open_furnishing_request(uuid)` | open |
| open | `withdraw_furnishing_request(uuid)` | withdrawn |
| draft | direct withdrawal | denied |
| open | return to draft | denied |
| draft or open | direct accepted/closed assignment | denied |
| accepted, withdrawn, or closed | any ordinary-customer transition | denied |

`open_furnishing_request(uuid)` performs draft → open only, and `withdraw_furnishing_request(uuid)` performs open → withdrawn only. Both transition functions are VOLATILE PL/pgSQL SECURITY DEFINER functions because authenticated has no direct lifecycle UPDATE. They use `SET search_path=''`, fully qualified relations and `auth.uid()`, verify ownership, update only `lifecycle_state`, and return one Boolean. `false` uniformly represents missing, foreign-owned, or invalid-state input. PUBLIC and anon cannot execute them; authenticated and the elevated server-only service_role receive EXECUTE without grant option.

## Other retained hardening

- `current_customer_profile_id()` remains SQL, STABLE, postgres-owned, SECURITY DEFINER, UUID-returning, fully qualified, and configured with an empty search path. PUBLIC/anon EXECUTE is removed; authenticated/service_role EXECUTE remains.
- Literal-true service-directory policies are replaced with active-only anon/authenticated service-type paths and approved-party plus active-service capability paths.
- Separate authenticated capability policies preserve eligible, seller-owner, and administrator reads.
- `order_financial_position` is not recreated. It remains non-updatable and `security_invoker=true`; PUBLIC/anon receive no access, authenticated receives SELECT only, and service_role remains.
- All 34 public base tables must retain enabled, unforced RLS.
- Phase 3.2B catalogue policies, Storage objects/default ACLs, service_role behavior, and client-role separation are reverified.

PUBLIC is always treated as ACL grantee OID 0, never resolved through `pg_roles` or `to_regrole('PUBLIC')`.

## Review and execution order

1. Review both source CSVs and the exact ledgers below.
2. Review the live-confirmed furnishing inventory, privilege baseline, allowlists, address condition, and transitions.
3. Independently review the complete core SQL and standalone preflight.
4. Only then run the standalone preflight; it always rolls back.
5. If it passes, obtain another human approval before applying the core migration to a fake-data testing branch.
6. Run each numbered SELECT in the verification file separately.
7. Run the interactive acceptance utility only after all metadata verification passes.

The evidence blocker is resolved, but no live preflight has been performed for this revision. The package remains review-only and is not deployable.

## Live acceptance contract

The live utility reuses Phase 3.2B’s exact TTY confirmation, password collection, publishable-key authentication, memory-only sessions, safe output labels, and elevated-secret rejection.

Its corrected review checks:

- deny anonymous execution of `current_customer_profile_id()`;
- read the seven safe review columns anonymously and cross-check product/seller eligibility;
- require safe permission denial for each sensitive review column;
- read an authenticated customer’s own raw review;
- never use a view or broaden authenticated review RLS.

It also checks active service-directory scope, a genuinely seller-only capability, financial-view scope, and furnishing fixtures. Direct lifecycle no-op PATCHes must be denied for draft/open fixtures. A no-op `coarse_location` PATCH must succeed for owned draft/open fixtures and fail for accepted, withdrawn, and closed fixtures; every probe reads the complete 13-column snapshot immediately before and after and requires equality. Transition functions and DELETE are verified through metadata only; the utility performs neither state transition nor DELETE. Missing lifecycle fixtures fail safely with `fixture_precondition_not_met`.

No output includes passwords, tokens, UUIDs, row bodies, review comments, product data, or configured endpoint values.

## Section 03 disposition ledger — exact 19 policy rows

The canonical summary row is validated separately and is not itself a policy disposition.

| Table | Policy | Mode | Roles | Classification | Evidence or named blocker |
|---|---|---|---|---|---|
| address | address_write_own | PERMISSIVE | {authenticated} | deferred_with_named_blocker | operation_scope_review:address.address_write_own |
| cart | cart_all_own | PERMISSIVE | {authenticated} | deferred_with_named_blocker | operation_scope_review:cart.cart_all_own |
| cart_line | cart_line_all_own | PERMISSIVE | {authenticated} | deferred_with_named_blocker | operation_scope_review:cart_line.cart_line_all_own |
| category | category_write_admin | PERMISSIVE | {authenticated} | accepted_with_evidence | phase32b_verified_guard_or_explicit_admin_scope |
| custom_offering | custom_offering_write_own | PERMISSIVE | {authenticated} | deferred_with_named_blocker | operation_scope_review:custom_offering.custom_offering_write_own |
| design_product_reference | design_product_reference_write_own | PERMISSIVE | {authenticated} | deferred_with_named_blocker | operation_scope_review:design_product_reference.design_product_reference_write_own |
| furnishing_request | furnishing_request_write_own | PERMISSIVE | {authenticated} | remediated | phase32c_furnishing_lifecycle_split |
| furnishing_request_design_version | furnishing_request_design_version_write_own | PERMISSIVE | {authenticated} | deferred_with_named_blocker | operation_scope_review:furnishing_request_design_version.furnishing_request_design_version_write_own |
| offer_line_item | offer_line_item_write_own | PERMISSIVE | {authenticated} | deferred_with_named_blocker | operation_scope_review:offer_line_item.offer_line_item_write_own |
| party_capability | party_capability_write_own | PERMISSIVE | {authenticated} | deferred_with_named_blocker | operation_scope_review:party_capability.party_capability_write_own |
| platform_config | platform_config_rw_admin | PERMISSIVE | {authenticated} | accepted_with_evidence | phase32b_verified_guard_or_explicit_admin_scope |
| product | product_write_own | PERMISSIVE | {authenticated} | accepted_with_evidence | phase32b_verified_guard_or_explicit_admin_scope |
| product_3d_model | product_3d_model_write_own | PERMISSIVE | {authenticated} | accepted_with_evidence | phase32b_verified_guard_or_explicit_admin_scope |
| product_color | product_color_write_own | PERMISSIVE | {authenticated} | accepted_with_evidence | phase32b_verified_guard_or_explicit_admin_scope |
| product_enrichment_assignment | product_enrichment_assignment_write_own | PERMISSIVE | {authenticated} | accepted_with_evidence | phase32b_verified_guard_or_explicit_admin_scope |
| product_image | product_image_write_own | PERMISSIVE | {authenticated} | accepted_with_evidence | phase32b_verified_guard_or_explicit_admin_scope |
| review | review_write_own | PERMISSIVE | {authenticated} | deferred_with_named_blocker | operation_scope_review:review.review_write_own |
| saved_space | saved_space_all_own | PERMISSIVE | {authenticated} | deferred_with_named_blocker | operation_scope_review:saved_space.saved_space_all_own |
| service_type | service_type_write_admin | PERMISSIVE | {authenticated} | accepted_with_evidence | phase32b_verified_guard_or_explicit_admin_scope |

## Section 12 disposition ledger — exact 122 findings

| Finding ID | Severity | Table | Policy | Finding | Classification | Evidence or named blocker |
|---|---|---|---|---|---|---|
| phase32c_0001 | critical | category | category_select_public | literal_true_or_tautology | accepted_with_evidence | phase32b_active_category_restrictive_guard |
| phase32c_0002 | critical | marketplace_party | marketplace_party_update_own | marketplace_party_approval_policy_gap | audit_false_positive | phase32b_column_grants_and_live_denial_evidence |
| phase32c_0003 | critical | party_capability | party_capability_select | literal_true_or_tautology | remediated | phase32c_targeted_policy_change:party_capability.party_capability_select |
| phase32c_0004 | critical | product_enrichment_attribute | product_enrichment_attribute_select | literal_true_or_tautology | accepted_with_evidence | approved_controlled_vocabulary_decision |
| phase32c_0005 | critical | review | review_select_public | literal_true_or_tautology | remediated | phase32c_targeted_policy_change:review.review_select_public |
| phase32c_0006 | critical | service_type | service_type_select_public | literal_true_or_tautology | remediated | phase32c_targeted_policy_change:service_type.service_type_select_public |
| phase32c_0007 | high | address | address_write_own | possible_cross_principal_read | audit_false_positive | section03_exact_ownership_predicate:address.address_write_own |
| phase32c_0008 | high | address | address_write_own | possible_cross_principal_write | audit_false_positive | section03_exact_ownership_predicate:address.address_write_own |
| phase32c_0009 | high | address | address_write_own | possible_cross_principal_write | audit_false_positive | section03_exact_ownership_predicate:address.address_write_own |
| phase32c_0010 | high | address | address_write_own | possible_cross_principal_write | audit_false_positive | section03_exact_ownership_predicate:address.address_write_own |
| phase32c_0011 | high | cart | cart_all_own | possible_cross_principal_read | audit_false_positive | section03_exact_ownership_predicate:cart.cart_all_own |
| phase32c_0012 | high | cart | cart_all_own | possible_cross_principal_write | audit_false_positive | section03_exact_ownership_predicate:cart.cart_all_own |
| phase32c_0013 | high | cart | cart_all_own | possible_cross_principal_write | audit_false_positive | section03_exact_ownership_predicate:cart.cart_all_own |
| phase32c_0014 | high | cart | cart_all_own | possible_cross_principal_write | audit_false_positive | section03_exact_ownership_predicate:cart.cart_all_own |
| phase32c_0015 | high | cart_line | cart_line_all_own | possible_cross_principal_read | audit_false_positive | section03_exact_ownership_predicate:cart_line.cart_line_all_own |
| phase32c_0016 | high | cart_line | cart_line_all_own | possible_cross_principal_write | audit_false_positive | section03_exact_ownership_predicate:cart_line.cart_line_all_own |
| phase32c_0017 | high | cart_line | cart_line_all_own | possible_cross_principal_write | audit_false_positive | section03_exact_ownership_predicate:cart_line.cart_line_all_own |
| phase32c_0018 | high | cart_line | cart_line_all_own | possible_cross_principal_write | audit_false_positive | section03_exact_ownership_predicate:cart_line.cart_line_all_own |
| phase32c_0019 | high | category | phase32b_category_authenticated_read_guard | unexpected_admin_branch | audit_false_positive | reviewed_restrictive_admin_preservation_branch |
| phase32c_0020 | high | custom_offering | custom_offering_write_own | owner_only_insert_or_state_transition_risk | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0021 | high | customer_profile | customer_profile_insert_own | owner_only_insert_or_state_transition_risk | deferred_with_named_blocker | initial_state_or_transition_review:customer_profile.customer_profile_insert_own |
| phase32c_0022 | high | design | design_insert_own | owner_only_insert_or_state_transition_risk | deferred_with_named_blocker | initial_state_or_transition_review:design.design_insert_own |
| phase32c_0023 | high | design_product_reference | design_product_reference_write_own | owner_only_insert_or_state_transition_risk | deferred_with_named_blocker | initial_state_or_transition_review:design_product_reference.design_product_reference_write_own |
| phase32c_0024 | high | design_version | design_version_insert_own | owner_only_insert_or_state_transition_risk | deferred_with_named_blocker | initial_state_or_transition_review:design_version.design_version_insert_own |
| phase32c_0025 | high | furnishing_request | furnishing_request_select | possible_cross_principal_read | deferred_with_named_blocker | principal_scope_review:furnishing_request.furnishing_request_select |
| phase32c_0026 | high | furnishing_request | furnishing_request_write_own | possible_cross_principal_read | remediated | phase32c_targeted_policy_change:furnishing_request.furnishing_request_write_own |
| phase32c_0027 | high | furnishing_request | furnishing_request_write_own | possible_cross_principal_write | remediated | phase32c_targeted_policy_change:furnishing_request.furnishing_request_write_own |
| phase32c_0028 | high | furnishing_request | furnishing_request_write_own | possible_cross_principal_write | remediated | phase32c_targeted_policy_change:furnishing_request.furnishing_request_write_own |
| phase32c_0029 | high | furnishing_request | furnishing_request_write_own | possible_cross_principal_write | remediated | phase32c_targeted_policy_change:furnishing_request.furnishing_request_write_own |
| phase32c_0030 | high | furnishing_request_design_version | furnishing_request_design_version_select | possible_cross_principal_read | deferred_with_named_blocker | principal_scope_review:furnishing_request_design_version.furnishing_request_design_version_select |
| phase32c_0031 | high | furnishing_request_design_version | furnishing_request_design_version_write_own | possible_cross_principal_read | audit_false_positive | section03_exact_ownership_predicate:furnishing_request_design_version.furnishing_request_design_version_write_own |
| phase32c_0032 | high | furnishing_request_design_version | furnishing_request_design_version_write_own | possible_cross_principal_write | audit_false_positive | section03_exact_ownership_predicate:furnishing_request_design_version.furnishing_request_design_version_write_own |
| phase32c_0033 | high | furnishing_request_design_version | furnishing_request_design_version_write_own | possible_cross_principal_write | audit_false_positive | section03_exact_ownership_predicate:furnishing_request_design_version.furnishing_request_design_version_write_own |
| phase32c_0034 | high | furnishing_request_design_version | furnishing_request_design_version_write_own | possible_cross_principal_write | audit_false_positive | section03_exact_ownership_predicate:furnishing_request_design_version.furnishing_request_design_version_write_own |
| phase32c_0035 | high | party_capability | party_capability_write_own | owner_only_insert_or_state_transition_risk | deferred_with_named_blocker | initial_state_or_transition_review:party_capability.party_capability_write_own |
| phase32c_0036 | high | payment | payment_select_customer | possible_cross_principal_read | deferred_with_named_blocker | principal_scope_review:payment.payment_select_customer |
| phase32c_0037 | high | product | phase32b_product_authenticated_read_guard | unexpected_admin_branch | audit_false_positive | reviewed_restrictive_admin_preservation_branch |
| phase32c_0038 | high | product | product_write_own | owner_only_insert_or_state_transition_risk | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0039 | high | product_3d_model | phase32b_product_3d_model_insert_guard | owner_only_insert_or_state_transition_risk | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0040 | high | product_3d_model | product_3d_model_write_own | owner_only_insert_or_state_transition_risk | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0041 | high | product_color | phase32b_product_color_insert_guard | owner_only_insert_or_state_transition_risk | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0042 | high | product_color | product_color_write_own | owner_only_insert_or_state_transition_risk | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0043 | high | product_enrichment_assignment | phase32b_enrichment_insert_guard | owner_only_insert_or_state_transition_risk | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0044 | high | product_enrichment_assignment | product_enrichment_assignment_write_own | owner_only_insert_or_state_transition_risk | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0045 | high | product_image | phase32b_product_image_insert_guard | owner_only_insert_or_state_transition_risk | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0046 | high | product_image | product_image_write_own | owner_only_insert_or_state_transition_risk | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0047 | high | refund | refund_select_customer | possible_cross_principal_read | deferred_with_named_blocker | principal_scope_review:refund.refund_select_customer |
| phase32c_0048 | high | review | review_write_own | possible_cross_principal_write | audit_false_positive | section03_exact_ownership_predicate:review.review_write_own |
| phase32c_0049 | high | review | review_write_own | possible_cross_principal_write | audit_false_positive | section03_exact_ownership_predicate:review.review_write_own |
| phase32c_0050 | high | review | review_write_own | possible_cross_principal_write | audit_false_positive | section03_exact_ownership_predicate:review.review_write_own |
| phase32c_0051 | high | saved_space | saved_space_all_own | possible_cross_principal_read | audit_false_positive | section03_exact_ownership_predicate:saved_space.saved_space_all_own |
| phase32c_0052 | high | saved_space | saved_space_all_own | possible_cross_principal_write | audit_false_positive | section03_exact_ownership_predicate:saved_space.saved_space_all_own |
| phase32c_0053 | high | saved_space | saved_space_all_own | possible_cross_principal_write | audit_false_positive | section03_exact_ownership_predicate:saved_space.saved_space_all_own |
| phase32c_0054 | high | saved_space | saved_space_all_own | possible_cross_principal_write | audit_false_positive | section03_exact_ownership_predicate:saved_space.saved_space_all_own |
| phase32c_0055 | high | service_request | service_request_insert_own | possible_cross_principal_write | deferred_with_named_blocker | principal_scope_review:service_request.service_request_insert_own |
| phase32c_0056 | medium | address | address_select_own_or_engaged | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:address.address_select_own_or_engaged |
| phase32c_0057 | medium | address | address_write_own | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:address.address_write_own |
| phase32c_0058 | medium | category | category_select_public | overlapping_permissive_policies | accepted_with_evidence | phase32b_active_category_restrictive_guard |
| phase32c_0059 | medium | category | category_write_admin | overlapping_permissive_policies | accepted_with_evidence | phase32b_active_category_restrictive_guard |
| phase32c_0060 | medium | category | phase32b_category_authenticated_read_guard | overlapping_permissive_policies | audit_false_positive | reviewed_restrictive_admin_preservation_branch |
| phase32c_0061 | medium | custom_offering | custom_offering_select_admin | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0062 | medium | custom_offering | custom_offering_select_published_or_own | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0063 | medium | custom_offering | custom_offering_write_own | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0064 | medium | design | design_select_admin | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:design.design_select_admin |
| phase32c_0065 | medium | design | design_select_own | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:design.design_select_own |
| phase32c_0066 | medium | design_product_reference | design_product_reference_select_own | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:design_product_reference.design_product_reference_select_own |
| phase32c_0067 | medium | design_product_reference | design_product_reference_write_own | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:design_product_reference.design_product_reference_write_own |
| phase32c_0068 | medium | design_version | design_version_select_admin | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:design_version.design_version_select_admin |
| phase32c_0069 | medium | design_version | design_version_select_own | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:design_version.design_version_select_own |
| phase32c_0070 | medium | furnishing_request | furnishing_request_select | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:furnishing_request.furnishing_request_select |
| phase32c_0071 | medium | furnishing_request | furnishing_request_select_admin | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:furnishing_request.furnishing_request_select_admin |
| phase32c_0072 | medium | furnishing_request | furnishing_request_write_own | overlapping_permissive_policies | remediated | phase32c_targeted_policy_change:furnishing_request.furnishing_request_write_own |
| phase32c_0073 | medium | furnishing_request_design_version | furnishing_request_design_version_select | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:furnishing_request_design_version.furnishing_request_design_version_select |
| phase32c_0074 | medium | furnishing_request_design_version | furnishing_request_design_version_write_own | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:furnishing_request_design_version.furnishing_request_design_version_write_own |
| phase32c_0075 | medium | marketplace_party | marketplace_party_select_admin | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:marketplace_party.marketplace_party_select_admin |
| phase32c_0076 | medium | marketplace_party | marketplace_party_select_own | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:marketplace_party.marketplace_party_select_own |
| phase32c_0077 | medium | marketplace_party | marketplace_party_select_public | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:marketplace_party.marketplace_party_select_public |
| phase32c_0078 | medium | offer | offer_select_admin | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:offer.offer_select_admin |
| phase32c_0079 | medium | offer | offer_select_own_or_requesting_customer | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:offer.offer_select_own_or_requesting_customer |
| phase32c_0080 | medium | offer_line_item | offer_line_item_select | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:offer_line_item.offer_line_item_select |
| phase32c_0081 | medium | offer_line_item | offer_line_item_select_admin | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:offer_line_item.offer_line_item_select_admin |
| phase32c_0082 | medium | offer_line_item | offer_line_item_write_own | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:offer_line_item.offer_line_item_write_own |
| phase32c_0083 | medium | order_line_item | order_line_item_select_admin | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:order_line_item.order_line_item_select_admin |
| phase32c_0084 | medium | order_line_item | order_line_item_select_engaged | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:order_line_item.order_line_item_select_engaged |
| phase32c_0085 | medium | party_capability | party_capability_select | overlapping_permissive_policies | remediated | phase32c_targeted_policy_change:party_capability.party_capability_select |
| phase32c_0086 | medium | party_capability | party_capability_write_own | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:party_capability.party_capability_write_own |
| phase32c_0087 | medium | payment | payment_select_admin | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:payment.payment_select_admin |
| phase32c_0088 | medium | payment | payment_select_customer | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:payment.payment_select_customer |
| phase32c_0089 | medium | product | phase32b_product_authenticated_read_guard | overlapping_permissive_policies | audit_false_positive | reviewed_restrictive_admin_preservation_branch |
| phase32c_0090 | medium | product | phase32b_product_owner_read | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0091 | medium | product | product_select_admin | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0092 | medium | product | product_select_published_or_own | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0093 | medium | product | product_write_own | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0094 | medium | product_3d_model | phase32b_product_3d_model_authenticated_read_guard | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0095 | medium | product_3d_model | phase32b_product_3d_model_owner_read | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0096 | medium | product_3d_model | product_3d_model_select | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0097 | medium | product_3d_model | product_3d_model_write_own | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0098 | medium | product_color | phase32b_product_color_authenticated_read_guard | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0099 | medium | product_color | phase32b_product_color_owner_read | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0100 | medium | product_color | product_color_select | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0101 | medium | product_color | product_color_write_own | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0102 | medium | product_enrichment_assignment | phase32b_enrichment_authenticated_read_guard | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0103 | medium | product_enrichment_assignment | phase32b_enrichment_owner_read | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0104 | medium | product_enrichment_assignment | product_enrichment_assignment_select | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0105 | medium | product_enrichment_assignment | product_enrichment_assignment_write_own | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0106 | medium | product_image | phase32b_product_image_authenticated_read_guard | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0107 | medium | product_image | phase32b_product_image_owner_read | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0108 | medium | product_image | product_image_select | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0109 | medium | product_image | product_image_write_own | overlapping_permissive_policies | accepted_with_evidence | phase32b_verification_and_live_catalogue_evidence |
| phase32c_0110 | medium | purchase_order | purchase_order_select_admin | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:purchase_order.purchase_order_select_admin |
| phase32c_0111 | medium | purchase_order | purchase_order_select_engaged | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:purchase_order.purchase_order_select_engaged |
| phase32c_0112 | medium | refund | refund_select_admin | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:refund.refund_select_admin |
| phase32c_0113 | medium | refund | refund_select_customer | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:refund.refund_select_customer |
| phase32c_0114 | medium | review | review_select_admin | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:review.review_select_admin |
| phase32c_0115 | medium | review | review_select_public | overlapping_permissive_policies | remediated | phase32c_targeted_policy_change:review.review_select_public |
| phase32c_0116 | medium | review | review_write_own | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:review.review_write_own |
| phase32c_0117 | medium | service_request | service_request_select | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:service_request.service_request_select |
| phase32c_0118 | medium | service_request | service_request_select_admin | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:service_request.service_request_select_admin |
| phase32c_0119 | medium | service_type | service_type_select_public | overlapping_permissive_policies | remediated | phase32c_targeted_policy_change:service_type.service_type_select_public |
| phase32c_0120 | medium | service_type | service_type_write_admin | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:service_type.service_type_write_admin |
| phase32c_0121 | medium | settlement | settlement_select_admin | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:settlement.settlement_select_admin |
| phase32c_0122 | medium | settlement | settlement_select_own | overlapping_permissive_policies | deferred_with_named_blocker | permissive_overlap_business_review:settlement.settlement_select_own |

## Disposition totals

Across the 19 policies and 122 findings:

- `remediated`: 12
- `accepted_with_evidence`: 45
- `audit_false_positive`: 28
- `deferred_with_named_blocker`: 56

Every source policy and finding appears once and only once. Local tests perform bidirectional set comparisons, so an altered, missing, duplicated, or unexpected identity fails.

## Remaining review gates

The inventory blocker is resolved. This revision still requires another human security review, a live rollback-only standalone preflight, controlled application to a fake-data testing branch, all 20 read-only verification sections, and the staged live acceptance utility. None of those live steps was performed during this correction pass.

Final status: **Human security review required; not approved for deployment.**
