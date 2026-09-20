# CLAUDE.md — Furn-APP Backend + AI Master Plan

> Primary project blueprint for Claude Code. Read this file before changing backend, Supabase, security, catalogue, AI, search, recommendation, vision, or deployment code.

## 1. Project Overview

**Furn-APP** is a furniture marketplace with:

- Flutter frontend
- Supabase Auth
- Supabase PostgreSQL
- PostgREST
- Row Level Security
- Python FastAPI backend
- AI search/recommendation layer
- future room-image analysis
- future conversational furniture assistant

Supabase remains the system of record for authentication, users, sellers, products, prices, stock, orders, addresses, and marketplace data. FastAPI provides authenticated APIs, stable client-facing models, business logic, secure catalogue access, AI orchestration, search, recommendation, comparison, vision, and future personalization.

## 2. System Architecture

```text
Flutter Furn-APP
      │
      │ HTTPS + Supabase JWT
      ▼
FastAPI Backend
      │
      ├── Auth / Current User
      ├── Catalogue API
      ├── Business Logic
      ├── Search
      ├── Recommendation
      ├── AI Orchestration
      ├── Comparison
      ├── Vision
      └── Observability
      │
      ▼
Supabase
      ├── Auth
      ├── PostgreSQL
      ├── PostgREST
      ├── RLS
      ├── Catalogue
      ├── Sellers
      ├── Inventory
      ├── Customers
      └── Orders
```

## 3. Source-of-Truth Rule

Marketplace facts must come from trusted application data. AI must never invent products, product IDs, sellers, prices, stock, dimensions, materials, images, availability, discounts, or publication state.

AI may understand natural language, infer preferences, ask clarifying questions, create structured search requirements, rank real products, compare real products, explain recommendations, infer room style, and suggest real alternatives.

If no suitable product exists, return that reality.

## 4. Current Project State

```text
Phase 1      FastAPI Foundation                    COMPLETE
Phase 2      Supabase Authentication               COMPLETE
Phase 3      Catalogue Integration                 COMPLETE
Phase 3.1    Live Catalogue Verification           COMPLETE
Phase 3.2A   Security Audit                        COMPLETE
Phase 3.2B   Initial Security Hardening            APPLIED LIVE, VERIFICATION PASSED (13/13)
Phase 3.2C   Correction + Reconciliation           APPLIED LIVE 2026-09-18, VERIFICATION PASSED (20/20)
Phase 3.2D   Deferred-Finding Remediation          APPLIED LIVE 2026-09-18, VERIFICATION PASSED (12/12)
Checkout     place_order + stock return             APPLIED LIVE 2026-09-18, LIVE-TESTED
Design links customer-attached design versions      APPLIED LIVE 2026-09-19 (post-3.2D)
Phase 4A-4D  AI Foundation                         COMMITTED (see section 13)
Phase 5A     Natural-Language Parser               COMMITTED, LIVE-VERIFIED
Phase 5C     Search Endpoint POST /v1/search       COMMITTED, LIVE-VERIFIED
Phase 6D     Comparison + similar products         COMMITTED, VERIFIED LOCALLY
Phase 10A/C  Request logging, rate limits, cache   COMMITTED, VERIFIED LOCALLY
Phase 7A     Clarification with tappable answers   COMMITTED; not yet exercised live
Phase 9B/6.10 Personalization + seller fallback    COMMITTED; inert for want of data
Intake AI    Service triage + furnishing brief     COMMITTED, LIVE-VERIFIED 2026-09-20
Fuzzy search Inferred style/room/feel tags         APPLIED LIVE 2026-09-20, VERIFIED (9/9)
```

The 2026-09-20 work is in docs/phase-9-fuzzy-intake-personalization.md.

Fuzzy search is live. `migrations/product-search-tags-2026-09-20.sql` was
applied on 2026-09-20 (verification 9/9) and `seed/search-tags-2026-09-20.sql`
loaded 277 inferred style, room and feel tags over all 45 eligible products,
read back through PostgREST as an anonymous visitor. These are the first rows
in this project that are not marketplace facts: they rank, never filter, cap
below a seller-confirmed attribute, and every reason built from one is
labelled a guess. `modern` sits on 36 of the 45 products, so a "modern" search
barely reorders; the discriminating tags are the rarer ones (scandinavian,
industrial, luxury, space_saving, hotel_like, cosy).

The signed-in smoke test passed end to end on 2026-09-20 at 17:15 with a real
customer session: search, the fuzzy sentence ranking on inferred tags with both
reasons labelled a guess, a follow-up, alternatives, compare, similar, public
reviews, service triage (a broken wardrobe door to Repair 0.85, a washing
machine to nothing), the furnishing brief (3 bedrooms and a reception at
150,000, style modern) and a room plan.

Two features are live in code but did nothing in that run, for want of data
rather than through a fault. Personalization needs two purchases and customer1
has one, so `personalized` was false. The seller fallback found no offers
because `custom_offering` is empty (0 rows). Phase 7A's tappable question was
not exercised at all: the smoke test has no sentence vague enough to trigger
one.

The three new prompts were measured live on 2026-09-20 with
`scripts/live_intake_smoke.py` (tagging, triage, brief; Gemini only, no
Supabase): triage 10/10, brief 16/16, tagging stable on style and room. It
found a real vocabulary gap first: every Egyptian colloquial room word (أوضة
نوم, أوض نوم, غرف نوم and the rest) resolved to nothing, so "٣ أوض نوم" became
a brief with no bedrooms, and search had the same blind spot. Fixed. It also
found that the tagger rotates its third feel between runs, which is why tags
are written as the consensus of several runs.

Branches: **`main` only.** On 2026-09-18, at the user's explicit request, `main`
was fast-forwarded to the tip of the stacked branches and the three phase
branches (`phase-3.2c-security-hardening`, `phase-3.2d-security-hardening`,
`phase-4a-catalogue-audit`) were deleted locally and on origin. Every commit
they held is on `main`; the history is linear, so nothing was lost.

**Being on `main` is not approval.** The Phase 3.2C and 3.2D SQL packages now
sit on `main` as files, still NOT EXECUTED and still pending human security
review. Merging code and applying a migration are different acts; section 15
still forbids the second without explicit authorization. Review now happens on
`main` directly (or on a review branch cut from it), not through the old PR
chain.

`README.md` is still the Phase 1 text because three security tests pin it
byte-for-byte as part of those packages. The current overview is
`docs/getting-started.md`. Update the README only together with the pins, after
the security review.

Live catalogue state (2026-09-17): the Phase 5 seed is loaded on the project
`.env` points at, giving 45 recommendation-eligible products, 41 seeded and 4
real. That project is not a separate testing branch. Remove the seed with
`seed/phase-5-fake-catalogue-remove.sql` before real customers see it.

Phase 3.2D resolves the 56 items 3.2C deferred plus two observed state-write
findings. Its three SQL files are generated from `docs/evidence/phase-3.2d/`
by `tests/phase_3_2d_package.py`; edit the generator and rerun it, never the
SQL. Decisions are recorded in `docs/phase-3.2d-decisions.md`; design in
`docs/phase-3.2d-security-hardening.md`. The live acceptance utility is
`scripts/live_phase_3_2d_acceptance.py` (GET and no-op PATCH only; never run
it without explicit authorization).

Latest verification (2026-09-18, on main after the fast-forward):

```text
pytest:                  719 passed (also in a clean copy with no .env)
ruff:                    passed
format:                  passed
git diff --check:        clean
SQL parsing:             all seed and security files parse
3.2C FOR ALL reconciliation:  19/19
3.2C finding reconciliation:  122/122
3.2D deferred reconciliation: 56/56 (20 remediated, 31 accepted, 7 false positive)
generator == SQL on disk:     yes (both security and seed generators)
app startup:             real lifespan boots; /health 200 with X-Request-ID
Supabase Auth leg:       reachable; a bogus token returns 401 invalid_access_token
```

Current status:

```text
Phase 3.2B migration:    APPLIED LIVE (found applied 2026-09-18); verification 13/13
Phase 3.2C migration:    APPLIED LIVE 2026-09-18 from commit a34159d; verification 20/20
Phase 3.2C undo:         rollback/phase-3.2c-undo-2026-09-18.sql (not run)
Phase 3.2D migration:    APPLIED LIVE 2026-09-18 from 7bedfb2 after a passing full rehearsal;
                         verification 12/12; undo rollback/phase-3.2d-undo-2026-09-18.sql
Checkout migration:      APPLIED LIVE from migrations/checkout-2026-09-18.sql (071ea16);
                         33/33 on a PostgreSQL replica first; live order placed and
                         cancelled 2026-09-19 00:06, stock returned
Live acceptance:         NOT EXECUTED (3.2C utility needs fixture accounts)
Approval:                3.2C, 3.2D and checkout applied at the user's decision without
                         an independent security review
Search with a real user session:  PASSED 2026-09-18 (scripts/live_search_smoke.py)
Smoke test after 3.2C:   PASSED 2026-09-18 22:02 (search, follow-up, meta, public
                         reviews, similar, compare, room plan; real customer account)
Server-side cart:        PASSED live 2026-09-18 22:54 (POST /v1/cart created
                         customer2's cart, second call returned it, created=false)
Supabase secret key:     in .env (git-ignored) since 2026-09-18; used ONLY by
                         app/cart/gateway.py SupabaseCartCreator to insert a cart
```

Applying 3.2C exposed eight bugs in the package, none in the database: six in
the migration and preflight (unqualified names under `search_path =
pg_catalog`, a wrong enum order, wrong policy roles, `pg_catalog.boolean` /
`integer`, an exact-only empty `search_path` match, and `aclexplode` on an
empty array) and two in the verification file (policy text printed without
`public.`, and the storage owner's own privileges). Each was confirmed against
live data before it was fixed, and `tests/test_security_sql_name_resolution.py`
now fails on every one of those patterns. The 3.2D generator shares the first
several and was fixed too, but 3.2D has still never run against a database:
expect its preflight to find more. The full record is in
docs/security-apply-runbook.md.

On 2026-09-18 the user decided to apply 3.2B and 3.2C directly to the live
project, skipping the testing-branch step. The user runs each file in the
Supabase SQL Editor; the step-by-step order, stop conditions and smoke tests
are in docs/security-apply-runbook.md. 3.2D is held until the backend has a
cart endpoint and Flutter uses the order and service-request functions. The
table above changes only when a package's verification sections are reported
passing.

Starting the API: `uv run python -m scripts.serve`. Not `uv run uvicorn`, which
Windows Application Control blocks on this machine (os error 4551).

CI: `.github/workflows/ci.yml` runs pytest, ruff check, ruff format --check and
a whitespace check on every push to `main` and every pull request, with no
secrets. Never add provider or Supabase keys to it.

Cost controls (app/core/): the three model-backed routes are rate limited per
verified user id (defaults 20 searches/min, 10 room plans/min, 20 previews/hour;
429 with Retry-After, localized) and cache identical requests for 15 minutes.
Parses are cached by exact sentence; previews by exact prompt plus reference
photo bytes, and only after every product is re-checked under the caller's
token. Both are in process memory: correct for one server, must move to a
shared store before a second. Every response carries X-Request-ID and produces
one log line (method, encoded path, status, duration); headers, query strings,
bodies and exception messages are never logged.

## 5. Backend Features

### 5.1 Health / Runtime

Existing:

```http
GET /health
```

Responsibilities:

- FastAPI startup
- configuration loading
- dependency wiring
- router registration
- health response

Status: **Implemented**

### 5.2 Configuration

Expected configuration:

- Supabase URL
- Supabase public/anon key when needed
- privileged server credentials only where justified
- AI provider credentials
- environment name
- logging level
- feature flags
- timeouts

Rules:

- secrets are never committed
- `.env.example` contains placeholders only
- secrets are never printed

Current file:

```text
app/config.py
```

Status: **Implemented / Extend as needed**

### 5.3 Authentication

```text
Flutter
   │ Bearer Supabase JWT
   ▼
FastAPI
   ▼
Auth dependency
   ▼
Supabase auth verification
   ▼
Authenticated current user
```

Existing files:

```text
app/auth/
├── gateway.py
├── dependencies.py
└── models.py
```

Representative route:

```http
GET /v1/me
```

Rules:

- do not trust client-provided user IDs as identity
- derive identity from the authenticated token
- do not expose privileged keys
- preserve RLS-aware user flows

Status: **Implemented**

### 5.4 Authorization / RLS

Normal authorization path:

```text
JWT
 ↓
FastAPI identity context
 ↓
user-scoped Supabase request
 ↓
PostgreSQL RLS
```

Do not use `service_role` as a shortcut for normal user operations.

Security areas include:

- customer ownership
- seller ownership
- seller lifecycle state
- product publication state
- child-table authorization
- address ownership
- financial boundaries

Status: **Audited; hardening package complete locally; awaiting human review**

### 5.5 Catalogue API

Current architecture:

```text
router
  ↓
dependencies
  ↓
gateway
  ↓
Supabase/PostgREST
  ↓
upstream model
  ↓
transform
  ↓
public model
```

Files:

```text
app/catalog/
├── gateway.py
├── dependencies.py
├── upstream_models.py
├── models.py
├── transform.py
└── router.py
```

Representative routes:

```http
GET /v1/catalog/products
GET /v1/catalog/products/{product_id}
```

Known real-schema mappings include:

```text
width_cm
height_cm
depth_cm
weight_kg
```

Status: **Implemented and live-verified with real products**

### 5.6 Product Detail

Target stable fields:

```text
id
title
description
category
seller
price
discount
images
dimensions
material
color
finish
attributes
stock
availability
publication state
```

Do not expose raw unstable Supabase row shapes directly to Flutter.

Status: **Partially covered by catalogue; expand when needed**

### 5.7 Product Attribute Normalization

Normalize:

- dimensions
- units
- materials
- colors
- styles
- finishes
- room types
- capacity
- categories
- synonyms

Example:

```text
"2.2 m"
"220cm"
"220 cm"
```

becomes:

```text
width_cm = 220
```

Keep original source values; add normalized/search-oriented representation.

Status: **Planned — Phase 4**

### 5.8 Structured Search

Filters may include:

```text
category
price range
width range
height range
depth range
material
color
style
stock
availability
seller
publication status
room type
capacity
```

Status: **Implemented (Phase 4D, app/search/service.py). Capacity and room type
are not catalogue fields, so "seats six" is understood and cannot be matched.**

### 5.9 Search Specification

Target typed model:

```json
{
  "category": "sofa",
  "hard_constraints": {
    "max_price": 30000,
    "max_width_cm": 220,
    "in_stock": true
  },
  "soft_preferences": {
    "style": ["modern"],
    "color": ["beige"]
  }
}
```

Potential models:

```text
SearchIntent
SearchConstraint
SearchPreferences
SearchSpecification
SearchResult
```

Status: **Implemented (Phase 4C, app/search/models.py). This is what the
roadmap calls Phase 5B.**

### 5.10 Hybrid Retrieval

```text
SearchSpecification
       ↓
Structured database filters
+ Keyword/full-text search
+ Attribute matching
+ Semantic/vector search
       ↓
Candidate products
```

Structured filters handle objective constraints. Semantic retrieval handles fuzzy concepts such as cozy, minimal, luxury, Scandinavian, warm, hotel-like.

Status: **Structured half implemented and shipped as POST /v1/search. The
semantic and vector half is deliberately deferred: section 11 requires
evaluation to prove it earns its place, and that evaluation is Phase 5D.**

### 5.11 Recommendation Engine

```text
candidate products
      ↓
hard-constraint validation
      ↓
feature scoring
      ↓
ranking
      ↓
top recommendations
```

Possible score components:

- semantic relevance
- style match
- color match
- material match
- size suitability
- price fit
- availability
- seller quality
- personalization

Hard constraints must pass before soft ranking.

Status: **Planned — Phase 6**

### 5.12 Compatibility Engine

Potential deterministic rules:

```text
chair seat height ↔ dining table height
coffee table width ↔ sofa width
bed dimensions ↔ room size
furniture footprint ↔ available room area
```

Use ordinary code for deterministic calculations. Use AI only for qualitative judgments.

Status: **Planned**

### 5.13 Product Comparison

Future capability:

```text
compare Product A vs Product B vs Product C
```

Compare:

- price
- dimensions
- materials
- style
- availability
- seller
- strengths
- tradeoffs
- fit to user requirements

Status: **Implemented (Phase 6D): POST /v1/compare, deterministic, facts
only, never names a winner. "Fit to user requirements" is not included because
the endpoint is not told the requirements. Similar products:
GET /v1/catalog/products/{id}/similar.**

### 5.14 Audit / Observability

Future logs may include:

- request ID
- route
- status code
- latency
- authenticated user ID when appropriate
- Supabase errors
- search latency
- candidate count
- ranking latency
- AI latency
- AI failures

Never log JWTs, passwords, service-role keys, or secrets.

Status: **Partial. Request id, route, status and latency are logged per request
(app/core/observability.py). User id, AI latency and AI failure counts are not
yet.**

### 5.15 Security Migration Pipeline

```text
evidence
  ↓
SQL
  ↓
local validation
  ↓
tests
  ↓
preflight
  ↓
human review
  ↓
controlled migration
  ↓
verification
  ↓
live acceptance
  ↓
evidence capture
```

Current status: **Local security package ready; human review required**

## 6. AI Features

### 6.1 Natural-Language Furniture Search

Example:

```text
"I need a modern beige sofa around 220 cm
for a small living room under 30,000 EGP."
```

AI converts it to:

```json
{
  "category": "sofa",
  "style": ["modern"],
  "color": ["beige"],
  "preferred_width_cm": 220,
  "room_type": "living_room",
  "max_price": 30000
}
```

Then the backend searches real catalogue data.

Status: **Implemented locally and driven end to end against the live Gemini
API on 2026-09-17. Parser in app/ai/ (Phase 5A), endpoint POST /v1/search
(Phase 5C). Passed with a real signed-in Supabase session on 2026-09-18:
Arabic and English searches, discount pricing, and nearest alternatives all
returned correctly through the real auth check and row-level security.**

### 6.2 Requirement Extraction

AI should separate:

```text
hard constraints
soft preferences
unknowns
```

Example:

```text
"I need a beige sofa under 30k, preferably modern."
```

Hard:

```text
category = sofa
max_price = 30000
```

Soft:

```text
color = beige
style = modern
```

Status: **Implemented (Phase 5A). "around 220 cm" is read as a preference and
"under 30,000" as a limit, verified live in Arabic and English.**

### 6.3 Clarification

Ask only when needed.

Example:

```text
User: I need a dining table.
```

Possible clarification:

```text
How many people should it seat, and roughly how much space do you have?
```

A detailed query should search immediately.

Status: **Partially implemented. The parser returns a `clarification` question
in the customer's language when a sentence is too vague, and the endpoint
passes it through. There is no conversational follow-up yet; that is Phase
7A.**

### 6.4 Semantic Search

Semantic search should understand concepts such as:

```text
cozy
luxury
warm
minimal
Scandinavian
hotel-like
modern-classic
```

Semantic relevance must not override hard constraints.

Status: **Planned**

### 6.5 Product Recommendation

For each recommendation provide:

```text
real product
why it matches
which constraints it satisfies
tradeoffs
alternatives
```

Example:

```text
Product X
- width 218 cm, inside 220 cm limit
- beige upholstery
- modern design
- price 28,500 EGP

Tradeoff:
- only 3 units currently available
```

Status: **Planned**

### 6.6 Grounded Recommendation Explanations

Good:

```text
"This sofa fits your width limit because its catalogue width is 218 cm."
```

Avoid subjective claims presented as fact.

Separate:

```text
catalogue fact
inference
aesthetic judgment
```

Status: **Planned**

### 6.7 Product Comparison

Example user request:

```text
"Which of these three sofas is better for a small room?"
```

AI may compare:

- size
- price
- style
- materials
- stock
- fit to constraints
- tradeoffs

All product facts come from backend data.

Status: **Deterministic half implemented (POST /v1/compare, section 5.13). The
AI half, answering "better for a small room", is not built: it needs the room's
size as input, and then a judgement separated from the facts per 6.6.**

### 6.8 Room Image Analysis

Pipeline:

```text
room image
   ↓
vision model
   ↓
room profile
   ↓
furniture requirements
   ↓
catalogue search
   ↓
recommendations
```

Possible inferred fields:

- room type
- dominant colors
- approximate style
- existing furniture
- floor appearance
- wall appearance
- lighting
- approximate free-space zones
- design opportunities

Do not claim exact measurements from a single image without calibration.

Status: **Planned — Phase 8**

### 6.9 Image + Text Search

Example:

```text
[room image]
"I need a coffee table that matches this room and costs under 12,000 EGP."
```

Flow:

```text
image analysis
+
text constraints
  ↓
combined SearchSpecification
  ↓
real catalogue
  ↓
ranked recommendations
```

Status: **Planned**

### 6.10 Seller / Sponsored Fallback

If no exact match exists:

```text
no exact match
  ↓
nearest real alternatives
  ↓
optional clearly-labelled seller/sponsored result
```

Never fabricate a product. Sponsored ranking must never be disguised as objective relevance.

Status: **Planned**

### 6.11 Arabic + English Search

Future examples:

```text
عايز كنبة مودرن بيج أقل من ٣٠ ألف
```

```text
عايز modern dining table لستة أفراد
```

Normalization should support:

- Arabic digits
- Western digits
- جنيه / EGP / LE
- Arabic furniture vocabulary
- mixed Arabic/English styles

Status: **Implemented. Arabic digits, "ألف", and mixed sentences all parse, and
the response answers in the customer's language with localized vocabulary
labels. Verified live on 2026-09-17.**

### 6.12 Personalization

Possible signals:

- saved products
- clicks
- searches
- preferred styles
- colors
- budget bands
- materials
- room types
- explicit likes/dislikes

Authorization must still apply.

Status: **Planned — Later phase**

### 6.13 Future Agent Actions

Potential future actions:

```text
save product
add to wishlist
compare saved items
find similar products
prepare room set
find seller alternatives
```

The LLM must use controlled application tools. It must never get unrestricted database credentials.

Status: **Future**

## 7. AI Architecture

```text
User request
   ↓
AI requirement parser
   ↓
typed SearchSpecification
   ↓
clarification if required
   ↓
structured filters
+ keyword search
+ semantic retrieval
   ↓
candidate products
   ↓
hard-constraint validation
   ↓
recommendation scoring
   ↓
compatibility checks
   ↓
AI explanation
   ↓
grounded response
```

## 8. Target Backend + AI Module Structure

Create modules only when their features are needed.

```text
app/
│
├── main.py
├── config.py
│
├── core/
│   ├── exceptions.py
│   ├── logging.py
│   ├── security.py
│   └── telemetry.py
│
├── auth/
│   ├── gateway.py
│   ├── dependencies.py
│   ├── models.py
│   └── service.py
│
├── users/
│   ├── models.py
│   ├── service.py
│   └── router.py
│
├── catalog/
│   ├── gateway.py
│   ├── dependencies.py
│   ├── upstream_models.py
│   ├── models.py
│   ├── transform.py
│   ├── service.py
│   └── router.py
│
├── search/
│   ├── models.py
│   ├── parser.py
│   ├── filters.py
│   ├── retrieval.py
│   ├── ranking.py
│   └── service.py
│
├── recommendations/
│   ├── models.py
│   ├── scoring.py
│   ├── compatibility.py
│   ├── explanations.py
│   └── service.py
│
├── ai/
│   ├── models.py
│   ├── prompts/
│   ├── providers/
│   ├── orchestration/
│   ├── guardrails/
│   └── service.py
│
├── vision/
│   ├── models.py
│   ├── analysis.py
│   └── service.py
│
└── audit/
    ├── events.py
    ├── models.py
    └── gateway.py
```

## 9. AI Provider Boundary

Avoid vendor-specific calls inside routers.

Conceptual interface:

```text
AIProvider

parse_requirements(...)
rank_candidates(...)
explain_recommendations(...)
analyze_room(...)
```

Keep provider-specific logic behind a narrow boundary.

As built in Phase 5A, the protocol is one vendor-neutral method,
`generate_json(instruction, prompt, schema)`. The capabilities listed above are
backend functions built on top of it, not methods a vendor implements:
`parse_requirements` is `app/ai/service.py`. Prompts, response schemas, and
guardrails therefore sit above the boundary, so a new provider inherits them
instead of reimplementing them. User text is always passed as `prompt` and
never spliced into `instruction`.

## 10. AI Guardrails

Validate AI output before application use.

Examples:

```text
unknown category → reject or normalize
negative max_price → reject
unknown product ID → reject
invalid dimension → reject
```

Typed validation sits between model output and business logic.

Phase 5A implements this as `app/ai/models.py` (the untrusted draft shape) and
`app/ai/guardrails.py` (bounds, then vocabulary resolution through
`build_specification`). Two properties matter and are tested: the draft has no
field capable of carrying a marketplace fact, so an invented product has
nowhere to travel; and an unrecognised word is reported as unresolved, never
mapped to a near neighbour. A bad hard constraint rejects the draft, because
silently widening a stated limit shows the customer products they ruled out; a
bad soft preference is dropped, because it only orders correct results.

## 11. Vector Search Plan

Do not add a separate vector database automatically.

First evaluate:

```text
Supabase PostgreSQL + pgvector
```

Introduce vector search only after:

- catalogue normalization exists
- structured search exists
- semantic use cases are clear
- evaluation proves value

## 12. AI Evaluation

Create repeatable benchmark cases.

Example:

```text
query:
modern beige sofa under 30k

expected:
category = sofa
max_price = 30000
style contains modern
color contains beige

acceptable products:
[...]

unacceptable products:
[products over budget]
```

Measure:

- requirement extraction accuracy
- retrieval recall
- top-k relevance
- hard-constraint violation rate
- hallucinated product rate
- clarification quality

Marketplace hallucination target: **0**

## 13. Master Roadmap

```text
BACKEND FOUNDATION
├── Phase 1   FastAPI Foundation                COMPLETE
├── Phase 2   Authentication                    COMPLETE
├── Phase 3   Catalogue                         COMPLETE
├── Phase 3.1 Live Catalogue                    COMPLETE
├── Phase 3.2A Security Audit                   COMPLETE
├── Phase 3.2B Initial Hardening                COMPLETE PACKAGE
├── Phase 3.2C Corrections                      COMMITTED, PENDING REVIEW
└── Phase 3.2D Deferred Findings                COMMITTED, PENDING REVIEW

SECURITY DEPLOYMENT
├── Human Review (3.2C, then 3.2D)             CURRENT
├── Preflight
├── Migration
├── Verification
└── Live Acceptance

AI FOUNDATION
├── Phase 4A Catalogue Quality Audit            COMPLETE (read-only run 2026-09-16)
├── Phase 4B Product Normalization              IMPLEMENTED LOCALLY (app/catalog/normalization.py)
├── Phase 4C Search Schema                      IMPLEMENTED LOCALLY (app/search/models.py)
└── Phase 4D Deterministic Structured Search    IMPLEMENTED LOCALLY (app/search/service.py)

Seed data: tests/seed_catalogue.py defines 44 fake products and renders
seed/phase-5-fake-catalogue.sql (testing branch only, never production; the
seed/ folder is the only place application-row DML may live). Offline tests
and evaluation use the same definition through as_json_fixture().

AI provider: Google Gemini, chosen 2026-09-17, model gemini-3.6-flash. The
vendor boundary is app/ai/provider.py; the only vendor code is
app/ai/providers/gemini.py, which calls the REST API over the existing httpx
client so no dependency is added. AI settings are a separate optional group
(app/config.py AISettings), so an instance with no GEMINI_API_KEY still starts
and refuses only the AI path.

Verified against the live API on 2026-09-17 via scripts/live_gemini_smoke.py:
Arabic, English, and too-vague sentences all parsed correctly. Two findings are
baked into the defaults. gemini-2.5-flash is listed but returns 404 on
generateContent for new keys, so the default is gemini-3.6-flash. Reasoning
tokens are charged against the output cap, so GEMINI_THINKING_BUDGET defaults
to 0 and the request adds the budget to the cap; without that the same request
overran the cap and returned truncated JSON, which the finishReason check
correctly refused.

The test suite never contacts a provider. Only scripts/live_gemini_smoke.py
does, and only with --i-have-authorization.

AI SEARCH
├── Phase 5A Natural-Language Parser         IMPLEMENTED LOCALLY (app/ai/)
├── Phase 5B SearchSpecification             DONE IN PHASE 4C (app/search/models.py)
├── Phase 5C Search Endpoint                 IMPLEMENTED LOCALLY (POST /v1/search)
└── Phase 5D Search Evaluation               IMPLEMENTED, RUN 2026-09-17

Phase 5D scored 48/48 on 16 cases at 3 repeats: extraction, field accuracy,
recall and clarification all 100%, constraint violations and hallucinations
both 0%. Ground truth is computed rather than listed, so the benchmark does not
rot when the seed changes, and 13 tests check the benchmark itself can fail
before it is allowed to grade anything. Design and the verdict are in
docs/phase-5d-search-evaluation.md; run it with
scripts/live_search_evaluation.py --i-have-authorization.

Its first run caught a real inconsistency and forced a decision now written
into the prompt: a colour the customer describes is a preference, a colour they
demand is a requirement, and a material they name is always a requirement.

Verdict on section 11: vector search is NOT yet justified. Structured
retrieval already reaches 100% recall on every case, so there is nothing for
semantic retrieval to recover, and the fuzzy cases where it would win (cosy,
luxury, hotel-like) cannot be benchmarked at all because the enrichment tables
are empty. Order is enrichment data, then fuzzy cases, then the vector
decision.

Phase 5C deliberately ships structured retrieval only, not the hybrid/vector
retrieval the name implies: section 11 requires evaluation to prove vector
search earns its place, and that evaluation is Phase 5D. Design and the live
run are in docs/phase-5c-search-endpoint.md. The endpoint reads the catalogue
with the caller's own token through the existing gateway, so RLS still decides
what is searchable, and ranking stays deterministic so the model shapes the
question but never the answer.

The response answers in the customer's language: any Arabic in the sentence,
including a mixed sentence, gets Arabic. This is deterministic, not translated
at request time. Phase 4C detects the language and the Phase 4B vocabularies
supply both labels, so every term ships a stable slug plus a localized label,
and error messages localize while their codes do not. Catalogue text is never
translated because it is a marketplace fact. The "Answering in the customer's
language" section of docs/phase-5c-search-endpoint.md records what is still
English only.

AI RECOMMENDATION
├── Phase 6A Ranking / Scoring               DONE IN PHASE 4D (app/search/ranking.py)
├── Phase 6B Compatibility                   BLOCKED: needs seat/table heights
├── Phase 6C Explanation                     IMPLEMENTED LOCALLY, LIVE-VERIFIED
├── Phase 6D Comparison                      IMPLEMENTED LOCALLY (+ similar products)
└── Phase 6.10 Nearest alternatives          IMPLEMENTED LOCALLY, LIVE-VERIFIED

Phase 6C and 6.10 are in app/recommendations/ and deterministic: no provider is
called, so neither can invent a product, a price, or a reason. Reasons are read
back from the ConstraintCheck values Phase 4D already recorded. Design and the
live measurements are in docs/phase-6-recommendations.md.

Verifying them surfaced a parser bug that predated them: the prompt listed the
catalogue vocabulary and asked the model to pick the matching entry, and it
copied the wrong entry in 1 run of 4, answering Beds to an Arabic sofa query.
Removing that paragraph made it worse (2 of 4). The fix was to stop asking the
model to choose a category at all: it copies the customer's own word and the
Phase 4B vocabulary maps it, which is what the vocabulary is for. Re-measured
over nine sentences at five runs each, every answer was correct.

AI ASSISTANT
├── Phase 7A Clarification                   IMPLEMENTED LOCALLY 2026-09-20
├── Phase 7B Conversational Search Refinement IMPLEMENTED, LIVE-VERIFIED 2026-09-18
└── Phase 7C Assistant State                 NOT BUILT (the app holds the history)

Phase 7B: POST /v1/search and POST /v1/rooms/plan accept `history`, up to four
earlier messages, oldest first. With no history the model gets exactly the
instruction and prompt it always did (a test pins it). With history the
messages travel only in the prompt, joined in order as one sentence, and a
fixed REFINEMENT_NOTE (app/ai/service.py) is appended to the instruction.
Measured live: labelled lines 23/24 against one sentence 24/24; "cheaper"
dropped an earlier limit 1 in 3 until the note forbade it; the fragment
"في حدود ١٥ ألف" read as a preference 3 in 5 until the note pinned it as a
limit; final 25/25 search and 6/6 room follow-ups.

VISION
├── Phase 8A Room Image Analysis             NOT BUILT, by decision (see below)
├── Phase 8B Image + Text Requirements       NOT BUILT
├── Phase 8C Image-to-Catalogue Recommendation
└── Room planning from text + AI preview     IMPLEMENTED LOCALLY, LIVE-VERIFIED 2026-09-18

Room planning (app/rooms/) replaces photo analysis for now, at the user's
direction on 2026-09-18: no customer photos. POST /v1/rooms/plan reads one
sentence ("a modern living room with a sofa, 2 chairs and a table under 40k")
into slots, and deterministic code picks one real product per slot so the whole
room fits the budget, with enough stock in one colour for each quantity. POST
/v1/rooms/image renders a labelled AI preview of exactly those products from
their real photos. The model never chooses a product; the image is the only
non-fact in the feature and is labelled everywhere. Product photos are fetched
server-side through an HTTPS host allowlist because the URLs are
seller-controlled. Default image model gemini-2.5-flash-image (14.5 s against 29
s for nano-banana-pro-preview at comparable fidelity). Design, measurements and
known limits: docs/phase-8-room-planning.md.

Room plans accept a budget per piece and for the whole room, ask for one when
none is given (without blocking), and offer up to two upgrades per piece: a
real product that scores higher on what the customer asked for and costs at
most 15% past the budget it would exceed. "Better" is never price or taste;
each upgrade states the concrete thing it matches. The preview prompt now asks
for a designer-styled room with small decor, while still forbidding extra
furniture; the disclaimer says decor is illustration only.

Photo analysis was probed on 2026-09-18 and works, but gemini-2.5-flash-image
deleted existing furniture when editing a customer's room photo, and customer
photos raise a privacy obligation. Revisit after the security review.

OPTIMIZATION
├── Phase 9A Arabic / English Normalization
├── Phase 9B Personalization                  IMPLEMENTED LOCALLY 2026-09-20
├── Phase 9C Seller Fallback                  IMPLEMENTED LOCALLY 2026-09-20
└── Phase 9D Ranking Optimization

INTAKE (new 2026-09-20)
├── Service triage      POST /v1/intake/service     IMPLEMENTED LOCALLY
├── Furnishing brief    POST /v1/intake/furnishing  IMPLEMENTED LOCALLY
└── Inferred tags       product_search_tag          APPLIED LIVE 2026-09-20 (277 tags)

PRODUCTION
├── Phase 10A Observability                   PARTIAL (request id + log line)
├── Phase 10B Performance
├── Phase 10C Cost Control                    PARTIAL (per-user limits + cache)
├── Phase 10D Evaluation Monitoring
└── Phase 10E Scale
```

## 14. Immediate Next Step

```text
Human security review of the 3.2C package (on main, NOT applied)
       ↓
approved?
  ├── no → correct + retest
  └── yes
       ↓
controlled preflight → migration → verification → live acceptance → evidence
       ↓
the same review/apply cycle for 3.2D
       ↓
remove the fake seed from the live project
       ↓
real customers
```

The user changed priorities on 2026-09-17 and authorized the AI work ahead of
the security review, for a demo on 2026-09-19, and on 2026-09-18 asked for
everything to be on `main` with no other branches. All code is merged; none of
the security SQL has been executed. The security review is still the blocker
for real customers, and it has not moved.

Handing features to Flutter: docs/flutter-integration.md is the entry point
(what goes to Supabase directly and what to this API, startup via
GET /v1/meta, conversation history, and what 3.2C changed for direct Supabase
calls). docs/openapi.json is generated by scripts/export_openapi.py and a test
fails if it drifts from the code. docs/flutter-search-contract.md holds search,
rooms, compare and similar products, with request and response shapes, error
codes (including 429 and X-Request-ID), and a working Dart client. Deployment:
Dockerfile, built and started in CI; docs/deploy.md; not deployed. Two
integration rules in it are not optional. Every decimal arrives as a JSON
string, so a direct cast to double throws. And the displayed price must prefer
`discount_price`, because search filters on what the customer pays.

Running the demo: docs/phase-5-demo-runbook.md. Getting started:
docs/getting-started.md.

Engineering candidates after the demo, in the recommended order: apply
`migrations/product-search-tags-2026-09-20.sql` and run
`scripts/derive_search_tags.py`, which is what makes fuzzy search do anything
at all and what finally allows section 11's vector decision to be measured;
measure the four 2026-09-20 features against the live model, none of which has
met it; per-user and AI-latency fields in the request log; a shared store for
limits and cache before a second server.

## 15. Live-System Safety

Default mode: **local/offline**.

Do not perform without explicit authorization:

- execute SQL on Supabase
- apply migrations
- change live policies
- run destructive live utilities
- deploy
- delete live data
- rotate secrets
- commit
- push
- force-push
- merge

## 16. Git Workflow

Before editing:

```bash
git status --short
git log -5 --oneline
git diff --stat
git diff
```

Protect existing user/Codex changes. Do not overwrite unrelated work.

## 17. Testing

Standard local checks:

```bash
uv sync --offline
uv run python -m pytest
uv run ruff check .
uv run ruff format --check .
git diff --check
```

For SQL/security also verify:

- SQL parsing
- security regression tests
- migration/preflight consistency
- verification consistency
- manual diff review

Never report checks that were not actually run.

## 18. Start-of-Task Rule

Before changing anything:

1. read this file
2. inspect Git status
3. inspect task-relevant files
4. identify the current project phase
5. determine whether the task is backend, AI, security, or deployment
6. preserve existing uncommitted work
7. implement the smallest correct change
8. test it
9. inspect final diff
10. report accurately

## 19. Reporting Format

After significant work, report:

```text
What changed
Backend feature affected
AI feature affected, if any
Files changed
Why
Tests/checks
Exact results
Live actions: yes/no
Security impact
Remaining blocker
Next step
```

## 20. Never Falsely Claim

Never claim:

```text
deployed
migration applied
production verified
secure
approved
committed
clean working tree
```

unless direct evidence proves it.

Use precise state language:

```text
implemented locally
verified locally
pending human review
approved for controlled execution
preflight passed
migration applied
verification passed
live acceptance passed
deployed
```

## 21. Core Project Principles

1. Real marketplace data is the source of truth.
2. AI must not invent products.
3. Security boundaries come before AI convenience.
4. User identity comes from authenticated context.
5. RLS remains part of authorization.
6. Stable API models protect Flutter from schema changes.
7. Structured filters handle objective constraints.
8. AI handles language, ambiguity, fuzzy preference, ranking, and explanation.
9. Deterministic code should replace AI where possible.
10. Human review is required before dangerous security deployment.
11. Tests protect behavior.
12. Actual repository state outranks this document.

## 22. Final Instruction to Claude

When working in this repository:

- identify whether the task belongs to backend, security, AI, or deployment
- preserve this architecture
- inspect real code before making assumptions
- do not bypass RLS for convenience
- do not invent marketplace data
- keep AI output grounded in real catalogue data
- build AI incrementally on top of reliable backend services
- do not execute live security changes without explicit authorization
- update this file when the project materially advances

This file is the master reference for both the **backend plan** and the **AI feature plan**.
