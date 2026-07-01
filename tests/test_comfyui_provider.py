"""Tests for the local ComfyUI provider — the 3-step submit→poll→fetch flow.

The provider is constructed directly with a mocked ``httpx.AsyncClient`` (no real
ComfyUI), and the multi-call flow is driven with ``post``/``get`` side-effect lists:
queued ``/prompt`` → pending ``/history`` → completed ``/history`` → ``/view`` bytes.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from image_gen.exceptions import ProviderError, UnsupportedParameterError
from image_gen.services import comfyui_provider
from image_gen.services._sizing import _RATIO_MAP, compute_size
from image_gen.services.comfyui_provider import (
    _RESOLUTION_BASE,
    ComfyUIProvider,
    _compute_dimensions,
)
from image_gen.services.provider import ProviderResult

# A minimal valid 1x1 PNG (same fixture shape the other provider tests use).
_FAKE_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
    b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

_PROMPT_ID = "p-123"


def _make_settings(**overrides):
    """Return a minimal Settings object with the ComfyUI provider configured."""
    from image_gen.config import Settings

    return Settings(
        google_api_key=overrides.pop("google_api_key", None),
        comfyui_url=overrides.pop("comfyui_url", "http://127.0.0.1:8188"),
        default_provider=overrides.pop("default_provider", "comfyui"),
        auth_enabled=False,
        data_dir=overrides.pop("data_dir", "/tmp/test-data"),
        **overrides,
    )


def _queued_response(node_errors=None):
    return httpx.Response(200, json={"prompt_id": _PROMPT_ID, "node_errors": node_errors or {}})


def _pending_history():
    # ComfyUI returns an empty object while the job is still queued/running.
    return httpx.Response(200, json={})


def _completed_history(filename="image-gen_00001_.png", subfolder="", node_id="9"):
    return httpx.Response(
        200,
        json={
            _PROMPT_ID: {
                "status": {"status_str": "success", "completed": True},
                "outputs": {
                    node_id: {
                        "images": [{"filename": filename, "subfolder": subfolder, "type": "output"}]
                    }
                },
            }
        },
    )


def _error_history():
    return httpx.Response(
        200,
        json={
            _PROMPT_ID: {
                "status": {
                    "status_str": "error",
                    "completed": False,
                    "messages": [["execution_error", {"node_type": "KSampler"}]],
                },
            }
        },
    )


def _view_response():
    return httpx.Response(200, content=_FAKE_PNG)


def _build_provider(settings=None):
    """Construct a provider whose pooled client is a mock (no real sockets)."""
    settings = settings or _make_settings()
    with patch("image_gen.services.comfyui_provider.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        provider = ComfyUIProvider(settings)
    return provider, mock_client


# ---------------------------------------------------------------------------
# Resolution / dimension mapping
# ---------------------------------------------------------------------------


class TestComfyUISizing:
    def test_square_1k(self):
        assert _compute_dimensions("1:1", "1K") == (1024, 1024)

    def test_square_2k(self):
        assert _compute_dimensions("1:1", "2K") == (2048, 2048)

    def test_landscape_16_9_2k(self):
        w, h = _compute_dimensions("16:9", "2K")
        assert (w, h) == (2048, 1152)
        assert w % 16 == 0 and h % 16 == 0

    def test_4k_raises_unsupported(self):
        with pytest.raises(UnsupportedParameterError, match="up to 2K"):
            _compute_dimensions("1:1", "4K")

    def test_unknown_resolution_raises(self):
        with pytest.raises(UnsupportedParameterError, match="resolution"):
            _compute_dimensions("1:1", "8K")

    def test_unknown_ratio_raises(self):
        with pytest.raises(UnsupportedParameterError, match="aspect ratio"):
            _compute_dimensions("7:3", "2K")

    def test_agrees_with_shared_compute_size(self):
        """ComfyUI dimensions must equal the shared compute_size math for 1K/2K."""
        for ratio in _RATIO_MAP:
            for res, base in _RESOLUTION_BASE.items():
                expected = tuple(int(p) for p in compute_size(ratio, base, "ComfyUI").split("x"))
                assert _compute_dimensions(ratio, res) == expected, f"diverged for {ratio} {res}"


# ---------------------------------------------------------------------------
# Generation flow (mocked httpx)
# ---------------------------------------------------------------------------


class TestComfyUIProvider:
    async def test_generate_returns_provider_result(self):
        provider, mock_client = _build_provider()
        mock_client.post = AsyncMock(return_value=_queued_response())
        mock_client.get = AsyncMock(side_effect=[_completed_history(), _view_response()])

        result = await provider.generate_image("a red fox in snow", "1:1", "2K")

        assert isinstance(result, ProviderResult)
        assert result.image_data == _FAKE_PNG
        assert result.mime_type == "image/png"

    async def test_graph_templating_injects_prompt_and_dimensions(self):
        provider, mock_client = _build_provider()
        mock_client.post = AsyncMock(return_value=_queued_response())
        mock_client.get = AsyncMock(side_effect=[_completed_history(), _view_response()])

        await provider.generate_image("a red fox in snow", "16:9", "2K")

        graph = mock_client.post.call_args.kwargs["json"]["prompt"]
        positive = next(
            n
            for n in graph.values()
            if n["class_type"] == "CLIPTextEncode" and "positive" in n["_meta"]["title"].lower()
        )
        latent = next(n for n in graph.values() if n["class_type"] == "EmptyLatentImage")
        assert positive["inputs"]["text"] == "a red fox in snow"
        assert (latent["inputs"]["width"], latent["inputs"]["height"]) == _compute_dimensions(
            "16:9", "2K"
        )
        # client_id is sent alongside the graph.
        assert mock_client.post.call_args.kwargs["json"]["client_id"]

    async def test_polling_pending_then_complete(self):
        provider, mock_client = _build_provider()
        mock_client.post = AsyncMock(return_value=_queued_response())
        mock_client.get = AsyncMock(
            side_effect=[_pending_history(), _completed_history(), _view_response()]
        )

        with patch.object(comfyui_provider, "_POLL_INTERVAL_SECONDS", 0.0):
            result = await provider.generate_image("test", "1:1", "1K")

        assert result.image_data == _FAKE_PNG
        # One pending poll, one completed poll, one /view fetch.
        assert mock_client.get.await_count == 3

    async def test_4k_raises_unsupported(self):
        provider, _ = _build_provider()
        with pytest.raises(UnsupportedParameterError, match="up to 2K"):
            await provider.generate_image("test", "1:1", "4K")

    async def test_unknown_ratio_raises_unsupported(self):
        provider, _ = _build_provider()
        with pytest.raises(UnsupportedParameterError):
            await provider.generate_image("test", "7:3", "2K")

    async def test_server_down_raises_provider_error(self):
        provider, mock_client = _build_provider()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        with pytest.raises(ProviderError, match="ComfyUI HTTP error"):
            await provider.generate_image("test", "1:1", "2K")

    async def test_node_errors_raise_provider_error(self):
        provider, mock_client = _build_provider()
        mock_client.post = AsyncMock(
            return_value=_queued_response(node_errors={"12": {"errors": ["bad model"]}})
        )

        with pytest.raises(ProviderError, match="rejected the workflow"):
            await provider.generate_image("test", "1:1", "2K")

    async def test_http_error_on_submit_raises_provider_error(self):
        provider, mock_client = _build_provider()
        mock_client.post = AsyncMock(return_value=httpx.Response(500, text="boom"))

        with pytest.raises(ProviderError, match="HTTP 500"):
            await provider.generate_image("test", "1:1", "2K")

    async def test_execution_error_raises_provider_error(self):
        provider, mock_client = _build_provider()
        mock_client.post = AsyncMock(return_value=_queued_response())
        mock_client.get = AsyncMock(return_value=_error_history())

        with pytest.raises(ProviderError, match="execution failed"):
            await provider.generate_image("test", "1:1", "2K")

    async def test_timeout_raises_provider_error(self):
        provider, mock_client = _build_provider()
        mock_client.post = AsyncMock(side_effect=httpx.ReadTimeout("timed out"))

        with pytest.raises(ProviderError, match="timed out"):
            await provider.generate_image("test", "1:1", "2K")

    async def test_completed_without_image_raises_provider_error(self):
        provider, mock_client = _build_provider()
        empty = httpx.Response(
            200,
            json={_PROMPT_ID: {"status": {"status_str": "success"}, "outputs": {"9": {}}}},
        )
        mock_client.post = AsyncMock(return_value=_queued_response())
        mock_client.get = AsyncMock(return_value=empty)

        with pytest.raises(ProviderError, match="no output image"):
            await provider.generate_image("test", "1:1", "2K")

    async def test_pooled_client_reused_across_calls(self):
        with patch("image_gen.services.comfyui_provider.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=_queued_response())
            mock_client.get = AsyncMock(
                side_effect=[
                    _completed_history(),
                    _view_response(),
                    _completed_history(),
                    _view_response(),
                ]
            )
            mock_cls.return_value = mock_client
            provider = ComfyUIProvider(_make_settings())
            await provider.generate_image("a", "1:1", "2K")
            await provider.generate_image("b", "1:1", "2K")

        # Client constructed once in __init__, reused for both generations.
        assert mock_cls.call_count == 1
        assert mock_client.post.await_count == 2

    async def test_aclose_closes_pooled_client(self):
        provider, mock_client = _build_provider()
        mock_client.aclose = AsyncMock()

        await provider.aclose()

        mock_client.aclose.assert_awaited_once()

    def test_workflow_override_is_loaded(self, tmp_path):
        """A configured comfyui_workflow replaces the bundled template."""
        import json

        custom = {
            "1": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": ""},
                "_meta": {"title": "Positive Prompt"},
            },
            "2": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": 0, "height": 0},
                "_meta": {"title": "Latent"},
            },
            "3": {
                "class_type": "KSampler",
                "inputs": {"seed": 0, "steps": 0},
                "_meta": {"title": "KSampler"},
            },
        }
        wf = tmp_path / "custom.json"
        wf.write_text(json.dumps(custom))

        provider, _ = _build_provider(_make_settings(comfyui_workflow=wf))
        graph = provider._build_graph("hello world", 512, 512)

        positive = next(n for n in graph.values() if n["class_type"] == "CLIPTextEncode")
        assert positive["inputs"]["text"] == "hello world"

    def test_missing_node_raises_provider_error(self):
        """A template drifted from the running ComfyUI fails clearly, not silently."""
        from image_gen.services.comfyui_provider import _find_node

        with pytest.raises(ProviderError, match="missing a"):
            _find_node({}, "KSampler")

    def test_malformed_node_without_inputs_raises_provider_error(self):
        """A matched node lacking an 'inputs' map is a template defect, surfaced clearly."""
        from image_gen.services.comfyui_provider import _find_node

        graph = {"1": {"class_type": "KSampler", "_meta": {"title": "KSampler"}}}
        with pytest.raises(ProviderError, match="no 'inputs' map"):
            _find_node(graph, "KSampler")

    def test_build_graph_invalid_json_raises_provider_error(self):
        """A corrupt/invalid workflow template surfaces as ProviderError, not JSONDecodeError."""
        provider, _ = _build_provider()
        provider._workflow_json = "not valid json {{{"
        with pytest.raises(ProviderError, match="not valid JSON"):
            provider._build_graph("prompt", 1024, 1024)

    def test_build_graph_non_object_template_raises_provider_error(self):
        """A UI-format export (JSON array) instead of an API-format object fails clearly."""
        provider, _ = _build_provider()
        provider._workflow_json = "[1, 2, 3]"
        with pytest.raises(ProviderError, match="API-format JSON object"):
            provider._build_graph("prompt", 1024, 1024)

    async def test_output_image_without_filename_raises_provider_error(self):
        """An images entry lacking a filename is not a fetchable output."""
        provider, mock_client = _build_provider()
        no_filename = httpx.Response(
            200,
            json={
                _PROMPT_ID: {
                    "status": {"status_str": "success"},
                    "outputs": {"9": {"images": [{"subfolder": "", "type": "output"}]}},
                }
            },
        )
        mock_client.post = AsyncMock(return_value=_queued_response())
        mock_client.get = AsyncMock(return_value=no_filename)

        with pytest.raises(ProviderError, match="no output image"):
            await provider.generate_image("test", "1:1", "2K")

    def test_find_node_skips_class_type_match_with_wrong_title(self):
        """A node of the right class_type but non-matching title is skipped, not returned."""
        from image_gen.services.comfyui_provider import _find_node

        graph = {
            "1": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": ""},
                "_meta": {"title": "CLIP Text Encode (Negative Prompt)"},
            },
            "2": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": ""},
                "_meta": {"title": "CLIP Text Encode (Positive Prompt)"},
            },
        }
        node = _find_node(graph, "CLIPTextEncode", "positive")
        assert node["_meta"]["title"] == "CLIP Text Encode (Positive Prompt)"

    def test_model_name_property_returns_configured_model(self):
        provider, _ = _build_provider(_make_settings(comfyui_model="my-custom-model"))
        assert provider.model_name == "my-custom-model"

    def test_build_graph_missing_node_logs_and_reraises_provider_error(self):
        """A drifted template (missing expected node) fails via _build_graph's own
        try/except wrapper, not just the bare _find_node helper."""
        provider, _ = _build_provider()
        provider._workflow_json = "{}"

        with pytest.raises(ProviderError, match="missing a"):
            provider._build_graph("a prompt", 512, 512)

    async def test_submit_missing_prompt_id_raises_provider_error(self):
        provider, mock_client = _build_provider()
        mock_client.post = AsyncMock(return_value=httpx.Response(200, json={"node_errors": {}}))

        with pytest.raises(ProviderError, match="no prompt_id"):
            await provider.generate_image("test", "1:1", "2K")

    async def test_history_http_error_raises_provider_error(self):
        provider, mock_client = _build_provider()
        mock_client.post = AsyncMock(return_value=_queued_response())
        mock_client.get = AsyncMock(return_value=httpx.Response(500, text="server error"))

        with pytest.raises(ProviderError, match="/history returned HTTP 500"):
            await provider.generate_image("test", "1:1", "2K")

    async def test_view_http_error_raises_provider_error(self):
        provider, mock_client = _build_provider()
        mock_client.post = AsyncMock(return_value=_queued_response())
        mock_client.get = AsyncMock(
            side_effect=[_completed_history(), httpx.Response(404, text="not found")]
        )

        with pytest.raises(ProviderError, match="/view returned HTTP 404"):
            await provider.generate_image("test", "1:1", "2K")


# ---------------------------------------------------------------------------
# list_models — best-effort enumeration with graceful degradation
# ---------------------------------------------------------------------------


class TestComfyUIListModels:
    async def test_degrades_to_model_name_on_error(self):
        provider, mock_client = _build_provider()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("down"))

        assert await provider.list_models() == ["flux1-schnell"]

    async def test_enumerates_and_lists_default_first(self):
        provider, mock_client = _build_provider()
        object_info = httpx.Response(
            200,
            json={
                "UNETLoader": {
                    "input": {
                        "required": {"unet_name": [["other.safetensors", "flux1-schnell"], {}]}
                    }
                }
            },
        )
        mock_client.get = AsyncMock(return_value=object_info)

        models = await provider.list_models()

        assert models[0] == "flux1-schnell"
        assert "other.safetensors" in models

    async def test_object_info_http_error_degrades_to_model_name(self):
        """A non-2xx /object_info response is caught by the broad except and
        degrades gracefully, same as a connection failure."""
        provider, mock_client = _build_provider()
        mock_client.get = AsyncMock(return_value=httpx.Response(500, text="boom"))

        assert await provider.list_models() == ["flux1-schnell"]


# ---------------------------------------------------------------------------
# Registry wiring — provider registers only when comfyui_url is set
# ---------------------------------------------------------------------------


class TestComfyUIRegistry:
    def test_registers_when_url_set(self):
        from image_gen.services.registry import build_registry

        with patch("image_gen.services.comfyui_provider.httpx.AsyncClient"):
            registry = build_registry(_make_settings())

        assert "comfyui" in registry

    def test_absent_when_url_unset(self):
        from image_gen.services.registry import build_registry

        settings = _make_settings(
            comfyui_url=None, google_api_key="g-test", default_provider="gemini"
        )
        with patch("image_gen.services.gemini.genai.Client"):
            registry = build_registry(settings)

        assert "comfyui" not in registry
