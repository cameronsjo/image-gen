"""Raw ASGI middleware for request tracing.

Implemented as a raw ASGI middleware (same pattern as MCPSlashRewrite) to
avoid BaseHTTPMiddleware's response-buffering which breaks MCP SSE streaming.
"""

from collections.abc import Awaitable, Callable
from uuid import uuid4

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger()


class RequestIDMiddleware:
    """Attach a request-ID to every HTTP request for log correlation.

    Reads an incoming ``X-Request-ID`` header and falls back to a fresh
    ``uuid4`` hex when none is present.  The ID is:

    - bound to ``structlog``'s context-var store so every log line emitted
      during the request carries ``request_id`` automatically;
    - echoed back in the ``X-Request-ID`` response header.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract or generate request-ID
        request_id: str | None = None
        for header_name, header_value in scope.get("headers", []):
            if header_name.lower() == b"x-request-id":
                request_id = header_value.decode("latin-1")
                break
        if not request_id:
            request_id = uuid4().hex

        # Bind to structlog context-vars for the duration of this request
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")

    # Type alias so mypy accepts the send wrapper's signature
    _SendCallable = Callable[[Message], Awaitable[None]]
