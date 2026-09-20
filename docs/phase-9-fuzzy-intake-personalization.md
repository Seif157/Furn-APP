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
against a real throwaway PostgreSQL, wired into CI). **Not applied.**

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

## What is not done

- **The tag migration has not been applied** and no tags exist, so fuzzy
  ranking is inert: a search for "cosy" behaves exactly as it did yesterday.
  Order: apply the migration, run the derivation script, read the generated
  file, run it.
- **Nothing here has met the live model.** Every test uses a stub. The
  tagging, triage and brief prompts have never been measured against Gemini,
  unlike the search parser, which was measured over 16 cases at 3 repeats
  (Phase 5D). Expect to tune them, and add them to the evaluation.
- **Section 11 is still open.** Once tags exist, fuzzy cases can be
  benchmarked for the first time, which is the precondition the vector-search
  decision was waiting on.
- **Personalization has no evaluation either.** It is a tie-breaker, so the
  risk is low, but "did it help?" is currently unanswered.
- **Seller-side AI** (writing a listing, normalizing dimensions on upload) is
  still not built.
