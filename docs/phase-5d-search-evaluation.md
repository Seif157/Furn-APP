# Phase 5D — search evaluation

Status: **Implemented and run against the live provider on 2026-09-17.**

Section 12 asks for repeatable cases and six measurements, with a stated target
of zero marketplace hallucination. This is that, plus the verdict it exists to
produce: whether semantic and vector search have earned their place.

## How ground truth is decided

Writing product ids into a benchmark by hand makes it rot the moment the seed
changes, and tempts you to fix the benchmark instead of the bug.

So ground truth is computed. Each case states the specification a perfect
parser would produce, and the products *that* specification finds through the
ordinary Phase 4D search are the right answer. The benchmark then measures the
thing actually in question, which is the parser, and survives a catalogue
change.

Two halves run separately. The deterministic half needs no provider and runs on
every commit, in `tests/test_evaluation.py`. The live half spends one call per
case and runs only on request:

```bash
uv run python -m scripts.live_search_evaluation --i-have-authorization --repeat 3
```

Violations are judged against what the *case* asked for, never against what the
parser decided, so a lenient parse cannot excuse a bad product.

## The benchmark tests itself

Thirteen tests check the benchmark before it is allowed to grade anything: that
every expected specification resolves cleanly, that no case matches the whole
catalogue or nothing at all, and that each metric can actually fail. A widened
budget, a dropped category, a missing clarification and an unnecessary one are
each fed in deliberately and must be caught. A metric that cannot fail reports
success it did not measure.

## Result, 2026-09-17

Sixteen cases, three runs each, `gemini-3.6-flash`, against the 41-product seed.

| Measurement | Result | Target |
|---|---|---|
| Requirement extraction accuracy | 100% | — |
| Field accuracy | 100% | — |
| Retrieval recall | 100% | — |
| Clarification accuracy | 100% | — |
| Hard-constraint violation rate | 0% | 0% |
| Hallucinated product rate | 0% | 0% |

Read that as "no known failures in sixteen cases", not as "the parser is
perfect". Sixteen sentences is a small benchmark. Its value is that it now
fails loudly when something regresses, which it already did once.

## What the first run caught

The first run scored 93%, failing the same case in all three repeats: asked in
Arabic for a white wardrobe, the colour landed in preferences rather than
requirements, so it ranked instead of filtering and nine wardrobes came back
where five were expected.

Investigating it showed the benchmark was the inconsistent one. It expected a
hard colour from the Arabic sentence and a soft colour from the equivalent
English sentence, so it was measuring its own disagreement.

That forced a decision that had been implicit. **A colour the customer
describes is a preference; a colour they demand is a requirement.** Colour is
the attribute people substitute most, and filtering it away hides products they
would have bought. **A material they name is a requirement**, because someone
asking for beech wood rarely accepts something else. The prompt now says this
outright instead of leaving the model to guess, and the benchmark gained a case
for the demanded form, "محتاج دولاب لازم يكون أبيض", which correctly filters to
five.

Re-measured: 48 of 48.

## The verdict on vector search

Section 11 allows vector search only once evaluation proves it adds value. On
this evidence it does not, and should not be built yet.

Structured retrieval reaches 100% recall on every case, so there is nothing for
semantic retrieval to recover. Every case is an objective constraint: a
category, a budget, a size, a material. Those are exactly what structured
filters are good at, and adding embeddings would cost a pgvector migration on a
database whose security review has not happened, in exchange for no measured
improvement.

The honest caveat is that this benchmark cannot test the cases where semantic
search would win. Section 6.4 names them: cosy, luxury, warm, minimal,
hotel-like. Those need confirmed style and mood attributes on products, and the
Phase 4A audit found the enrichment tables empty. Until sellers confirm those
attributes there is no ground truth for a fuzzy query, so the question is not
merely unanswered, it is currently unanswerable.

**So the order is: enrichment data first, then fuzzy cases in this benchmark,
then a decision about vector search.** Building it before that is guessing with
a migration attached.

## Cost

One provider call per case: 16 per run, 48 at `--repeat 3`. Under a minute.
