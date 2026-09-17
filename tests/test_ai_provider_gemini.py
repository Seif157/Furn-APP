"""Tests for the Gemini transport. Every request is served by a mock."""

import json
from collections.abc import Callable

import httpx
import pytest

from app.ai.provider import AIProviderUnavailableError, AIResponseInvalidError
from app.ai.providers.gemini import (
    ANSWER_TOKEN_ALLOWANCE,
    GeminiProvider,
    build_gemini_provider,
)
from app.config import AISettings

TEST_API_KEY = "test-gemini-key-must-not-leak"
SCHEMA = {"type": "OBJECT", "properties": {"category": {"type": "STRING"}}}

MockHandler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def build_ai_settings(**overrides: object) -> AISettings:
    configuration: dict[str, object] = {
        "GEMINI_API_KEY": TEST_API_KEY,
        "GEMINI_MODEL": "gemini-3.6-flash",
        "GEMINI_TIMEOUT_SECONDS": 20.0,
        "GEMINI_BASE_URL": "https://generativelanguage.googleapis.com",
        "GEMINI_THINKING_BUDGET": 0,
    }
    return AISettings(_env_file=None, **(configuration | overrides))


def provider_with(handler: MockHandler, **overrides: object) -> GeminiProvider:
    return GeminiProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        settings=build_ai_settings(**overrides),
        api_key=TEST_API_KEY,
    )


def candidate_response(text: str, *, finish_reason: str = "STOP") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {"parts": [{"text": text}], "role": "model"},
                    "finishReason": finish_reason,
                }
            ]
        },
    )


@pytest.mark.anyio
async def test_request_shape_carries_key_in_header_and_user_text_in_contents() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return candidate_response('{"category": "sofas"}')

    provider = provider_with(handler)
    result = await provider.generate_json(
        instruction="backend rules", prompt="I need a sofa", schema=SCHEMA
    )

    assert result == {"category": "sofas"}
    url = str(seen["url"])
    assert url == (
        "https://generativelanguage.googleapis.com"
        "/v1beta/models/gemini-3.6-flash:generateContent"
    )
    # The key must never ride in the URL, where proxies and error pages keep it.
    assert TEST_API_KEY not in url
    headers = seen["headers"]
    assert isinstance(headers, dict)
    assert headers["x-goog-api-key"] == TEST_API_KEY

    body = seen["body"]
    assert isinstance(body, dict)
    assert body["systemInstruction"] == {"parts": [{"text": "backend rules"}]}
    # User text stays in `contents`, never concatenated into the instruction.
    assert body["contents"] == [{"role": "user", "parts": [{"text": "I need a sofa"}]}]
    assert "I need a sofa" not in json.dumps(body["systemInstruction"])
    generation = body["generationConfig"]
    assert generation["responseMimeType"] == "application/json"
    assert generation["responseSchema"] == SCHEMA
    assert generation["temperature"] == 0
    assert generation["candidateCount"] == 1
    assert generation["thinkingConfig"] == {"thinkingBudget": 0}


@pytest.mark.anyio
async def test_model_and_thinking_budget_come_from_settings() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return candidate_response("{}")

    provider = provider_with(
        handler, GEMINI_MODEL="gemini-2.5-pro", GEMINI_THINKING_BUDGET=512
    )
    await provider.generate_json(instruction="i", prompt="p", schema=SCHEMA)

    assert "models/gemini-2.5-pro:generateContent" in str(seen["url"])
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 512}
    # Reasoning tokens are charged against the same cap as the answer, so the
    # budget is added to it. A live run with the cap sized for the answer alone
    # spent 1908 reasoning tokens and came back truncated.
    assert body["generationConfig"]["maxOutputTokens"] == ANSWER_TOKEN_ALLOWANCE + 512


@pytest.mark.anyio
async def test_multipart_answers_are_joined_before_parsing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": '{"category":'},
                                {"text": ' "beds"}'},
                            ]
                        },
                        "finishReason": "STOP",
                    }
                ]
            },
        )

    result = await provider_with(handler).generate_json(
        instruction="i", prompt="p", schema=SCHEMA
    )

    assert result == {"category": "beds"}


@pytest.mark.anyio
@pytest.mark.parametrize("status", [429, 500, 502, 503])
async def test_transient_upstream_failures_are_unavailable(status: int) -> None:
    provider = provider_with(lambda request: httpx.Response(status, json={}))

    with pytest.raises(AIProviderUnavailableError):
        await provider.generate_json(instruction="i", prompt="p", schema=SCHEMA)


@pytest.mark.anyio
@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_rejected_requests_are_invalid_not_retryable(status: int) -> None:
    provider = provider_with(lambda request: httpx.Response(status, json={}))

    with pytest.raises(AIResponseInvalidError):
        await provider.generate_json(instruction="i", prompt="p", schema=SCHEMA)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError("boom"), httpx.ReadTimeout("slow")],
)
async def test_transport_failures_are_unavailable(error: Exception) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    with pytest.raises(AIProviderUnavailableError):
        await provider_with(handler).generate_json(
            instruction="i", prompt="p", schema=SCHEMA
        )


@pytest.mark.anyio
@pytest.mark.parametrize("finish_reason", ["MAX_TOKENS", "SAFETY", "RECITATION"])
async def test_truncated_or_filtered_answers_are_refused(finish_reason: str) -> None:
    # The text is valid JSON and would parse. Accepting it would silently drop
    # whichever constraints fell off the end of the completion.
    provider = provider_with(
        lambda request: candidate_response(
            '{"category": "sofas"}', finish_reason=finish_reason
        )
    )

    with pytest.raises(AIResponseInvalidError):
        await provider.generate_json(instruction="i", prompt="p", schema=SCHEMA)


@pytest.mark.anyio
async def test_blocked_prompts_are_refused() -> None:
    provider = provider_with(
        lambda request: httpx.Response(
            200, json={"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []}
        )
    )

    with pytest.raises(AIResponseInvalidError):
        await provider.generate_json(instruction="i", prompt="p", schema=SCHEMA)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"candidates": []},
        {"candidates": "nope"},
        {"candidates": [None]},
        {"candidates": [{"content": {}}]},
        {"candidates": [{"content": {"parts": []}}]},
        {"candidates": [{"content": {"parts": [{"inlineData": {}}]}}]},
    ],
)
async def test_unusable_response_bodies_are_refused(payload: object) -> None:
    provider = provider_with(lambda request: httpx.Response(200, json=payload))

    with pytest.raises(AIResponseInvalidError):
        await provider.generate_json(instruction="i", prompt="p", schema=SCHEMA)


@pytest.mark.anyio
@pytest.mark.parametrize("text", ["not json at all", '{"unclosed": ', "[1, 2, 3]"])
async def test_generated_text_that_is_not_a_json_object_is_refused(text: str) -> None:
    provider = provider_with(lambda request: candidate_response(text))

    with pytest.raises(AIResponseInvalidError):
        await provider.generate_json(instruction="i", prompt="p", schema=SCHEMA)


@pytest.mark.anyio
async def test_a_non_json_body_is_refused() -> None:
    provider = provider_with(lambda request: httpx.Response(200, text="<html>"))

    with pytest.raises(AIResponseInvalidError):
        await provider.generate_json(instruction="i", prompt="p", schema=SCHEMA)


@pytest.mark.anyio
async def test_errors_never_carry_the_prompt_or_the_response_body() -> None:
    secret_sentence = "a very private sentence about my bedroom"
    provider = provider_with(
        lambda request: httpx.Response(200, text=f"garbage {secret_sentence}")
    )

    with pytest.raises(AIResponseInvalidError) as raised:
        await provider.generate_json(
            instruction="i", prompt=secret_sentence, schema=SCHEMA
        )

    assert secret_sentence not in str(raised.value)
    assert secret_sentence not in repr(raised.value)


def test_no_key_configured_builds_no_provider() -> None:
    settings = AISettings(_env_file=None)

    assert settings.gemini_enabled is False
    assert build_gemini_provider(client=httpx.AsyncClient(), settings=settings) is None


def test_a_configured_key_builds_a_provider() -> None:
    provider = build_gemini_provider(
        client=httpx.AsyncClient(), settings=build_ai_settings()
    )

    assert isinstance(provider, GeminiProvider)
