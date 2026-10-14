"""Model selection exercised through the actual MCP tool and SQLite persistence."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgi_lifespan import LifespanManager
from fastmcp import Client

from image_gen.app import create_app
from image_gen.db import repository
from image_gen.mcp.server import create_mcp_server
from image_gen.models import GenerationStatus
from image_gen.services.comfyui_provider import ComfyUIProvider

DEFAULT_MODEL = "gemini-3-pro-image-preview"
ALTERNATE_MODEL = "gemini-2.5-flash-image"
PROMPT = (
    "A photorealistic image of a test pattern used in automated unit tests. "
    "Clean white background with simple geometric shapes arranged in a grid. "
    "Neutral colours including grey, white, and black. Professional studio lighting "
    "from overhead with soft diffusion. Minimal composition with sharp focus and "
    "high contrast edges, suitable for automated visual regression tests in CI pipelines."
)


@pytest.fixture
async def mcp_env(settings, mock_gemini_result):
    with (
        patch("image_gen.services.gemini.genai.Client", return_value=MagicMock()),
        patch(
            "image_gen.services.gemini.GeminiProvider.list_models",
            new=AsyncMock(return_value=[DEFAULT_MODEL, ALTERNATE_MODEL]),
        ),
    ):
        app = create_app(settings)
        async with LifespanManager(app):
            generate = AsyncMock(return_value=mock_gemini_result)
            app.state.provider_registry["gemini"].generate_image = generate
            async with Client(create_mcp_server(settings)) as client:
                yield app, client, generate


async def test_mcp_model_is_optional_in_tool_schema(mcp_env):
    _, client, _ = mcp_env
    tool = next(tool for tool in await client.list_tools() if tool.name == "generate_image")
    assert "model" in tool.input_schema["properties"]
    assert "model" not in tool.input_schema.get("required", [])
    assert tool.input_schema["properties"]["model"]["default"] is None


@pytest.mark.parametrize(
    "arguments", [{}, {"model": None}, {"model": ""}, {"model": ALTERNATE_MODEL}]
)
async def test_mcp_model_is_forwarded_and_persisted(mcp_env, arguments):
    app, client, generate = mcp_env
    expected = arguments.get("model") or DEFAULT_MODEL
    result = await client.call_tool(
        "generate_image", {"name": "model-test", "prompt": PROMPT, **arguments}
    )
    assert "Image generated successfully!" in result.data
    generate.assert_awaited_once_with(
        prompt=PROMPT, aspect_ratio="1:1", resolution="2K", model=expected
    )
    records = await repository.list_generations(app.state.db, user_id="anonymous")
    assert len(records) == 1
    assert records[0].model == expected
    assert records[0].status == GenerationStatus.COMPLETED


@pytest.mark.parametrize("discovery", ["normal", "empty", "missing-provider", "missing-cache"])
async def test_mcp_rejects_unknown_model_before_side_effects(mcp_env, discovery):
    app, client, generate = mcp_env
    if discovery == "empty":
        app.state.provider_models["gemini"] = []
    elif discovery == "missing-provider":
        app.state.provider_models = {"openai": ["other-provider-model"]}
    elif discovery == "missing-cache":
        del app.state.provider_models
    app.state.quota.consume_token = AsyncMock()
    result = await client.call_tool(
        "generate_image",
        {"name": "invalid-model", "prompt": PROMPT, "model": "other-provider-model"},
    )
    assert "not available for provider 'gemini'" in result.data
    assert DEFAULT_MODEL in result.data
    app.state.quota.consume_token.assert_not_awaited()
    generate.assert_not_awaited()
    assert await repository.list_generations(app.state.db, user_id="anonymous") == []


@pytest.mark.parametrize("arguments", [{}, {"model": DEFAULT_MODEL}])
async def test_mcp_default_model_still_works_when_discovery_degrades(mcp_env, arguments):
    app, client, generate = mcp_env
    app.state.provider_models = {}
    result = await client.call_tool(
        "generate_image", {"name": "fallback", "prompt": PROMPT, **arguments}
    )
    assert "Image generated successfully!" in result.data
    assert generate.await_args.kwargs["model"] == DEFAULT_MODEL
    records = await repository.list_generations(app.state.db, user_id="anonymous")
    assert records[0].model == DEFAULT_MODEL


@pytest.mark.parametrize(
    ("arguments", "expected_checkpoint"),
    [
        ({}, "flux1-schnell.safetensors"),
        ({"model": "flux1-schnell"}, "flux1-schnell.safetensors"),
        ({"model": "flux1-dev.safetensors"}, "flux1-dev.safetensors"),
    ],
)
async def test_mcp_comfyui_model_preserves_workflow_default(
    mcp_env, arguments, expected_checkpoint
):
    app, client, _ = mcp_env
    settings = app.state.settings.model_copy(update={"comfyui_url": "http://127.0.0.1:8188"})
    provider = ComfyUIProvider(settings)
    provider._submit = AsyncMock(return_value="test-prompt")
    provider._await_output = AsyncMock(return_value={})
    provider._fetch_image = AsyncMock(return_value=b"test-image")
    app.state.provider_registry["comfyui"] = provider
    app.state.provider_models["comfyui"] = ["flux1-schnell", "flux1-dev.safetensors"]
    result = await client.call_tool(
        "generate_image",
        {"name": "comfy-model", "prompt": PROMPT, "provider": "comfyui", **arguments},
    )
    assert "Image generated successfully!" in result.data
    graph = provider._submit.await_args.args[0]
    loader = next(node for node in graph.values() if node["class_type"] == "UNETLoader")
    assert loader["inputs"]["unet_name"] == expected_checkpoint
    records = await repository.list_generations(app.state.db, user_id="anonymous")
    assert records[0].model == (arguments.get("model") or "flux1-schnell")
