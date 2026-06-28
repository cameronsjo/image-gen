"""Tests for provider implementations — param mapping and error cases.

Providers are constructed directly (no running app) with mocked SDK/HTTP clients,
so these tests run without real API keys.
"""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from image_gen.exceptions import UnsupportedParameterError
from image_gen.services.openai_provider import (
    _RATIO_MAP,
    _RESOLUTION_MAP,
    OpenAIProvider,
    _compute_size,
)
from image_gen.services.openrouter_provider import (
    OpenRouterProvider,
    _compute_resolution,
)
from image_gen.services.provider import ProviderResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
    b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

_FAKE_B64 = base64.b64encode(_FAKE_PNG).decode()


def _make_settings(**overrides):
    """Return a minimal Settings object for provider tests."""
    from image_gen.config import Settings

    return Settings(
        google_api_key=None,
        openai_api_key=overrides.get("openai_api_key", "sk-test"),
        openrouter_api_key=overrides.get("openrouter_api_key", "or-test"),
        auth_enabled=False,
        data_dir=overrides.get("data_dir", "/tmp/test-data"),
    )


# ---------------------------------------------------------------------------
# OpenAI param mapping
# ---------------------------------------------------------------------------


class TestOpenAIParamMapping:
    def test_square_2k(self):
        size = _compute_size("1:1", "2K")
        assert size == "2048x2048"

    def test_square_1k(self):
        size = _compute_size("1:1", "1K")
        assert size == "1024x1024"

    def test_square_4k(self):
        size = _compute_size("1:1", "4K")
        w, h = map(int, size.split("x"))
        assert w == h  # square
        assert w <= 3840

    def test_landscape_16_9_2k(self):
        size = _compute_size("16:9", "2K")
        w, h = map(int, size.split("x"))
        # Long edge should be 2048, short edge proportional
        assert w == 2048
        # h = 2048 * 9 / 16 = 1152, which is divisible by 16
        assert h == 1152
        assert h % 16 == 0

    def test_portrait_9_16_2k(self):
        size = _compute_size("9:16", "2K")
        w, h = map(int, size.split("x"))
        # Portrait: height is long edge, capped at 2160
        assert h <= 2160
        assert w % 16 == 0

    def test_ultrawide_21_9(self):
        size = _compute_size("21:9", "2K")
        w, h = map(int, size.split("x"))
        assert w % 16 == 0
        assert h % 16 == 0

    def test_all_canonical_ratios_accepted(self):
        """All AspectRatio values should map without raising."""
        from image_gen.services.openai_provider import _MAX_DIM

        for ratio in _RATIO_MAP:
            for res in _RESOLUTION_MAP:
                size = _compute_size(ratio, res)
                w, h = map(int, size.split("x"))
                assert w % 16 == 0
                assert h % 16 == 0
                assert w <= _MAX_DIM
                assert h <= _MAX_DIM

    def test_unknown_ratio_raises(self):
        with pytest.raises(UnsupportedParameterError, match="aspect ratio"):
            _compute_size("7:3", "2K")

    def test_unknown_resolution_raises(self):
        with pytest.raises(UnsupportedParameterError, match="resolution"):
            _compute_size("1:1", "8K")

    def test_quality_mapping(self):
        """Verify resolution -> quality mapping."""
        assert _RESOLUTION_MAP["1K"][0] == "low"
        assert _RESOLUTION_MAP["2K"][0] == "medium"
        assert _RESOLUTION_MAP["4K"][0] == "high"


# ---------------------------------------------------------------------------
# OpenAI provider integration (mocked SDK)
# ---------------------------------------------------------------------------


class TestOpenAIProvider:
    def _build_provider(self):
        settings = _make_settings()
        with patch("image_gen.services.openai_provider.AsyncOpenAI"):
            provider = OpenAIProvider(settings)
        return provider

    async def test_generate_returns_provider_result(self):
        settings = _make_settings()
        mock_resp = MagicMock()
        mock_resp.data = [MagicMock(b64_json=_FAKE_B64)]

        with patch("image_gen.services.openai_provider.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_client.images.generate = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client

            provider = OpenAIProvider(settings)
            result = await provider.generate_image("a test prompt", "1:1", "2K")

        assert isinstance(result, ProviderResult)
        assert result.image_data == _FAKE_PNG
        assert result.mime_type == "image/png"

    async def test_generate_passes_correct_size_and_quality(self):
        settings = _make_settings()
        mock_resp = MagicMock()
        mock_resp.data = [MagicMock(b64_json=_FAKE_B64)]

        with patch("image_gen.services.openai_provider.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_client.images.generate = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client

            provider = OpenAIProvider(settings)
            await provider.generate_image("test", "16:9", "1K")
            call_kwargs = mock_client.images.generate.call_args.kwargs

        assert call_kwargs["size"] == _compute_size("16:9", "1K")
        assert call_kwargs["quality"] == "low"
        assert call_kwargs["response_format"] == "b64_json"

    async def test_generate_raises_provider_error_on_sdk_failure(self):
        from image_gen.exceptions import ProviderError

        settings = _make_settings()
        with patch("image_gen.services.openai_provider.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_client.images.generate = AsyncMock(side_effect=RuntimeError("API down"))
            mock_cls.return_value = mock_client

            provider = OpenAIProvider(settings)
            with pytest.raises(ProviderError, match="API down"):
                await provider.generate_image("test", "1:1", "2K")

    async def test_generate_raises_unsupported_for_unknown_ratio(self):
        settings = _make_settings()
        with patch("image_gen.services.openai_provider.AsyncOpenAI"):
            provider = OpenAIProvider(settings)
        with pytest.raises(UnsupportedParameterError):
            await provider.generate_image("test", "7:3", "2K")


# ---------------------------------------------------------------------------
# OpenRouter param mapping
# ---------------------------------------------------------------------------


class TestOpenRouterParamMapping:
    def test_square_2k(self):
        size = _compute_resolution("1:1", "2K")
        assert size == "2048x2048"

    def test_landscape_16_9_1k(self):
        size = _compute_resolution("16:9", "1K")
        w, h = map(int, size.split("x"))
        assert w == 1024
        assert h == 576  # 1024 * 9/16 = 576, already divisible by 16
        assert h % 16 == 0

    def test_all_canonical_ratios_accepted(self):
        from image_gen.services.openrouter_provider import _RATIO_MAP, _RESOLUTION_MAP

        for ratio in _RATIO_MAP:
            for res in _RESOLUTION_MAP:
                size = _compute_resolution(ratio, res)
                w, h = map(int, size.split("x"))
                assert w % 16 == 0
                assert h % 16 == 0

    def test_unknown_ratio_raises(self):
        with pytest.raises(UnsupportedParameterError, match="aspect ratio"):
            _compute_resolution("7:3", "2K")

    def test_unknown_resolution_raises(self):
        with pytest.raises(UnsupportedParameterError, match="resolution"):
            _compute_resolution("1:1", "8K")


# ---------------------------------------------------------------------------
# OpenRouter provider integration (mocked httpx)
# ---------------------------------------------------------------------------


class TestOpenRouterProvider:
    def _build_provider(self):
        settings = _make_settings()
        return OpenRouterProvider(settings)

    async def test_generate_returns_provider_result(self):
        import httpx

        settings = _make_settings()
        fake_response = httpx.Response(
            200,
            json={"data": [{"b64_json": _FAKE_B64}]},
        )

        provider = OpenRouterProvider(settings)
        with patch("image_gen.services.openrouter_provider.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=fake_response)
            mock_cls.return_value = mock_client

            result = await provider.generate_image("test prompt", "1:1", "2K")

        assert isinstance(result, ProviderResult)
        assert result.image_data == _FAKE_PNG
        assert result.mime_type == "image/png"

    async def test_generate_raises_provider_error_on_4xx(self):
        import httpx

        from image_gen.exceptions import ProviderError

        settings = _make_settings()
        fake_response = httpx.Response(401, text="Unauthorized")

        provider = OpenRouterProvider(settings)
        with patch("image_gen.services.openrouter_provider.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=fake_response)
            mock_cls.return_value = mock_client

            with pytest.raises(ProviderError, match="HTTP 401"):
                await provider.generate_image("test", "1:1", "2K")

    async def test_generate_raises_unsupported_for_unknown_ratio(self):
        settings = _make_settings()
        provider = OpenRouterProvider(settings)
        with pytest.raises(UnsupportedParameterError):
            await provider.generate_image("test", "7:3", "2K")
