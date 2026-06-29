"""Tests for provider implementations — param mapping and error cases.

Providers are constructed directly (no running app) with mocked SDK/HTTP clients,
so these tests run without real API keys.
"""

import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from image_gen.exceptions import UnsupportedParameterError
from image_gen.services._sizing import _MAX_DIM, _RATIO_MAP
from image_gen.services.openai_provider import (
    _RESOLUTION_MAP,
    OpenAIProvider,
    _compute_size,
)
from image_gen.services.openrouter_provider import (
    OpenRouterProvider,
    _compute_resolution,
)
from image_gen.services.provider import ProviderResult


def _gemini_settings(google_api_key="g-test", data_dir="/tmp/test-data", **kwargs):
    """Return a minimal Settings object with a Gemini key configured."""
    from image_gen.config import Settings

    return Settings(
        google_api_key=google_api_key,
        auth_enabled=False,
        data_dir=data_dir,
        **kwargs,
    )


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
        # gpt-image models reject response_format; it must not be sent.
        assert "response_format" not in call_kwargs

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

    async def test_aclose_closes_client(self):
        settings = _make_settings()
        with patch("image_gen.services.openai_provider.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            provider = OpenAIProvider(settings)

        await provider.aclose()

        mock_client.close.assert_awaited_once()

    async def test_list_models_filters_image_ids(self):
        """Only gpt-image-* / dall-e-* ids survive; the configured default leads."""
        settings = _make_settings()
        page = MagicMock()
        page.data = [
            SimpleNamespace(id="gpt-image-2"),
            SimpleNamespace(id="dall-e-3"),
            SimpleNamespace(id="gpt-4o"),
            SimpleNamespace(id="text-embedding-3-small"),
        ]
        with patch("image_gen.services.openai_provider.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_client.models.list = AsyncMock(return_value=page)
            mock_cls.return_value = mock_client
            provider = OpenAIProvider(settings)
            models = await provider.list_models()

        assert models[0] == "gpt-image-2"  # configured default, first
        assert "dall-e-3" in models
        assert "gpt-4o" not in models
        assert "text-embedding-3-small" not in models

    async def test_list_models_falls_back_on_error(self):
        settings = _make_settings()
        with patch("image_gen.services.openai_provider.AsyncOpenAI") as mock_cls:
            mock_client = AsyncMock()
            mock_client.models.list = AsyncMock(side_effect=RuntimeError("API down"))
            mock_cls.return_value = mock_client
            provider = OpenAIProvider(settings)
            models = await provider.list_models()

        assert models == ["gpt-image-2"]  # degrades to the configured default


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
        from image_gen.services.openrouter_provider import _RESOLUTION_MAP

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
    def _build_provider(self, settings=None):
        """Construct a provider whose pooled client is a mock (no real sockets)."""
        settings = settings or _make_settings()
        with patch("image_gen.services.openrouter_provider.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            provider = OpenRouterProvider(settings)
        return provider, mock_client

    async def test_generate_returns_provider_result(self):
        import httpx

        fake_response = httpx.Response(200, json={"data": [{"b64_json": _FAKE_B64}]})
        provider, mock_client = self._build_provider()
        mock_client.post = AsyncMock(return_value=fake_response)

        result = await provider.generate_image("test prompt", "1:1", "2K")

        assert isinstance(result, ProviderResult)
        assert result.image_data == _FAKE_PNG
        assert result.mime_type == "image/png"

    async def test_generate_raises_provider_error_on_4xx(self):
        import httpx

        from image_gen.exceptions import ProviderError

        fake_response = httpx.Response(401, text="Unauthorized")
        provider, mock_client = self._build_provider()
        mock_client.post = AsyncMock(return_value=fake_response)

        with pytest.raises(ProviderError, match="HTTP 401"):
            await provider.generate_image("test", "1:1", "2K")

    async def test_generate_raises_unsupported_for_unknown_ratio(self):
        provider, _ = self._build_provider()
        with pytest.raises(UnsupportedParameterError):
            await provider.generate_image("test", "7:3", "2K")

    async def test_pooled_client_reused_across_calls(self):
        import httpx

        fake_response = httpx.Response(200, json={"data": [{"b64_json": _FAKE_B64}]})
        with patch("image_gen.services.openrouter_provider.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=fake_response)
            mock_cls.return_value = mock_client
            provider = OpenRouterProvider(_make_settings())
            await provider.generate_image("a", "1:1", "2K")
            await provider.generate_image("b", "1:1", "2K")

        # The client is constructed once in __init__ and reused for both requests —
        # no per-call client creation.
        assert mock_cls.call_count == 1
        assert mock_client.post.await_count == 2

    async def test_aclose_closes_pooled_client(self):
        provider, mock_client = self._build_provider()
        mock_client.aclose = AsyncMock()

        await provider.aclose()

        mock_client.aclose.assert_awaited_once()

    async def test_list_models_filters_image_modalities(self):
        import httpx

        catalogue = {
            "data": [
                {"id": "openai/gpt-image-2", "architecture": {"output_modalities": ["image"]}},
                {
                    "id": "google/gemini-2.5-flash-image",
                    "architecture": {"output_modalities": ["image", "text"]},
                },
                {"id": "anthropic/claude", "architecture": {"output_modalities": ["text"]}},
                {"id": "no-architecture-field"},
            ]
        }
        provider, mock_client = self._build_provider()
        mock_client.get = AsyncMock(return_value=httpx.Response(200, json=catalogue))

        models = await provider.list_models()

        assert models[0] == "openai/gpt-image-2"  # configured default, first
        assert "google/gemini-2.5-flash-image" in models
        assert "anthropic/claude" not in models
        assert "no-architecture-field" not in models

    async def test_list_models_falls_back_on_error(self):
        provider, mock_client = self._build_provider()
        mock_client.get = AsyncMock(side_effect=RuntimeError("network down"))

        models = await provider.list_models()

        assert models == ["openai/gpt-image-2"]  # degrades to the configured default


# ---------------------------------------------------------------------------
# Shared sizing — both providers must agree (dedup invariant, #12)
# ---------------------------------------------------------------------------


class TestSharedSizing:
    def test_providers_compute_identical_sizes(self):
        """OpenAI and OpenRouter share one sizing helper, so for every canonical
        ratio + resolution they must return byte-identical WxH strings."""
        for ratio in _RATIO_MAP:
            for res in _RESOLUTION_MAP:
                assert _compute_size(ratio, res) == _compute_resolution(ratio, res), (
                    f"size diverged for {ratio} {res}"
                )

    def test_shared_helper_attributes_provider_in_error(self):
        from image_gen.services._sizing import compute_size

        with pytest.raises(UnsupportedParameterError, match="OpenAI provider"):
            compute_size("7:3", 2048, "OpenAI")


# ---------------------------------------------------------------------------
# Gemini provider — native SDK timeout (#9)
# ---------------------------------------------------------------------------


class TestGeminiProvider:
    def test_client_constructed_with_native_http_timeout(self):
        """genai.Client must receive a native HTTP timeout (in ms) so a hung
        upstream releases its worker thread instead of occupying it."""
        from image_gen.services.gemini import GeminiProvider

        settings = _gemini_settings(request_timeout_seconds=30.0)
        with patch("image_gen.services.gemini.genai.Client") as mock_cls:
            GeminiProvider(settings)

        kwargs = mock_cls.call_args.kwargs
        assert "http_options" in kwargs
        # HttpOptions.timeout is milliseconds; settings is seconds.
        assert kwargs["http_options"].timeout == int(30.0 * 1000)

    async def test_aclose_is_noop_by_default(self):
        """Providers holding no pooled client inherit the base no-op aclose."""
        from image_gen.services.gemini import GeminiProvider

        settings = _gemini_settings()
        with patch("image_gen.services.gemini.genai.Client", return_value=MagicMock()):
            provider = GeminiProvider(settings)

        # Must be awaitable and not raise.
        assert await provider.aclose() is None

    async def test_list_models_filters_and_strips_prefix(self):
        """Keeps image/imagen models, strips the ``models/`` prefix, default first."""
        from image_gen.services.gemini import GeminiProvider

        settings = _gemini_settings()
        fake_client = MagicMock()
        fake_client.models.list.return_value = [
            SimpleNamespace(name="models/gemini-2.5-flash-image"),
            SimpleNamespace(name="models/imagen-4.0-generate"),
            SimpleNamespace(name="models/gemini-2.0-flash"),  # no image → dropped
            SimpleNamespace(name=None),  # skipped without raising
        ]
        with patch("image_gen.services.gemini.genai.Client", return_value=fake_client):
            provider = GeminiProvider(settings)
            models = await provider.list_models()

        assert models[0] == "gemini-3-pro-image-preview"  # configured default, first
        assert "gemini-2.5-flash-image" in models  # prefix stripped
        assert "imagen-4.0-generate" in models
        assert "gemini-2.0-flash" not in models

    async def test_list_models_falls_back_on_error(self):
        from image_gen.services.gemini import GeminiProvider

        settings = _gemini_settings()
        fake_client = MagicMock()
        fake_client.models.list.side_effect = RuntimeError("list failed")
        with patch("image_gen.services.gemini.genai.Client", return_value=fake_client):
            provider = GeminiProvider(settings)
            models = await provider.list_models()

        assert models == ["gemini-3-pro-image-preview"]


# ---------------------------------------------------------------------------
# Model discovery orchestration (registry.discover_models)
# ---------------------------------------------------------------------------


async def test_discover_models_tolerates_failing_provider():
    """A provider whose list_models raises degrades to [model_name]; others succeed."""
    from image_gen.services.registry import discover_models

    good = MagicMock()
    good.model_name = "m-a"
    good.list_models = AsyncMock(return_value=["m-a", "m-b"])

    bad = MagicMock()
    bad.model_name = "bad-default"
    bad.list_models = AsyncMock(side_effect=RuntimeError("boom"))

    result = await discover_models({"good": good, "bad": bad}, timeout=5.0)

    assert result["good"] == ["m-a", "m-b"]
    assert result["bad"] == ["bad-default"]


async def test_discover_models_times_out_to_default():
    """A list_models that exceeds the timeout degrades to [model_name]."""
    from image_gen.services.registry import discover_models

    async def _slow() -> list[str]:
        await asyncio.sleep(10)
        return ["never-returned"]

    slow = MagicMock()
    slow.model_name = "slow-default"
    slow.list_models = _slow

    result = await discover_models({"slow": slow}, timeout=0.01)

    assert result["slow"] == ["slow-default"]


# ---------------------------------------------------------------------------
# App lifespan — provider clients are closed on shutdown (#11)
# ---------------------------------------------------------------------------


async def test_lifespan_closes_providers(tmp_path):
    """The lifespan teardown must call aclose() on every registered provider so
    pooled clients are released cleanly on shutdown."""
    from asgi_lifespan import LifespanManager

    from image_gen.app import create_app

    settings = _gemini_settings(data_dir=tmp_path / "data")
    with patch("image_gen.services.gemini.genai.Client", return_value=MagicMock()):
        app = create_app(settings)
        async with LifespanManager(app):
            provider = app.state.provider_registry["gemini"]
            provider.aclose = AsyncMock()
        # Block exit runs lifespan shutdown.
        provider.aclose.assert_awaited_once()
