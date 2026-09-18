"""Per-user rate limiting for the endpoints that spend money.

Every search, room plan and room preview costs a paid model call, and a room
preview costs several times a text call. Without a limit, one scripted client,
or one stuck retry loop in the app, can spend the month's budget in an hour.

The limit is keyed by the user id taken from the verified Supabase token,
never by anything the client sends, so it cannot be dodged by changing a
header. It is a sliding window held in process memory: correct for the single
server this project runs today, and the first thing to move to a shared store
the day a second server is added.

The check runs inside each route rather than as a dependency, after the
customer's language is known, so the refusal is in their language like every
other error. It still runs before any model call is spent.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, Request, status

from app.search.localization import message
from app.search.models import Language

Bucket = Literal["search", "room_plan", "room_image"]


@dataclass(frozen=True, slots=True)
class Limit:
    requests: int
    per_seconds: float


class RateLimiter:
    """Sliding-window counts per (user, bucket), in memory."""

    def __init__(
        self,
        limits: dict[Bucket, Limit],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = limits
        self._clock = clock
        self._events: dict[tuple[str, Bucket], deque[float]] = {}

    def check(self, user_id: str, bucket: Bucket) -> float | None:
        """Record a request, or return how many seconds until one is allowed."""

        limit = self._limits[bucket]
        now = self._clock()
        events = self._events.setdefault((user_id, bucket), deque())
        while events and now - events[0] >= limit.per_seconds:
            events.popleft()
        if len(events) >= limit.requests:
            return max(0.0, limit.per_seconds - (now - events[0]))
        events.append(now)
        # Users who stop sending requests would otherwise keep an empty entry
        # forever; sweeping on write keeps memory proportional to active users.
        if len(self._events) > 10_000:
            self._sweep(now)
        return None

    def _sweep(self, now: float) -> None:
        for key in list(self._events):
            window = self._limits[key[1]].per_seconds
            events = self._events[key]
            if not events or now - events[-1] >= window:
                del self._events[key]


def rate_limited(retry_after: float, language: Language) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"code": "rate_limited", "message": message("rate_limited", language)},
        headers={"Retry-After": str(max(1, round(retry_after)))},
    )


def enforce_rate_limit(
    request: Request, *, user_id: object, bucket: Bucket, language: Language
) -> None:
    """Refuse with 429 once this user is over the bucket's limit.

    Without a limiter installed nothing is limited. Only the test application
    runs that way; a test asserts the real startup installs one.
    """

    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        return
    retry_after = limiter.check(str(user_id), bucket)
    if retry_after is not None:
        raise rate_limited(retry_after, language)
