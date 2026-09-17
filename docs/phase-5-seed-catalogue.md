# Phase 5 seed catalogue

Status: **Rendered locally; not applied to any database.**

Search evaluation needs more than the four real products the Phase 4A audit
found. This seed defines 44 fake products that follow every convention the
audit recorded, so anything that works on the seed works on real rows.

## One definition, two uses

`tests/seed_catalogue.py` is the single source of truth. From it:

- `as_json_fixture()` produces the PostgREST-shaped payload the gateway would
  return, so offline tests and the Phase 5 evaluation run against the seed
  without touching Supabase. `tests/test_seed_catalogue.py` already runs the
  Phase 4D search over it.
- `seed/phase-5-fake-catalogue.sql`, `seed/phase-5-fake-catalogue-remove.sql`,
  and `seed/phase-5-fake-catalogue-images.sql` are rendered from the same data
  for the fake-data testing branch. A test asserts all three files on disk are
  byte-identical to the renderer; never hand-edit them.

The seed lives under `seed/`, not `sql/`, because the repository's tests
forbid application row DML under `sql/`, which is reserved for reviewed
migrations.

## What the seed contains

| Group | Count | Purpose |
|---|---:|---|
| Published, in stock, with dimensions | 40 | 8 per category: beds, dining, sofas, wardrobes, chairs; four styles; every colour and material in the Phase 4B vocabularies used at least once; a third discounted; every fifth without weight |
| Published, in stock, no dimensions | 1 | proves dimension constraints exclude unknown sizes |
| Published, no stock in any colour | 1 | proves the stock rule |
| Draft | 1 | must never appear |
| Hidden | 1 | must never appear |

Conventions matched from the audit: category names `Arabic — English`, colour
values `Arabic — English`, Arabic material tokens, Arabic names, English
descriptions, centimetre dimensions, and `SEED-NNN` SKUs. Product, colour, and
image identifiers are fixed UUIDs in the `7a`, `7b`, and `7c` ranges so reruns
are reproducible. Every product carries a real furniture photograph from
Unsplash, chosen from an eight-photo pool for its own category by product
number, so the assignment is deterministic and a sofa never illustrates a
bed. Each photo id was fetched on 2026-09-17 and confirmed to return an
image; none is a guess.

## Running it on the fake-data testing branch

Only a human runs this, and only on the testing branch.

1. Open `seed/phase-5-fake-catalogue.sql` in the Supabase SQL Editor for the
   testing branch and run it whole. It is one transaction. Its preflight stops
   with a clear error if the five active bilingual categories are missing, if
   no approved seller exists, or if `SEED-` products are already present.
2. The products are attached to the first approved seller by id.
3. To remove them, run `seed/phase-5-fake-catalogue-remove.sql`. It deletes
   only rows whose product has a `SEED-` SKU, children first.
4. If the seed is already loaded and only the images changed, run
   `seed/phase-5-fake-catalogue-images.sql` instead of reseeding. It updates one
   column on rows owned by `SEED-` products, inserts and deletes nothing, and is
   safe to run more than once. A test asserts it contains no `INSERT`, `DELETE`,
   `DROP`, or `TRUNCATE`.

After seeding, the Phase 3.1 live smoke should report 41 eligible products
instead of 4, and Phase 4A audit sections 05 and 07 will show the full
vocabulary.

## Not in scope

No enrichment attributes are seeded, so style and room-type preferences still
score zero on live data until sellers confirm attributes; the offline fixture
carries none either, deliberately matching the audit. No orders, reviews, or
customer data are seeded.
