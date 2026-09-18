# Phase 6 — grounded reasons and nearest alternatives

Status: **Implemented locally and verified against the live Gemini API and the
live catalogue on 2026-09-17.**

Two additions to `POST /v1/search`, both deterministic. No provider is called
for either, so neither can invent a product, a price, or a reason.

## Reasons, per result (6C)

Each item now carries `reasons`: short statements of why it matches, in the
customer's language.

```json
"reasons": [
  {"code": "category", "text": "a match for beds"},
  {"code": "materials", "text": "made of beech wood"},
  {"code": "price", "text": "12,000 EGP, within your 20,000 EGP budget"},
  {"code": "in_stock", "text": "in stock"}
]
```

Section 6.6 draws the line between a catalogue fact, an inference, and an
aesthetic judgement, and requires the three to stay separate. Everything here
is the first kind. Each sentence restates a number or a term the catalogue
holds next to the limit the customer stated. Nothing says a sofa is cosy.

The data was already there. Phase 4D's `ConstraintCheck` records the observed
product value precisely so an outcome can be explained without re-deriving the
rule, and this reads it back.

Only constraints the customer actually stated produce a reason. An
unconstrained check passes trivially, and "it is within your budget" when no
budget was given is noise dressed as insight.

## Alternatives, when nothing matches (6.10)

An empty result that says only "nothing found" is a dead end. When
`match_count` is zero the response now carries up to three real products that
came closest, each with what it missed by.

```json
"alternatives": [
  {
    "product": {"...": "a real catalogue row"},
    "missed": [{"code": "price", "text": "4,900 EGP over your budget"}],
    "missed_count": 1
  }
]
```

Three rules keep the offer honest.

**Stock is never relaxed.** A sold-out row is not an alternative, it is a
broken promise.

**Category is never relaxed**, and this one was a bug before it was a rule.
Counting misses alone makes a 1,200 EGP chair the closest thing to a sofa under
5,000: the chair fails only the category, every sofa fails only the price, and
the chair is cheaper so it sorts first. Arithmetically nearest, obviously
wrong. Naming a category is the strongest statement of intent a customer makes,
so alternatives stay inside it, and when nothing in that category comes close
the honest answer is none.

**A product failing more than two constraints is not shown.** Past that it
stops being an alternative and becomes a random product.

Ordering is fewest misses, then cheapest, then product id, so it is total and
stable.

## What the live run changed

Verifying this surfaced a parser bug that predated it. Asked in Arabic for a
modern beige sofa, the model returned the category **Beds** in one run of five.
Repeating it at temperature zero showed it was genuinely flaky, not a one-off.

The cause was the prompt listing the catalogue's own vocabulary and asking the
model to pick the matching entry. The model copied list entries verbatim, and
sometimes copied the wrong one. A controlled comparison over four sentences,
four runs each, measured it:

| Instruction | Arabic sofa query |
|---|---|
| Pick the nearest listed category | Beds 1 of 4 |
| That paragraph removed entirely | Beds 2 of 4 |
| Ask for the customer's own word | Correct 4 of 4 |

So the fix was to stop asking the model to choose a category at all. It now
copies the customer's own word, and the Phase 4B vocabulary maps that word to a
slug, which is what the vocabulary is for. The model handles language;
deterministic code handles the marketplace. Re-measured across nine sentences,
five runs each: every answer correct, with one transient HTTP 503 from Google.

That change also revealed a vocabulary gap rather than a model error. Asked for
an office chair the model correctly returned "كرسي مكتب", which resolved to
nothing because lookup matches a whole surface and not its tokens. Common
multi-word phrasings are now listed explicitly for all five categories.

## Comparison (6D), added 2026-09-18

`POST /v1/compare` takes 2 to 4 product ids and returns them side by side:
price, discount, width, depth, height, floor space, weight, materials, colours
in stock, units in stock, seller. `app/recommendations/comparison.py`, no
provider.

It states facts and marks differences; it never names a winner. The master
plan's example, "which of these three sofas is better for a small room?",
needs the room's size, which this endpoint is not told, so answering it would
be a guess. What it does say is checkable: the cheapest, the largest discount,
the smallest floor space, the most units in stock. A row is highlighted only
when its values differ and every one is known, and a tie highlights every
product in it, because breaking a tie by list order would imply a preference
that does not exist.

Every product is looked up under the caller's own token and rechecked for
eligibility, so a product the customer cannot buy is a 404, never a column.

## Similar products, added 2026-09-18

`GET /v1/catalog/products/{id}/similar`, `app/recommendations/similar.py`, no
provider. Only in-stock products of the same kind, never the product itself.
Ranked by shared catalogue facts: same material (2 each), a colour in common
(1 each), a confirmed style (2 each), price closeness (up to 3, continuous so
it breaks ties), and width within 10 cm (1). Each suggestion lists the facts it
shares, and always its price difference, in the customer's language.

Style is scored only from confirmed enrichment attributes, which are empty
today, so on the current catalogue similarity is material, colour, price and
size.

## Not built

Compatibility rules (6B) need seat and table heights the catalogue does not
record.
