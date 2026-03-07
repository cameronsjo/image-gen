"""Shared fixtures for image-gen tests."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from image_gen.app import create_app
from image_gen.config import Settings
from image_gen.services.gemini import GeminiResult


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Provide a temporary data directory for tests."""
    return tmp_path / "data"


@pytest.fixture
def settings(tmp_data_dir: Path) -> Settings:
    """Create test settings with auth disabled and temp storage."""
    return Settings(
        google_api_key="test-key-not-real",
        auth_enabled=False,
        data_dir=tmp_data_dir,
        log_level="DEBUG",
    )


@pytest.fixture
def mock_gemini_result() -> GeminiResult:
    """A fake 1x1 red pixel PNG for testing."""
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
        b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
        b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return GeminiResult(image_data=png_bytes, mime_type="image/png")


@pytest.fixture
async def client(settings: Settings, mock_gemini_result: GeminiResult) -> AsyncClient:
    """Create a test client with mocked Gemini SDK and full lifespan."""
    with patch("image_gen.services.gemini.genai.Client", return_value=MagicMock()):
        app = create_app(settings)
        async with LifespanManager(app):
            # Patch generate_image on the live GeminiService instance
            app.state.gemini.generate_image = AsyncMock(return_value=mock_gemini_result)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                yield ac
