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

Stop inserting into the `cart` table from the app. It still works today, but
the 3.2D security package removes that permission, and after that only this
endpoint can create a cart. Errors: 409 `customer_profile_required` (a seller
or admin account, or a customer without a profile yet), 503
`cart_unavailable` (retry).

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

## What changed in Supabase on 2026-09-18 (security package 3.2C)

These affect calls the app makes to Supabase directly:

- **Reviews.** A signed-in user can read only their own reviews from the
  `review` table. Product and seller review lists must use
  `GET /v1/reviews/public`. Writing a review is unchanged.
- **Furnishing requests.** Insert without `id`, `lifecycle_state` or
  `created_at`; a new request starts as `draft`. Change its state only with
  the functions, not by updating `lifecycle_state`:

  ```dart
  await supabase.rpc('open_furnishing_request', params: {'request_id': id});
  await supabase.rpc('withdraw_furnishing_request', params: {'request_id': id});
  ```

  Each returns `true` if the change happened. Editing and deleting are
  allowed only while the request is `draft` or `open`, and the address must
  belong to the customer.
- **Service directory.** Only active service types, and only capabilities of
  approved parties with active services, are visible.

Coming later (security package 3.2D, not applied): the app loses INSERT on
`cart` (use `POST /v1/cart` now, and it keeps working), order status changes
only through `advance_purchase_order` / `cancel_purchase_order`, service
requests only through their four functions, and reviews can no longer be
edited or deleted. Nothing else changes before 3.2D is applied.

## Generating a client

Instead of hand-writing models, generate them from
[openapi.json](openapi.json), for example with openapi-generator's
`dart-dio` generator. A test keeps that file identical to what the server
serves.
