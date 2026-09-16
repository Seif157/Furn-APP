# Phase 4B: catalogue normalization

Status: **Implemented locally; no API, database, or AI change.**

Phase 4B adds `app/catalog/normalization.py`, a pure and deterministic layer
that turns a validated `UpstreamProduct` into a `NormalizedProduct`: every
original value is kept, and a canonical, bilingual, search-oriented form is
added beside it. Nothing consumes it yet. Phase 4C (search schema) and 4D
(deterministic structured search) will build on it. The public catalogue
endpoints and their response models are unchanged.

## What the Phase 4A evidence dictated

| Audit finding | Design consequence |
|---|---|
| Categories and colours are labelled `Arabic — English` with an em dash | A script-aware label splitter, not a positional one; both halves become synonyms of one term |
| Materials are Arabic free text plus `mdf` | A hand-built bilingual material vocabulary; unknown tokens are surfaced as `unmapped_terms`, never guessed |
| Names are Arabic, descriptions short English | Text fields record `has_arabic` and `has_latin`; Arabic normalization folds alef, teh marbuta, and alef maqsura variants and strips diacritics |
| Digits may appear in Arabic-Indic or Persian form | Digit folding in `normalize_text` so `٣ مقاعد` and `3 مقاعد` match |
| Width, height, and depth are already centimetres | Dimensions are carried through as-is; `parse_length_cm` exists for text-embedded sizes but is not applied to structured columns |
| Weight is null on every product | `weight_kg` stays optional; nothing depends on it |
| Enrichment tables are empty | Confirmed attributes are normalized and indexed as `kind:value`, so styles, finishes, and room types plug in when sellers confirm them |
| Four products only | Vocabularies are marked `verified` only for terms seen in the audit; other entries are candidates for the next audit run to confirm or prune |

## Rules

**Text.** NFKC, Arabic-Indic and Persian digits to ASCII, Arabic decimal and
thousands separators, alef variants to bare alef, alef maqsura to yeh, teh
marbuta to heh, Farsi yeh and keheh to Arabic forms, diacritics and tatweel
removed, casefold, whitespace collapsed. The function is idempotent.

**Bilingual labels.** Split on em dash, en dash, pipe, slash, or a spaced
hyphen. Each piece is assigned by script, so `Beds — أسرّة` and `أسرّة — Beds`
give the same result. An unspaced hyphen, as in `dark-brown`, is not a
separator.

**Vocabularies.** Three controlled vocabularies, each term with a slug, an
English label, an Arabic label, synonyms, and a `verified` flag:

- categories: beds, dining, sofas, wardrobes, chairs; all five verified.
- colours: the eight audit colours verified, plus black, red, blue, green,
  yellow, cream, walnut, oak as candidates.
- materials: beech wood, wood, cotton, fabric, mdf verified, plus oak, linen,
  velvet, leather, metal, steel, glass, marble, plywood, foam, rattan, walnut
  as candidates.

Lookup normalizes the surface form, tries it whole, then tries each half of a
bilingual label. If the halves resolve to different terms the label is
ambiguous and no mapping is made. Building a vocabulary with a synonym shared
by two terms raises at import time.

**Units.** `parse_length_cm` and `parse_weight_kg` accept English and Arabic
unit names, Arabic digits, comma decimals, and inch marks, return two-decimal
`Decimal` values, and return `None` for zero, missing, or trailing-letter units.

**Product.** `normalize_product` keeps `id`, the original name and description,
structured dimensions, and prices; adds the category term, colours in display
order with stock, material terms in seller order, confirmed attributes sorted by
kind and value, `effective_price` (the discount only when it is below the
price), sorted unique `search_terms` covering slugs and both labels, and
`unmapped_terms`. Only `party_confirmed` enrichment assignments are used, the
same rule the API applies. The result is frozen and carries `schema_version`.

## What it does not do

- It does not write anything to Supabase, add columns, or create tables. A
  persisted normalized index, if ever needed, is a Phase 4C decision.
- It does not call any AI provider. Unknown terms are reported, not inferred.
- It does not change the API. `ProductResponse` is untouched.
- It does not translate. Arabic and English labels come only from the
  vocabulary; free text stays in its language.

## Feedback loop with the audit

Every `unmapped_terms` value seen in real data is a vocabulary gap. When more
products exist, rerun audit sections 05 and 07 and add the new tokens as
verified terms. Candidate terms that never appear can be pruned.

## Next

- Phase 4C: a typed `SearchSpecification` and the filter fields the normalized
  product can answer today: category slug, colour slug, material slug, price
  range, width, height, and depth ranges, in-stock.
- Seed data: at least a few dozen products across the five categories are
  needed before retrieval can be evaluated; four real rows cannot support a
  benchmark.
