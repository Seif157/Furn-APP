# What Flutter needs for search

Everything here was dumped from the running application, not written from
memory. If this document and the API disagree, the API is right.

## The one call

```http
POST /v1/search
Authorization: Bearer <supabase access token>
Content-Type: application/json

{"query": "عايز كنبة مودرن بيج", "limit": 20}
```

`query` is 1 to 500 characters. `limit` is 1 to 50 and defaults to 20. Any
other field in the body is rejected with 422, so do not send extras.

The token is the Supabase session's access token, the same one the catalogue
endpoints already use. Without it the response is 401. Search reads the
catalogue as that user, so row-level security decides what is searchable.

## The trap that will cost an hour

**Every number arrives as a JSON string, not a number.** Prices, dimensions,
scores, and range bounds are all decimals, and they serialize quoted so no
precision is lost on the way.

```json
"price": "13500", "discount_price": "13430", "width": "220", "score": "0.5556"
```

In Dart that means `double.parse(json['price'] as String)`, never
`json['price'] as double`. The second form throws at runtime. Integers are
genuine JSON numbers: `limit`, `match_count`, `candidate_count`,
`stock_quantity`, `display_order`, `excluded`.

## Showing a price

Show `discount_price` when it is not null, and `price` otherwise. Search
filters on what the customer actually pays, so a product listed at 21000 with a
discount price of 17850 correctly matches "under 20000". Display the list price
alone and correct behaviour looks like a bug. Showing the list price struck
through next to the real one is better still.

## Response shape

```json
{
  "query": "عايز كنبة مودرن بيج",
  "language": "ar",
  "interpretation": {
    "category": {"slug": "sofas", "label": "كنب"},
    "colours": [], "materials": [],
    "price": {"minimum": null, "maximum": "30000"},
    "width_cm": null, "height_cm": null, "depth_cm": null,
    "in_stock_only": true,
    "preferred_colours": [{"slug": "beige", "label": "بيج"}],
    "preferred_materials": [], "styles": ["modern"], "room_type": null
  },
  "items": [
    {
      "product": { "...the same ProductResponse the catalogue endpoints return..." },
      "score": "0.6111",
      "matched": ["category", "colours", "materials", "price", "width",
                  "height", "depth", "in_stock"]
    }
  ],
  "limit": 2,
  "match_count": 8,
  "candidate_count": 41,
  "truncated": false,
  "has_more": true,
  "clarification": null,
  "unresolved": [],
  "excluded_by": [{"constraint": "category", "excluded": 33}]
}
```

`product` is byte-for-byte the shape `GET /v1/catalog/products` already
returns, so an existing product card widget works unchanged.

Every field listed is always present. Nullable ones are `category`,
`room_type`, `clarification`, the four ranges, and `discount_price`. Lists
arrive empty rather than absent.

## The minimum that works

Send the query, read `items`, render each `product`, parse prices as strings.
That is a working demo. Everything below makes it better, not possible.

## Four fields worth using

**`language`** is `"ar"` or `"en"` and says which language the response speaks.
Drive text direction from it so an Arabic answer lays out right to left.

**`clarification`** is a question in the customer's own language, set only when
the sentence was too vague to search. "عايز أثاث" returns "تحب تدور على أثاث
لإيه بالظبط؟ زي كنب، أسرّة، أو سفرة؟". Show it as a prompt above the results.

**`unresolved`** lists words the catalogue does not recognise, as
`{"field": "category", "surface": "coffee table"}`. When `field` is `category`,
say you do not carry that kind of product. Without this the customer sees a
grid of everything and assumes the search ignored them.

**`excluded_by`** explains an empty result: which constraint removed how many
candidates, largest first. "عايز كنبة بمية جنيه" returns zero items and
`[{"constraint": "price", "excluded": 45}]`, so you can offer to relax the
budget. The counts overlap, since one product can fail several constraints, so
the first entry is the one to relax, not a total.

`interpretation` is what the backend understood. Showing it as chips the
customer can remove is the natural next feature, and every `label` in it is
already in their language.

## Errors

The `code` never changes with language. The `message` is localized. Branch on
the code, display the message.

| Status | `code` | What to do |
|---|---|---|
| 401 | `authentication_required` | No token was sent |
| 401 | `invalid_access_token` | Session expired; sign in again |
| 422 | `invalid_search_query` | Empty or over-long query |
| 422 | FastAPI validation | Malformed body; this one is English only |
| 503 | `search_unavailable` | Provider down or rate limited. Offer retry |
| 502 | `search_upstream_error` | Answer could not be trusted. Ask them to rephrase |
| 503 | `catalogue_service_unavailable` | Supabase unreachable |

All errors are shaped `{"detail": {"code": ..., "message": ...}}`, except the
FastAPI validation one, which uses its own format.

## Timing

Two to three seconds per search, nearly all of it the model. Show a spinner and
disable the submit button. There is no caching, so an identical repeated query
costs the same again.
