# Furn-APP backend — Flutter handoff

The API behind the Furn-APP furniture marketplace: Arabic and English search,
room planning, comparison, similar products, public reviews, the cart, and
request intake. FastAPI over Supabase, with Google Gemini for the language
parts.

**Start with [FLUTTER.md](FLUTTER.md).** It covers what to put in `.env`, how
to run the server so a phone can reach it, which calls go here and which go to
Supabase directly, and the rules that will otherwise cost you an afternoon.

```bash
uv sync
uv run python -m scripts.serve --host 0.0.0.0
```

Then open <http://127.0.0.1:8000/docs> and try an endpoint by hand.

## What is in here

```text
app/      the API
scripts/  serve.py, the one way to start it locally
docs/     flutter-integration.md   what goes to Supabase, what comes here
          flutter-search-contract.md  every request and response, with Dart
          openapi.json             generated from the running code
```

This branch is a handoff snapshot with no shared history with `main`: it
carries only what is needed to run and integrate with the API. Database
migrations, the security packages, the seed data, the evaluation harness and
the test suite live on `main` and are deliberately absent here. Do not merge
this branch back.
