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
