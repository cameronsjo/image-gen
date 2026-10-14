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


class MCPHostStatusMiddleware:
    """Expose the SDK's rejected-Host status (421) as the required HTTP 403.

    Mounted around only the protected MCP sub-app; header validation stays in
    FastMCP's strict Host/Origin guard rather than a second custom allowlist.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        rejection_status: int | None = None

        async def send_forbidden_host(message: Message) -> None:
            nonlocal rejection_status
            if message["type"] == "http.response.start":
                status = message["status"]
                if status == 421:
                    logger.info("MCP request rejected", status=403, reason="invalid_host")
                    message = {**message, "status": 403}
                elif status == 401:
                    logger.info("MCP request rejected", status=401, reason="authentication_failed")
                elif status == 403:
                    rejection_status = status
            elif message["type"] == "http.response.body" and rejection_status is not None:
                # Recognize the SDK's fixed guard response, never log arbitrary
                # response bodies, headers, claims, or bearer-token material.
                reason = (
                    "invalid_origin"
                    if message.get("body") == b"Forbidden Origin"
                    else "access_forbidden"
                )
                logger.info("MCP request rejected", status=rejection_status, reason=reason)
                rejection_status = None
            await send(message)

        await self.app(scope, receive, send_forbidden_host)


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
