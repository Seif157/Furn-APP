"""Fetch product photographs to guide the room preview, safely.

Rendering a preview means this server downloads each product's photo, and the
photo URL is catalogue data a seller controls. Fetching an arbitrary URL
server-side is the classic way to make a server reach something it should not:
an internal address, a metadata service, a port behind the firewall.

So every fetch is bounded:

  HTTPS only, on the default port, to a host on an explicit allowlist.
  Redirects are followed by hand, at most three, and every hop is checked
  against the same rules, because an allowed host that redirects is otherwise
  a way around the allowlist.
  Only JPEG, PNG and WebP are accepted, and the body is read in chunks and
  abandoned past a size cap, so a hostile URL cannot make this server hold an
  unbounded response.

A photo that fails any rule is skipped rather than failing the request. The
preview is then made from fewer references, which the response reports.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit

import httpx

from app.ai.provider import ImageBytes

ALLOWED_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
MAX_REFERENCE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 3


class ReferenceImageFetcher:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        allowed_hosts: frozenset[str],
        timeout_seconds: float = 10.0,
    ) -> None:
        self._client = client
        self._allowed_hosts = frozenset(host.lower() for host in allowed_hosts)
        self._timeout = timeout_seconds

    def is_allowed(self, url: str) -> bool:
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            return False
        return (
            parts.scheme == "https"
            and port in (None, 443)
            and not parts.username
            and not parts.password
            and (parts.hostname or "").lower() in self._allowed_hosts
        )

    async def fetch(self, url: str) -> ImageBytes | None:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            if not self.is_allowed(current):
                return None
            try:
                async with self._client.stream(
                    "GET", current, timeout=self._timeout, follow_redirects=False
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            return None
                        current = urljoin(current, location)
                        continue
                    if response.status_code != httpx.codes.OK:
                        return None
                    mime_type = (
                        response.headers.get("content-type", "")
                        .split(";")[0]
                        .strip()
                        .lower()
                    )
                    if mime_type not in ALLOWED_TYPES:
                        return None
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_REFERENCE_BYTES:
                            return None
                    if not body:
                        return None
                    return ImageBytes(mime_type=mime_type, data=bytes(body))
            except (httpx.TimeoutException, httpx.RequestError):
                return None
        return None
