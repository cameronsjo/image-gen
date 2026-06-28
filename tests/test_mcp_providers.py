"""Tests for the MCP generate_image tool's provider-selection behaviour."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from image_gen.app import create_app
from image_gen.config import Settings
from image_gen.services.provider import ProviderResult

_FAKE_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
    b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

VALID_PROMPT = (
    "A photorealistic image of a test pattern used in automated unit tests. "
    "Clean white background with simple geometric shapes arranged in a grid. "
    "Neutral colours including grey, white, and black. Professional studio lighting "
    "from overhead with soft diffusion. Minimal composition with sharp focus and "
    "high contrast edges, suitable for automated visual regression tests in CI pipelines."
)


@pytest.fixture
def mcp_settings(tmp_path: Path) -> Settings:
    return Settings(
        google_api_key="test-gemini-key",
        auth_enabled=False,
        data_dir=tmp_path / "data",
        log_level="DEBUG",
    )


@pytest.fixture
async def mcp_client(mcp_settings: Settings):
    fake_result = ProviderResult(image_data=_FAKE_PNG, mime_type="image/png")
    with patch("image_gen.services.gemini.genai.Client", return_value=MagicMock()):
        app = create_app(mcp_settings)
        async with LifespanManager(app):
            app.state.provider_registry["gemini"].generate_image = AsyncMock(
                return_value=fake_result
            )
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac, app


async def test_mcp_generate_image_default_provider_succeeds(mcp_client):
    ac, app = mcp_client
    gemini_mock = app.state.provider_registry["gemini"].generate_image

    # Invoke via REST /api/generate (same registry path as MCP tool)
    resp = await ac.post(
        "/api/generate",
        json={"name": "mcp-default", "prompt": VALID_PROMPT},
    )
    assert resp.status_code == 201
    assert resp.json()["provider"] == "gemini"
    gemini_mock.assert_awaited()


async def test_mcp_registry_selects_injected_provider(mcp_client):
    """Injecting a second provider into the registry and requesting it works."""
    ac, app = mcp_client
    fake_result = ProviderResult(image_data=_FAKE_PNG, mime_type="image/png")
    mock_openai = AsyncMock(return_value=fake_result)

    openai_provider = MagicMock()
    openai_provider.name = "openai"
    openai_provider.generate_image = mock_openai
    app.state.provider_registry["openai"] = openai_provider

    resp = await ac.post(
        "/api/generate",
        json={"name": "mcp-openai", "prompt": VALID_PROMPT, "provider": "openai"},
    )
    assert resp.status_code == 201
    assert resp.json()["provider"] == "openai"
    mock_openai.assert_awaited_once()

    del app.state.provider_registry["openai"]


async def test_mcp_unknown_provider_returns_422(mcp_client):
    ac, _ = mcp_client
    resp = await ac.post(
        "/api/generate",
        json={"name": "bad", "prompt": VALID_PROMPT, "provider": "nonexistent"},
    )
    assert resp.status_code == 422
