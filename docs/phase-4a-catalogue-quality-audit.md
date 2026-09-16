# Phase 4A: catalogue quality audit

Status: **Audit package ready for a read-only run; not yet run.**

Phase 4A is the first AI-foundation step in the master plan. Before any
normalization (Phase 4B) or search schema (Phase 4C) can be designed, the real
catalogue has to be measured against the normalization targets: dimensions,
units, materials, colours, styles, finishes, room types, capacity, categories,
and synonyms. This package measures it without changing anything and without
exporting product content.

It is independent of the pending Phase 3.2C and 3.2D security packages. It reads
the catalogue through the SQL Editor as the project owner, not through the API,
so RLS state does not affect it and it does not require either migration.

## Safety

`sql/phase-4a-catalogue-quality-audit.sql` contains twelve independently
runnable SELECT-only statements. Run each numbered statement separately in the
Supabase SQL Editor and export the result with Download CSV, not the on-screen
grid, to `docs/evidence/phase-4a/section-NN.csv`.

Every statement returns aggregates or catalogue vocabulary only:

- no product name, description, image URL, or row UUID;
- no seller business name, user identifier, address, or order data;
- category names, material tokens, colour tokens, enrichment kinds, and scalar
  enrichment values are returned, because they are the vocabulary that Phase 4B
  must normalize.

Section 10 is capped at 500 rows. No other statement can return more rows than
there are categories, vocabulary tokens, or enum states.

A local test parses the file, requires every statement to be a SELECT, and
rejects any projection of the private columns above.

## What each section measures and which target it serves

| Section | Measures | Normalization target |
|---:|---|---|
| 01 | Exact column signature of the seven catalogue tables | the complete schema Phase 4B designs against; the API currently selects only a subset |
| 02 | Products per lifecycle state and the recommendation-eligible count | catalogue size and how much of it search can use |
| 03 | Null, non-positive, and out-of-range rates plus min, median, max for width, height, depth, weight of eligible products | dimensions, units |
| 04 | Non-positive prices, discounts not below price, price spread | price fit and hard-constraint filtering |
| 05 | Distinct lower-cased material tokens with product counts, and products with no materials | materials, synonyms |
| 06 | Category inventory with total, published, and in-stock counts | categories, the initial high-demand category set |
| 07 | Distinct colour tokens with row, product, and in-stock counts, and published products with no stock | colours, synonyms |
| 08 | Products without images or primary image, multiple primaries, non-HTTPS URLs, colour-linked images | image grounding for recommendations |
| 09 | Enrichment kinds with value types inferred from the text (number, boolean, JSON-like, string) and confirmed versus proposed assignment counts | styles, finishes, room types, capacity, whatever else the enrichment layer already carries |
| 10 | Distinct scalar enrichment values per kind with assigned and confirmed product counts | the same, as vocabulary |
| 11 | Short or missing names and descriptions, units embedded in text, Arabic text presence, duplicate names per seller | text normalization, Arabic and English search |
| 12 | Completeness check that all catalogue tables exist with RLS enabled | audit validity |

## What is already known without running it

From the Phase 3 and 3.1 work and the strict upstream models:

- The API exposes `width`, `height`, `depth`, and `weight` as raw decimals whose
  units are fixed by the physical column names `width_cm`, `height_cm`,
  `depth_cm`, and `weight_kg`. No unit conversion happens anywhere yet.
- `materials` is a free-text array with no vocabulary control.
- `color_value` is free text per colour row.
- Style, finish, room type, and capacity have no dedicated columns. If they
  exist at all they are enrichment attributes, keyed by `attribute_kind` with a
  text `attribute_value`, and only `party_confirmed` assignments reach the API.
  The first live run of section 09 (2026-09-16) proved the column is `text`,
  not `jsonb`; the API's `JsonValue` typing had hidden that because PostgREST
  serializes text as a JSON string.
- There is no synonym table and no Arabic handling.
- The last live smoke found four recommendation-eligible products, so the
  dataset is small; the audit is about shape, not scale.

## How the results feed Phase 4B

1. Section 01 fixes the schema Phase 4B may rely on.
2. Sections 05, 07, 09, and 10 give the raw vocabulary. Phase 4B maps each token
   to a controlled value and records synonyms, including Arabic forms.
3. Section 03 decides whether dimension normalization is a no-op (all in
   centimetres already) or needs parsing of units embedded in text (section 11).
4. Sections 06 and 02 choose the initial high-demand categories with enough
   eligible products to be worth indexing.
5. Sections 08 and 11 list the content gaps that sellers or an enrichment job
   must fill before recommendations can be grounded in images and descriptions.

Save the CSVs under `docs/evidence/phase-4a/` and the Phase 4B design will be
written against them, in the same evidence-driven shape as the security phases.

## Run record (2026-09-16)

All twelve sections were run read-only in the SQL Editor with the row cap
disabled. Sections 01 to 08, 11, and 12 are saved under
`docs/evidence/phase-4a/`. Sections 09 and 10 returned zero rows, so no CSV
exists for them: `product_enrichment_attribute` and
`product_enrichment_assignment` are empty. Section 12 passed.

Findings, from the saved sections:

- Four products, all published and recommendation-eligible, one in each of
  four categories; the fifth category (chairs) has no products.
- Width, height, and depth are present on every product in centimetres with
  sane values. Weight is null on every product.
- Prices are positive; both discounts are below list price.
- Every product has one or two HTTPS images with exactly one primary; one
  product links images to colours.
- Categories and colours use a bilingual label convention, `Arabic — English`
  with an em dash, for example `Beds — أسرّة` and `أبيض — white`.
- Materials are Arabic free text (beech wood, wood, cotton, fabric) plus the
  English token `mdf`, with no separator convention.
- Every product name contains Arabic; every description is English and shorter
  than 40 characters; no names or descriptions embed units; no duplicate names.
- The schema has columns the API does not use: `category.parent_id` (a
  hierarchy exists), `category.icon_url`, `category.display_order`,
  `product.sku`, `product_3d_model.model_url`, and
  `product_enrichment_assignment.proposed_at`. Enrichment assignments default to
  `ai_proposed`, which the API hides until a seller confirms them.

Consequences for Phase 4B: normalization must be schema- and convention-driven,
not statistics-driven; the bilingual separator gives category and colour
synonyms for free; materials need a hand-built bilingual vocabulary; weight and
enrichment-based attributes are unavailable until data exists; and search
evaluation needs seed products beyond the four real ones.

## Not in scope

No application code changes, no schema changes, no AI calls, and no live
execution by Claude. The API contract in `docs/phase-3-supabase-catalog.md` is
unchanged.
