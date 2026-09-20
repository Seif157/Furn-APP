"""Gemini transport for the AI provider boundary.

The only vendor-specific module in the backend. It speaks Gemini's REST API
over the shared ``httpx`` client, in the same shape as ``SupabaseAuthGateway``:
an injected client, an explicit timeout, no client lifecycle of its own.

Structured output is requested rather than hoped for. ``responseMimeType`` and
an explicit ``responseSchema`` make the answer machine-readable, and a zero
temperature makes the same sentence parse the same way on every call.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from app.ai.provider import (
    AIProviderUnavailableError,
    AIResponseInvalidError,
    ImageBytes,
)
from app.config import AISettings

ANSWER_TOKEN_ALLOWANCE = 2048
API_VERSION = "v1beta"
MAX_IMAGE_BYTES = 20 * 1024 * 1024


class GeminiProvider:
    """Generate JSON with Gemini's ``generateContent`` endpoint."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        settings: AISettings,
        api_key: str,
    ) -> None:
        base = str(settings.gemini_base_url).rstrip("/")
        self._client = client
        self._endpoint = (
            f"{base}/{API_VERSION}/models/{settings.gemini_model}:generateContent"
        )
        self._image_endpoint = (
            f"{base}/{API_VERSION}/models/{settings.gemini_image_model}:generateContent"
        )
        self._api_key = api_key
        self._timeout_seconds = settings.gemini_timeout_seconds
        self._image_timeout_seconds = settings.gemini_image_timeout_seconds
        self._thinking_budget = settings.gemini_thinking_budget

    async def generate_json(
        self,
        *,
        instruction: str,
        prompt: str,
        schema: Mapping[str, Any],
        references: Sequence[ImageBytes] = (),
    ) -> Mapping[str, Any]:
        """Send one request and return its parsed JSON answer."""

        parts: list[dict[str, Any]] = [
            {
                "inlineData": {
                    "mimeType": reference.mime_type,
                    "data": base64.b64encode(reference.data).decode("ascii"),
                }
            }
            for reference in references
        ]
        parts.append({"text": prompt})
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": instruction}]},
            # User text stays in `contents`. Splicing it into the instruction
            # would erase the only structural distinction the API offers
            # between backend rules and whatever the user typed.
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": dict(schema),
                "temperature": 0,
                "candidateCount": 1,
                # Reasoning tokens are charged against this same cap, so the
                # answer keeps its full allowance whatever the budget is set
                # to. Sizing the cap for the answer alone is what produced an
                # observed truncated completion.
                "maxOutputTokens": ANSWER_TOKEN_ALLOWANCE + self._thinking_budget,
                "thinkingConfig": {"thinkingBudget": self._thinking_budget},
            },
        }

        response = await self._post(self._endpoint, body, self._timeout_seconds)
        return self._parse_generated_json(response)

    async def generate_image(
        self,
        *,
        prompt: str,
        references: Sequence[ImageBytes],
    ) -> ImageBytes:
        """Render one image, with the real product photos as references."""

        parts: list[dict[str, Any]] = [
            {
                "inlineData": {
                    "mimeType": reference.mime_type,
                    "data": base64.b64encode(reference.data).decode("ascii"),
                }
            }
            for reference in references
        ]
        parts.append({"text": prompt})
        body = {
            "contents": [{"role": "user", "parts": parts}],
            # Image models answer with an image part and often a short text
            # part; asking for both is what the API accepts reliably.
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "candidateCount": 1,
            },
        }
        response = await self._post(
            self._image_endpoint, body, self._image_timeout_seconds
        )
        for part in self._candidate_parts(response):
            inline = part.get("inlineData") or part.get("inline_data")
            if not isinstance(inline, dict):
                continue
            mime_type = inline.get("mimeType") or inline.get("mime_type")
            data = inline.get("data")
            if not isinstance(mime_type, str) or not mime_type.startswith("image/"):
                continue
            if not isinstance(data, str):
                continue
            try:
                decoded = base64.b64decode(data, validate=True)
            except (ValueError, TypeError):
                raise AIResponseInvalidError from None
            if not decoded or len(decoded) > MAX_IMAGE_BYTES:
                raise AIResponseInvalidError
            return ImageBytes(mime_type=mime_type, data=decoded)
        # A text-only answer means the model declined to draw. It is not an
        # image, so it is not returned as one.
        raise AIResponseInvalidError

    async def _post(
        self, endpoint: str, body: dict[str, Any], timeout: float
    ) -> httpx.Response:
        try:
            response = await self._client.post(
                endpoint,
                # Header, not query string: a key in a URL survives in proxy
                # logs, error messages, and redirects.
                headers={
                    "x-goog-api-key": self._api_key,
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=timeout,
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise AIProviderUnavailableError from None

        if response.status_code != httpx.codes.OK:
            # 429 and 5xx are transient. Everything else means this request
            # will keep being rejected, so it is not a retry candidate.
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                raise AIProviderUnavailableError
            if response.status_code >= 500:
                raise AIProviderUnavailableError
            raise AIResponseInvalidError
        return response

    @staticmethod
    def _candidate_parts(response: httpx.Response) -> list[dict[str, Any]]:
        """Return the first candidate's parts, refusing anything partial.

        No branch here includes the response body in an exception. The body
        echoes the user's sentence, and an exception message is the one place
        that text should never end up.
        """

        try:
            payload = response.json()
        except (TypeError, ValueError):
            raise AIResponseInvalidError from None
        if not isinstance(payload, dict):
            raise AIResponseInvalidError

        feedback = payload.get("promptFeedback")
        if isinstance(feedback, dict) and feedback.get("blockReason") is not None:
            raise AIResponseInvalidError

        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise AIResponseInvalidError
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise AIResponseInvalidError

        # A MAX_TOKENS or SAFETY finish still carries content, and that content
        # is truncated or filtered. Using it would silently drop whichever
        # constraints happened to fall off the end.
        finish_reason = candidate.get("finishReason")
        if finish_reason not in (None, "STOP"):
            raise AIResponseInvalidError

        content = candidate.get("content")
        if not isinstance(content, dict):
            raise AIResponseInvalidError
        parts = content.get("parts")
        if not isinstance(parts, list) or not parts:
            raise AIResponseInvalidError
        return [part for part in parts if isinstance(part, dict)]

    @classmethod
    def _parse_generated_json(cls, response: httpx.Response) -> Mapping[str, Any]:
        texts = [
            part["text"]
            for part in cls._candidate_parts(response)
            if isinstance(part.get("text"), str)
        ]
        if not texts:
            raise AIResponseInvalidError

        try:
            generated = json.loads("".join(texts))
        except (TypeError, ValueError):
            raise AIResponseInvalidError from None
        if not isinstance(generated, dict):
            raise AIResponseInvalidError
        return generated


def build_gemini_provider(
    *,
    client: httpx.AsyncClient,
    settings: AISettings,
) -> GeminiProvider | None:
    """Construct a provider, or return ``None`` when no key is configured."""

    if settings.gemini_api_key is None:
        return None
    return GeminiProvider(
        client=client,
        settings=settings,
        api_key=settings.gemini_api_key.get_secret_value(),
    )
