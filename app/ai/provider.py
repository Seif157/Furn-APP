"""The vendor-neutral AI provider boundary.

A provider does one thing: given an instruction, a prompt, and a JSON schema,
return parsed JSON. It owns no prompt, no schema, and no guardrail, so every
provider behaves identically from the caller's side and swapping one out
changes a single module.

The capabilities the master plan names -- parsing requirements, ranking,
explaining -- are backend functions built on top of this boundary, not methods
a vendor implements. Keeping them above the boundary means each new provider
inherits the existing guardrails instead of reimplementing them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


class AIProviderError(Exception):
    """Base class for every failure of the AI boundary."""


class AIProviderNotConfiguredError(AIProviderError):
    """Raised when the AI path is used on an instance with no provider key."""


class AIProviderUnavailableError(AIProviderError):
    """Raised when the provider could not be reached or could not answer.

    Timeouts, transport failures, rate limiting, and server errors. A caller
    may retry these; the request itself was not rejected.
    """


class AIResponseInvalidError(AIProviderError):
    """Raised when the provider answered with something unusable.

    A rejected request, a blocked prompt, a truncated completion, or a body
    that is not the JSON shape that was asked for. Retrying is pointless
    without changing the input.
    """


@dataclass(frozen=True, slots=True)
class ImageBytes:
    """An image in transit: raw bytes and their declared media type."""

    mime_type: str
    data: bytes


class AIProvider(Protocol):
    """The only interface the rest of the backend may depend on."""

    async def generate_image(
        self,
        *,
        prompt: str,
        references: Sequence[ImageBytes],
    ) -> ImageBytes:
        """Render one image from a text prompt and reference photographs.

        ``prompt`` is backend-built text. ``references`` are photographs of
        real catalogue products the image must depict. Implementations raise
        ``AIProviderUnavailableError`` or ``AIResponseInvalidError`` and never
        return a partial or empty image.
        """
        ...

    async def generate_json(
        self,
        *,
        instruction: str,
        prompt: str,
        schema: Mapping[str, Any],
        references: Sequence[ImageBytes] = (),
    ) -> Mapping[str, Any]:
        """Return the provider's JSON answer as a mapping.

        ``instruction`` is trusted backend text. ``prompt`` is user-controlled
        and must be sent as conversational content, never spliced into the
        instruction. ``references`` are photographs the answer may describe,
        sent alongside the prompt; they are backend-chosen, never user-supplied
        bytes. Implementations raise ``AIProviderUnavailableError`` or
        ``AIResponseInvalidError`` and never return a partial answer.
        """
        ...
