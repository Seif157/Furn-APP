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
Phase 3.2B   Initial Security Hardening            COMPLETE PACKAGE
Phase 3.2C   Correction + Reconciliation           COMMITTED, PENDING HUMAN REVIEW
Phase 3.2D   Deferred-Finding Remediation          COMMITTED, PENDING HUMAN REVIEW
```

Branches (both pushed to origin, neither merged):

```text
main                              b7931a0
phase-3.2c-security-hardening     fb3e0ca  (PR target: main)
phase-3.2d-security-hardening     78ae8c3  (stacked on 3.2C; PR target: the 3.2C branch)
```

Phase 3.2D resolves the 56 items 3.2C deferred plus two observed state-write
findings. Its three SQL files are generated from `docs/evidence/phase-3.2d/`
by `tests/phase_3_2d_package.py`; edit the generator and rerun it, never the
SQL. Decisions are recorded in `docs/phase-3.2d-decisions.md`; design in
`docs/phase-3.2d-security-hardening.md`. The live acceptance utility is
`scripts/live_phase_3_2d_acceptance.py` (GET and no-op PATCH only; never run
it without explicit authorization).

Latest verification (2026-09-15, on the 3.2D branch):

```text
pytest:                  280 passed
ruff:                    passed
format:                  passed
git diff --check:        clean
SQL parsing:             15/15
3.2C FOR ALL reconciliation:  19/19
3.2C finding reconciliation:  122/122
3.2D deferred reconciliation: 56/56 (20 remediated, 31 accepted, 7 false positive)
generator == SQL on disk:     yes
```

Current status:

```text
Phase 3.2C migration:    NOT EXECUTED
Phase 3.2D migration:    NOT EXECUTED (requires 3.2C applied first)
Live acceptance:         NOT EXECUTED
Approval:                HUMAN SECURITY REVIEW REQUIRED (both packages)
```

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

Status: **Planned**

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

Status: **Planned**

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

Status: **Planned — Phase 5**

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

Status: **Planned**

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

Status: **Planned / Partial**

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

Status: **Parser implemented locally (Phase 5A, app/ai/) and verified against
the live Gemini API on 2026-09-17. No HTTP route yet, so nothing is exposed to
Flutter.**

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

Status: **Planned**

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

Status: **Planned**

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

Status: **Planned**

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

Status: **Planned**

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
├── Phase 5B SearchSpecification
├── Phase 5C Hybrid Retrieval
└── Phase 5D Search Evaluation

AI RECOMMENDATION
├── Phase 6A Ranking / Scoring
├── Phase 6B Compatibility
├── Phase 6C Explanation
└── Phase 6D Comparison

AI ASSISTANT
├── Phase 7A Clarification
├── Phase 7B Conversational Search Refinement
└── Phase 7C Assistant State

VISION
├── Phase 8A Room Image Analysis
├── Phase 8B Image + Text Requirements
└── Phase 8C Image-to-Catalogue Recommendation

OPTIMIZATION
├── Phase 9A Arabic / English Normalization
├── Phase 9B Personalization
├── Phase 9C Seller Fallback
└── Phase 9D Ranking Optimization

PRODUCTION
├── Phase 10A Observability
├── Phase 10B Performance
├── Phase 10C Cost Control
├── Phase 10D Evaluation Monitoring
└── Phase 10E Scale
```

## 14. Immediate Next Step

```text
Phase 3.2C PR (branch → main)
       ↓
Human security review
       ↓
approved?
  ├── no → correct + retest
  └── yes
       ↓
controlled preflight → migration → verification → live acceptance → evidence
       ↓
merge 3.2C; retarget the 3.2D PR to main
       ↓
Phase 3.2D: write live acceptance utility, then the same review/apply cycle
       ↓
Phase 4 AI foundation
```

Do not jump directly into live AI work unless the user explicitly changes priorities.

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
