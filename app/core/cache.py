"""A small time-limited cache for model answers.

What is cached is chosen so that sharing an entry can never leak anything
between customers:

  A parsed search or room request depends only on the sentence. Two customers
  typing the same sentence get the same parse, and nothing about either of them
  is in it. The catalogue is still read fresh on every request, under each
  caller's own token, so row-level security still decides what they see.

  A rendered preview depends only on which products, quantities and colours it
  shows. The image endpoint still looks every product up again under the
  caller's token before a cached image is returned, so a cached render can
  never show someone a product they could not have been shown.

Held in process memory with a size cap and an age cap, so it cannot grow
without bound and stale answers expire.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from collections.abc import Callable

from fastapi import Request


class TTLCache[T]:
    def __init__(
        self,
        *,
        max_entries: int,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_entries
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, T]] = OrderedDict()

    def get(self, key: str) -> T | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if self._clock() - stored_at >= self._ttl:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return value

    def put(self, key: str, value: T) -> None:
        self._entries[key] = (self._clock(), value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)


class AICaches:
    """The caches the AI endpoints share, installed once at startup."""

    def __init__(self, *, ttl_seconds: float) -> None:
        self.parses: TTLCache[object] = TTLCache(
            max_entries=1024, ttl_seconds=ttl_seconds
        )
        # Rendered images are around 1.5 MB each, so this cap keeps the cache
        # near 50 MB at most.
        self.images: TTLCache[object] = TTLCache(
            max_entries=32, ttl_seconds=ttl_seconds
        )


def cache_key(*parts: str | bytes) -> str:
    """A fixed-length key over exact inputs, with parts kept unambiguous."""

    digest = hashlib.sha256()
    for part in parts:
        data = part.encode("utf-8") if isinstance(part, str) else part
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def get_ai_caches(request: Request) -> AICaches | None:
    """The lifespan-installed caches, or ``None`` when caching is off."""

    return getattr(request.app.state, "ai_caches", None)
