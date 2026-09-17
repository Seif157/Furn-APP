"""Gemini transport for the AI provider boundary.

The only vendor-specific module in the backend. It speaks Gemini's REST API
over the shared ``httpx`` client, in the same shape as ``SupabaseAuthGateway``:
an injected client, an explicit timeout, no client lifecycle of its own.

Structured output is requested rather than hoped for. ``responseMimeType`` and
an explicit ``responseSchema`` make the answer machine-readable, and a zero
temperature makes the same sentence parse the same way on every call.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import httpx

from app.ai.provider import AIProviderUnavailableError, AIResponseInvalidError
from app.config import AISettings

ANSWER_TOKEN_ALLOWANCE = 2048
API_VERSION = "v1beta"


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
        self._api_key = api_key
        self._timeout_seconds = settings.gemini_timeout_seconds
        self._thinking_budget = settings.gemini_thinking_budget

    async def generate_json(
        self,
        *,
        instruction: str,
        prompt: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Send one request and return its parsed JSON answer."""

        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": instruction}]},
            # User text stays in `contents`. Splicing it into the instruction
            # would erase the only structural distinction the API offers
            # between backend rules and whatever the user typed.
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
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

        try:
            response = await self._client.post(
                self._endpoint,
                # Header, not query string: a key in a URL survives in proxy
                # logs, error messages, and redirects.
                headers={
                    "x-goog-api-key": self._api_key,
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=self._timeout_seconds,
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

        return self._parse_generated_json(response)

    @staticmethod
    def _parse_generated_json(response: httpx.Response) -> Mapping[str, Any]:
        """Extract the candidate's JSON, refusing anything partial.

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

        # A MAX_TOKENS or SAFETY finish still carries text, and that text is
        # truncated or filtered JSON. Parsing it would silently drop whichever
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

        texts = [
            part["text"]
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("text"), str)
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
