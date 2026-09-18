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

## Budgets for each piece and for the whole room

Added on 2026-09-18 at the user's request. A customer can give a budget for one
piece, for the room, or both: "كنبة في حدود 12 ألف و2 كرسي بـ 2000 للواحد،
والميزانية كلها 25 ألف". A price per piece is multiplied by the quantity, so two
chairs at 2,000 each is a 4,000 line budget. A room is within budget only when
every line is within its own budget and the total is within the room's; when
nothing fits, the room that is over by the least comes back, and each response
line says whether it is over its own budget and by how much.

When the customer gives no budget at all, the plan is still complete, and
`budget_question` invites one: "تحب تحدد ميزانية للأوضة كلها أو لكل قطعة؟
هنختارلك أنسب حاجة في حدودها ونقولك لو فيه حاجة أحسن بفرق بسيط." It never
blocks the answer.

## Something better for a little more

Each planned piece can carry up to two upgrades: another real product for the
same piece that costs a little more and is measurably better. Both halves of
that sentence are defined precisely, because a vague version would invent
claims.

**"Better" means it scores higher on what this customer asked for**, using the
same scoring search uses. Nothing is called nicer, premium or higher quality,
because nothing in the catalogue measures those, and section 6.6 of the master
plan forbids presenting judgement as fact. Each upgrade's `reasons` name the
concrete thing it matches that the current pick does not: the customer's own
words in its listing, a preferred colour it is in stock in, a size closer to
the one asked for.

**"A little more" means at most 15% past the budget it would exceed**: a line
may reach 115% of its own budget, the room 115% of the room's. With no budget
at all nothing is offered, because the planner has already taken the best match.

Live, for "عايز أوضة معيشة مودرن فيها كنبة في حدود 12 ألف و2 كرسي وترابيزة،
والميزانية كلها 25 ألف", the plan kept the sofa at 9,900 within its 12,000
budget and offered:

> بزيادة 3,600 جنيه: بيطابق «مودرن» اللي طلبته، أكتر من ميزانية القطعة بـ 1,500
> جنيه، والأوضة تفضل في حدود ميزانيتك

Each upgrade also carries `image_item`, ready to swap into the preview request
to see the room with it.

Verifying this caught two scoring bugs that predated it. Filler words in a
request counted as matches: "13000 in total" let a leather sofa tie with the
modern one because its description contains "in", which would also have
produced an upgrade reason claiming it "matches “in”". Function words and
request vocabulary in both languages are now ignored when matching, in search
too. And in room requests count words counted: "two chairs" matched a sofa
described as "two-seat". Count words are now left out of the words a room is
ranked by.

## A room worth looking at

The first previews were accurate and bare: a white box with furniture parked in
it. The rendering prompt now asks for a magazine-quality photograph composed by
an interior designer: sofas against a wall or floating to face the room, chairs
grouped around their table, warm daylight through sheer curtains, a palette
built around the furniture's own colours, and small decor such as a rug,
plants, cushions, a lamp and framed art.

The furniture rules did not loosen. Each piece is still reproduced from its own
photo, in the planned colour, in the planned quantity, with an explicit
instruction to add no other seating, tables, beds or storage. Decor is allowed
only because it is small, and the disclaimer now says decor is illustration
only and that the listed products are what the customer buys.

In the live render the room looked like a real interior photo, and both planned
chairs appeared, in the beige the plan chose. Stating the copies explicitly
("show 2 separate, identical copies") fixed the earlier renders that drew one
chair where two were planned. The same render added a small round side table
beside the sofa despite the instruction; it is decor-sized, and covered by the
disclaimer, but it shows the rule is followed closely rather than perfectly.

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

**A preview costs noticeably more than a text call.** Since 2026-09-18 both
room endpoints are rate limited per user (10 plans a minute, 20 previews an
hour by default) and cache identical requests for 15 minutes; see
`app/core/limits.py` and `app/core/cache.py`. A cached preview is returned only
after every product has been looked up again under the caller's token, and
only for an identical prompt and identical reference photos. Both live in
process memory, which is correct for one server and must move to a shared
store before a second.
