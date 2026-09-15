# Phase 3.2D scoping — deferred finding decision packs

Status: **Planning only; no SQL, no migration, no live access.**

Phase 3.2C left 56 items classified `deferred_with_named_blocker`: 10 `FOR ALL` policies from the Section 03 ledger and 46 findings from the Section 12 ledger. Every blocker is a business or workflow decision, not a SQL defect. This document turns those blockers into four decision packs. Each pack states what the evidence shows, the questions that were put to the product owner, the recorded decision from `docs/phase-3.2d-decisions.md`, and the SQL shape that follows. Where the evidence settles a finding outright, the pack proposes a disposition for human confirmation.

Nothing here changes the database. The Phase 3.2C package remains: **Human security review required; not approved for deployment.**

## Evidence contract

All inputs are user-supplied, read-only catalog exports and are treated as immutable. A local test fails if any of them drifts from the counts below or from each other.

| File | Content | Reconciled facts |
|---|---|---|
| `docs/evidence/phase-3.2c/section-03-for-all.csv` | Complete predicates of the 19 `FOR ALL` policies | 19 policy rows |
| `docs/evidence/phase-3.2c/section-12-findings.csv` | The 122 audit findings | 122 rows |
| `docs/evidence/phase-3.2d/section-02-policies.csv` | Complete policy inventory: every public policy with mode, roles, command, `USING`, `WITH CHECK` | 114 policies, 34 tables, 19 `FOR ALL`, 89 permissive, 25 restrictive; its `FOR ALL` set equals Section 03 exactly |
| `docs/evidence/phase-3.2d/section-05-operation-review.csv` | Every policy expanded per effective operation with the audit's static signals | 171 rows over the same 114 policies |
| `docs/evidence/phase-3.2d/column-inventory.csv` | Exact column signature (ordinal, type, nullability, default, identity, generated) | 149 columns over 18 tables |
| `docs/evidence/phase-3.2d/column-privileges.csv` | Effective table and column SELECT/INSERT/UPDATE per API role | 447 rows: 18 tables, 3 roles |
| `docs/evidence/phase-3.2d/state-enums.csv` | Every enum used by a candidate table, with ordered labels | 41 labels over 11 enums |
| `docs/evidence/phase-3.2d/constraints.csv` | Primary, unique, foreign-key, and check constraints, with delete rules | 103 constraints over 18 tables |

Section 02 contains no `phase32c_*` policy and still contains `furnishing_request_write_own`, so every export records the deployed state **before** the Phase 3.2C migration. All 25 restrictive policies are Phase 3.2B catalogue guards; no other table has a restrictive guard.

The metadata is safe: names, types, policy text, roles, and Boolean flags only. No application rows, identifiers, credentials, or endpoints.

### Evidence completeness

All four column-level exports cover the same 18 tables, and a local test fails if the inventory ever disagrees with the privilege export column for column. The SQL package that implements this scoping lives in `sql/phase-3.2d-security-hardening*.sql` and is described in `docs/phase-3.2d-security-hardening.md`; every catalog block in it is generated from these exports by `tests/phase_3_2d_package.py`.

## What the column evidence changed

- **No state columns exist** on `customer_profile`, `design`, `design_version`, `design_product_reference`, or `party_capability`. The five Pack B findings have nothing to guard and become `audit_false_positive`.
- **One profile per user and one cart per customer are enforced** by `customer_profile_user_unique (user_id)` and `cart_customer_unique (customer_profile_id)`.
- **Address deletes are already blocked by the database** while a `purchase_order` or `service_request` references the address (`ON DELETE RESTRICT`). The `furnishing_request` foreign key is in the pending export.
- **Service request and purchase order UPDATE surfaces are already column-limited** by existing column ACLs, so the earlier "reassign the other party" hypothesis was wrong. What remains writable is the state itself: `service_request.lifecycle_state` and `completed_at` by either principal, and `purchase_order.lifecycle_state` by the seller.
- **A customer can create a service request that is already accepted.** Authenticated INSERT covers all 14 columns and the policy checks ownership only, so a customer may insert `lifecycle_state = 'accepted'`, any `marketplace_party_id`, `accepted_at`, and `price` in one statement and the check constraints are satisfied. This is the strongest finding in the package.
- **Purchase orders are server-created.** Authenticated holds INSERT on all 24 columns, but no INSERT or DELETE policy exists, so RLS denies both. The grants are dormant and should be revoked as hygiene.
- **The real state machines** are recorded below; the guessed transitions in the decision sheet are replaced by them.

## Priority order

| Order | Pack | Items | Why this order |
|---:|---|---:|---|
| 1 | C — principal scope | 5 findings, all high | Four resolve without SQL. The fifth, `service_request_insert_own`, allows self-assignment of a seller and is the top remediation. |
| 2 | A — `FOR ALL` operation scope | 10 policies | Decisions recorded; SQL can be drafted once the seven remaining inventories arrive. |
| 3 | B — initial state and transitions | 5 findings, all high | Closed by evidence: no state columns exist. |
| 4 | D — permissive overlap | 36 findings, all medium | 31 close by evidence; `marketplace_party` public columns need the grant change decided in D1. |

## Pack C — principal scope review (5 high findings)

| Finding | Table | Policy | Signal |
|---|---|---|---|
| phase32c_0025 | furnishing_request | furnishing_request_select | possible_cross_principal_read |
| phase32c_0030 | furnishing_request_design_version | furnishing_request_design_version_select | possible_cross_principal_read |
| phase32c_0036 | payment | payment_select_customer | possible_cross_principal_read |
| phase32c_0047 | refund | refund_select_customer | possible_cross_principal_read |
| phase32c_0055 | service_request | service_request_insert_own | possible_cross_principal_write |

### Complete predicates (Section 02)

| Policy | `USING` / `WITH CHECK` |
|---|---|
| furnishing_request_select | `(customer_profile_id = current_customer_profile_id()) OR ((lifecycle_state = 'open'::furnishing_request_state) AND current_party_is_approved())` |
| furnishing_request_design_version_select | `EXISTS (SELECT 1 FROM furnishing_request fr WHERE fr.id = furnishing_request_design_version.furnishing_request_id AND (fr.customer_profile_id = current_customer_profile_id() OR (fr.lifecycle_state = 'open'::furnishing_request_state AND current_party_is_approved())))` |
| payment_select_customer | `EXISTS (SELECT 1 FROM purchase_order po WHERE po.id = payment.order_id AND po.customer_profile_id = current_customer_profile_id())` |
| refund_select_customer | `EXISTS (SELECT 1 FROM purchase_order po WHERE po.id = refund.order_id AND po.customer_profile_id = current_customer_profile_id())` |
| service_request_insert_own | `WITH CHECK (customer_profile_id = current_customer_profile_id())` |

### Proposed dispositions

- **phase32c_0036 and phase32c_0047 → `audit_false_positive`.** Anchored to the owning customer through the parent order. Confirmed in decision C5.
- **phase32c_0025 and phase32c_0030 → `accepted_with_evidence`.** The owner branch is exact; the second branch is the marketplace feature that lets approved sellers read open requests to make offers. Decision C1 keeps budget and deadline visible to sellers. Address rows stay protected by `address_select_own_or_engaged`, which gives a seller an address only through a non-pending `service_request` or a `purchase_order`.
- **phase32c_0055 → `remediated` in Phase 3.2D.** See the service request section below.

### Service request: evidence and remediation

Columns (14): `id`, `customer_profile_id`, `service_type_id`, `marketplace_party_id` (nullable), `address_id`, `related_order_id` (nullable), `scheduled_date`, `scheduled_time`, `details`, `price` (nullable), `lifecycle_state` (default `pending`), `accepted_at`, `completed_at`, `created_at` (default `now()`).

States, in enum order: `pending`, `accepted`, `in_progress`, `completed`, `cancelled`.

Check constraints already enforce: any state other than `pending` or `cancelled` requires `marketplace_party_id`, `accepted_at`, and `price`; `completed` requires `completed_at`.

Effective authenticated privileges today: INSERT on all 14 columns; table UPDATE denied; column UPDATE on `scheduled_date`, `scheduled_time`, `details`, `lifecycle_state`, `completed_at`. Policies: `service_request_insert_own` (owner only) and `service_request_update_engaged` (customer OR assigned seller, all five columns).

Decisions C2, C3, C4, and the service request block of the decision sheet give:

- **INSERT allowlist:** `customer_profile_id`, `service_type_id`, `address_id`, `related_order_id`, `scheduled_date`, `scheduled_time`, `details`. Denied: `id`, `marketplace_party_id`, `price`, `lifecycle_state`, `accepted_at`, `completed_at`, `created_at`. `WITH CHECK`: owner, `lifecycle_state = 'pending'`, `marketplace_party_id IS NULL`, `address_id` owned by the customer, and `related_order_id` null or an order owned by the customer.
- **Customer UPDATE allowlist:** `scheduled_date`, `scheduled_time`, `details`, only while `lifecycle_state = 'pending'`, owner preserved in `WITH CHECK`.
- **Seller direct UPDATE:** none. The existing `service_request_update_engaged` policy is replaced.
- **Transition functions** (SECURITY DEFINER, `SET search_path = ''`, uniform Boolean, EXECUTE for `authenticated` and `service_role` only), following the 3.2C shape:
  - `cancel_service_request(uuid)`: owner, `pending` → `cancelled`.
  - `accept_service_request(uuid, price numeric)`: approved seller with a `party_capability` for the request's `service_type_id`, `pending` → `accepted`; sets `marketplace_party_id` to the caller's party, `accepted_at = now()`, and `price`.
  - `start_service_request(uuid)`: assigned seller, `accepted` → `in_progress`.
  - `complete_service_request(uuid)`: assigned seller, `in_progress` → `completed`; sets `completed_at = now()`.

Residual questions recorded in the decision sheet: **S1** whether `in_progress` is a real step or `accepted` → `completed` is enough; **S2** whether the seller may set `scheduled_date` and `scheduled_time` after acceptance; **S3** whether `price` is fixed at acceptance or editable later by the seller.

## Pack A — `FOR ALL` operation scope review (10 policies)

A `FOR ALL` policy applies one predicate to SELECT, INSERT, UPDATE, and DELETE. Section 05 flags every customer-owned policy below with `possible_cross_principal_write` on INSERT, UPDATE, and DELETE because the predicate is ownership-only. The Phase 3.2C `furnishing_request` split is the template: keep the owner predicate, split by operation, deny DELETE where the product does not need it, lock rows by state, and grant INSERT/UPDATE only on a column allowlist.

Predicates are quoted from the Section 03 evidence. In every case `USING` and `WITH CHECK` are identical. The "Decision" column is the recorded answer from the decision sheet.

### A1 — customer-owned, direct ownership column

| Table | Policy | Predicate |
|---|---|---|
| address | address_write_own | `customer_profile_id = current_customer_profile_id()` |
| cart | cart_all_own | `customer_profile_id = current_customer_profile_id()` |
| saved_space | saved_space_all_own | `customer_profile_id = current_customer_profile_id()` |
| review | review_write_own | `customer_profile_id = current_customer_profile_id()` |

Decisions:

- **address:** insert, update, delete; delete blocked while referenced. The database already restricts deletes referenced by `purchase_order` and `service_request`; the DELETE policy will repeat the condition so the client receives a policy denial rather than a constraint error, and will include `furnishing_request` once its foreign key is confirmed.
- **cart:** one cart per customer (enforced by `cart_customer_unique`), created server-side. Client: update and delete only. INSERT policy removed.
- **saved_space:** insert, update, delete.
- **review:** insert only, final. Targets immutable. Verified purchase or service required (see below). No UPDATE or DELETE policy.

Immutable on all four: `id`, `customer_profile_id`, `created_at` where present.

**Review verification `WITH CHECK`**, using the constraint `review_exactly_one_target` and the enum `review_target_kind`:

- `product`: an `order_line_item` with that `product_id` on a `purchase_order` owned by the customer.
- `service_request`: a `service_request` owned by the customer with that id.
- `marketplace_party`: a `purchase_order` owned by the customer with that `marketplace_party_id`, or an owned `service_request` assigned to that party.

Residual question **R1**: must the order be `delivered` and the service request `completed`, or does any order or request count?

### A2 — customer-owned through a parent row

| Table | Policy | Predicate |
|---|---|---|
| cart_line | cart_line_all_own | `EXISTS (SELECT 1 FROM cart c WHERE c.id = cart_line.cart_id AND c.customer_profile_id = current_customer_profile_id())` |
| furnishing_request_design_version | furnishing_request_design_version_write_own | `EXISTS (SELECT 1 FROM furnishing_request fr WHERE fr.id = furnishing_request_design_version.furnishing_request_id AND fr.customer_profile_id = current_customer_profile_id())` |

Decisions:

- **cart_line:** insert, update, delete. The product reference is `product_color_id`; `cart_line_unique_per_color (cart_id, product_color_id)` prevents duplicates. Immutable: `id`, `cart_id`, `product_color_id`. The published-and-in-stock condition at insert reuses the 3.2B catalogue predicate.
- **furnishing_request_design_version:** server-created through `service_role`; the customer may delete only while the parent request is `draft` or `open`. It is a link table with primary key `(furnishing_request_id, design_version_id)`, so there is nothing to update; no INSERT or UPDATE policy for authenticated.

### A3 — seller-owned

| Table | Policy | Predicate |
|---|---|---|
| custom_offering | custom_offering_write_own | `marketplace_party_id = current_marketplace_party_id() AND current_party_is_approved()` |
| party_capability | party_capability_write_own | `marketplace_party_id = current_marketplace_party_id()` |
| offer_line_item | offer_line_item_write_own | `EXISTS (SELECT 1 FROM offer o WHERE o.id = offer_line_item.offer_id AND o.marketplace_party_id = current_marketplace_party_id() AND o.lifecycle_state = 'submitted'::offer_state)` |

Decisions:

- **custom_offering:** insert, update, delete; delete blocked once a `purchase_order` references it (`purchase_order_custom_offering_fk` already restricts; the policy repeats it). `publication_state` is a Phase 3.2B-verified column and stays client-writable as today; immutable `id`, `marketplace_party_id`, `created_at`.
- **party_capability:** require `current_party_is_approved()`; insert and delete (the row is only `marketplace_party_id`, `service_type_id`, `declared_at`, so there is nothing to update). Immutable `marketplace_party_id`.
- **offer_line_item:** insert, update, delete while the offer is `submitted`. Immutable `id`, `offer_id`.

### A4 — user-owned through design

| Table | Policy | Predicate |
|---|---|---|
| design_product_reference | design_product_reference_write_own | `EXISTS (SELECT 1 FROM design d WHERE d.id = design_product_reference.design_id AND d.originating_user_id = auth.uid())` |

Decision: keep `auth.uid()` ownership. The table is a link with primary key `(design_id, product_id)` and no other columns, so the split is insert and delete only.

## Pack B — initial state and transition review (5 high findings)

| Finding | Table | Policy | `WITH CHECK` (Section 02) | Proposed disposition |
|---|---|---|---|---|
| phase32c_0021 | customer_profile | customer_profile_insert_own | `user_id = auth.uid()` | audit_false_positive |
| phase32c_0022 | design | design_insert_own | `originating_user_id = auth.uid()` | audit_false_positive |
| phase32c_0023 | design_product_reference | design_product_reference_write_own | see Pack A4 | audit_false_positive |
| phase32c_0024 | design_version | design_version_insert_own | `EXISTS (SELECT 1 FROM design d WHERE d.id = design_version.design_id AND d.originating_user_id = auth.uid())` | audit_false_positive |
| phase32c_0035 | party_capability | party_capability_write_own | see Pack A3 | audit_false_positive |

Section 05 raises `possible_owner_only_insert_check` on all five because the INSERT predicate checks ownership only. The column inventory shows that none of the five tables has a state column of any kind: `customer_profile` holds profile fields, `design` holds derivation links, `design_version` holds generated-image fields and a `version_sequence`, and the two link tables hold only their keys and a timestamp. An ownership-only INSERT check is therefore the complete rule. `customer_profile_user_unique` additionally enforces one profile per user. No SQL. The `party_capability` approval requirement is handled in Pack A3 as an ownership question, not a state question.

## Pack D — permissive overlap business review (36 medium findings)

Multiple permissive policies on the same table and operation combine with OR. That is by design when the policies are "own rows" plus "admin sees all", and a risk only when the union is wider than intended. Section 05 gives the co-applying policy count per operation; Section 02 shows that all 21 `*_admin` policies are exactly `is_admin()`.

| Table | Flagged policies | Findings |
|---|---|---|
| address | address_select_own_or_engaged, address_write_own | phase32c_0056, phase32c_0057 |
| design | design_select_admin, design_select_own | phase32c_0064, phase32c_0065 |
| design_product_reference | design_product_reference_select_own, design_product_reference_write_own | phase32c_0066, phase32c_0067 |
| design_version | design_version_select_admin, design_version_select_own | phase32c_0068, phase32c_0069 |
| furnishing_request | furnishing_request_select, furnishing_request_select_admin | phase32c_0070, phase32c_0071 |
| furnishing_request_design_version | furnishing_request_design_version_select, furnishing_request_design_version_write_own | phase32c_0073, phase32c_0074 |
| marketplace_party | marketplace_party_select_admin, marketplace_party_select_own, marketplace_party_select_public | phase32c_0075, phase32c_0076, phase32c_0077 |
| offer | offer_select_admin, offer_select_own_or_requesting_customer | phase32c_0078, phase32c_0079 |
| offer_line_item | offer_line_item_select, offer_line_item_select_admin, offer_line_item_write_own | phase32c_0080, phase32c_0081, phase32c_0082 |
| order_line_item | order_line_item_select_admin, order_line_item_select_engaged | phase32c_0083, phase32c_0084 |
| party_capability | party_capability_write_own | phase32c_0086 |
| payment | payment_select_admin, payment_select_customer | phase32c_0087, phase32c_0088 |
| purchase_order | purchase_order_select_admin, purchase_order_select_engaged | phase32c_0110, phase32c_0111 |
| refund | refund_select_admin, refund_select_customer | phase32c_0112, phase32c_0113 |
| review | review_select_admin, review_write_own | phase32c_0114, phase32c_0116 |
| service_request | service_request_select, service_request_select_admin | phase32c_0117, phase32c_0118 |
| service_type | service_type_write_admin | phase32c_0120 |
| settlement | settlement_select_admin, settlement_select_own | phase32c_0121, phase32c_0122 |

### Proposed dispositions by group

- **Own-plus-admin pairs → `accepted_with_evidence` (22 findings).** design, design_version, offer, order_line_item, payment, purchase_order, refund, settlement, service_request read pairs, and the admin halves of furnishing_request and offer_line_item. The engaged definitions are explicit: `purchase_order_select_engaged` is customer or seller of the order; `order_line_item_select_engaged` is the same through the parent order; `offer_select_own_or_requesting_customer` is the offering seller or the customer whose furnishing request the offer answers; `service_request_select` is the customer, the assigned seller, or an approved seller with a matching capability while the request is `pending`. Confirmed in decision D3.
- **`FOR ALL` write policies flagged on SELECT → resolved by Pack A (7 findings).** `address_write_own`, `design_product_reference_write_own`, `furnishing_request_design_version_write_own`, `offer_line_item_write_own`, `party_capability_write_own`, `review_write_own`, and `service_type_write_admin` overlap on SELECT only because `FOR ALL` includes SELECT. `service_type_write_admin` is admin-only and its public read is narrowed by Phase 3.2C, so it needs no split; it becomes `accepted_with_evidence`.
- **Already remediated by Phase 3.2C (2 findings).** `furnishing_request_select` overlap count 4 includes `furnishing_request_write_own`, which 3.2C removes; `review_write_own` overlaps `review_select_public`, which 3.2C narrows to anon only.
- **`marketplace_party` public read → decision D1: hide `user_id` and `state_reason` from the public (3 findings).** Today `anon` and `authenticated` both hold table-level SELECT on all eight columns, and `marketplace_party_select_public` exposes every approved party to both roles. Treatment, in the 3.2C `review` shape: revoke table-level SELECT from `anon` and grant `anon` column SELECT on `id`, `business_name`, `business_description`, `logo_url`, `coverage_area`, `approval_state`; revoke column SELECT on `user_id` from `authenticated` as well, which is safe because RLS policies evaluate `user_id` internally without a column grant. `state_reason` stays readable to `authenticated` so that an owner can read their own rejection reason. Residual question **M1**: confirm that approved parties carry no sensitive `state_reason`, or accept a SECURITY DEFINER reader for the owner instead.
- **`address_select_own_or_engaged` → decision D2: keep access while linked (2 findings).** `accepted_with_evidence`.

## Purchase order: observed outside the ledger

Not a ledger row. Recorded here because the evidence shows a direct state write, and it enters the 3.2D ledger with its own identifier.

Columns (24) include `lifecycle_state` (default `pending`), `cancelled_at`, `notes`, amounts, shipping snapshot fields, and origin references. States, in enum order: `pending`, `confirmed`, `preparing`, `out_for_delivery`, `delivered`, `cancelled`. `purchase_order_cancelled_timestamp` requires `cancelled_at` when cancelled.

Effective authenticated privileges today: INSERT on all 24 columns but no INSERT policy, so inserts are denied and orders are server-created; table UPDATE denied; column UPDATE on `lifecycle_state` and `notes` through `purchase_order_update_party` (`marketplace_party_id = current_marketplace_party_id()`, no state guard). No customer UPDATE policy exists, so customers cannot cancel today.

Decision (purchase order block): the seller edits nothing directly. Treatment: revoke the dormant authenticated INSERT; revoke column UPDATE on `lifecycle_state`; keep `notes` updatable by the owning seller; add `advance_purchase_order(uuid, order_state)` for the owning seller with the strict forward map `pending → confirmed → preparing → out_for_delivery → delivered`, and `cancel_purchase_order(uuid)` that sets `cancelled_at = now()`. Residual questions **P1**: which states may the customer cancel from (default: `pending` only); **P2**: whether the seller may cancel at all (default: no, admin or server only).

## Decision checklist

Answered on 2026-09-15 and recorded in `docs/phase-3.2d-decisions.md`: C1–C5, all ten Pack A tables, D1–D3, and the service request and purchase order blocks. Still open, with defaults stated above: S1, S2, S3, R1, M1, P1, P2, and the seven-table inventory re-export.

## What the Phase 3.2D package will contain

- A core migration with embedded preflight and postflight, one transaction, `SET LOCAL` safeguards, and exact fail-closed catalog checks for every touched table, following the 3.2C `furnishing_request` inventory pattern.
- A standalone rollback-only preflight whose DO block is byte-identical to the core preflight.
- A SELECT-only verification file with one uniform result row per section.
- Static tests that reconcile the new dispositions against this document bidirectionally, parse all SQL with pglast, and pin Phase 3.2B and 3.2C SQL by digest.
- An updated ledger in which each of the 56 items moves to `remediated`, `accepted_with_evidence`, or `audit_false_positive`, plus a new row for the purchase order state write.

Final status of the deployed security posture remains: **Human security review required; not approved for deployment.**
