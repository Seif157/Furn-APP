"""GET /v1/meta, /v1/search/vocabulary and /v1/search/examples."""

from __future__ import annotations

import httpx
import pytest

from app.catalog.normalization import CATEGORIES
from app.config import AISettings
from app.main import app
from app.routers.meta import EXAMPLES
from app.search.models import MAX_TEXT_LENGTH, detect_language


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def get(path: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.get(path)


@pytest.mark.anyio
async def test_meta_needs_no_sign_in_and_reports_ai_off_without_a_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app.state, "ai_provider", None, raising=False)
    monkeypatch.setattr(
        app.state, "ai_settings", AISettings(_env_file=None), raising=False
    )

    response = await get("/v1/meta")

    assert response.status_code == 200
    payload = response.json()
    assert payload["languages"] == ["ar", "en"]
    assert payload["features"]["search"] is False
    assert payload["features"]["room_preview"] is False
    assert payload["features"]["compare"] is True
    assert payload["limits"]["search_per_minute"] == 20
    assert payload["limits"]["max_history"] == 4


@pytest.mark.anyio
async def test_meta_reports_ai_on_and_configured_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app.state, "ai_provider", object(), raising=False)
    monkeypatch.setattr(
        app.state,
        "ai_settings",
        AISettings(
            _env_file=None,
            GEMINI_API_KEY="test-key-not-real-123",
            RATE_LIMIT_SEARCH_PER_MINUTE=7,
        ),
        raising=False,
    )

    response = await get("/v1/meta")

    payload = response.json()
    assert payload["features"]["search"] is True
    assert payload["limits"]["search_per_minute"] == 7
    # Configuration is described, never disclosed.
    assert "test-key-not-real-123" not in response.text


@pytest.mark.anyio
async def test_the_vocabulary_is_the_one_search_resolves_words_to() -> None:
    response = await get("/v1/search/vocabulary")

    assert response.status_code == 200
    payload = response.json()
    assert [t["slug"] for t in payload["categories"]] == [
        term.slug for term in CATEGORIES.terms
    ]
    for group in ("categories", "colours", "materials"):
        slugs = [t["slug"] for t in payload[group]]
        assert len(slugs) == len(set(slugs))
        assert all(t["en"] and t["ar"] for t in payload[group])


@pytest.mark.anyio
@pytest.mark.parametrize("language", ["ar", "en"])
async def test_examples_are_in_the_requested_language_and_searchable(
    language: str,
) -> None:
    response = await get(f"/v1/search/examples?language={language}")

    assert response.status_code == 200
    payload = response.json()
    sentences = [s for group in payload.values() for s in group]
    assert sentences
    for sentence in sentences:
        assert len(sentence) <= MAX_TEXT_LENGTH
        detected = detect_language(sentence)
        assert (detected in ("ar", "mixed")) == (language == "ar"), sentence


@pytest.mark.anyio
async def test_an_unsupported_example_language_is_422() -> None:
    response = await get("/v1/search/examples?language=fr")

    assert response.status_code == 422


def test_both_languages_offer_every_kind_of_example() -> None:
    for examples in EXAMPLES.values():
        assert examples.search
        assert examples.search_refinements
        assert examples.rooms
        assert examples.room_refinements
