"""Conversational refinement: a follow-up refines the earlier search."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from app.ai.prompts.requirements import REQUIREMENT_INSTRUCTION
from app.ai.service import (
    MAX_HISTORY,
    REFINEMENT_NOTE,
    InvalidQueryError,
    conversation,
)
from app.rooms.prompts import ROOM_INSTRUCTION
from app.search.models import MAX_TEXT_LENGTH
from tests import test_rooms_endpoint as rooms
from tests import test_search_endpoint as search


class RecordingProvider:
    def __init__(self, answer: Mapping[str, Any]) -> None:
        self.answer = answer
        self.calls: list[dict[str, str]] = []

    async def generate_json(self, *, instruction, prompt, schema):
        self.calls.append({"instruction": instruction, "prompt": prompt})
        return self.answer

    async def generate_image(self, *, prompt, references):  # pragma: no cover
        raise AssertionError("not used")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# --- the turn shape -------------------------------------------------------------


def test_without_history_the_model_gets_exactly_what_it_always_did() -> None:
    turn = conversation(REQUIREMENT_INSTRUCTION, "  a modern sofa  ")

    assert turn.instruction == REQUIREMENT_INSTRUCTION
    assert turn.prompt == "a modern sofa"
    assert turn.query == "a modern sofa"


def test_history_goes_in_the_prompt_and_only_fixed_text_in_the_instruction() -> None:
    turn = conversation(
        REQUIREMENT_INSTRUCTION, "in grey instead", ["a modern sofa", "under 30000"]
    )

    assert turn.instruction == REQUIREMENT_INSTRUCTION + REFINEMENT_NOTE
    assert "modern sofa" not in turn.instruction
    assert turn.prompt == "a modern sofa ... under 30000 ... in grey instead"
    # Ranking still scores words said earlier.
    assert turn.query == "a modern sofa under 30000 in grey instead"


def test_messages_are_collapsed_to_one_line_in_order() -> None:
    turn = conversation(REQUIREMENT_INSTRUCTION, "a  sofa", ["a bed\n\nin oak"])

    assert "\n" not in turn.prompt
    assert turn.prompt == "a bed in oak ... a sofa"


def test_the_ranking_text_keeps_the_newest_messages_within_the_limit() -> None:
    old = "x" * 400
    newer = "y" * 150  # 400 + 150 + "grey" is past the 500-character limit
    turn = conversation(REQUIREMENT_INSTRUCTION, "grey", [old, newer])

    assert turn.query == f"{newer} grey"
    assert len(turn.query) <= MAX_TEXT_LENGTH
    # The model still sees every message.
    assert old in turn.prompt


@pytest.mark.parametrize(
    "history", [["a sofa"] * (MAX_HISTORY + 1), ["   "], ["x" * (MAX_TEXT_LENGTH + 1)]]
)
def test_unusable_history_is_refused_before_any_call(history: list[str]) -> None:
    with pytest.raises(InvalidQueryError):
        conversation(REQUIREMENT_INSTRUCTION, "grey", history)


def test_rooms_use_the_same_note() -> None:
    turn = conversation(ROOM_INSTRUCTION, "make the sofa grey", ["a living room"])

    assert turn.instruction == ROOM_INSTRUCTION + REFINEMENT_NOTE


# --- the endpoints --------------------------------------------------------------


@pytest.mark.anyio
async def test_search_refines_the_earlier_messages() -> None:
    provider = RecordingProvider(search.SOFA_DRAFT)

    async with search.search_client(search.seed_response, provider) as client:
        response = await search.post_search(
            client,
            {"query": "خليها رمادي", "history": ["عايز كنبة مودرن أقل من ٣٠ ألف"]},
        )

    assert response.status_code == 200
    assert response.json()["language"] == "ar"
    (call,) = provider.calls
    assert call["prompt"] == "عايز كنبة مودرن أقل من ٣٠ ألف ... خليها رمادي"
    assert call["instruction"].endswith(REFINEMENT_NOTE)


@pytest.mark.anyio
async def test_search_without_history_is_unchanged() -> None:
    provider = RecordingProvider(search.SOFA_DRAFT)

    async with search.search_client(search.seed_response, provider) as client:
        response = await search.post_search(client, {"query": "a modern sofa"})

    assert response.status_code == 200
    assert provider.calls == [
        {"instruction": REQUIREMENT_INSTRUCTION, "prompt": "a modern sofa"}
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "history", [["a sofa"] * (MAX_HISTORY + 1), [""], "a sofa", [42]]
)
async def test_bad_history_is_422_and_never_reaches_the_model(history) -> None:
    provider = RecordingProvider(search.SOFA_DRAFT)

    async with search.search_client(search.unexpected_catalogue_call, provider) as c:
        response = await search.post_search(c, {"query": "grey", "history": history})

    assert response.status_code == 422
    assert provider.calls == []


@pytest.mark.anyio
async def test_a_refinement_is_cached_separately_from_the_same_last_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.cache import AICaches
    from app.main import app

    monkeypatch.setattr(
        app.state, "ai_caches", AICaches(ttl_seconds=600), raising=False
    )
    provider = RecordingProvider(search.SOFA_DRAFT)

    async with search.search_client(search.seed_response, provider) as client:
        await search.post_search(client, {"query": "in grey"})
        await search.post_search(client, {"query": "in grey", "history": ["a sofa"]})
        await search.post_search(client, {"query": "in grey", "history": ["a sofa"]})

    assert len(provider.calls) == 2


@pytest.mark.anyio
async def test_room_plans_refine_too() -> None:
    provider = rooms.StubProvider()

    async with rooms.room_client(rooms.seed_catalogue, provider) as client:
        response = await client.post(
            "/v1/rooms/plan",
            json={"query": "خلي الميزانية 50 ألف", "history": [rooms.ARABIC_ROOM]},
            headers=rooms.auth_headers(),
        )

    assert response.status_code == 200
    (prompt,) = provider.json_calls
    assert prompt == f"{rooms.ARABIC_ROOM} ... خلي الميزانية 50 ألف"
