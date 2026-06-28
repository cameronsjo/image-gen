"""Raw ASGI middleware for request tracing.

Implemented as a raw ASGI middleware (same pattern as MCPSlashRewrite) to
avoid BaseHTTPMiddleware's response-buffering which breaks MCP SSE streaming.
"""

import re
from uuid import uuid4

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger()

# A request-ID we are willing to echo into a response header / log context.
# Bounds length and forbids CR/LF and other control chars so a client-supplied
# value can't inject headers or forge log lines.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


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

        # Extract or generate request-ID. ASGI delivers header names lowercased.
        request_id: str | None = None
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"x-request-id":
                candidate = header_value.decode("latin-1")
                # Only honor a well-formed client value; otherwise generate one.
                if _REQUEST_ID_RE.match(candidate):
                    request_id = candidate
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
