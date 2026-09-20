# Fuzzy search, clarification, intake and personalization

What was built on 2026-09-20, why each decision went the way it did, and what
is still needed before any of it helps a real customer.

Four features, in the order they were asked for:

1. **Enrichment + fuzzy search** — "cosy", "hotel-like", "for a reception" now
   rank real products.
2. **Conversational clarification (7A)** — the question comes with answers the
   customer can tap.
3. **Intake AI** — a described problem becomes a real service; a furnishing job
   becomes a filled-in form.
4. **Personalization + seller fallback** — past purchases break ties; when
   nothing matches, sellers who make things to order are offered, labelled.

## 1. Fuzzy search needs data nobody has

No seller states a style, a room or a feel, so nothing in the catalogue can
answer "cosy". Section 11's vector-search decision was blocked on exactly this:
there was nothing to retrieve semantically.

### Where the guesses live, and why not in the seller's table

`product_enrichment_attribute` already has an `ai_proposed` state, which looks
like the obvious home. It is not usable:

- Phase 3.2B added a **restrictive** policy to
  `product_enrichment_assignment` limiting customers to `party_confirmed`
  rows. AI-proposed rows are invisible to the API by live, reviewed security
  policy.
- Writing guesses as `party_confirmed` would present the platform's opinion as
  the seller's word.
- Loosening 3.2B would reverse a reviewed decision to buy a ranking signal.

So inferences get their own table, `product_search_tag`, where provenance is a
column (`source = 'ai_inferred'`, `model_name`, `generated_at`, `confidence`)
rather than a convention. Clients may read tags for published products and can
never write one; rows are written by the owner from a reviewed file.

Migration: `migrations/product-search-tags-2026-09-20.sql`, with `-undo.sql`,
`-verify.sql` (9 checks) and `scripts/replica_search_tags_test.py` (24 checks
against a real throwaway PostgreSQL, wired into CI). **Applied live on
2026-09-20, verification 9/9**, then filled by
`seed/search-tags-2026-09-20.sql` with 277 tags over all 45 products.

### A guess may rank, never filter, and is always labelled

- `INFERRED_CEILING = 0.8` in `app/search/ranking.py`: a seller-confirmed
  attribute scores 1, a guess scores its confidence capped below 1. A product
  whose seller said "modern" always outranks one we merely think looks modern.
- Hard constraints never see a tag. `test_a_tag_can_never_exclude_a_product`
  pins that.
- Every reason built from a tag is marked. `ReasonResponse.basis` is
  `"catalogue"` or `"inferred"`, and the wording differs too: "looks modern
  (our guess)" against a plain "modern". Section 6.6 asks for fact, inference
  and judgement to stay separate; this keeps them separate in the data, not
  only in the prose.

### Styles, rooms and feels became vocabulary slugs

They were free text, which meant "مودرن" and "modern" were two unrelated
strings and could never match the same tag. They now resolve through
`STYLES`, `ROOM_TYPES` and `FEELS` in `app/catalog/normalization.py`, exactly
as colours and materials do, and an unrecognised word is reported as
unresolved rather than mapped to a near neighbour.

This changes the search response: `interpretation.styles` and
`interpretation.room_type` are now `{slug, label}` objects, and
`interpretation.feels` is new.

The room vocabulary is Egyptian: `reception` carries ريسبشن and انتريه, because
that is the room customers name out loud.

### How tags get written

`scripts/derive_search_tags.py` signs a real user in, reads the catalogue that
user may see, asks Gemini to label each product from its own entry (and, with
`--with-photos`, its primary photograph), and writes `seed/search-tags-<date>.sql`
for a human to read and run. It writes nothing to Supabase.

The model answers with slugs only. `app/ai/tagging.py` drops anything outside
the vocabulary, anything below 0.4 confidence, and everything beyond the three
surest per kind. The draft has no field that can carry a price, a product or a
seller, so an invented fact has nowhere to travel.

`generate_json` gained an optional `references` argument so a photograph can
travel with the prompt; the boundary is otherwise unchanged and no existing
caller passes one.

### Reading tags cannot break search

The tag read is a separate request, made only when the sentence mentions a
style, room or feel, and it fails soft: a 404 (the answer until the migration
is applied), a timeout, a 500 or junk all mean "no tags", and search answers
exactly as it did before. That is what makes the code safe to ship ahead of the
migration.

## 2. Clarification with answers (7A)

`app/search/clarification.py`. A question appears in `follow_up` when the
parser asked one, or when the customer named no kind of furniture and matched
broadly (8 or more). A sentence with a category and a budget is answered, not
interrogated, per section 6.3.

Every option is grounded in what actually matched: categories offered are
categories with matching products, and price bands are computed from those
products' real prices, rounded to something a person would say. Bands are
offered only when the dearest match costs at least half again as much as the
cheapest, because splitting a narrow range asks the customer to choose between
things that are, to them, the same price.

An option carries `send`: an ordinary sentence in the customer's language. The
app sends it as the next `query` with the previous message in `history`, so a
tap and a typed answer take the same path and the server keeps no state.

## 3. Intake: service triage and the furnishing brief

`POST /v1/intake/service` and `POST /v1/intake/furnishing`. Neither writes
anything; the app still creates the row in Supabase under the customer's own
row-level security.

**Triage** reads the real service directory with the caller's token and asks
the model to choose **by position**. The draft carries a number into the list
the backend sent, never an id or a name, so an invented service cannot exist:
a number out of range resolves to nothing. An empty answer is a real answer and
means the marketplace does not offer it. With no readable directory the
endpoint returns 503 rather than guessing, and does not spend a model call.

The service table's columns are not recorded in this repository's evidence, so
the gateway reads whole rows and looks for a display name among `name`,
`title`, `label`, `service_name`, `display_name`. A row with no name it can
show is dropped rather than labelled with its id.

**The furnishing brief** reads one description into the request form's fields:
rooms and their counts, a total budget, styles and feels. Rooms, styles and
feels resolve through the same vocabularies search uses, so the brief a seller
reads and the search a customer runs mean the same words. A stated count out of
range falls back to 1, which is the smallest claim that stays true; an
impossible budget is dropped.

## 4. Personalization, and the seller fallback

**Personalization is deliberately weak and deliberately visible.**

Weak: the `taste` component weighs 0.5 against 1 to 2 for everything the
customer actually said, and it applies only to products that already satisfy
every hard constraint. `test_a_profile_can_never_change_which_products_match`
pins that it reorders and nothing else.

Visible: the response carries `personalized: true` when history moved the
order.

The profile is built from the caller's own order lines, read with the caller's
own token and scoped by the **verified** user id, never by anything the client
sends. Two purchases are the minimum: one is an accident. The price that counts
is what they paid, not today's price, because a discount they never saw says
nothing about them. It is cached per user for the cache TTL, never stored, and
never shared.

**The seller fallback** (section 6.10) offers published `custom_offering` rows
when nothing matched, in their own list, with a label saying they are made to
order and not catalogue products. On a successful search the gateway is not
even called. Nothing is sponsored: this marketplace has no paid placement, and
inventing a "sponsored" flag for something nobody paid for would be the
disguise 6.10 forbids.

## Measured against the live model, 2026-09-20

`scripts/live_intake_smoke.py --i-have-authorization` puts the three new
prompts in front of Gemini. It contacts Google and nothing else: the products
come from the offline seed and the service directory is a plausible list
written in the script, because reading the real one needs a signed-in session.

Final run, `--repeats 2` (four tagging calls per product, two per other case):

```text
tagging   style and room identical across two taggings, 4 of 4 products
triage    5 of 5 cases, twice each, including the one that must match nothing
brief     16 of 16 checks
```

Three things it found.

**A vocabulary gap that would have shipped.** "عايز أفرش شقة فيها ٣ أوض نوم
وريسبشن" came back with a reception and no bedrooms at all. The room vocabulary
knew only the formal غرفة نوم; every Egyptian colloquial form — أوضة نوم, أوض
نوم, غرف نوم, and the same for children's, dining, guest and office rooms —
resolved to nothing and was silently reported as unresolved. This affected
search too, not only the brief. Fixed by adding those forms.

**The tagger is not deterministic at the margin.** Over six runs per product at
temperature 0, style and room are identical every time and their confidences
move by at most 0.05. The third feel rotates among two or three equally
defensible ones: the same wooden bed is "cosy" in one run and "hotel-like" in
the next.

Two responses. The derivation script writes the consensus of several runs
(`--runs`, default 2) rather than one run's opinion, which removes the
once-in-six flukes. And the smoke test requires style and room to hold still
while reporting a differing feel rather than failing on it, because demanding
determinism there would mean either dropping feels or pretending to a precision
that is not there. A borderline feel is worth at most 0.6 of one soft component
and only when a customer asks for that feel.

**A regression the tests did not catch.** Making style and room vocabulary
slugs broke the room planner, which was still handing `SoftPreferences` the
customer's own words. `POST /v1/rooms/plan` returned 502 for "عايز أوضة معيشة
مودرن" on the first live run after the change, because `"living room"` is not
the slug `living_room` and the specification refused it, which the router reads
as an untrustworthy answer.

Nothing covered it: the room parser's tests never set a room or a style, and
the image-prompt tests pass their own strings without going through the parser.
The room parser now resolves both through the same vocabularies, an unknown
room costs the preference rather than the plan, and the slugs turn back into
words for the image prompt so it reads "a modern living room". Six parser tests
and one end-to-end test now fail without the fix.

**Triage against the real directory, and what it cost.** The live
`service_type` table turned out to hold six rows — Delivery, Installation,
Assembly, Disassembly, Repair, Maintenance — with `name` and `description`
columns and **not one description filled in**. The gateway reads all six.

With only names to go on, "عايز حد يصلح الغسالة" (fix my washing machine)
matched `Repair` at 0.95. The name alone says nothing about furniture, so a
washing machine looked like a repair job. The instruction now states that every
service in the list is about furniture and nothing else, and names the observed
failure. Re-measured over nine cases against the real six names: 9 of 9,
including an air conditioner, which also now returns nothing.

The two genuinely ambiguous cases behave as designed: "عايز حد يركب الدولاب"
returns Installation and Assembly at similar confidences **and** asks, in
Egyptian Arabic, whether they mean fixing it to the wall or putting it
together. That is the case the whole confidence-plus-clarification shape exists
for.

**Worth doing on the data side:** filling in those six descriptions would help
more than any prompt wording, and it is the marketplace's own text rather than
a guess. One sentence each, saying what the service covers.

## The signed-in run, 2026-09-20 17:15

`scripts/live_search_smoke.py` with a real customer session, against the live
project and the live model, passed everything it checks:

```text
search, refinement, alternatives, compare, similar, public reviews   ok
the fuzzy sentence, ranking on inferred tags, both reasons labelled    ok
service triage: a broken wardrobe door -> Repair 0.85                  ok
service triage: a washing machine -> no service                        ok
the furnishing brief: {bedroom: 3, reception: 1}, 150000, modern       ok
room planning: 4 pieces, 24,330 of a 40,000 budget                     ok
```

Two features were live and did nothing, for want of data rather than through a
fault, and it is worth writing down which is which. Personalization needs two
purchases and that account has one, so `personalized` was false. The seller
fallback found nothing because `custom_offering` holds no rows at all. Phase
7A's question was not exercised: no sentence in the smoke test is vague enough
to produce one.

## What is not done

- **`modern` is on 36 of 45 products.** A tag that covers 80% of the catalogue
  cannot reorder anything, so "modern sofa" ranks about as it did before; the
  rare tags (scandinavian, industrial, luxury, space_saving, hotel_like) are
  where the difference shows. The fix, if real searches justify it, is to weigh
  a tag by how rare it is. Not done: it should be decided from observed
  searches, not from this one observation.
- **The live measurement is a smoke test, not an evaluation.** Four products,
  five triage cases and three briefs, against Phase 5D's 16 cases at 3 repeats
  with computed ground truth. The service directory it uses is invented, so
  triage has never met the real one. Fold these into the Phase 5D benchmark.
- **Section 11 is still open.** Once tags exist, fuzzy cases can be
  benchmarked for the first time, which is the precondition the vector-search
  decision was waiting on.
- **Personalization has no evaluation either.** It is a tie-breaker, so the
  risk is low, but "did it help?" is currently unanswered.
- **Seller-side AI** (writing a listing, normalizing dimensions on upload) is
  still not built.
