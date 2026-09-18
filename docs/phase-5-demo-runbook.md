# Demo runbook

For showing natural-language search against the live catalogue. Everything here
was run on 2026-09-17 against the real Supabase project and the real Gemini API.

## Starting the server

```bash
uv run python -m scripts.serve
```

**Not** `uv run uvicorn app.main:app`. On this machine that fails with

```text
error: Failed to spawn: `uvicorn`
Caused by: An Application Control policy has blocked this file. (os error 4551)
```

Windows Application Control blocks the `uvicorn.exe` console script. Importing
uvicorn from Python spawns no blocked executable, which is all `scripts/serve.py`
does. Worth knowing before demo morning rather than during it.

## Preflight, in order

1. `uv run python -m pytest -q` passes.
2. Server starts and logs `Application startup complete`.
3. `curl http://127.0.0.1:8000/health` returns `{"status":"ok",...}`.
4. A request with no token returns 401 `authentication_required`.
5. A request with a nonsense token returns 401 `invalid_access_token`. This one
   matters: it proves the app really reached Supabase Auth and Supabase
   rejected the token, so the authentication leg is live rather than assumed.
6. Prove search with a real signed-in session. From PowerShell or cmd, not Git
   Bash:

   ```bash
   uv run python -m scripts.live_search_smoke
   ```

   It asks for a real account's email and password, signs in to Supabase, and
   runs three searches through the real application with that user's token.
   The password is read without echo and neither it nor the token is printed.
   `PASSED` at the end means the last unproven link is proven. Git Bash is
   refused because it cannot hide the password.

## Sentences that hold up

Verified against the live catalogue of 45 products. Arabic sentences answer in
Arabic. Expect two to three seconds per query, most of it the model.

| Say this | What it shows |
|---|---|
| عايز كنبة مودرن بيج أقل من ٣٠ ألف | Budget, colour and style from one Arabic sentence. 9 matches |
| عايز سرير خشب زان بحد أقصى ١٥ ألف | Material plus budget. Exactly 1 match, which reads as precision |
| محتاج كنبة مش أوسع من ٢٠٠ سم | A width limit understood from Arabic. 3 matches |
| a beech wood bed under 20000 | The same engine answering in English |
| عايز أثاث | Too vague to search, so it asks back in Egyptian Arabic |
| عايز كنبة بمية جنيه | Finds nothing, and says price excluded all 45 |

The last one is worth doing on purpose. Refusing to invent a product is the
central design claim, and an empty result with a reason demonstrates it better
than any successful search.

## Sentences to avoid, and why

Each of these is understood correctly and then fails on missing catalogue data,
so they look worse than the system is.

| Avoid | What goes wrong |
|---|---|
| عايز سفرة تكفي ٦ أفراد | Seating capacity is not a catalogue field, so a four-seater outranks the six-seater |
| عايز أثاث لغرفة النوم في حدود ٢٠ ألف | No category and no style data, so ranking falls back to cheapest and dining chairs come first |
| محتاج دولاب أبيض كبير | The colour applies; "كبير" does not, because no size was stated in numbers. A child's wardrobe ranks first |
| I need a turquoise coffee table | Coffee tables are not stocked. The word is now reported in `unresolved`, but the response still lists the catalogue unless the client acts on that |

## Room planning

Plan, then preview. The plan answers in about three seconds; the preview image
takes ten to twenty, so show the plan first and let the image arrive after.
Always state a style: without one, a room can mix styles.

| Say this | What it shows |
|---|---|
| عايز أوضة معيشة مودرن فيها كنبة و2 كرسي وترابيزة في حدود 40 ألف | A coherent modern room, 24,330 of 40,000, with the colour to order for each piece |
| a scandinavian living room with a sofa, two chairs and a table under 30000 | The same in English, all Scandinavian |
| عايز كنبة و4 كراسي بـ 10 آلاف | Cannot be done for 10,000, and says so: the cheapest room is 8,700 over |

The preview is labelled "معاينة بالذكاء الاصطناعي" and carries a disclaimer.
Leave both visible. It is generated, and it can drift, including drawing one
chair where two were planned; the plan's list is what the customer buys.

Avoid asking for five of anything: no chair has five in stock in one colour, so
that piece comes back unfilled. Avoid "coffee table": it is not stocked.

## If something fails mid-demo

| Symptom | Meaning |
|---|---|
| 401 `authentication_required` | No bearer token reached the API |
| 401 `invalid_access_token` | Supabase rejected the token; the session likely expired. Sign in again |
| 503 `search_unavailable` | No `GEMINI_API_KEY`, or Gemini timed out or rate limited. Retrying is reasonable |
| 502 `search_upstream_error` | Gemini answered with something untrustworthy. Rephrase rather than retry |
| 503 `catalogue_service_unavailable` | Supabase is unreachable |
| 400 parsing error from curl | Git Bash mangling Arabic in an inline `-d`. Put the body in a file and use `--data-binary @file` |

Every search spends one Gemini call. There is no caching and no rate limiting,
which is fine for a demo and is not fine for real traffic.

## Two client-side details that change how it looks

**Show the discounted price.** Search filters on what a customer actually pays.
The Cairo sofa lists at 12000 and charges 9999, and a bed listed at 21000
legitimately matches "under 20000" through its 17850 discount. Showing only the
list price makes correct behaviour look like a bug.

**Use `unresolved`.** When it comes back non-empty, the customer used a word the
catalogue does not know. Saying so beats showing a grid of everything.

## Not covered

The Phase 3.2C and 3.2D security packages are still unapplied, so the
row-level-security hardening from the audit is not in place. That is acceptable
for a demo and is the first thing to deal with before real users.
