# Phase 4D: deterministic structured search

Status: **Implemented locally; no API, database, or AI change.**

Phase 4D completes the AI-foundation group. `app/search/service.py` applies a
Phase 4C `SearchSpecification` to a sequence of Phase 4B `NormalizedProduct`
values and returns a deterministic, explainable page. There is no learned
component and no network call: every number in a result can be recomputed by
hand from the product and the specification.

## Pipeline

```text
normalized products
      ↓
hard constraints  (app/search/filters.py)   exclude only; each check records
      ↓                                     the compared value
soft preferences  (app/search/ranking.py)   weighted mean of 0..1 parts, only
      ↓                                     for preferences actually expressed
stable order      score desc, effective price asc, product id
      ↓
page              limit, has_more, match and candidate counts, rejections
```

## Hard constraints

| Check | Rule |
|---|---|
| category | product category slug equals the requested slug |
| colours | at least one requested colour slug is present, in stock when `in_stock_only` |
| materials | every requested material slug is present |
| price | `effective_price` within the inclusive range |
| width, height, depth | value known and within the inclusive range; an unknown dimension fails a constraint on it, because the catalogue cannot prove the fit |
| in_stock | at least one colour with stock, when `in_stock_only` |

Each `ConstraintCheck` carries `observed`, a short label such as the slug set,
the effective price, or the total stock, never free text. `rejections` counts
how many candidates each constraint excluded; Phase 6 uses that to propose
alternatives when nothing matches.

## Soft score

| Component | Weight | Value |
|---|---:|---|
| colours | 2 | 1 if any preferred colour is in stock, else 0 |
| materials | 2 | fraction of preferred materials present |
| styles | 1.5 | fraction of preferred styles among confirmed `style` attributes |
| room_type | 1 | 1 if a confirmed room attribute equals the preference |
| width, height, depth | 1 each | closeness: 1 at the target, linear to 0 at 100 percent deviation, absent when unknown |
| price | 1.5 | the same closeness against `target_price` using `effective_price` |
| query | 1 | fraction of query tokens found among the product's normalized name, description, and bilingual search terms |

The score is the weighted mean of the applicable parts, quantized to four
decimals; a product with no applicable part scores 0. Parts are returned with
the result so a client or a later explanation step can say why.

## Guardrails

- Hard constraints run first and can only exclude; a high score never rescues
  a product that fails a constraint.
- Candidate sequences are bounded and must not contain duplicate ids.
- Results are strict, frozen models that carry ids, slugs, numbers, and
  booleans only; no product name, description, or seller text.
- Ordering is total, so identical inputs give identical pages regardless of the
  input order.

## Not in scope

No endpoint exposes this yet; wiring it to the catalogue gateway is a Phase 5
decision, because the gateway currently pages 50 products at a time and a
search over the whole eligible catalogue needs either server-side filters or a
bounded in-memory load. No semantic retrieval; the `query` component is exact
token overlap after normalization. No personalization.

## Next

Phase 5A: the natural-language requirement parser that produces
`SearchSpecification` values, behind the AI provider boundary, with typed
validation between the model's output and this pipeline.
