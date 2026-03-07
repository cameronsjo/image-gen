"""Tests for authentication behavior."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from image_gen.app import create_app
from image_gen.config import Settings
from image_gen.services.gemini import GeminiResult

VALID_PROMPT = (
    "A photorealistic image of a single red cube sitting on a clean white surface "
    "with soft studio lighting. The cube has slightly rounded edges and a matte finish. "
    "The background is a pure white gradient that fades gently, creating a minimal and "
    "elegant composition. Light reflects subtly off the surface beneath the cube, casting "
    "a soft shadow to the right. The overall aesthetic is clean, modern, and suitable for "
    "product photography or design reference material."
)


async def _make_auth_client(tmp_path: Path, mock_result: GeminiResult | None = None):
    """Helper to create an app with auth enabled and proper lifespan."""
    settings = Settings(
        google_api_key="test-key",
        auth_enabled=True,
        data_dir=tmp_path / "data",
    )
    with patch("image_gen.services.gemini.genai.Client", return_value=MagicMock()):
        app = create_app(settings)
        async with LifespanManager(app):
            if mock_result:
                app.state.gemini.generate_image = AsyncMock(return_value=mock_result)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client


async def test_auth_enabled_rejects_unauthenticated(tmp_path: Path) -> None:
    async for client in _make_auth_client(tmp_path):
        resp = await client.post(
            "/api/generate",
            json={"name": "test", "prompt": VALID_PROMPT},
        )
        assert resp.status_code == 401


async def test_auth_enabled_accepts_forward_auth_headers(
    tmp_path: Path, mock_gemini_result: GeminiResult
) -> None:
    async for client in _make_auth_client(tmp_path, mock_gemini_result):
        resp = await client.post(
            "/api/generate",
            json={"name": "auth-test", "prompt": VALID_PROMPT},
            headers={
                "Remote-User": "testuser",
                "Remote-Name": "Test User",
                "Remote-Email": "test@example.com",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["user_id"] == "testuser"


async def test_health_accessible_without_auth(tmp_path: Path) -> None:
    async for client in _make_auth_client(tmp_path):
        resp = await client.get("/health")
        assert resp.status_code == 200
