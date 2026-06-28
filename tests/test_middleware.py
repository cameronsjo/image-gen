"""Tests for RequestIDMiddleware."""

from unittest.mock import MagicMock, patch

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from image_gen.app import create_app
from image_gen.config import Settings


@pytest.fixture
def settings(tmp_path: object) -> Settings:
    """Test settings with auth disabled."""
    from pathlib import Path

    return Settings(
        google_api_key="test-key-not-real",
        auth_enabled=False,
        data_dir=Path(str(tmp_path)) / "data",
        log_level="DEBUG",
    )


@pytest.fixture
async def client(settings: Settings) -> AsyncClient:
    """HTTP client backed by the full test app."""
    with patch("image_gen.services.gemini.genai.Client", return_value=MagicMock()):
        app = create_app(settings)
        async with LifespanManager(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac


async def test_response_includes_request_id_header(client: AsyncClient) -> None:
    """Every response should carry an X-Request-ID header."""
    response = await client.get("/health")
    assert "x-request-id" in response.headers
    assert response.headers["x-request-id"]  # non-empty


async def test_echoes_incoming_request_id(client: AsyncClient) -> None:
    """When the caller supplies X-Request-ID, the same value is echoed back."""
    response = await client.get("/health", headers={"X-Request-ID": "my-trace-id-123"})
    assert response.headers["x-request-id"] == "my-trace-id-123"


async def test_generates_request_id_when_none_supplied(client: AsyncClient) -> None:
    """When no X-Request-ID is sent, a generated UUID hex is returned."""
    response = await client.get("/health")
    request_id = response.headers["x-request-id"]
    # UUID4 hex is 32 hex characters
    assert len(request_id) == 32
    assert all(c in "0123456789abcdef" for c in request_id)


async def test_different_requests_get_different_ids(client: AsyncClient) -> None:
    """Two requests without a client-supplied ID should get distinct request IDs."""
    r1 = await client.get("/health")
    r2 = await client.get("/health")
    assert r1.headers["x-request-id"] != r2.headers["x-request-id"]


async def test_malicious_request_id_not_reflected() -> None:
    """A CRLF header-injection attempt in X-Request-ID is dropped, not echoed.

    Driven at the ASGI scope level because httpx rejects CRLF in outgoing
    header values client-side — so the defense must be proven on the middleware.
    """
    from image_gen.middleware import RequestIDMiddleware

    sent: list[dict] = []

    async def dummy_app(scope: dict, receive: object, send: object) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})  # type: ignore[operator]
        await send({"type": "http.response.body", "body": b""})  # type: ignore[operator]

    async def receive() -> dict:
        return {"type": "http.request"}

    async def send(message: dict) -> None:
        sent.append(message)

    middleware = RequestIDMiddleware(dummy_app)
    scope = {"type": "http", "headers": [(b"x-request-id", b"abc\r\nX-Injected: evil")]}
    await middleware(scope, receive, send)

    start = next(m for m in sent if m["type"] == "http.response.start")
    rid_values = [v for (k, v) in start["headers"] if k == b"x-request-id"]
    assert len(rid_values) == 1
    rid = rid_values[0]
    assert b"\r" not in rid and b"\n" not in rid
    assert b"X-Injected" not in rid
    # The malicious value is discarded; a clean uuid4 hex is generated instead.
    assert len(rid) == 32
