"""The reference-photo fetcher and the provider's image method. All mocked.

The fetcher reads seller-controlled URLs server-side, so most of these tests
are about what it must refuse to fetch.
"""

import base64
import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import ValidationError

from app.ai.provider import (
    AIProviderUnavailableError,
    AIResponseInvalidError,
    ImageBytes,
)
from app.ai.providers.gemini import GeminiProvider
from app.config import AISettings
from app.rooms.images import MAX_REFERENCE_BYTES, ReferenceImageFetcher

ALLOWED = frozenset({"images.unsplash.com", "project.supabase.co"})
JPEG = b"\xff\xd8\xff" + b"x" * 100


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def fetcher_with(handler: Callable[[httpx.Request], httpx.Response]):
    seen: list[str] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return handler(request)

    fetcher = ReferenceImageFetcher(
        client=httpx.AsyncClient(transport=httpx.MockTransport(recording)),
        allowed_hosts=ALLOWED,
    )
    return fetcher, seen


def jpeg(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})


@pytest.mark.anyio
async def test_an_allowed_https_photo_is_fetched() -> None:
    fetcher, _ = fetcher_with(jpeg)

    image = await fetcher.fetch("https://images.unsplash.com/photo-1?w=800")

    assert image == ImageBytes(mime_type="image/jpeg", data=JPEG)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "url",
    [
        "http://images.unsplash.com/photo-1",
        "https://evil.example.com/photo.jpg",
        "https://169.254.169.254/latest/meta-data/",
        "https://127.0.0.1/admin",
        "https://images.unsplash.com:8443/photo-1",
        "https://user:pass@images.unsplash.com/photo-1",
        "https://images.unsplash.com.evil.example.com/photo-1",
        "file:///etc/passwd",
        "not a url",
    ],
)
async def test_anything_outside_the_allowlist_is_never_requested(url: str) -> None:
    fetcher, seen = fetcher_with(jpeg)

    assert await fetcher.fetch(url) is None
    # Refused before a request is made, not after.
    assert seen == []


@pytest.mark.anyio
async def test_a_redirect_to_a_disallowed_host_is_not_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "images.unsplash.com":
            return httpx.Response(302, headers={"location": "http://10.0.0.1/secret"})
        return jpeg(request)

    fetcher, seen = fetcher_with(handler)

    assert await fetcher.fetch("https://images.unsplash.com/photo-1") is None
    assert all("10.0.0.1" not in url for url in seen)


@pytest.mark.anyio
async def test_a_redirect_between_allowed_hosts_is_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "images.unsplash.com":
            return httpx.Response(
                301, headers={"location": "https://project.supabase.co/storage/p.jpg"}
            )
        return jpeg(request)

    fetcher, _ = fetcher_with(handler)

    assert await fetcher.fetch("https://images.unsplash.com/photo-1") is not None


@pytest.mark.anyio
async def test_a_redirect_loop_gives_up() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": str(request.url)})

    fetcher, seen = fetcher_with(handler)

    assert await fetcher.fetch("https://images.unsplash.com/photo-1") is None
    assert len(seen) <= 4


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"}),
        httpx.Response(200, content=b"x", headers={"content-type": "image/svg+xml"}),
        httpx.Response(200, content=b"", headers={"content-type": "image/jpeg"}),
        httpx.Response(404, content=JPEG, headers={"content-type": "image/jpeg"}),
    ],
)
async def test_anything_that_is_not_a_plain_photo_is_skipped(
    response: httpx.Response,
) -> None:
    fetcher, _ = fetcher_with(lambda request: response)

    assert await fetcher.fetch("https://images.unsplash.com/photo-1") is None


@pytest.mark.anyio
async def test_an_oversized_photo_is_abandoned() -> None:
    fetcher, _ = fetcher_with(
        lambda request: httpx.Response(
            200,
            content=b"x" * (MAX_REFERENCE_BYTES + 1),
            headers={"content-type": "image/jpeg"},
        )
    )

    assert await fetcher.fetch("https://images.unsplash.com/photo-1") is None


@pytest.mark.anyio
async def test_a_network_failure_is_a_skipped_photo_not_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    fetcher, _ = fetcher_with(handler)

    assert await fetcher.fetch("https://images.unsplash.com/photo-1") is None


# --- the provider's image method ------------------------------------------------


def image_settings(**overrides: object) -> AISettings:
    values: dict[str, object] = {"GEMINI_API_KEY": "test-gemini-key"} | overrides
    return AISettings(_env_file=None, **values)


def provider_with(handler: Callable[[httpx.Request], httpx.Response]) -> GeminiProvider:
    return GeminiProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        settings=image_settings(),
        api_key="test-gemini-key",
    )


def image_answer(data: bytes, *, finish: str = "STOP") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "finishReason": finish,
                    "content": {
                        "parts": [
                            {"text": "Here is the room."},
                            {
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": base64.b64encode(data).decode(),
                                }
                            },
                        ]
                    },
                }
            ]
        },
    )


@pytest.mark.anyio
async def test_the_image_request_sends_references_first_and_the_prompt_last() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return image_answer(b"PNGDATA")

    image = await provider_with(handler).generate_image(
        prompt="a room",
        references=[
            ImageBytes("image/jpeg", b"ref-1"),
            ImageBytes("image/png", b"ref-2"),
        ],
    )

    assert image == ImageBytes("image/png", b"PNGDATA")
    assert "models/gemini-2.5-flash-image:generateContent" in str(seen["url"])
    body = seen["body"]
    assert isinstance(body, dict)
    parts = body["contents"][0]["parts"]
    assert parts[0]["inlineData"] == {
        "mimeType": "image/jpeg",
        "data": base64.b64encode(b"ref-1").decode(),
    }
    assert parts[1]["inlineData"]["mimeType"] == "image/png"
    assert parts[2] == {"text": "a room"}
    assert body["generationConfig"]["responseModalities"] == ["TEXT", "IMAGE"]


@pytest.mark.anyio
async def test_a_text_only_answer_is_not_an_image() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": "I cannot draw that."}]},
                    }
                ]
            },
        )

    with pytest.raises(AIResponseInvalidError):
        await provider_with(handler).generate_image(prompt="p", references=[])


@pytest.mark.anyio
@pytest.mark.parametrize("finish", ["SAFETY", "IMAGE_SAFETY", "PROHIBITED_CONTENT"])
async def test_a_filtered_image_is_refused(finish: str) -> None:
    provider = provider_with(lambda request: image_answer(b"PNG", finish=finish))

    with pytest.raises(AIResponseInvalidError):
        await provider.generate_image(prompt="p", references=[])


@pytest.mark.anyio
async def test_image_rate_limiting_is_retryable() -> None:
    provider = provider_with(lambda request: httpx.Response(429, json={}))

    with pytest.raises(AIProviderUnavailableError):
        await provider.generate_image(prompt="p", references=[])


# --- configuration ------------------------------------------------------------


def test_the_image_model_must_be_one_path_segment() -> None:
    with pytest.raises(ValidationError):
        image_settings(GEMINI_IMAGE_MODEL="../other/model")


@pytest.mark.parametrize("hosts", ["evil.com/path", "http://x.com", "a b.com"])
def test_reference_hosts_must_be_plain_hostnames(hosts: str) -> None:
    with pytest.raises(ValidationError):
        image_settings(IMAGE_REFERENCE_HOSTS=hosts)


def test_reference_hosts_are_parsed_and_lowercased() -> None:
    settings = image_settings(
        IMAGE_REFERENCE_HOSTS="Images.Unsplash.com, cdn.example.com"
    )

    assert settings.reference_hosts == frozenset(
        {"images.unsplash.com", "cdn.example.com"}
    )
