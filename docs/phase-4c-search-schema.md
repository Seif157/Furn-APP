# Phase 4C: search schema

Status: **Implemented locally; no API, database, or AI change.**

Phase 4C adds `app/search/models.py`, the typed `SearchSpecification` that
every later search phase consumes. It separates hard constraints, which a
product must satisfy, from soft preferences, which only influence ranking, and
it admits only fields the Phase 4B `NormalizedProduct` can answer today.

## The specification

The master plan's example query, "a modern beige sofa around 220 cm for a small
living room under 30,000 EGP", becomes:

```json
{
  "hard": {
    "category": "sofas",
    "colours": [],
    "materials": [],
    "price": {"minimum": null, "maximum": "30000"},
    "width": {"minimum_cm": null, "maximum_cm": "220"},
    "height": null,
    "depth": null,
    "in_stock_only": true
  },
  "soft": {
    "colours": ["beige"],
    "materials": [],
    "styles": ["modern"],
    "room_type": "living room",
    "preferred_width_cm": "220",
    "preferred_height_cm": null,
    "preferred_depth_cm": null,
    "target_price": null
  },
  "query": {"original": "...", "normalized": "...", "language": "en"},
  "limit": 20,
  "schema_version": 1
}
```

Whether "beige" is hard or soft is the parser's decision in Phase 5A; the
schema supports both.

## Fields and what backs them

| Field | Kind | Backed by | Rule |
|---|---|---|---|
| `hard.category` | hard | `NormalizedProduct.category.slug` | must be a category vocabulary slug |
| `hard.colours` | hard, any-of | `colours[].slug` with stock | colour vocabulary slugs, at most 10, no duplicates |
| `hard.materials` | hard, all-of | `materials[].slug` | material vocabulary slugs, at most 10 |
| `hard.price` | hard | `effective_price` | non-negative, ordered, at least one bound |
| `hard.width` / `height` / `depth` | hard | `width_cm` etc. | positive centimetres, ordered, at least one bound |
| `hard.in_stock_only` | hard | any colour with stock | default true |
| `soft.colours` / `materials` | soft | same slugs | vocabulary-validated |
| `soft.styles` | soft | confirmed enrichment `style:` terms | normalized non-empty text, at most 10 |
| `soft.room_type` | soft | confirmed enrichment, later room inference | normalized text |
| `soft.preferred_*_cm`, `soft.target_price` | soft | dimensions, price | positive |
| `query` | trace | none | original, normalized, detected language |
| `limit` | paging | none | 1 to 50, default 20 |

Deliberately absent: weight, because the audit found it null on every product;
finish, capacity, and seller, because no normalized field carries them yet.
Styles and room type are soft only because the enrichment tables are empty; a
hard style filter would return nothing today.

## Guardrails

- Unknown category, colour, or material slugs are rejected at construction.
- Ranges reject negative, zero-length, inverted, non-finite, or absurd bounds.
- Soft text must already be normalized, so two spellings cannot both survive.
- A specification with no constraint, preference, or query text is invalid.
- Models are strict, frozen, and forbid extra fields; they round-trip JSON.

## Building from surface forms

`build_specification` accepts what a parser or a form would produce, in Arabic
or English or the catalogue's bilingual label form, resolves it through the
Phase 4B vocabularies, and returns the specification together with every
surface it could not resolve, tagged by field. An unresolved category leaves
the category unset rather than guessing. That list is the input for
clarification in Phase 7A, and `query.language` tells the assistant which
language to ask in.

## Next

Phase 4D applies a specification to a sequence of normalized products
deterministically: hard filters first, then a scoring function over the soft
preferences, then a stable order. No AI is involved until Phase 5A produces
specifications from natural language.
