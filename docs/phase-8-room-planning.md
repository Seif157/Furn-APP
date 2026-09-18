# Room planning from a sentence, with an AI preview

Status: **Implemented locally and run end to end on 2026-09-18 against the live
Gemini API, the live catalogue, and live product photos.** Built for the demo on
2026-09-19.

A customer describes a room in one sentence. The backend picks one real product
for every piece they asked for so the whole room fits their budget, then
renders a labelled preview image of exactly those products.

```text
"عايز أوضة معيشة مودرن فيها كنبة و2 كرسي وترابيزة في حدود 40 ألف"
        |
POST /v1/rooms/plan        ~3 s    real products, quantities, colours, total
        |
POST /v1/rooms/image       ~15 s   AI preview of those products, labelled
```

## No customer photos

The roadmap's Phase 8 pictured analysing a photo of the customer's room. That
was deliberately not built. A text description needs no upload, sends nothing
private to a third party, and avoids the one failure measured when a model
edits a customer's own photo: `gemini-2.5-flash-image`, asked to place a sofa
into a room photo, deleted the armchair, lamp and side table already there.

## The model never chooses a product

The same division of labour as search. The model reads the sentence into slots:
a kind of furniture, a quantity, colour preferences, material requirements, a
total budget, a style. It copies the customer's own word for each piece, and the
Phase 4B vocabulary maps that word to a category. Choosing products is
deterministic code.

The room draft, like the search draft, has no field that could carry a product,
a seller, or a price that exists.

## How a room is chosen

`app/rooms/planner.py`, deterministic and exhaustive over a bounded space.

1. For each slot, every product in that category that meets its material
   requirement and has **enough stock in a single colour for the whole
   quantity**. Two chairs means one chair model with at least two in one colour;
   a pair that arrives in two colours is not what anyone asked for.
2. Each candidate is scored by the same Phase 4D ranking search uses, with the
   room sentence as the query, so "مودرن" favours products whose own name or
   description says so.
3. Each slot keeps its four best-scoring **and** its three cheapest candidates.
   Keeping only the best-scoring was a real bug caught before shipping: with a
   tight budget, the room that fits may need a sofa that ranks sixth, and a
   planner that never looks at it reports "over budget" for a room that exists.
4. Every combination is costed. Any room within budget beats every room over
   it; among those that fit, the best-scoring wins, then the cheaper.
5. If nothing fits, the cheapest room is returned with how far over it is,
   rather than a room missing pieces or nothing at all.

Slots that cannot be filled are reported with a reason, in the customer's
language: not stocked, not in that material, or not enough in one colour.

Repeated kinds of furniture are merged, so "a chair and another chair" is one
slot of two, and a bare "table" or "ترابيزة" means a dining table because those
are the only tables this catalogue sells. "coffee table" stays unresolved.

## The preview image

`POST /v1/rooms/image` takes product ids, quantities, and the chosen colour for
each. The plan response carries this request ready-made in `image_request`.

The endpoint never trusts what it is sent. Each product is looked up again under
the caller's own token, so a product that is not for sale, or that this user
cannot see, is refused with 404 before any rendering. Each product's photo is
fetched server-side and given to the model as a reference, and the prompt names
every piece, its quantity, and the colour the customer will receive.

The image is the one thing in this feature that is not a catalogue fact, so it
is labelled everywhere it appears: `label` reads "معاينة بالذكاء الاصطناعي" or
"AI preview", and `disclaimer` says details and proportions may differ from the
real products, which are what the customer is buying. Show both.

### Fetching product photos safely

Product photo URLs are seller-controlled catalogue data, and fetching arbitrary
URLs server-side is how a server gets tricked into reaching internal addresses.
`app/rooms/images.py` fetches only HTTPS, on the default port, from an explicit
host allowlist (`IMAGE_REFERENCE_HOSTS` plus the Supabase project host). It
follows redirects by hand and re-checks every hop, accepts only JPEG, PNG and
WebP, and abandons a body past 5 MB. Tests cover the metadata address, loopback,
lookalike hostnames, userinfo, non-default ports, and a redirect into a private
address; each is refused before any request is made.

A photo that fails any rule is skipped. Each piece then carries its own photo
number, or none, because numbering photos by position was a second real bug: one
skipped photo shifted every later piece onto the wrong reference.

### Which image model

Measured on 2026-09-18 rendering the same planned room from three real product
photos:

| Model | Time | Result |
|---|---|---|
| gemini-2.5-flash-image | 14.5 s | All three products reproduced, right counts |
| nano-banana-pro-preview | 29 s | All three products reproduced, right counts |

Fidelity was comparable, so the default is `gemini-2.5-flash-image`: half the
wait, and a stable release rather than a preview. `GEMINI_IMAGE_MODEL` switches
it.

The first render exposed a mismatch: the plan chose a grey sofa and the image
showed an orange one, because the model copied the photo. Plans now pass each
chosen colour to the image request, the preview uses that colour's own photo
when the catalogue has one, and the prompt names the colour. Re-rendered, the
sofa came out grey with the photo's shape, buttons and legs.

## Live run, 2026-09-18

Real Gemini, live catalogue of 45 products, live photo fetches.

| Sentence | Plan |
|---|---|
| عايز أوضة معيشة مودرن فيها كنبة و2 كرسي وترابيزة في حدود 40 ألف | Modern sofa (grey), 2 modern dining chairs (beige), modern dining set. 24,330 of 40,000. All modern |
| a scandinavian living room with a sofa, two chairs and a table under 30000 | Scandinavian sofa, 2 Scandinavian chairs, dining set. 22,800 of 30,000 |
| عايز كنبة و4 كراسي بـ 10 آلاف | Cheapest possible room is 18,700, and the summary says it is 8,700 over |

## Known limits

**The preview is not guaranteed to be exact.** In one render of a two-chair plan
the model drew one chair. Counts, proportions and details can drift. That is
what the label and disclaimer are for, and why the plan's product list, not the
image, is what the customer buys from.

**Without a stated style, rooms can mix styles.** Style is only scored from
product names and descriptions, because confirmed style attributes are empty.
"عايز أوضة مودرن" produces a coherent room; a sentence with no style may pair a
Scandinavian sofa with modern chairs.

**Dining sets include chairs.** Several catalogue "tables" are sets with four or
six chairs, so a plan for a table and two chairs can show more chairs than
asked.

**Seed photos are stock photos.** On the seed catalogue the reference photo is a
category photograph, not the listed product. Real products with their own
photos will render closer to reality.

**No caching, no rate limiting, and a preview costs noticeably more than a
text call.** Fine for a demo; not for real traffic.
