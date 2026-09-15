# Phase 3.2D targeted security hardening

Status: **Human security review required; not approved for deployment.**

This package is review-only. No migration, standalone preflight, verification SELECT, or live utility has been run. It resolves the 56 items that Phase 3.2C deferred with named blockers and two additional state-write findings observed in the Phase 3.2D evidence. It must run only after the Phase 3.2C migration has been applied and verified.

## Evidence contract

Every embedded catalog signature, privilege expectation, replaced-policy predicate, and policy inventory in the three SQL files is generated from the read-only exports under `docs/evidence/phase-3.2d/` by `tests/phase_3_2d_package.py`. The local tests assert that the files on disk are byte-identical to that generator's output, so the SQL cannot drift from the evidence without a test failure. The generator performs no database access.

Inputs (all immutable, all reconciled by tests):

| File | Rows | Used for |
|---|---:|---|
| `section-02-policies.csv` | 114 policies | Exact predicates of the 14 replaced policies; the 18-policy `FOR ALL` set after 3.2C; retained policies per table |
| `section-05-operation-review.csv` | 171 rows | Audit signals backing each disposition |
| `column-inventory.csv` | 149 columns, 18 tables | Exact 104-column signature of the 13 touched tables |
| `column-privileges.csv` | 447 rows | Effective privilege baseline and the derived post-migration expectation, 312 rows each |
| `state-enums.csv` | 41 labels, 11 enums | Exact state machines and enum label pins |
| `constraints.csv` | 103 constraints | Unique, foreign-key, and check facts the predicates rely on |
| `phase-3.2d-decisions.md` | — | Product-owner decisions recorded on 2026-09-15 |

The exports record the deployed state before Phase 3.2C. The privilege baseline embedded in the preflight applies the one Phase 3.2C privilege change on a touched table: anon SELECT on `review` reduced to seven columns.

## Touched tables and the exact changes

Thirteen tables are touched. For every one, authenticated table-level INSERT and UPDATE are revoked, every column-level INSERT and UPDATE is revoked, and only the approved allowlist is granted back. `id`, owner columns, timestamps, and state columns are never client-writable. anon and service_role privileges are untouched except the marketplace_party SELECT change in D1.

| Table | Dropped policy | New policies | Authenticated INSERT allowlist | Authenticated UPDATE allowlist |
|---|---|---|---|---|
| address | address_write_own | insert_own, update_own, delete_own | customer_profile_id, label, recipient_name, contact_phone, address_line_1, address_line_2, city, country, latitude, longitude, is_default | label, recipient_name, contact_phone, address_line_1, address_line_2, city, country, latitude, longitude, is_default |
| cart | cart_all_own | select_own, delete_own | none (server-created) | none |
| cart_line | cart_line_all_own | select_own, insert_own, update_own, delete_own | cart_id, product_color_id, quantity | quantity |
| saved_space | saved_space_all_own | select_own, insert_own, update_own, delete_own | customer_profile_id, space_name, width_cm, depth_cm, measurement_source | space_name, width_cm, depth_cm, measurement_source |
| review | review_write_own | select_own, insert_verified | customer_profile_id, target_kind, target_product_id, target_service_request_id, target_marketplace_party_id, rating, comment | none |
| furnishing_request_design_version | furnishing_request_design_version_write_own | delete_own | none (server-created) | none |
| custom_offering | custom_offering_write_own | insert_own, update_own, delete_own | marketplace_party_id, design_id, published_price, title, description, publication_state, published_at | design_id, published_price, title, description, publication_state, published_at |
| party_capability | party_capability_write_own | insert_own, delete_own | marketplace_party_id, service_type_id, declared_at | none |
| offer_line_item | offer_line_item_write_own | insert_own, update_own, delete_own | offer_id, line_kind, product_id, item_name, specification, unit_price, quantity, display_order | line_kind, product_id, item_name, specification, unit_price, quantity, display_order |
| design_product_reference | design_product_reference_write_own | insert_own, delete_own | design_id, product_id | none |
| service_request | service_request_insert_own, service_request_update_engaged | insert_own, update_own_pending | customer_profile_id, service_type_id, address_id, related_order_id, scheduled_date, scheduled_time, details | scheduled_date, scheduled_time, details |
| purchase_order | purchase_order_update_party | update_party_notes | none (dormant grant revoked) | notes |
| marketplace_party | none | none | unchanged (3.2B) | unchanged (3.2B) |

All new policies are named `phase32d_<table>_<operation>_<scope>`, apply `TO authenticated` only, and carry an owner anchor: `current_customer_profile_id()`, `current_marketplace_party_id()`, or `design.originating_user_id = auth.uid()`.

### Predicates beyond ownership

- **address delete** is denied while any `furnishing_request`, `service_request`, or `purchase_order` references the address. The foreign keys already restrict; the policy makes the denial a policy result rather than a constraint error.
- **cart_line insert** requires the colour's product to be `published`, its seller `approved`, its category active, and `stock_quantity > 0`, the same conditions the Phase 3.2B catalogue guards enforce on reads.
- **review insert** requires a verified purchase or service: a product review needs an `order_line_item` for that product on a `delivered` order owned by the customer; a service-request review needs an owned `completed` request; a marketplace-party review needs a delivered order or a completed request with that party. Reviews are insert-only and final. Customers read their own reviews through the new owner SELECT policy; the Phase 3.2C restrictive guard still applies.
- **furnishing_request_design_version delete** requires the parent request to be owned and `draft` or `open`. Rows are created by `service_role`.
- **custom_offering insert and update** require an approved seller and a design the caller originated. Delete is denied once a `purchase_order` references the offering.
- **party_capability insert** requires an approved seller and an active service type. The old policy did not require approval.
- **offer_line_item** writes require the parent offer to belong to the caller's party and be `submitted`.
- **service_request insert** requires owner, `lifecycle_state = 'pending'`, `marketplace_party_id IS NULL`, an owned address, and a null or owned `related_order_id`. Customer update is allowed only while `pending`, preserves those conditions, and reaches only the three schedule and details columns.

## State machines and transition functions

Direct state writes are removed. Authenticated has no UPDATE grant on `service_request.lifecycle_state`, `service_request.completed_at`, or `purchase_order.lifecycle_state` after this package.

| Function | Caller | Transition | Also sets |
|---|---|---|---|
| `cancel_service_request(uuid)` | owning customer | pending → cancelled | — |
| `accept_service_request(uuid, numeric)` | approved seller with a `party_capability` for the request's service type | pending → accepted | `marketplace_party_id` = caller's party, `accepted_at = now()`, `price` = argument (must be non-negative) |
| `start_service_request(uuid)` | the assigned approved seller | accepted → in_progress | — |
| `complete_service_request(uuid)` | the assigned approved seller | in_progress → completed | `completed_at = now()` |
| `advance_purchase_order(uuid, order_state)` | the order's approved seller | pending → confirmed → preparing → out_for_delivery → delivered, one step at a time | — |
| `cancel_purchase_order(uuid)` | owning customer | pending → cancelled | `cancelled_at = now()` |

Every function is PL/pgSQL, VOLATILE, SECURITY DEFINER, postgres-owned, `SET search_path = ''`, fully qualifies every relation and `auth.uid()`, returns one Boolean, and returns `false` uniformly for a missing, foreign, or wrong-state row so that existence is not revealed. EXECUTE is revoked from PUBLIC and anon and granted without grant option to `authenticated` and `service_role`.

Transitions that remain impossible for clients: any backward move, skipping a step, seller cancellation of an order, customer acceptance or completion of a service request, seller cancellation of a service request, and any transition from a terminal state.

Residual defaults applied because they were not answered: `in_progress` is kept as a seller step (S1); the seller cannot set the schedule after acceptance (S2); price is fixed at acceptance (S3); reviews require a delivered order or completed request (R1); approved sellers' `state_reason` stays readable to signed-in users (M1); customers cancel orders only from `pending` (P1); sellers cannot cancel orders (P2).

## Public marketplace-party columns (D1)

Both `anon` and `authenticated` held table-level SELECT on all eight `marketplace_party` columns. The package revokes table-level and column-level SELECT from PUBLIC, anon, and authenticated, then grants anon SELECT on `id`, `business_name`, `business_description`, `logo_url`, `coverage_area`, `approval_state`, and authenticated the same six plus `state_reason`. No client role can read `user_id`. RLS policies keep evaluating `user_id` internally, which requires no column grant, so `marketplace_party_select_own` and `marketplace_party_update_own` still work. Client code must select explicit columns; `select=*` on this table now fails for both roles.

## Preflight and postflight

The preflight (embedded in the core migration and byte-identical in the standalone rollback-only file) fails closed on: PostgreSQL 15 or newer; the four roles; the exact 34-table inventory with enabled, unforced RLS; the applied Phase 3.2C policies and functions and the absence of the policies 3.2C removed; any pre-existing `phase32d_*` policy or any of the six function signatures; the four hardened helpers; the exact 18-policy `FOR ALL` set; every replaced policy's exact command, roles, `USING`, and `WITH CHECK` text; the exact 104-column signature of the 13 touched tables including type, modifier, nullability, default, and no identity or generated drift; the exact 312-row effective privilege baseline; the 14 constraints and 7 enum label sets the package relies on; and the 15 columns of other tables the new predicates reference.

The postflight verifies the exact policy inventory on the touched tables and that exactly 8 `FOR ALL` policies remain, owner anchoring and no broadening on every new policy, the state, address, catalogue, and approval predicates, the exact 312-row post-migration privilege matrix with no grantable or PUBLIC column ACL, the six transition functions' metadata, direction, forbidden states, and grants, and enabled, unforced RLS everywhere.

## Verification file

`sql/phase-3.2d-security-hardening-verify.sql` has 12 SELECT-only sections, each returning `check_name`, `expected_count`, `actual_count`, `failed_count`, and `check_passed`: 3.2C prerequisites and no survivors; the exact 8 `FOR ALL` policies; the 104-column inventory; the 312-row privilege matrix; the touched-table policy inventory; owner anchoring of the 29 new policies; 36 required predicate fragments; six function definitions; six function grant sets; four helpers unchanged; RLS on all 34 tables; and a Storage and default-ACL report row. Run each section separately.

## Review and execution order

1. Confirm the Phase 3.2C migration has been applied and its 20 verification sections pass.
2. Review the decision sheet, this document, and `tests/phase_3_2d_package.py`, which is the single source of every generated block.
3. Independently review the complete core SQL and the standalone preflight.
4. Only then run the standalone preflight; it always rolls back.
5. If it passes, obtain another human approval before applying the core migration to a fake-data testing branch.
6. Run each numbered SELECT in the verification file separately.
7. No live acceptance utility is included in this package. One should be written in the Phase 3.2C shape before production use, covering no-op PATCH probes on each touched table and metadata-only checks of the six functions.

## Section 03 disposition ledger — the 10 deferred policies

| Table | Policy | Mode | Roles | Classification | Evidence or named blocker |
|---|---|---|---|---|---|
| address | address_write_own | PERMISSIVE | {authenticated} | remediated | phase32d_operation_split:address.address_write_own |
| cart | cart_all_own | PERMISSIVE | {authenticated} | remediated | phase32d_operation_split:cart.cart_all_own |
| cart_line | cart_line_all_own | PERMISSIVE | {authenticated} | remediated | phase32d_operation_split:cart_line.cart_line_all_own |
| custom_offering | custom_offering_write_own | PERMISSIVE | {authenticated} | remediated | phase32d_operation_split:custom_offering.custom_offering_write_own |
| design_product_reference | design_product_reference_write_own | PERMISSIVE | {authenticated} | remediated | phase32d_operation_split:design_product_reference.design_product_reference_write_own |
| furnishing_request_design_version | furnishing_request_design_version_write_own | PERMISSIVE | {authenticated} | remediated | phase32d_operation_split:furnishing_request_design_version.furnishing_request_design_version_write_own |
| offer_line_item | offer_line_item_write_own | PERMISSIVE | {authenticated} | remediated | phase32d_operation_split:offer_line_item.offer_line_item_write_own |
| party_capability | party_capability_write_own | PERMISSIVE | {authenticated} | remediated | phase32d_operation_split:party_capability.party_capability_write_own |
| review | review_write_own | PERMISSIVE | {authenticated} | remediated | phase32d_operation_split:review.review_write_own |
| saved_space | saved_space_all_own | PERMISSIVE | {authenticated} | remediated | phase32d_operation_split:saved_space.saved_space_all_own |

## Section 12 disposition ledger — the 46 deferred findings and 2 new findings

| Finding ID | Severity | Table | Policy | Finding | Classification | Evidence or named blocker |
|---|---|---|---|---|---|---|
| phase32c_0021 | high | customer_profile | customer_profile_insert_own | owner_only_insert_or_state_transition_risk | audit_false_positive | column_inventory_no_state_column:customer_profile |
| phase32c_0022 | high | design | design_insert_own | owner_only_insert_or_state_transition_risk | audit_false_positive | column_inventory_no_state_column:design |
| phase32c_0023 | high | design_product_reference | design_product_reference_write_own | owner_only_insert_or_state_transition_risk | audit_false_positive | column_inventory_no_state_column:design_product_reference |
| phase32c_0024 | high | design_version | design_version_insert_own | owner_only_insert_or_state_transition_risk | audit_false_positive | column_inventory_no_state_column:design_version |
| phase32c_0025 | high | furnishing_request | furnishing_request_select | possible_cross_principal_read | accepted_with_evidence | decision_c1_open_request_marketplace_read |
| phase32c_0030 | high | furnishing_request_design_version | furnishing_request_design_version_select | possible_cross_principal_read | accepted_with_evidence | decision_c1_open_request_marketplace_read |
| phase32c_0035 | high | party_capability | party_capability_write_own | owner_only_insert_or_state_transition_risk | audit_false_positive | column_inventory_no_state_column:party_capability |
| phase32c_0036 | high | payment | payment_select_customer | possible_cross_principal_read | audit_false_positive | section02_parent_order_owner_anchor:payment.payment_select_customer |
| phase32c_0047 | high | refund | refund_select_customer | possible_cross_principal_read | audit_false_positive | section02_parent_order_owner_anchor:refund.refund_select_customer |
| phase32c_0055 | high | service_request | service_request_insert_own | possible_cross_principal_write | remediated | phase32d_service_request_insert_allowlist_and_pending_pin |
| phase32c_0056 | medium | address | address_select_own_or_engaged | overlapping_permissive_policies | accepted_with_evidence | decision_d2_engaged_seller_address_read |
| phase32c_0057 | medium | address | address_write_own | overlapping_permissive_policies | remediated | phase32d_operation_split:address.address_write_own |
| phase32c_0064 | medium | design | design_select_admin | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:design |
| phase32c_0065 | medium | design | design_select_own | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:design |
| phase32c_0066 | medium | design_product_reference | design_product_reference_select_own | overlapping_permissive_policies | accepted_with_evidence | overlap_removed_by_phase32d_split:design_product_reference |
| phase32c_0067 | medium | design_product_reference | design_product_reference_write_own | overlapping_permissive_policies | remediated | phase32d_operation_split:design_product_reference.design_product_reference_write_own |
| phase32c_0068 | medium | design_version | design_version_select_admin | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:design_version |
| phase32c_0069 | medium | design_version | design_version_select_own | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:design_version |
| phase32c_0070 | medium | furnishing_request | furnishing_request_select | overlapping_permissive_policies | accepted_with_evidence | phase32c_for_all_removed_remaining_overlap_intended:furnishing_request |
| phase32c_0071 | medium | furnishing_request | furnishing_request_select_admin | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:furnishing_request |
| phase32c_0073 | medium | furnishing_request_design_version | furnishing_request_design_version_select | overlapping_permissive_policies | accepted_with_evidence | overlap_removed_by_phase32d_split:furnishing_request_design_version |
| phase32c_0074 | medium | furnishing_request_design_version | furnishing_request_design_version_write_own | overlapping_permissive_policies | remediated | phase32d_operation_split:furnishing_request_design_version.furnishing_request_design_version_write_own |
| phase32c_0075 | medium | marketplace_party | marketplace_party_select_admin | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:marketplace_party |
| phase32c_0076 | medium | marketplace_party | marketplace_party_select_own | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:marketplace_party |
| phase32c_0077 | medium | marketplace_party | marketplace_party_select_public | overlapping_permissive_policies | remediated | phase32d_marketplace_party_column_grants |
| phase32c_0078 | medium | offer | offer_select_admin | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:offer |
| phase32c_0079 | medium | offer | offer_select_own_or_requesting_customer | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:offer |
| phase32c_0080 | medium | offer_line_item | offer_line_item_select | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:offer_line_item |
| phase32c_0081 | medium | offer_line_item | offer_line_item_select_admin | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:offer_line_item |
| phase32c_0082 | medium | offer_line_item | offer_line_item_write_own | overlapping_permissive_policies | remediated | phase32d_operation_split:offer_line_item.offer_line_item_write_own |
| phase32c_0083 | medium | order_line_item | order_line_item_select_admin | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:order_line_item |
| phase32c_0084 | medium | order_line_item | order_line_item_select_engaged | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:order_line_item |
| phase32c_0086 | medium | party_capability | party_capability_write_own | overlapping_permissive_policies | remediated | phase32d_operation_split:party_capability.party_capability_write_own |
| phase32c_0087 | medium | payment | payment_select_admin | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:payment |
| phase32c_0088 | medium | payment | payment_select_customer | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:payment |
| phase32c_0110 | medium | purchase_order | purchase_order_select_admin | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:purchase_order |
| phase32c_0111 | medium | purchase_order | purchase_order_select_engaged | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:purchase_order |
| phase32c_0112 | medium | refund | refund_select_admin | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:refund |
| phase32c_0113 | medium | refund | refund_select_customer | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:refund |
| phase32c_0114 | medium | review | review_select_admin | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:review |
| phase32c_0116 | medium | review | review_write_own | overlapping_permissive_policies | remediated | phase32d_operation_split:review.review_write_own |
| phase32c_0117 | medium | service_request | service_request_select | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:service_request |
| phase32c_0118 | medium | service_request | service_request_select_admin | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:service_request |
| phase32c_0120 | medium | service_type | service_type_write_admin | overlapping_permissive_policies | accepted_with_evidence | admin_only_write_with_phase32c_narrowed_public_read |
| phase32c_0121 | medium | settlement | settlement_select_admin | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:settlement |
| phase32c_0122 | medium | settlement | settlement_select_own | overlapping_permissive_policies | accepted_with_evidence | own_plus_is_admin_pair:settlement |
| phase32d_0001 | high | service_request | service_request_update_engaged | direct_lifecycle_state_write | remediated | phase32d_service_request_update_allowlist_and_transition_functions |
| phase32d_0002 | high | purchase_order | purchase_order_update_party | direct_lifecycle_state_write | remediated | phase32d_purchase_order_notes_allowlist_and_transition_functions |

## Disposition totals

Across the 10 policies, 46 deferred findings, and 2 new findings:

- `remediated`: 20
- `accepted_with_evidence`: 31
- `audit_false_positive`: 7
- `deferred_with_named_blocker`: 0

Every Phase 3.2C deferred identity appears exactly once. Local tests compare the sets in both directions against the Phase 3.2C ledgers.

## Client contract changes

- Carts are created by the backend with `service_role`; the client no longer inserts carts.
- Furnishing-request design versions are created by the backend; the client may only delete them while the request is draft or open.
- Reviews cannot be edited or deleted by the client and must reference a delivered order or a completed service request.
- Service requests are created `pending` with no seller; state changes go through the four RPC functions.
- Sellers change order state only through `advance_purchase_order`; customers cancel only through `cancel_purchase_order`.
- Clients must select explicit `marketplace_party` columns; `user_id` is never returned.

Final status: **Human security review required; not approved for deployment.**
