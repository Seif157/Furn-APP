# Applying the security SQL to the live project

Written 2026-09-18, when the user decided to apply the security packages to the
live project the app uses, the evening before the 2026-09-19 demo. This
replaces the documented "fake-data testing branch first" step with a direct
live application, by the user's decision. Everything else in the documented
order still applies.

Every file is pasted into the Supabase dashboard: **SQL Editor → New query**.
The backend holds only the publishable key and cannot run any of this, which
is correct.

## Order

```text
0  status check + backup
1  3.2B  preflight → core → verify (14 sections) → smoke test
2  3.2C  preflight → core → verify (20 sections) → smoke test
3  3.2D  HELD until the backend and Flutter are ready (see the end)
```

Stop at the first failure. Do not skip ahead. Each core migration is one
transaction: if it fails part-way, nothing changes.

## 0. Before anything

**Status check.** Tells us which packages the live project already has. Read
only.

```sql
select
  count(*) filter (where policyname like 'phase32b\_%') as phase32b_policies,
  count(*) filter (where policyname like 'phase32c\_%') as phase32c_policies,
  count(*) filter (where policyname like 'phase32d\_%') as phase32d_policies,
  (select count(*) from pg_proc
     where pronamespace = 'public'::regnamespace
       and proname in ('is_admin', 'current_marketplace_party_id',
                       'current_party_is_approved')) as phase32b_helpers,
  current_setting('server_version') as postgres_version
from pg_policies
where schemaname = 'public';
```

**Backup.** There is no tested undo script. If a migration succeeds and then
breaks the app, a restore is the undo, so take one first:

- Paid plan: Dashboard → Database → Backups. Confirm a backup from today
  exists, or create one.
- Free plan: there are no dashboard backups. Use `pg_dump` with the
  connection string from Dashboard → Connect, on your own machine. Never paste
  the database password into chat.

## 1. Phase 3.2B

1. Paste `sql/phase-3.2b-security-hardening-preflight.sql`, run it. It ends
   in `ROLLBACK`, so it changes nothing. **Success** is "Success. No rows
   returned". Any `ERROR` is a stop: send the message.
2. Paste `sql/phase-3.2b-security-hardening.sql`, run it. Success is the same
   message. It checks everything again inside its own transaction before
   changing anything.
3. Open `sql/phase-3.2b-security-hardening-verify.sql`. Select section 01 up
   to the start of section 02, press **Run selected**, and repeat for each
   section through 13. Then run section 14, the summary: every row must pass.
   If a row fails, send the section and the failing row.
4. Smoke test (below).

Do **not** run `sql/phase-3.2b-supabase-admin-default-privileges-optional.sql`.
It was never part of the reviewed application.

## 2. Phase 3.2C

0. Gate: only start once every 3.2B verification section passed. The 3.2C
   preflight does **not** check that 3.2B is applied (only 3.2C's
   verification section 16 does), so running 3.2C without 3.2B could succeed
   and leave a combination nobody reviewed.
1. Paste `sql/phase-3.2c-security-hardening-preflight.sql`, run it. Ends in
   `ROLLBACK`.
2. Paste `sql/phase-3.2c-security-hardening.sql`, run it.
3. Run each of the 20 sections of `sql/phase-3.2c-security-hardening-verify.sql`
   separately, as above. Each must pass.
4. Smoke test.

What changes for the app after 3.2C:

- **Reviews.** A signed-in user can read only their own reviews directly.
  Product and seller review lists must come from `GET /v1/reviews/public`
  (built 2026-09-18, works before and after 3.2C). Flutter must switch to it.
- Anonymous visitors see only the seven safe review columns.
- `current_customer_profile_id()` is no longer callable anonymously.
- Furnishing requests move between states through
  `open_furnishing_request` / `withdraw_furnishing_request`, not by direct
  updates to `lifecycle_state`.
- The service directory shows only active services.

## Smoke test after each package

1. Backend, signed in (PowerShell, not Git Bash):
   `uv run python -m scripts.live_search_smoke`
   It must end with PASSED.
2. In the Flutter app, walk the demo path by hand: sign in, browse, open a
   product, its reviews, search, plan a room. Anything that errors is a stop.

If step 2 breaks something the demo needs and it cannot be fixed quickly,
restore the backup.

## 3. Phase 3.2D: held

3.2D changes what the Flutter app itself may do, and the replacements do not
exist yet:

- Carts are created by the backend using the privileged Supabase key. The app
  can no longer insert a cart, so "add to cart" fails for a user who has
  none.
- Sellers change order state only through `advance_purchase_order`; customers
  cancel only through `cancel_purchase_order`.
- Service requests are created `pending` with no seller and change state only
  through four functions.
- Reviews can no longer be edited or deleted, and must reference a delivered
  order or a completed service request.
- `marketplace_party` must be selected column by column; `user_id` is never
  returned.

Applying it before the backend has a cart endpoint (which needs the Supabase
secret key on the server, a decision in itself) and before Flutter calls the
functions above would break checkout. Apply it after both are ready, in the
same way: preflight, core, 12 verify sections, and then
`scripts/live_phase_3_2d_acceptance.py`.

## Record

After each package, note here the date, who ran it, and which verification
sections passed. Until then, CLAUDE.md keeps reporting it as not executed.

### 2026-09-18, run by the user in the SQL Editor

- Status check: 36 `phase32b_` policies, 0 `phase32c_`, 0 `phase32d_`, 3
  helpers, PostgreSQL 17.6. **3.2B was already applied to the live project**,
  although the 3.2B document only records a testing-branch run.
- 3.2B verification summary (section 14): all 13 sections passed, every
  `failed_count` 0.
- 3.2C preflight, first live run: failed four times, each time on a bug in the
  package rather than drift in the database. Every fix makes the file match
  the evidence recorded from the live database:
  1. `42P01 relation "review" does not exist`. The files set
     `search_path = pg_catalog` and then cast unqualified names such as
     `'review'::pg_catalog.regclass`, which resolve only in `pg_catalog`. Fixed
     by qualifying with `public.` in 3.2C (13 names) and in the 3.2D generator
     (15 names). `tests/test_security_sql_name_resolution.py` now fails on
     any recurrence.
  2. `review target-kind enum drift`. The check expected `product,
     marketplace_party, service_request`; live and the recorded evidence are
     `product, service_request, marketplace_party`.
  3. `target policy baseline drift`. Three policies were expected on role
     `public`; live and the recorded evidence are `{anon,authenticated}`,
     which is narrower. Confirmed with a read-only diagnostic.
- 3.2C preflight after the fixes: **Success. No rows returned.** Nothing
  changed.
- The byte pins on the two 3.2C files were updated with the user's approval.
- Free plan, so no restorable backup. Instead a read-only snapshot query
  captured the live definitions of everything 3.2C changes (the customer
  profile helper, four policies, grants on `review`, `furnishing_request` and
  `order_financial_position`) and produced
  `rollback/phase-3.2c-undo-2026-09-18.sql`. It reverses 3.2C exactly and
  touches no data rows. It lives outside `sql/` because only reviewed
  migrations may contain DDL there. Run it in the SQL Editor only if 3.2C must
  be reversed.
- 3.2C migration, first live run: `42704 type "pg_catalog.boolean" does not
  exist`, rolled back, nothing changed. Two more authoring bugs, fixed in 3.2C
  and the 3.2D generator:
  4. `pg_catalog.boolean` and `pg_catalog.integer` are not type names; the
     qualified names are `pg_catalog.bool` and `pg_catalog.int4`.
  5. An empty search path is stored as `search_path=""` (confirmed live on
     `is_admin`, which 3.2B set up the same way), so post-change checks that
     required exactly `search_path=` would have failed next. They now accept
     both spellings, as 3.2B does.
  A read-only query also confirmed the helper's current grantees are only
  PUBLIC, postgres, anon, authenticated and service_role, all covered by the
  migration's REVOKE.
- 3.2C migration, second live run: every change executed, then the
  postflight stopped with `22023 ACL arrays must be one-dimensional` and the
  whole transaction rolled back. Bug 6:
  `aclexplode(COALESCE(attribute.attacl, ARRAY[]::pg_catalog.aclitem[]))`
  hands aclexplode a zero-dimensional array for any column without its own
  grants. `aclexplode(attribute.attacl)` means the same (it is STRICT, so a
  NULL list gives no rows). Fixed in the migration, the verification file
  (two places) and the 3.2D generator. The migration's granted columns were
  also checked mechanically against the postflight's expected columns: 10
  for INSERT and 9 for UPDATE, identical.
- **3.2C migration, third live run: applied.** "Success. No rows returned",
  committed with every postflight check passing. The file run was commit
  `a34159d` (sha256 of the CRLF checkout `8b04c44d…`).
- 3.2C verification, first run (all 20 sections in one read-only query): 18
  passed. Two failed on bugs in the verification file, each confirmed against
  live data with a read-only diagnostic before any change:
  7. Section 11 required `public.address` in policy text. The migration's
     postflight ran with `search_path = pg_catalog` and saw the qualified
     name; the SQL Editor has `public` on its path, so pg_policies prints
     `address`. The live policies are exactly right (draft-only insert on an
     owned address, update and delete only while draft or open). The check
     now accepts either spelling and still requires the `address` table under
     the alias `request_address`.
  8. Section 20 counted the storage owner's own default privileges (12 rows,
     all `postgres`, none grantable) as unexpected. The 3.2B check that
     passed live excludes them with `acl.grantee <> defaclrole`; this copy did
     not. 3.2C does not touch storage.
- **3.2C verification, second run: all 20 sections passed**, every
  `failed_count` 0 (section 11: 3 of 3; section 20: 36 of 36).
- Backend check after 3.2C (read-only): `GET /v1/reviews/public` returns 200
  as anon, so the seven-column anon grant works as designed; `/health` 200.
- **Signed-in smoke test after 3.2C: PASSED** (2026-09-18 22:02, run by the
  user as a customer account). Through the real Supabase Auth check and the
  3.2C policies: Arabic and English search with reasons and nearest
  alternatives, a conversational follow-up (sofa and 30,000 kept, grey added),
  `/v1/meta`, anonymous public reviews, similar products, comparison, and a
  room plan within budget. Real products appear alongside the seed.
- Still to do for 3.2C: the Flutter walkthrough, and the staged live
  acceptance utility `scripts/live_phase_3_2c_acceptance.py`, which needs
  fixture accounts and has not been run.
- The snapshot shows that before 3.2C, anon and authenticated held INSERT,
  UPDATE, DELETE, TRUNCATE, TRIGGER, REFERENCES and MAINTAIN on the
  `order_financial_position` view. 3.2C removes them; the undo would restore
  them, because its job is exact restoration.
- Server-side cart (`POST /v1/cart`, the 3.2D cart design) built with the
  Supabase secret key and passed live at 22:54: the first call created
  customer2's cart, the second returned it.

### 2026-09-18, Phase 3.2D preflight (read-only, always rolls back)

- First run stopped at `Phase 3.2D replaced policy drift`; nothing changed.
  Bug 9: the check compared the 13 replaced policies' text exactly with text
  recorded in the SQL Editor, but the preflight narrows the search path, so
  the same policies print `public.current_customer_profile_id()` and
  `FROM public.cart`. A read-only diagnostic running the identical comparison
  in the SQL Editor returned no rows: every policy matched apart from the
  qualifier. The comparison now strips `public.` first (commit `b65dd89`),
  as the column check already did for defaults.
- **Second run: Success. No rows returned.** The live database matches
  everything 3.2D expects: 3.2C applied, helpers, the 18 FOR ALL policies,
  the 13 replaced policies, the 104-column inventory, the 312-row privilege
  baseline, constraints and enum labels.
- **3.2D is NOT applied.** Before it is: Flutter must call `POST /v1/cart`
  instead of inserting carts, use `advance_purchase_order` /
  `cancel_purchase_order` for order status and the four service-request
  functions, and stop editing or deleting reviews. Then, as for 3.2C: take an
  undo snapshot of everything 3.2D changes, run the migration, run its 12
  verification sections, run the smoke test, and run
  `scripts/live_phase_3_2d_acceptance.py`.

### 2026-09-18/19, Phase 3.2D and checkout applied

- 3.2D undo captured first: `rollback/phase-3.2d-undo-2026-09-18.sql` (the
  snapshot mechanism passed a replica round trip). Not run.
- 3.2D migration, first run: `postflight policy inventory mismatch`, rolled
  back. A dry run (preflight and changes, then a block that reports the drift
  and raises, so it cannot commit) showed bug 10: one expected policy listed a
  single role literally named "anon,authenticated". Fixed (`80bd2a1`).
- Full rehearsal (the whole migration with COMMIT replaced by a raise):
  `postflight transition function mismatch`. Bug 11: the check required
  `lifecycle_state::text = 'pending'` in every function, but
  advance_purchase_order lists its allowed (from, to) pairs. Fixed (`7bedfb2`);
  the rehearsal then reported every check passing.
- **3.2D migration: applied** from `7bedfb2`, byte-identical to the passing
  rehearsal up to COMMIT. **Verification 12/12.**
- **Checkout migration (`migrations/checkout-2026-09-18.sql`, `071ea16`):
  applied**, after passing 33 checks on a local PostgreSQL replica built from
  the recorded schema with 3.2D's real order functions.
- **Smoke test with `--checkout` as customer1: PASSED** at 00:06: the cart was
  created, `place_order` ordered one Cairo sofa (stock 8 -> 7),
  `cancel_purchase_order` cancelled it (stock 7 -> 8), and search, follow-ups,
  similar, compare, reviews and room planning all work under 3.2D.
- Known gap left by 3.2D: the app can no longer insert
  `furnishing_request_design_version`; the design expects a backend AI step
  that is not built.
