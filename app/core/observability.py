"""One log line per request, and a request id the client can quote.

Each request gets an id, returned as `X-Request-ID`, and one log line with the
method, path, status and time taken. When a customer reports a problem, the id
on their screen finds the exact line in the server log.

What is never logged: headers (the bearer token lives there), query strings,
request and response bodies (a customer's sentence is theirs), and exception
messages, which can quote upstream responses. An unhandled error logs its type
and traceback under the same request id.

A client may send its own `X-Request-ID` to correlate with its own logs. It is
accepted only if it is a short run of safe characters, so it cannot forge a log
line or smuggle anything into a response header.
"""

from __future__ import annotations

import logging
import re
import time
import traceback
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("app.requests")

REQUEST_ID_HEADER = "x-request-id"
SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")


def configure_logging(level: str) -> None:
    """Send the application's own log lines to stderr, once."""

    app_logger = logging.getLogger("app")
    app_logger.setLevel(level)
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        app_logger.addHandler(handler)


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", ()):
        if name == REQUEST_ID_HEADER.encode("ascii"):
            candidate = value.decode("latin-1")
            if SAFE_REQUEST_ID.fullmatch(candidate):
                return candidate
            return None
    return None


def _loggable_path(scope: Scope) -> str:
    """The path as sent, still percent-encoded, so it holds no line breaks.

    The decoded path would turn `%0A` into a newline and let a client write a
    fake log line. The query string is not part of it.
    """

    raw = scope.get("raw_path")
    path = raw.decode("latin-1") if raw else scope.get("path", "")
    path = path.split("?", 1)[0]
    return "".join(c if c.isprintable() and c != " " else "?" for c in path[:200])


class RequestLogMiddleware:
    """Pure ASGI, so it never buffers a response body."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        status_code = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != REQUEST_ID_HEADER.encode("ascii")
                ]
                headers.append(
                    (REQUEST_ID_HEADER.encode("ascii"), request_id.encode("ascii"))
                )
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception as error:
            # Frames only: the standard formatter would also print the
            # exception's message, which is where upstream text ends up.
            frames = "".join(
                traceback.format_list(traceback.extract_tb(error.__traceback__))
            )
            logger.error(
                "request_id=%s unhandled %s\n%s",
                request_id,
                type(error).__name__,
                frames,
            )
            raise
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "request_id=%s method=%s path=%s status=%d duration_ms=%.0f",
                request_id,
                scope.get("method", ""),
                _loggable_path(scope),
                status_code,
                elapsed_ms,
            )
