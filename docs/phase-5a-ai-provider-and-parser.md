# Phase 5A — AI provider boundary and natural-language parser

Status: **Implemented locally and verified against the live Gemini API on
2026-09-17.** No HTTP route yet, so nothing is exposed to Flutter.

Phase 5A adds the first AI code in the repository: a narrow provider boundary,
a Gemini transport behind it, and a parser that turns one natural-language
sentence into the Phase 4C `SearchSpecification` that Phase 4D already knows
how to execute.

## The one guarantee

The model never contributes a marketplace fact. It contributes language
understanding only, and everything it says passes through deterministic code
before it can influence a query.

Two mechanisms enforce that, and they are independent:

1. **The draft schema has no marketplace fields.** A requirement draft can
   carry a category surface form, colour and material words, numeric bounds,
   style words, and a room type. It has no product id, no seller, no stock
   count, no image, no title, no publication state. There is no field in which
   an invented product could travel, so no prompt wording and no model failure
   can introduce one.
2. **Every word the model emits is resolved by the vocabulary, not accepted.**
   Category, colour, and material surfaces go through the Phase 4B
   vocabularies. A surface that does not resolve becomes an `UnresolvedTerm`
   and is reported, never guessed into a nearby slug. Numbers are re-validated
   against the same bounds that guard a hand-built specification.

The parser's output is a `SearchSpecification`, the same type a deterministic
caller builds. Retrieval cannot tell whether a specification came from a model
or from a form, and it does not need to.

## Layering

```text
natural language
      │
      ▼
app/ai/service.py          input validation, prompt assembly, orchestration
      │
      ▼
app/ai/provider.py         AIProvider protocol  ── vendor-neutral
      │
      ▼
app/ai/providers/gemini.py Gemini REST over httpx  ── the only vendor code
      │
      ▼
   raw JSON  (untrusted)
      │
      ▼
app/ai/models.py           RequirementDraft, tolerant parse of foreign JSON
      │
      ▼
app/ai/guardrails.py       bounds, caps, unit sanity
      │
      ▼
app/search/models.py       build_specification  ── vocabulary resolution
      │
      ▼
   SearchSpecification + unresolved terms
```

### Why the provider interface is `generate_json`, not `parse_requirements`

The master plan sketches an `AIProvider` with `parse_requirements`,
`rank_candidates`, and the rest. Those names describe capabilities the backend
offers, not work a vendor does. Putting them on the provider would push the
prompt, the draft schema, and the guardrails behind the vendor boundary, and
each new provider would have to reimplement them identically.

So the protocol is one vendor-neutral method that takes an instruction, a
prompt, and a JSON schema, and returns parsed JSON. The named capability still
exists: `parse_requirements` is the public function in `app/ai/service.py`.
Swapping Gemini for another provider replaces one file and no guardrail.

## Gemini transport

`GeminiProvider` follows the same shape as `SupabaseAuthGateway`: an injected
`httpx.AsyncClient`, an explicit timeout, no client construction of its own.

- Endpoint `POST {base}/v1beta/models/{model}:generateContent`.
- The key travels in the `x-goog-api-key` header, never in the query string,
  so it cannot leak through a proxy log or an error URL.
- `generationConfig` sets `responseMimeType: application/json` with an explicit
  `responseSchema`, `temperature: 0`, and a token cap. Structured output plus
  zero temperature makes the same sentence parse the same way.
- `finishReason` other than `STOP` is an error, not a partial result. A
  `MAX_TOKENS` finish yields truncated JSON, and accepting it would silently
  drop constraints.
- A blocked prompt, a malformed body, and a missing candidate are all reported
  as an invalid response rather than an empty specification.

No new dependency. Gemini's REST API over the `httpx` client the app already
uses keeps `uv sync --offline` working.

### Errors

`AIProviderUnavailableError` for timeouts, transport failures, 429, and 5xx,
which a caller may retry. `AIResponseInvalidError` for a 4xx, a body that is
not the expected shape, or output that is not valid JSON. Neither carries the
response body or the prompt, because both can contain the user's text and
neither belongs in a log line.

## Configuration

AI settings live in their own `AISettings` class, loaded separately from
`Settings`. The Supabase settings stay required; the AI settings are optional
as a group. An instance with no Gemini key configured still starts, still
serves catalogue and auth, and refuses only the AI path. Adding a required
variable would have turned a missing AI key into a total outage.

```text
GEMINI_API_KEY            secret, required to enable the AI path
GEMINI_MODEL              default gemini-3.6-flash
GEMINI_TIMEOUT_SECONDS    default 20, bounded 0 < t <= 60
GEMINI_BASE_URL           default https://generativelanguage.googleapis.com,
                          HTTPS enforced
GEMINI_THINKING_BUDGET    default 0, bounded 0..24576
```

`GEMINI_MODEL` is a setting rather than a constant because the right model for
requirement extraction is a cost decision, not an architectural one. A small
fast model is the default; a stronger one is one environment variable away.

`GEMINI_THINKING_BUDGET` defaults to zero because requirement extraction is
short and mechanical. Reasoning tokens are charged against the same output cap
as the answer, and the live run below measured exactly that: with the field
absent the identical request spent 1908 reasoning tokens, overran the cap, and
came back truncated, while a zero budget spent none and answered correctly.
Not every model accepts the field, and some reject the whole request with
`INVALID_ARGUMENT`, so changing the model can mean removing it rather than
tuning it. The request sizes its token cap as the answer allowance plus the
budget, so raising the budget cannot starve the answer.

Two of these values are validated more narrowly than they look. The model name
is interpolated into the request path and the key into a request header, so the
model must be a single path segment and the key must contain no byte that could
start a second header line.

The default base URL is Google AI Studio. Vertex AI uses a different host,
path, and credential type, so it is not reachable by changing this value
alone; it would be a second provider class behind the same protocol.

## What the model is asked to do

One system instruction, in `app/ai/prompts/requirements.py`, built at import
time from the live vocabularies so the prompt can never drift from the code
that validates its output. The instruction states the rules that matter:

- Return only what the sentence says. Omit anything not stated.
- A stated limit is a hard constraint. A stated liking is a soft preference.
- All lengths in centimetres.
- Never invent a product, a seller, a price, or stock.
- Ask for clarification only when the sentence is too vague to search at all.

The user's sentence is the only user-controlled content, and it travels as
`contents`, never concatenated into the instruction.

## Prompt injection

The sentence is attacker-controlled in the sense that any user can type
anything. The design assumes the instruction can be overridden and does not
rely on the model obeying it. If a sentence talks the model into emitting
`category: "free sofas"`, the vocabulary does not resolve it and the term is
reported unresolved. If it talks the model into a negative price, the bound
check rejects it. The blast radius of a fully compromised model response is a
specification whose every field was independently validated, which is the same
blast radius as a malicious client posting a specification directly.

## Testing

Every test is offline. A `StubProvider` returns canned JSON, so the suite never
opens a socket and never needs a key.

- Draft parsing: tolerant of extra keys, strict about types and bounds.
- Guardrails: negative price, inverted range, absurd dimension, over-long
  lists, and non-finite numbers each rejected.
- Vocabulary resolution: Arabic, English, and mixed sentences reaching the same
  slugs, and an unknown word reported rather than guessed.
- Transport: `finishReason` handling, blocked prompt, malformed body, timeout,
  429, and 5xx mapped to the right error, driven through a mock transport.
- End to end offline: a parsed specification running through Phase 4D search
  over the Phase 5 seed catalogue and returning sensible products.

A live smoke script sends exactly one request and prints the resulting
specification. It is not run by tooling, and it refuses to do anything without
an explicit flag, because the call costs money and leaves the sentence in a
provider's logs.

```bash
uv run python -m scripts.live_gemini_smoke --i-have-authorization "<sentence>"
```

The key comes from `GEMINI_API_KEY` or from an unechoed prompt, and is never
printed. A provider failure is reported by class name only, since the errors
are built to carry neither the prompt nor the response body.

## Failure behaviour

| Situation | Result |
|---|---|
| Empty or over-long sentence | Refused before a call is spent |
| Timeout, transport error, 429, 5xx | `AIProviderUnavailableError`, retryable |
| 4xx, blocked prompt, truncated or malformed answer | `AIResponseInvalidError` |
| Impossible hard constraint in the draft | Rejected, because silently widening a stated limit shows products the customer ruled out |
| Impossible soft preference in the draft | Dropped, because it only orders results that are already correct |
| `NaN` or `Infinity` in any number | Rejected at the draft boundary, before the hard-versus-soft rule applies. `json.loads` accepts all three literals, so they are a real thing a provider can return |
| Word outside the vocabularies | Reported as unresolved, never mapped to a near neighbour |

## Live verification, 2026-09-17

Run against Google AI Studio with a real key. Three sentences, one call each,
per model.

The default model changed as a direct result. `gemini-2.5-flash` appears in the
model listing but returns 404 on `generateContent` for a key created after its
retirement, with Google's own error naming `gemini-3.6-flash` as the
replacement. `gemini-3.5-flash-lite` rejected the request body with
`INVALID_ARGUMENT` and was dropped from consideration.

| Sentence | Result on gemini-3.6-flash |
|---|---|
| "I need a modern beige sofa around 220 cm for a small living room under 30,000 EGP" | category `sofas`, max price 30000, soft colour `beige`, style `modern`, room `living room`, preferred width 220 |
| "عايز كنبة مودرن بيج أقل من ٣٠ ألف" | category `sofas`, max price 30000, soft colour `beige`, style `modern`. The Arabic numerals and the word for thousand were read correctly |
| "I need furniture" | no constraints, and a clarification question asking which piece and which room |

Latency sat near two seconds per call, against roughly eleven seconds for
`gemini-3.8-flash` on the same work, which is why the faster model is the
default.

One behaviour worth recording: asked for "either the English or the Arabic
form", the model sometimes returns both, as `Sofas / كنب`. The vocabulary's
bilingual label splitting resolves that to the right slug already, since real
catalogue labels have the same shape, and a test now pins it.

## Out of scope

No HTTP route. Exposing the parser to Flutter belongs with Phase 5C retrieval,
when there is a ranked result to return rather than a specification object. No
clarification dialogue, which is Phase 7A; the parser reports that a question
is needed and what the model would ask, and stops there. No ranking or
explanation calls, which are Phase 6. No caching and no rate limiting; both
belong with the route that will carry real traffic.
