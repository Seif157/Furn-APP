# Phase 3.2D decision sheet

Answered 2026-09-15 with the product owner. How to use this file: every line that starts with `answer:` is pre-filled with the fail-closed default from `docs/phase-3.2d-scoping.md`. Keep a line as it is if the default matches how the product should work. Change it if not. Add a short note after `because:` when the reason is not obvious. Do not delete questions; write `answer: default` if you have no opinion.

Words used below:

- **customer** = a signed-in user acting through their `customer_profile`.
- **seller** = a signed-in user acting through their `marketplace_party`. "Approved seller" means `approval_state = 'approved'`.
- **admin** = a user for whom `is_admin()` is true.
- **immutable** = the client can never write the column; only the database default or server-side code sets it.

## Pack C — who may read or insert

### C1 — open furnishing requests visible to sellers

Today every approved seller can read every column of every request whose state is `open`, so they can make offers. This includes `budget_min`, `budget_max`, and `offer_deadline`.

- Option A: keep it. Sellers see budget and deadline.
- Option B: hide budget and deadline from sellers; only the owning customer sees them.

answer: A
because: sellers use budget and deadline to shape offers; address rows stay protected separately

### C2 — service request initial state

When a customer creates a service request, which `lifecycle_state` must it start in?

answer: pending
because: default confirmed

### C3 — service request address ownership

Must the `address_id` on a new service request point to an address the same customer owns?

answer: yes
because: default confirmed

### C4 — service request party assignment at creation

May the customer choose the seller (`marketplace_party_id`) when creating the request, or must it stay empty until a seller accepts?

- Option A: customer picks the seller at creation.
- Option B: empty at creation; assignment happens later.

answer: B
because: seller accepts a pending request later; customer never sets marketplace_party_id

### C5 — confirm proposed dispositions

- payment_select_customer and refund_select_customer: audit false positive (anchored through the customer's order).
- furnishing_request_select and furnishing_request_design_version_select: accepted with evidence, subject to C1.

answer: confirmed
because:

## Pack A — what customers and sellers may do on each table

For each table answer four things:

- **ops** — which of insert, update, delete the client app really performs. Anything not listed becomes impossible from the client.
- **immutable** — columns the client must never write. `id`, the owner column, and `created_at` are always immutable; list any others.
- **delete** — `allowed`, `never`, or a condition.
- **lock** — a state that freezes the row, if any.

### address

Referenced by furnishing requests, service requests, and purchase orders. Sellers read an address only through those references.

- ops: insert, update, delete
- immutable: id, customer_profile_id, created_at
- delete: never while referenced by any request or order
- lock: none

answer: ops insert,update,delete; delete blocked while referenced by any request or order
because:

### cart

- one cart per customer: yes
- ops: update, delete
- immutable: id, customer_profile_id, created_at
- delete: allowed
- lock: none

answer: one cart per customer, created server-side; client ops update,delete only
because:

### cart_line

- ops: insert, update, delete
- immutable: id, cart_id, product reference columns, created_at
- product must be published and in stock at insert: yes
- delete: allowed
- lock: none

answer: default; delete allowed
because:

### saved_space

- ops: insert, update, delete
- immutable: id, customer_profile_id, created_at
- delete: allowed
- lock: none

answer: default; delete allowed
because:

### review

- ops: insert
- edit after creation: no
- delete: never
- immutable: id, customer_profile_id, created_at, target_kind, target_product_id, target_marketplace_party_id, target_service_request_id
- must reference something the customer actually bought or used: yes

answer: insert only; no edit, no delete; targets immutable; verified purchase or service required once order_line_item product column is known
because: fake-review prevention

### furnishing_request_design_version

- ops: insert, update, delete
- immutable: id, furnishing_request_id, created_at
- delete: allowed while the parent request is draft or open
- lock: parent request not in draft or open
- versions created by the customer app (not server-side): yes

answer: server creates via service_role; customer reads; update/delete only while parent is draft or open
because: versions are produced by the backend AI step; change to customer-creates if the app inserts them

### custom_offering (seller)

- ops: insert, update, delete
- immutable: id, marketplace_party_id, created_at, any publication or approval state column
- delete: never once ordered
- lock: none

answer: default; delete blocked once ordered
because:

### party_capability (seller)

Today an unapproved seller can already declare capabilities. Every other seller write requires an approved seller.

- require approved seller: yes
- ops: insert, update, delete
- immutable: id, marketplace_party_id, created_at, any approval or activation column
- delete: allowed
- lock: none

answer: require approved seller; ops insert,update,delete; delete allowed
because: consistent with offers and custom offerings

### offer_line_item (seller)

Today lines can change only while the offer is `submitted`.

- ops: insert, update, delete
- immutable: id, offer_id, created_at
- delete: allowed while offer is submitted
- lock: offer not submitted

answer: default; delete allowed while offer is submitted
because:

### design_product_reference

Owned through `design.originating_user_id = auth.uid()`.

- keep user-id ownership (not customer or seller profile): yes
- ops: insert, update, delete
- immutable: id, design_id, created_at
- delete: allowed
- lock: none

answer: keep auth.uid() ownership; default
because:

## Pack B — state columns and transitions

These cannot be answered fully until the column inventory export exists. Answer what you know now; leave `unknown` otherwise.

### customer_profile

- one profile per signed-in user: yes
- state columns: unknown
- allowed initial value: unknown
- transitions the customer may perform: none

answer: audit false positive: no state column exists; one profile per user enforced by customer_profile_user_unique
because: column inventory 2026-09-15

### design

- state columns: unknown
- allowed initial value: unknown
- transitions the owner may perform: none

answer: audit false positive: no state column exists
because: column inventory 2026-09-15

### design_version

- state columns: unknown
- allowed initial value: unknown
- transitions the owner may perform: none

answer: audit false positive: no state column exists
because: column inventory 2026-09-15

### party_capability

- state columns: unknown
- allowed initial value: unknown
- transitions the seller may perform: none

answer: audit false positive: no state column exists; approval requirement handled in Pack A3
because: column inventory 2026-09-15

### service_request (observed outside the ledger)

Today the customer and the assigned seller can each update every column, including reassigning the other party and changing the state directly.

- customer may update: which columns? (default: address_id and description-type columns, only while pending)
- seller may update: which columns? (default: none directly; state changes through transition functions only)
- customer transitions: pending → cancelled
- seller transitions: pending → accepted, accepted → completed
- admin-only transitions: everything else

answer: customer edits scheduled_date, scheduled_time, details only while pending; seller edits nothing directly; customer pending->cancelled; seller pending->accepted (sets party, accepted_at, price), accepted->in_progress, in_progress->completed; open: S1 in_progress needed?, S2 seller sets schedule after acceptance?, S3 price editable after acceptance?
because: real enum: pending, accepted, in_progress, completed, cancelled

### purchase_order (observed outside the ledger)

Today the seller can update every column of an order.

- seller may update: which columns? (default: none directly; state changes through transition functions only)
- seller transitions: unknown
- customer transitions: unknown

answer: seller edits notes only; seller advances pending->confirmed->preparing->out_for_delivery->delivered via function; customer cancels from pending via function; open: P1 customer cancel states, P2 seller cancel
because: real enum: pending, confirmed, preparing, out_for_delivery, delivered, cancelled; orders are server-created

## Pack D — read overlaps

### D1 — public marketplace party columns

Anyone, including signed-out visitors, can read all eight columns of an approved seller: `id`, `user_id`, `business_name`, `business_description`, `logo_url`, `coverage_area`, `approval_state`, `state_reason`.

- Option A: keep all eight public.
- Option B: hide `user_id` and `state_reason` from the public.

answer: B
because: hide user_id and state_reason from public

### D2 — seller address access after completion

A seller can read a customer's address while a non-pending service request or any purchase order links them. Should that access end at some point?

- Option A: keep it forever.
- Option B: end it when the request or order reaches these states: (list them)

answer: A
because: access lasts while the linking request or order row exists

### D3 — confirm proposed group dispositions

- 22 own-plus-admin read pairs: accepted with evidence.
- 7 FOR ALL overlaps: resolved by the Pack A split.
- 2 overlaps already removed by Phase 3.2C.

answer: confirmed
because:

## Open residual questions (defaults apply until answered)

- S1: is `in_progress` a real seller step, or is `accepted -> completed` enough? default: keep in_progress.
- S2: may the seller set scheduled_date and scheduled_time after acceptance? default: no.
- S3: is price fixed at acceptance? default: yes.
- R1: must an order be delivered and a service request completed before it can be reviewed? default: yes.
- M1: may approved sellers' state_reason stay readable to signed-in users? default: yes.
- P1: from which states may a customer cancel an order? default: pending only.
- P2: may a seller cancel an order? default: no.

## Column inventory export

Statements 01, 02, and 04 of `sql/phase-3.2d-column-inventory-diagnostic.sql` were extended to cover address, cart, cart_line, saved_space, custom_offering, offer_line_item, furnishing_request_design_version, furnishing_request, and marketplace_party. Re-run those three and overwrite `column-inventory.csv`, `column-privileges.csv`, and `constraints.csv`.
