# Flutter integration: start here

This is the entry point for the Flutter developer. It says what the app talks
to, in what order, and what changed on 2026-09-18. The detailed request and
response shapes, error tables and Dart code are in
[flutter-search-contract.md](flutter-search-contract.md); the machine-readable
description of every endpoint is [openapi.json](openapi.json).

## Two backends, one sign-in

The app talks to **Supabase directly** for sign-in and for the marketplace
tables it already uses (profile, addresses, cart, orders, saved spaces,
writing reviews), and to **this API** for everything AI, comparison, similar
products and public reviews.

Both use the same Supabase session. Send its access token to this API:

```dart
final token = Supabase.instance.client.auth.currentSession?.accessToken;
headers: {'Authorization': 'Bearer $token'}
```

The app only ever holds the Supabase URL, the **publishable** key, and this
API's address. Never put the Gemini key or any Supabase secret key in the app;
they live only on the server.

## Base URL

Pass it at build time so the same code runs against a laptop and production:

```bash
flutter run --dart-define=API_BASE_URL=http://192.168.1.9:8000   # laptop
flutter build apk --dart-define=API_BASE_URL=https://api.example.com
```

```dart
const apiBaseUrl = String.fromEnvironment('API_BASE_URL');
```

On a laptop, start the API with `uv run python -m scripts.serve --host
0.0.0.0` and use the laptop's LAN address; phone and laptop must be on the
same Wi-Fi. Plain `http://` needs a debug-only exception: on Android
`android:usesCleartextTraffic="true"` in the debug manifest, on iOS an
`NSAppTransportSecurity` exception. Production is HTTPS and needs neither.

## On startup: ask what is switched on

```http
GET /v1/meta          (no sign-in needed)
```

```json
{
  "api_version": "0.1.0",
  "languages": ["ar", "en"],
  "features": {"search": true, "room_planning": true, "room_preview": true,
               "compare": true, "similar_products": true, "public_reviews": true},
  "limits": {"search_per_minute": 20, "room_plan_per_minute": 10,
             "room_preview_per_hour": 20, "max_query_length": 500,
             "max_history": 4, "max_search_results": 50, "max_room_pieces": 6,
             "max_piece_quantity": 10, "max_compared_products": 4,
             "max_similar_products": 12}
}
```

Hide a feature whose flag is `false` rather than letting the customer meet an
error. Use `limits` for input lengths and counters instead of hard-coding them.

## Screens and the calls behind them

| Screen | Call | Notes |
|---|---|---|
| Search | `POST /v1/search` | 2-3 s. Send `history` for follow-ups |
| Search, empty state | `GET /v1/search/examples?language=ar` | Tap-to-try sentences |
| Filter chips | `GET /v1/search/vocabulary` | Same words search understands |
| Product page, "you may also like" | `GET /v1/catalog/products/{id}/similar?language=ar` | No AI, fast |
| Product page, reviews | `GET /v1/reviews/public?product_id=…` | No sign-in needed |
| Compare (2-4 products) | `POST /v1/compare` | No AI, fast |
| Room planner | `POST /v1/rooms/plan` | ~3 s. Send `history` for follow-ups |
| Room preview image | `POST /v1/rooms/image` | 10-20 s. Body is the plan's `image_request` |
| Catalogue list and detail | `GET /v1/catalog/products`, `/{id}` | Or Supabase directly, as today |
| Cart, before the first "add to cart" | `POST /v1/cart` | Returns `cart_id`; then add lines in Supabase |
| Checkout | `supabase.rpc('place_order', …)` | One order per seller; see Checkout |
| Cancel / advance an order | `supabase.rpc('cancel_purchase_order' / 'advance_purchase_order', …)` | See Supabase rules |

## The cart

Every customer has exactly one cart, and **the server creates it**. Before the
first "add to cart", call:

```http
POST /v1/cart
Authorization: Bearer <access token>
```

```json
{"cart_id": "…", "created": true}
```

It is safe to call every time: the first call creates the cart, later calls
return the same `cart_id` with `"created": false`. Then add, change and
remove lines in Supabase directly, as today, using that `cart_id`:

```dart
await supabase.from('cart_line').insert({
  'cart_id': cartId, 'product_color_id': colorId, 'quantity': 1,
});
```

The app cannot insert into the `cart` table (security package 3.2D, applied
2026-09-18); only this endpoint creates a cart. Errors: 409
`customer_profile_required` (a seller or admin account, or a customer without
a profile yet), 503 `cart_unavailable` (retry).

A cart line can be added only for a product that is published, from an
approved seller, in an active category, with stock in that colour. Only
`quantity` can be changed afterwards; delete and re-add to change the colour.

## Checkout

Placing an order is one database call, made with the customer's own session:

```dart
final placed = await supabase.rpc('place_order', params: {'address_id': addressId});
// [{"order_id": "…", "marketplace_party_id": "…"}, …]  one order per seller
```

In one transaction it rechecks every cart line (still for sale, enough stock),
creates one order per seller at the current catalogue price (the discount
price when lower), copies the delivery address onto the order, reserves the
stock, and empties the cart. Delivery is free and payment is cash on delivery
for now. If anything is wrong, nothing is written and it throws a
`PostgrestException` whose `message` is one of:

| `message` | Meaning | `details` |
|---|---|---|
| `cart_empty` | Nothing to order | |
| `address_not_found` | Not one of this customer's addresses | |
| `product_unavailable` | An item is no longer for sale | the `product_color_id` |
| `insufficient_stock` | Not enough of a colour left | the `product_color_id` |
| `customer_profile_required` | Not a customer account | |

After a success, reload the cart (now empty) and show the orders. Tested live
on 2026-09-18: one Cairo sofa ordered, stock 8 → 7, cancelled, stock back to 8.

## Conversation: follow-ups keep context

For search and the room planner, keep the customer's messages in a list for
the current session and send the earlier ones as `history` (oldest first, at
most 4). "خليها رمادي" after "عايز كنبة مودرن أقل من ٣٠ ألف" searches grey
modern sofas under 30,000. Clear the list on "new search". The server
remembers nothing; the list lives in the app.

## Rules that are not optional

1. **Every decimal is a JSON string.** `double.parse(json['price'] as
   String)`. A direct `as double` throws.
2. **Show `discount_price` when present.** Search filters on what the
   customer pays.
3. **Errors are `{"detail": {"code", "message"}}`.** Branch on `code`, show
   `message`; it is already in the customer's language. Validation errors
   (422 from a malformed body) are FastAPI's own shape.
4. **429 `rate_limited`:** wait the `Retry-After` header's seconds; do not
   auto-retry sooner.
5. **401 `invalid_access_token`:** refresh the Supabase session, retry once.
6. **Every response has `X-Request-ID`.** Log it; show it on a "report a
   problem" screen.
7. **Timeouts:** 45 s for search and room plans, 120 s for room previews,
   20 s for everything else.
8. **Label AI previews.** Show the response's `label` and `disclaimer` with
   every room preview; the product list, not the picture, is what is sold.

## Supabase rules the app must follow (final, applied 2026-09-18)

Security packages 3.2C and 3.2D and checkout are all applied and verified on
the live project. These are the rules for calls the app makes to Supabase
directly. Nothing further is planned to change them.

**The general rule.** Writes accept only the columns listed below. Sending any
other column, even with an unchanged value, fails with a permission error, so
insert and update with exactly these keys.

### Orders

- **Placing:** `place_order` only (see Checkout). The app cannot insert orders.
- **Customer cancels** a `pending` order:
  `supabase.rpc('cancel_purchase_order', params: {'order_id': id})` returns
  `true` if it was cancelled. The reserved stock goes back automatically.
- **Seller advances** one step at a time,
  pending → confirmed → preparing → out_for_delivery → delivered:
  `supabase.rpc('advance_purchase_order', params: {'order_id': id, 'next_state': 'confirmed'})`
  returns `true` if the step was allowed.
- **Seller may edit** only `notes`. The customer cannot edit an order.
- Customers read their own orders, sellers the orders sent to them.

### Service requests

- **Customer creates** with `customer_profile_id, service_type_id, address_id,
  related_order_id, scheduled_date, scheduled_time, details`. It starts
  `pending` with no seller.
- **Customer may edit** `scheduled_date, scheduled_time, details` while pending,
  and cancels with `cancel_service_request(request_id)`.
- **Seller** calls `accept_service_request(request_id, agreed_price)` (pending),
  `start_service_request(request_id)` (accepted) and
  `complete_service_request(request_id)` (in progress). Each returns `true` if
  it happened.

### Reviews

- **Write once:** insert `customer_profile_id, target_kind` and exactly one of
  `target_product_id`, `target_service_request_id`, `target_marketplace_party_id`,
  plus `rating, comment`. A product review needs a delivered order containing
  that product; a service review needs a completed service request.
- **No edit, no delete.** Hide those buttons.
- **Lists:** `GET /v1/reviews/public` for any product or seller; a customer's
  own reviews can still be read directly.

### Other tables

| Table | Insert columns | Update columns |
|---|---|---|
| `address` | customer_profile_id, label, recipient_name, contact_phone, address_line_1, address_line_2, city, country, latitude, longitude, is_default | the same minus customer_profile_id |
| `cart_line` | cart_id, product_color_id, quantity | quantity |
| `saved_space` | customer_profile_id, space_name, width_cm, depth_cm, measurement_source | space_name, width_cm, depth_cm, measurement_source |
| `custom_offering` (seller) | marketplace_party_id, design_id, published_price, title, description, publication_state, published_at | the same minus marketplace_party_id |
| `offer_line_item` (seller) | offer_id, line_kind, product_id, item_name, specification, unit_price, quantity, display_order | the same minus offer_id, only while the offer is submitted |
| `party_capability` (seller) | marketplace_party_id, service_type_id, declared_at | none |
| `design_product_reference` | design_id, product_id | none |
| `furnishing_request_design_version` | furnishing_request_id, design_version_id | none |

An address cannot be deleted while an order, service request or furnishing
request uses it.

### Sellers (`marketplace_party`)

Never `select('*')`: select these columns explicitly, or the request fails.

- Anyone: `id, business_name, business_description, logo_url, coverage_area,
  approval_state`
- Signed in: the same plus `state_reason`

Seller sign-up inserts `user_id, business_name, business_description,
logo_url, coverage_area`; afterwards only the last four can be edited.

### Furnishing requests (3.2C)

Insert without `id`, `lifecycle_state` or `created_at`; a new request starts
as `draft`. Change its state only with the functions:

```dart
await supabase.rpc('open_furnishing_request', params: {'request_id': id});
await supabase.rpc('withdraw_furnishing_request', params: {'request_id': id});
```

Editing and deleting are allowed only while it is `draft` or `open`, and the
address must belong to the customer.

**Attaching a design** to a furnishing request (applied 2026-09-19):

```dart
await supabase.from('furnishing_request_design_version').insert({
  'furnishing_request_id': requestId,
  'design_version_id': versionId,
});
```

Allowed only when the request is the customer's own and still `draft` or
`open`, and the design version belongs to a design the customer created.
Send exactly these two keys. A link cannot be edited; to change it, delete it
(allowed while the request is `draft` or `open`) and insert the new one.
Anything else is refused with a row-level security error.

### Service directory

Only active service types, and only capabilities of approved sellers with
active services, are visible.

## Generating a client

Instead of hand-writing models, generate them from
[openapi.json](openapi.json), for example with openapi-generator's
`dart-dio` generator. A test keeps that file identical to what the server
serves.
