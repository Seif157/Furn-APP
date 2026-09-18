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
  }) async {
    final response = await _client
        .post(
          Uri.parse('$baseUrl/v1/search'),
          headers: {
            'Authorization': 'Bearer $accessToken',
            'Content-Type': 'application/json; charset=utf-8',
          },
          // jsonEncode handles the Arabic; do not hand-build this string.
          body: jsonEncode({'query': query, 'limit': limit}),
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
  Future<RoomPlan> planRoom(String query, {required String accessToken}) async {
    final r = await _client
        .post(Uri.parse('$baseUrl/v1/rooms/plan'),
            headers: {
              'Authorization': 'Bearer $accessToken',
              'Content-Type': 'application/json; charset=utf-8',
            },
            body: jsonEncode({'query': query}))
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
