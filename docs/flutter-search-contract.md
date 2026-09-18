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

### Follow-ups: `history`

A follow-up such as "خليها رمادي", "cheaper" or "في حدود ١٥ ألف" refines the
previous search instead of starting over. Send the customer's earlier
messages in this search, oldest first, as `history`:

```json
{"query": "خليها رمادي", "history": ["عايز كنبة مودرن أقل من ٣٠ ألف"]}
```

- At most 4 earlier messages, each 1 to 500 characters. More is a 422.
- The app keeps the list; the server remembers nothing between requests.
- Later messages win; anything not mentioned carries over. A different kind
  of furniture ("I need a wardrobe instead") starts a fresh search.
- Relative words ("cheaper", "أرخص") never invent or drop a budget. Show the
  interpretation chips so the customer sees what was understood.
- Start a new list when the customer taps "new search" or clears the box.
- Leaving `history` out, or sending `[]`, is exactly the single-sentence
  search.

Measured live on 2026-09-18: 25/25 across five conversations in Arabic and
English.

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
| 429 | `rate_limited` | Too many searches from this account. Wait `Retry-After` seconds, then allow retry |
| 503 | `search_unavailable` | Provider down or overloaded. Offer retry |
| 502 | `search_upstream_error` | Answer could not be trusted. Ask them to rephrase |
| 503 | `catalogue_service_unavailable` | Supabase unreachable |

All errors are shaped `{"detail": {"code": ..., "message": ...}}`, except the
FastAPI validation one, which uses its own format.

Limits per signed-in account, by default: 20 searches a minute, 10 room plans a
minute, 20 room previews an hour. Normal use never reaches them; a retry loop
does. On 429, read the `Retry-After` header (whole seconds) and do not retry
automatically before it passes.

Every response, errors included, carries an `X-Request-ID` header. Log it, and
show it on a "report a problem" screen: the backend finds the exact request
from it.

## Timing

Two to three seconds per search, nearly all of it the model. Show a spinner and
disable the submit button. An identical sentence repeated within 15 minutes
skips the model and comes back in well under a second, but the catalogue is
still read fresh, so prices and stock are always current.

## Copy this

A working client. Needs `http` in `pubspec.yaml` and nothing else. The parsing
here is the whole point: note every decimal going through `_decimal`.

```dart
import 'dart:convert';
import 'package:http/http.dart' as http;

/// Thrown for anything the API rejected. [code] is stable across languages;
/// [message] is already in the customer's language, so show it as-is.
class SearchException implements Exception {
  SearchException(this.code, this.message, this.status);
  final String code;
  final String message;
  final int status;
  bool get canRetry => code == 'search_unavailable';
  bool get mustSignIn => code == 'invalid_access_token';
  @override
  String toString() => 'SearchException($status $code): $message';
}

/// Every decimal arrives as a JSON string so no precision is lost in transit.
/// Casting straight to double throws; this is the only safe reader.
double? _decimal(Object? value) =>
    value == null ? null : double.parse(value as String);

class SearchTerm {
  SearchTerm(this.slug, this.label);
  final String slug;   // stable: branch on this
  final String label;  // already in the customer's language: show this
  factory SearchTerm.fromJson(Map<String, dynamic> j) =>
      SearchTerm(j['slug'] as String, j['label'] as String);
}

class SearchProduct {
  SearchProduct({
    required this.id,
    required this.name,
    required this.price,
    required this.discountPrice,
    required this.imageUrl,
    required this.width,
  });

  final String id;
  final String name;
  final double price;
  final double? discountPrice;
  final String? imageUrl;
  final double? width;

  /// What the customer actually pays, and what search filtered on. Showing
  /// [price] alone makes a correct match look like it ignored the budget.
  double get payable => discountPrice ?? price;
  bool get isDiscounted => discountPrice != null;

  factory SearchProduct.fromJson(Map<String, dynamic> j) {
    final images = (j['images'] as List).cast<Map<String, dynamic>>();
    return SearchProduct(
      id: j['id'] as String,
      name: j['name'] as String,
      price: _decimal(j['price'])!,
      discountPrice: _decimal(j['discount_price']),
      imageUrl: images.isEmpty ? null : images.first['url'] as String,
      width: _decimal(j['width']),
    );
  }
}

class SearchItem {
  SearchItem(this.product, this.score, this.matched);
  final SearchProduct product;
  final double score;
  final List<String> matched;
  factory SearchItem.fromJson(Map<String, dynamic> j) => SearchItem(
        SearchProduct.fromJson(j['product'] as Map<String, dynamic>),
        _decimal(j['score'])!,
        (j['matched'] as List).cast<String>(),
      );
}

class SearchResult {
  SearchResult({
    required this.language,
    required this.items,
    required this.matchCount,
    required this.clarification,
    required this.unresolvedCategory,
    required this.bindingConstraint,
  });

  final String language;               // 'ar' or 'en'; drives text direction
  final List<SearchItem> items;
  final int matchCount;
  final String? clarification;         // ask this when the query was too vague
  final String? unresolvedCategory;    // a kind of furniture we do not carry
  final String? bindingConstraint;     // why an empty result is empty

  bool get isArabic => language == 'ar';

  factory SearchResult.fromJson(Map<String, dynamic> j) {
    final unresolved = (j['unresolved'] as List).cast<Map<String, dynamic>>();
    final excluded = (j['excluded_by'] as List).cast<Map<String, dynamic>>();
    return SearchResult(
      language: j['language'] as String,
      items: (j['items'] as List)
          .cast<Map<String, dynamic>>()
          .map(SearchItem.fromJson)
          .toList(),
      matchCount: j['match_count'] as int,
      clarification: j['clarification'] as String?,
      unresolvedCategory: unresolved
          .where((u) => u['field'] == 'category')
          .map((u) => u['surface'] as String)
          .firstOrNull,
      bindingConstraint:
          excluded.isEmpty ? null : excluded.first['constraint'] as String,
    );
  }
}

class SearchApi {
  SearchApi(this.baseUrl, {http.Client? client})
      : _client = client ?? http.Client();
  final String baseUrl;
  final http.Client _client;

  Future<SearchResult> search(
    String query, {
    required String accessToken,
    int limit = 20,
    List<String> history = const [], // earlier messages, oldest first, max 4
  }) async {
    final response = await _client
        .post(
          Uri.parse('$baseUrl/v1/search'),
          headers: {
            'Authorization': 'Bearer $accessToken',
            'Content-Type': 'application/json; charset=utf-8',
          },
          // jsonEncode handles the Arabic; do not hand-build this string.
          body: jsonEncode({'query': query, 'limit': limit, 'history': history}),
        )
        // The model takes two to three seconds, so allow well past that.
        .timeout(const Duration(seconds: 45));

    final body = jsonDecode(utf8.decode(response.bodyBytes));
    if (response.statusCode == 200) {
      return SearchResult.fromJson(body as Map<String, dynamic>);
    }
    final detail = (body as Map<String, dynamic>)['detail'];
    if (detail is Map<String, dynamic>) {
      throw SearchException(
        detail['code'] as String,
        detail['message'] as String,
        response.statusCode,
      );
    }
    throw SearchException('invalid_request', 'Invalid request.',
        response.statusCode);
  }
}
```

Using it, with the three rules already applied:

```dart
final result = await SearchApi(apiBaseUrl).search(
  controller.text,
  accessToken: supabase.auth.currentSession!.accessToken,
);

if (result.clarification != null) showPrompt(result.clarification!);
if (result.unresolvedCategory != null) {
  showNotice('We do not carry ${result.unresolvedCategory}.');
} else if (result.matchCount == 0) {
  showNotice('Nothing matched. Try relaxing ${result.bindingConstraint}.');
}

// Arabic answers lay out right to left.
Directionality(
  textDirection: result.isArabic ? TextDirection.rtl : TextDirection.ltr,
  child: ListView(children: [
    for (final item in result.items)
      ProductCard(
        product: item.product,
        // Always the payable price, struck-through list price beside it.
        price: item.product.payable,
        strikethrough: item.product.isDiscounted ? item.product.price : null,
      ),
  ]),
);
```

`firstOrNull` comes from `package:collection`, or replace it with
`.isEmpty ? null : ....first`.

---

# Room planning

Two calls. The plan comes first and is what the customer acts on. The preview is
optional decoration that loads after it. Never block the plan on the image.

## 1. Plan the room

```http
POST /v1/rooms/plan
Authorization: Bearer <supabase access token>
Content-Type: application/json

{"query": "عايز أوضة معيشة مودرن فيها كنبة و2 كرسي وترابيزة في حدود 40 ألف"}
```

Follow-ups work the same way as search: send the earlier room messages as
`history` (up to 4, oldest first). "خلي الكراسي 4" changes only the chairs and
keeps the budget; "زود الميزانية لـ 50 ألف" changes only the budget and keeps
the pieces (6/6 live).

```json
{"query": "خلي الكراسي 4", "history": ["عايز أوضة معيشة فيها كنبة و2 كرسي في حدود 40 ألف"]}
```

About three seconds. The response, trimmed:

```json
{
  "language": "ar",
  "items": [
    {
      "requested": {"slug": "sofas", "label": "كنب"},
      "product": { "...the same ProductResponse as search and the catalogue..." },
      "quantity": 1,
      "unit_price": "13500",
      "line_total": "13500",
      "colour": "رمادي — grey",
      "reasons": [{"code": "category", "text": "كنب"}, {"code": "in_stock", "text": "متوفر"}]
    }
  ],
  "total": "24330",
  "budget": "40000",
  "within_budget": true,
  "remaining": "15670",
  "over_budget_by": null,
  "summary": "4 قطع بإجمالي 24,330 جنيه، في حدود ميزانيتك 40,000 جنيه",
  "unfilled": [],
  "unresolved": [],
  "clarification": null,
  "image_request": { "items": [{"product_id": "...", "quantity": 1, "colour_id": "..."}],
                     "room_type": "living room", "styles": ["modern"], "language": "ar" }
}
```

The same two rules as search apply. Every decimal is a JSON string, and
`unit_price` is already what the customer pays, discount included.

- `colour` is the catalogue colour to order. It was chosen because it has
  enough stock for the whole quantity.
- `summary` is one ready-made sentence in the customer's language. Show it.
- `unfilled` lists pieces that could not be supplied, each with a localized
  `text` such as "الكمية المطلوبة مش متوفرة بلون واحد".
- `within_budget: false` still returns a full room, the cheapest possible, and
  `over_budget_by` says by how much. The `summary` already says so in words.
- `clarification` is set, and `items` empty, when the sentence named no
  furniture at all.

### Budgets and upgrades

Each item also carries:

- `budget` and `over_budget_by`: the budget the customer set for that line,
  all units together, and how far over it the pick is. Both null when no
  budget was given for the piece.
- `upgrades`: up to two options for the same piece that cost a little more and
  match better. Each has `summary`, one ready-made sentence in the customer's
  language, for example "بزيادة 3,600 جنيه: بيطابق «مودرن» اللي طلبته، أكتر من
  ميزانية القطعة بـ 1,500 جنيه، والأوضة تفضل في حدود ميزانيتك". Show it under
  the item with a "switch" action. `extra_cost`, `room_total` and
  `within_room_budget` are there if you want your own layout.

The plan also carries `every_line_within_budget`, and `budget_question` when
the customer gave no budget at all. Show the question as a gentle prompt under
the plan; the plan is already complete.

To preview the room with an upgrade, replace that item in `image_request.items`
with the upgrade's `image_item`, then call the image endpoint as usual.

## 2. Render the preview

Send `image_request` from the plan back unchanged:

```http
POST /v1/rooms/image
Authorization: Bearer <supabase access token>
Content-Type: application/json

<the plan's image_request object>
```

Ten to twenty seconds. Show a placeholder while it loads.

```json
{
  "image_base64": "iVBORw0KGgo...",
  "mime_type": "image/png",
  "label": "معاينة بالذكاء الاصطناعي",
  "disclaimer": "صورة توضيحية متولدة من صور المنتجات...",
  "items": [...],
  "references_used": 3
}
```

**Show `label` on the image and `disclaimer` beneath it. Both are required.**
The image is generated and can differ from the real products, sometimes in
counts. The plan's product list is what the customer buys. Never use this image
as a product photo.

`image_request` is null when the plan has no items; hide the preview then.

## Errors

Same codes as search. Two additions for the image call:

| Status | Code | Meaning |
|---|---|---|
| 404 | `product_not_found` | A product is no longer for sale. Re-plan |
| 502 | `search_upstream_error` | The model declined to draw it. Hide the preview, keep the plan |
| 429 | `rate_limited` | Preview limit reached (20 an hour). Keep the plan; offer the preview again after `Retry-After` |

## Dart

Uses `_decimal` and `SearchProduct` from the search client above.

```dart
class RoomItem {
  RoomItem(this.product, this.quantity, this.unitPrice, this.lineTotal, this.colour);
  final SearchProduct product;
  final int quantity;
  final double unitPrice;   // already the payable price
  final double lineTotal;
  final String colour;
  factory RoomItem.fromJson(Map<String, dynamic> j) => RoomItem(
        SearchProduct.fromJson(j['product'] as Map<String, dynamic>),
        j['quantity'] as int,
        _decimal(j['unit_price'])!,
        _decimal(j['line_total'])!,
        j['colour'] as String,
      );
}

class RoomPlan {
  RoomPlan(this.raw);
  final Map<String, dynamic> raw;
  List<RoomItem> get items => (raw['items'] as List)
      .cast<Map<String, dynamic>>()
      .map(RoomItem.fromJson)
      .toList();
  double get total => _decimal(raw['total'])!;
  bool get withinBudget => raw['within_budget'] as bool;
  String get summary => raw['summary'] as String;
  String? get clarification => raw['clarification'] as String?;
  bool get isArabic => raw['language'] == 'ar';
  Map<String, dynamic>? get imageRequest =>
      raw['image_request'] as Map<String, dynamic>?;
}

class RoomPreview {
  RoomPreview(this.bytes, this.label, this.disclaimer);
  final Uint8List bytes;      // Image.memory(bytes)
  final String label;         // overlay on the image
  final String disclaimer;    // under the image
}

extension RoomApi on SearchApi {
  Future<RoomPlan> planRoom(String query,
      {required String accessToken, List<String> history = const []}) async {
    final r = await _client
        .post(Uri.parse('$baseUrl/v1/rooms/plan'),
            headers: {
              'Authorization': 'Bearer $accessToken',
              'Content-Type': 'application/json; charset=utf-8',
            },
            body: jsonEncode({'query': query, 'history': history}))
        .timeout(const Duration(seconds: 45));
    final body = jsonDecode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>;
    if (r.statusCode != 200) throw _error(body, r.statusCode);
    return RoomPlan(body);
  }

  Future<RoomPreview> renderRoom(RoomPlan plan, {required String accessToken}) async {
    final r = await _client
        .post(Uri.parse('$baseUrl/v1/rooms/image'),
            headers: {
              'Authorization': 'Bearer $accessToken',
              'Content-Type': 'application/json; charset=utf-8',
            },
            body: jsonEncode(plan.imageRequest))
        // Rendering takes 10 to 20 seconds; allow well past that.
        .timeout(const Duration(seconds: 120));
    final body = jsonDecode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>;
    if (r.statusCode != 200) throw _error(body, r.statusCode);
    return RoomPreview(
      base64Decode(body['image_base64'] as String),
      body['label'] as String,
      body['disclaimer'] as String,
    );
  }

  SearchException _error(Map<String, dynamic> body, int status) {
    final d = body['detail'];
    return d is Map<String, dynamic>
        ? SearchException(d['code'] as String, d['message'] as String, status)
        : SearchException('invalid_request', 'Invalid request.', status);
  }
}
```

`_client` and `baseUrl` are the fields of `SearchApi` above; if the extension
cannot see them in your file layout, move these two methods into `SearchApi`.
`Uint8List` needs `import 'dart:typed_data';`.

Typical screen flow: call `planRoom`, render the plan immediately, then if
`plan.imageRequest != null` call `renderRoom` and fade the preview in when it
arrives. If `renderRoom` throws, hide the preview and keep the plan.


# Compare and similar products

Neither calls a model: both are fast (well under a second), free, and never
rate limited. Every value is a catalogue fact. Neither says which product is
"better", because that depends on what the customer needs.

## Compare 2 to 4 products

```http
POST /v1/compare
Authorization: Bearer <access token>
Content-Type: application/json

{"product_ids": ["<uuid>", "<uuid>", "<uuid>"], "language": "ar"}
```

`language` is `"ar"` or `"en"` (default `"en"`); send the app's current
language. Ids must be distinct. Fewer than 2 or more than 4 is a 422, and a
product the customer cannot buy is a 404 `product_not_found`.

```json
{
  "language": "ar",
  "products": ["…the full products, in the order sent…"],
  "rows": [
    {
      "code": "price",
      "label": "السعر",
      "values": [
        {"product_id": "…", "text": "13,500 جنيه", "value": "13500"},
        {"product_id": "…", "text": "9,900 جنيه", "value": "9900"}
      ],
      "highlight": ["<id of the cheaper one>"],
      "highlight_rule": "lowest"
    }
  ],
  "summary": [{"code": "cheapest", "text": "الأرخص: …، بفرق 3,600 جنيه عن الأغلى"}]
}
```

Row codes, always in this order: `price`, `discount`, `width_cm`, `depth_cm`,
`height_cm`, `footprint`, `weight_kg`, `materials`, `colours`, `stock`,
`seller`. Render a table with `label` down the side and each value's `text` in
its product's column. `value` is the number behind it (a decimal string, as
everywhere) or null.

`highlight` lists the products holding a notable value: lowest price, largest
discount, smallest floor space, most units in stock. It is empty when all
values are equal or one is missing, and a tie lists every product in it. Mark
highlighted cells, for example in bold. `summary` holds up to three
ready-to-show sentences.

## Similar products

```http
GET /v1/catalog/products/{id}/similar?limit=6&language=ar
Authorization: Bearer <access token>
```

`limit` is 1 to 12 (default 6). Returns real, in-stock products of the same
kind, most similar first:

```json
{
  "product_id": "…",
  "language": "ar",
  "items": [
    {
      "product": {"…": "full product"},
      "price_difference": "-3600",
      "reasons": [
        {"code": "material", "text": "نفس الخامة: قماش"},
        {"code": "colour", "text": "متاح كمان بلون بيج"},
        {"code": "price", "text": "أرخص بـ 3,600 جنيه"}
      ]
    }
  ],
  "candidate_count": 45,
  "truncated": false
}
```

`price_difference` is this item's price minus the viewed product's; negative
means cheaper. Show it as a "You may also like" row on the product page, with
the first one or two `reasons` under each card. An empty `items` means nothing
similar is in stock; hide the row.

## Dart

```dart
class ComparisonCell {
  ComparisonCell(this.productId, this.text, this.highlighted);
  final String productId;
  final String text;
  final bool highlighted;
}

class ComparisonRow {
  ComparisonRow(this.code, this.label, this.cells);
  final String code;
  final String label;
  final List<ComparisonCell> cells;
}

class Comparison {
  Comparison(this.products, this.rows, this.summary);
  final List<SearchProduct> products;
  final List<ComparisonRow> rows;
  final List<String> summary;
}

class SimilarItem {
  SimilarItem(this.product, this.priceDifference, this.reasons);
  final SearchProduct product;
  final double priceDifference; // negative = cheaper
  final List<String> reasons;
}

extension CompareApi on SearchApi {
  Future<Comparison> compare(List<String> ids, String language,
      {required String accessToken}) async {
    final r = await _client
        .post(Uri.parse('$baseUrl/v1/compare'),
            headers: {
              'Authorization': 'Bearer $accessToken',
              'Content-Type': 'application/json; charset=utf-8',
            },
            body: jsonEncode({'product_ids': ids, 'language': language}))
        .timeout(const Duration(seconds: 20));
    final body = jsonDecode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>;
    if (r.statusCode != 200) throw _error(body, r.statusCode);
    return Comparison(
      [
        for (final p in body['products'] as List)
          SearchProduct.fromJson(p as Map<String, dynamic>),
      ],
      [
        for (final row in body['rows'] as List)
          ComparisonRow(row['code'] as String, row['label'] as String, [
            for (final v in row['values'] as List)
              ComparisonCell(
                v['product_id'] as String,
                v['text'] as String,
                (row['highlight'] as List).contains(v['product_id']),
              ),
          ]),
      ],
      [for (final s in body['summary'] as List) s['text'] as String],
    );
  }

  Future<List<SimilarItem>> similar(String productId, String language,
      {required String accessToken, int limit = 6}) async {
    final r = await _client
        .get(
            Uri.parse('$baseUrl/v1/catalog/products/$productId/similar'
                '?limit=$limit&language=$language'),
            headers: {'Authorization': 'Bearer $accessToken'})
        .timeout(const Duration(seconds: 20));
    final body = jsonDecode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>;
    if (r.statusCode != 200) throw _error(body, r.statusCode);
    return [
      for (final i in body['items'] as List)
        SimilarItem(
          SearchProduct.fromJson(i['product'] as Map<String, dynamic>),
          _decimal(i['price_difference'])!,
          [for (final reason in i['reasons'] as List) reason['text'] as String],
        ),
    ];
  }
}
```

Like the room methods, these use `_client`, `baseUrl`, `_error`, `_decimal`
and `SearchProduct` from the clients above; if your file layout hides private
members, move these methods into `SearchApi`.


# Reviews: switch before the 3.2C security migration

After Phase 3.2C is applied, a signed-in user can read only **their own**
reviews directly from Supabase. Any screen that lists a product's or a
seller's reviews by querying the `review` table with the user's session will
come back empty. Switch those screens to this endpoint first; it works both
before and after the migration.

```http
GET /v1/reviews/public?product_id=<uuid>&limit=20&offset=0
GET /v1/reviews/public?seller_id=<uuid>
```

No sign-in needed. Exactly one of `product_id` or `seller_id` (otherwise 422
`invalid_review_target`). `limit` 1 to 50, newest first.

```json
{
  "items": [
    {
      "id": "…",
      "target_kind": "product",
      "product_id": "…",
      "seller_id": null,
      "rating": 4,
      "comment": "مريحة جدا",
      "created_at": "2026-09-10T12:00:00Z"
    }
  ],
  "limit": 20,
  "offset": 0,
  "has_more": false
}
```

Nothing identifies the reviewer: no customer id, no name. Errors: 503
`reviews_unavailable` (retry), 502 `reviews_upstream_error`.

A customer's own reviews (for example, "my reviews") can still be read directly
with their session, as before.
