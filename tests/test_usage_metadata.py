"""Usage metadata survives provider, REST/MCP and legacy SQLite boundaries."""

import base64
from unittest.mock import AsyncMock

import httpx
import pytest
from fastmcp import Client

from image_gen.config import Settings
from image_gen.db import engine, migrations, repository
from image_gen.mcp.server import create_mcp_server
from image_gen.services.openrouter_provider import OpenRouterProvider

VALID_PROMPT = "A detailed photograph of a red fox in a snowy forest with warm morning light. " * 6

USAGE = {
    "prompt_tokens": 12,
    "completion_tokens": 0,
    "total_tokens": 12,
    "cost_details": {"upstream_inference_cost": 0.003, "nested": {"cached": None}},
}


@pytest.mark.parametrize("usage", [USAGE, {}, None, {"prompt_tokens": None}, "invalid"])
async def test_provider_captures_nullable_usage(usage):
    provider = OpenRouterProvider(Settings(openrouter_api_key="test"))
    response = {"data": [{"b64_json": base64.b64encode(b"image").decode()}], "usage": usage}
    provider._client.post = AsyncMock(return_value=httpx.Response(200, json=response))
    try:
        result = await provider.generate_image("test")
        expected = usage if isinstance(usage, dict) and usage else None
        assert result.usage == expected
    finally:
        await provider.aclose()


async def test_usage_round_trips_through_rest_and_database(client, mock_gemini_result):
    mock_gemini_result.usage = USAGE
    response = await client.post("/api/generate", json={"name": "usage", "prompt": VALID_PROMPT})
    assert response.status_code == 201
    record = response.json()
    assert record["usage"] == USAGE
    assert (await client.get(f"/api/images/{record['id']}")).json()["usage"] == USAGE
    assert (await client.get("/api/images")).json()[0]["usage"] == USAGE


async def test_usage_round_trips_through_mcp(client, mock_gemini_result):
    mock_gemini_result.usage = USAGE
    app = client._transport.app
    async with Client(create_mcp_server(app.state.settings)) as mcp:
        result = await mcp.call_tool("generate_image", {"name": "usage", "prompt": VALID_PROMPT})
    assert "Image generated successfully!" in result.data
    records = await repository.list_generations(app.state.db, user_id="anonymous")
    assert records[0].usage == USAGE


async def test_legacy_database_migrates_idempotently(tmp_path):
    db = await engine.connect(tmp_path / "legacy.db")
    try:
        await db.executescript(migrations.SCHEMA)
        await db.execute(
            "INSERT INTO generations (id, user_id, name, prompt, created_at) "
            "VALUES ('old', 'user', 'legacy', 'prompt', '2026-01-01T00:00:00+00:00')"
        )
        await db.commit()
        # A row written before the column exists remains readable with no usage.
        old = await repository.get_generation(db, "old")
        assert old.usage is None
        await migrations.run_migrations(db)
        await migrations.run_migrations(db)
        assert (await repository.get_generation(db, "old")).usage is None
        await repository.update_generation(db, "old", usage=USAGE)
        assert (await repository.get_generation(db, "old")).usage == USAGE
    finally:
        await db.close()
