# Furn-APP backend — start here

This is the API behind the Furn-APP marketplace: search in Arabic and English,
room planning, comparison, similar products, public reviews, the cart, and two
endpoints that read a customer's own words into the service and furnishing
request forms.

You run it on your laptop, point the app at it, and build your screens against
it. Nothing here needs to be deployed first.

**What is in this branch.** Only what you need to run the API and integrate
with it: the backend, the two contract documents, and `docs/openapi.json`. The
database migrations, the security packages, the evaluation harness and the test
suite are not here; they are not yours to run and they would only be noise.
This branch has no shared history with `main`, so do not merge it back.

---

## 1. What you need from the backend owner

Ask for these and put them in a file called `.env` in this folder. Copy
`.env.example` and fill in the three marked values; everything else in that
file already has a sensible default.

| Value | What it is | Without it |
|---|---|---|
| `SUPABASE_URL` | the project URL | nothing works |
| `SUPABASE_PUBLISHABLE_KEY` | the public key, the same one your app uses | nothing works |
| `GEMINI_API_KEY` | the AI key | search, rooms and intake return 503; everything else works |
| `SUPABASE_SECRET_KEY` | server-only, optional | `POST /v1/cart` returns 503 and you cannot create a cart |

**`.env` is never committed.** It is in `.gitignore` already. Do not paste any
of these keys into the Flutter app, into a screenshot, or into a chat. The app
only ever holds `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`.

---

## 2. Run it

You need [uv](https://docs.astral.sh/uv/) and Python 3.12 or newer.

```bash
uv sync
uv run python -m scripts.serve --host 0.0.0.0
```

`--host 0.0.0.0` matters: without it the server only answers itself and a phone
cannot reach it. You should see `Uvicorn running on http://0.0.0.0:8000`.

Check it in a browser: <http://127.0.0.1:8000/health> should answer
`{"status":"ok", ...}`, and `/docs` gives you an interactive page where you can
try every endpoint by hand. Use `/docs` before writing any Dart — it is the
fastest way to see what a response actually looks like.

### The address the app should use

They are not interchangeable. `localhost` inside an emulator means the
emulator, not your laptop.

| App runs on | `API_BASE_URL` |
|---|---|
| Android emulator | `http://10.0.2.2:8000` |
| iOS simulator | `http://127.0.0.1:8000` |
| A real phone on the same Wi-Fi | `http://<your laptop's IP>:8000` |
| Flutter web or desktop | `http://127.0.0.1:8000` |

Find the laptop's address with `ipconfig` (Windows) or `ifconfig` (macOS) — the
`192.168.x.x` one. Test it from the phone's browser first:
`http://<that address>:8000/health`. If it hangs, it is the laptop's firewall,
not your code. On Windows, in an **administrator** PowerShell:

```powershell
New-NetFirewallRule -DisplayName "Furn API 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Profile Private -Action Allow
```

Pass the address at build time so the same code works later against a real
server:

```bash
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
```

```dart
const apiBaseUrl = String.fromEnvironment('API_BASE_URL');
```

Android debug builds also need `android:usesCleartextTraffic="true"` in the
debug manifest, and iOS an `NSAppTransportSecurity` exception, because plain
`http://` is blocked by default. Production will be HTTPS and needs neither.

---

## 3. Two backends, one sign-in

The app talks to **Supabase directly** for sign-in and for the marketplace
tables — profile, addresses, cart lines, orders, saved spaces, writing reviews —
and to **this API** for search, rooms, comparison, similar products, public
reviews, creating the cart, and intake.

Both use the same session. Send its token to this API:

```dart
final token = Supabase.instance.client.auth.currentSession?.accessToken;
headers: {'Authorization': 'Bearer $token'}
```

This API reads the catalogue **with that token**, so row-level security decides
what a customer can see. It cannot show them anything Supabase would not.

`docs/flutter-integration.md` is the full list of what goes where, including
the exact columns each table accepts on insert and update. Read it before
writing any direct Supabase write — sending one extra column fails with a
permission error.

---

## 4. The endpoints

| Screen | Call | Notes |
|---|---|---|
| Startup | `GET /v1/meta` | no sign-in; feature flags and limits |
| Search | `POST /v1/search` | 3–8 s. Send `history` for follow-ups |
| Empty search state | `GET /v1/search/examples?language=ar` | tap-to-try sentences |
| Filter chips | `GET /v1/search/vocabulary` | the words search understands |
| Product page, "you may also like" | `GET /v1/catalog/products/{id}/similar` | fast, no AI |
| Product page, reviews | `GET /v1/reviews/public?product_id=…` | no sign-in |
| Compare (2–4 products) | `POST /v1/compare` | fast, no AI |
| Room planner | `POST /v1/rooms/plan` | ~3 s. Send `history` for follow-ups |
| Room preview image | `POST /v1/rooms/image` | 10–20 s. Body is the plan's `image_request` |
| Catalogue list and detail | `GET /v1/catalog/products`, `/{id}` | or Supabase directly |
| Before the first "add to cart" | `POST /v1/cart` | returns `cart_id`; then add lines in Supabase |
| Service request form | `POST /v1/intake/service` | reads "the wardrobe door broke" into real services |
| Furnishing request form | `POST /v1/intake/furnishing` | reads "3 bedrooms and a reception, 150k" into the form |
| Checkout | `supabase.rpc('place_order', …)` | in Supabase, not here |

Start every session with `GET /v1/meta` and hide any feature whose flag is
`false` rather than letting a customer meet an error. Use its `limits` for
input lengths and counters instead of hard-coding them.

---

## 5. Nine rules that are not optional

1. **Every decimal is a JSON string.** `double.parse(json['price'] as String)`.
   A direct `as double` throws. This will be your first bug if you skip it.
2. **Show `discount_price` when it is present.** Search filters on what the
   customer actually pays; showing the full price makes a correct match look
   like it ignored the budget.
3. **Errors are `{"detail": {"code", "message"}}`.** Branch on `code`, display
   `message` — it is already in the customer's language.
4. **429 means slow down.** Wait the `Retry-After` header's seconds. Do not
   auto-retry sooner.
5. **401 `invalid_access_token`:** refresh the Supabase session and retry once.
6. **Every response carries `X-Request-ID`.** Log it. When you report a problem,
   send it — it is how the server log line for your exact request is found.
7. **A reason with `"basis": "inferred"` is a guess, not a fact.** Style, room
   and feel are not stated by any seller; the marketplace inferred them. The
   text already says so ("looks modern (our guess)"). Style it differently from
   a catalogue fact, or hide it. Never present it as a fact.
8. **Label AI previews.** Show the room preview's `label` and `disclaimer` with
   the image. The product list is what is sold; the picture is an illustration.
9. **`awaiting_answer: true` is a question, not an empty result.** The sentence
   asked for nothing — "عايز أثاث", or something off-topic entirely — so
   `items` is empty deliberately and `match_count` is 0. Show `follow_up`.
   Never render "no results found" for it: nothing was searched for, so nothing
   was missing. `candidate_count` still says how many products were examined,
   if you want a number on the screen.

---

## 6. A request, end to end

```dart
final res = await http.post(
  Uri.parse('$apiBaseUrl/v1/search'),
  headers: {
    'Authorization': 'Bearer $token',
    'Content-Type': 'application/json',
  },
  body: jsonEncode({
    'query': 'عايز كنبة مودرن بيج أقل من ٣٠ ألف',
    'limit': 20,
    'history': <String>[],   // earlier messages, oldest first, at most 4
  }),
);
```

The response carries the products, what the backend understood (`interpretation`),
why each one matched (`reasons`), near misses when nothing matched
(`alternatives`), a tappable follow-up question when the sentence was too vague
(`follow_up`), and `awaiting_answer`, which tells you to show that question
instead of an empty list.

A full Dart client, with the decimal parsing already correct, is in
`docs/flutter-search-contract.md` under "Copy this". Copy that rather than
writing your own models. The same file documents rooms, compare, similar
products, the two intake endpoints and every error code.

`docs/openapi.json` is generated from the running code, so you can also
generate models from it (openapi-generator's `dart-dio`, for example).

---

## 7. When something breaks

| What you see | What it means |
|---|---|
| `RuntimeError: Application configuration is invalid.` on startup | `.env` is missing or incomplete. Copy `.env.example` whole; several values it sets have no default |
| connection refused / hangs on a phone | the server is not on `0.0.0.0`, or the firewall; test `/health` in the phone's browser |
| `401 authentication_required` | no `Authorization` header |
| `401 invalid_access_token` | expired session; refresh and retry once |
| `503 search_unavailable` | no `GEMINI_API_KEY` in `.env`, or the model is down |
| `503 cart_unavailable` | no `SUPABASE_SECRET_KEY` in `.env` |
| `503 service_directory_unavailable` | the service list could not be read |
| `409 customer_profile_required` | that account is a seller or has no customer profile yet |
| `429 rate_limited` | you are over the per-minute limit; wait `Retry-After` |
| `422` with a FastAPI shape | your request body is malformed — check `/docs` |

The server prints one line per request: method, path, status, duration and the
same `X-Request-ID` your client saw. That line plus the id is usually enough to
find anything.

---

## 8. What I need back from you

**First, the six service descriptions.** The `service_type` table has six rows
with a `description` column that is empty on every one of them:

| Service | One sentence saying what it covers |
|---|---|
| Delivery | |
| Installation | |
| Assembly | |
| Disassembly | |
| Repair | |
| Maintenance | |

This is not cosmetic. `POST /v1/intake/service` routes a customer's problem to
one of these six, and with only a bare name to read it once sent "fix my
washing machine" to **Repair** at 0.95 confidence. One honest sentence each
fixes that better than anything I can do in code. If these are the owner's to
write rather than yours, please pass the question on.

**Then six questions, so the API fits your screens rather than the other way
round:**

1. Which of the screens in section 4 does your design actually have, and is
   there a screen with no endpoint behind it yet?
2. Does your design show *why* a product matched, and if so, how do you want to
   show the difference between a catalogue fact and a guess?
3. Do you need server-side filtering or sorting (category, price, colour chips)
   as its own endpoint, or is search enough?
4. Do you need the catalogue paginated through this API, or are you reading
   products straight from Supabase?
5. Which Flutter version, HTTP client and state management are you using, so
   the sample code matches what you already have?
6. Do you need the API reachable off your Wi-Fi — a deployed URL — and by when?

Answer in a message or by editing this file; either is fine.
