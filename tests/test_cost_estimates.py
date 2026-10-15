"""Published exact combinations and separate output-estimate persistence."""

import base64
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client

from image_gen.config import Settings
from image_gen.db import engine, migrations, repository
from image_gen.mcp.server import create_mcp_server
from image_gen.services.gemini import GeminiProvider
from image_gen.services.openai_provider import OpenAIProvider
from image_gen.services.pricing import gemini_output_estimate, openai_output_estimate

PROMPT = "A detailed photograph of a red fox in a snowy forest with warm morning light. " * 6


@pytest.mark.parametrize("resolution,expected", [("1K", 0.134), ("2K", 0.134), ("4K", 0.24)])
async def test_gemini_exact_table_and_provider(resolution, expected):
    assert gemini_output_estimate("gemini-3-pro-image", resolution) == expected
    sdk = MagicMock()
    sdk.models.generate_content.return_value = SimpleNamespace(
        parts=[SimpleNamespace(inline_data=SimpleNamespace(data=b"image", mime_type="image/png"))]
    )
    with patch("image_gen.services.gemini.genai.Client", return_value=sdk):
        provider = GeminiProvider(
            Settings(google_api_key="test", gemini_model="gemini-3-pro-image")
        )
        result = await provider.generate_image(PROMPT, resolution=resolution)
    assert result.estimated_output_cost_usd == expected
    assert result.cost_usd is None
    assert sdk.models.generate_content.call_args.kwargs["model"] == "gemini-3-pro-image"


@pytest.mark.parametrize(
    "model", ["gemini-3-pro-image-preview", "gemini-3-pro-image-extra", "unknown"]
)
def test_no_gemini_model_alias_guesses(model):
    for resolution in ("1K", "2K", "4K"):
        assert gemini_output_estimate(model, resolution) is None
    assert gemini_output_estimate("gemini-3-pro-image", "8K") is None


@pytest.mark.parametrize(
    "size,values",
    [
        ("1024x1024", (0.006, 0.053, 0.211)),
        ("1024x1536", (0.005, 0.041, 0.165)),
        ("1536x1024", (0.005, 0.041, 0.165)),
    ],
)
def test_openai_exact_published_table(size, values):
    for quality, expected in zip(("low", "medium", "high"), values, strict=True):
        assert openai_output_estimate("gpt-image-2", quality, size) == expected


@pytest.mark.parametrize(
    "model,quality,size",
    [
        ("gpt-image-2", "medium", "2048x2048"),
        ("gpt-image-2", "high", "3840x2160"),
        ("gpt-image-2", "low", "auto"),
        ("gpt-image-2", "auto", "1024x1024"),
        ("gpt-image-2-2026-04-21", "low", "1024x1024"),
        ("unknown", "low", "1024x1024"),
    ],
)
def test_unknown_combinations_are_not_scaled_or_aliased(model, quality, size):
    assert openai_output_estimate(model, quality, size) is None


@pytest.mark.parametrize(
    "resolution,ratio,model,expected",
    [
        ("1K", "1:1", None, 0.006),
        ("2K", "1:1", None, None),
        ("4K", "1:1", None, None),
        ("1K", "2:3", None, None),
        ("1K", "1:1", "gpt-image-2-2026-04-21", None),
    ],
)
async def test_openai_provider_uses_actual_model_size_quality(resolution, ratio, model, expected):
    sdk = MagicMock()
    sdk.images.generate = AsyncMock(
        return_value=SimpleNamespace(
            data=[SimpleNamespace(b64_json=base64.b64encode(b"image").decode())]
        )
    )
    with patch("image_gen.services.openai_provider.AsyncOpenAI", return_value=sdk):
        provider = OpenAIProvider(Settings(openai_api_key="test"))
        result = await provider.generate_image(PROMPT, ratio, resolution, model=model)
    assert result.estimated_output_cost_usd == expected
    assert result.cost_usd is None
    assert sdk.images.generate.await_args.kwargs["model"] == (model or "gpt-image-2")


async def test_gemini_preview_and_override_remain_unknown():
    sdk = MagicMock()
    sdk.models.generate_content.return_value = SimpleNamespace(
        parts=[SimpleNamespace(inline_data=SimpleNamespace(data=b"image", mime_type="image/png"))]
    )
    with patch("image_gen.services.gemini.genai.Client", return_value=sdk):
        provider = GeminiProvider(Settings(google_api_key="test"))
        assert (await provider.generate_image(PROMPT)).estimated_output_cost_usd is None
        known = await provider.generate_image(PROMPT, model="gemini-3-pro-image")
        assert known.estimated_output_cost_usd == 0.134
        assert (
            await provider.generate_image(PROMPT, model="unknown")
        ).estimated_output_cost_usd is None


async def test_estimate_round_trip_separate_from_reported_cost(client, mock_gemini_result):
    mock_gemini_result.estimated_output_cost_usd = 0.134
    response = await client.post("/api/generate", json={"name": "estimated", "prompt": PROMPT})
    assert response.status_code == 201
    record = response.json()
    assert record["estimated_output_cost_usd"] == 0.134
    assert record["cost_usd"] is None
    fetched = (await client.get(f"/api/images/{record['id']}")).json()
    assert fetched["estimated_output_cost_usd"] == 0.134
    assert (await client.get("/api/images")).json()[0]["estimated_output_cost_usd"] == 0.134
    page = (await client.get("/ui/")).text
    # Execute the shipped renderer on the real REST record, not a label search.
    script = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {page, record} = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const renderer = page.match(/function showResult\(rec\)\{[\s\S]*?\n  \}/);
assert.ok(renderer, 'shipped result renderer must exist');
const stage = {style:{}};
const els = {
  img:{closest:()=>stage}, dim:{}, overlay:{}, meta:{},
  btnDownload:{}, btnOpen:{}
};
const context = {
  els, API:{file:id=>'/api/images/'+id+'/file'},
  clearError:()=>{}, ratioOf:()=>1, dur:()=>'', dims:()=>'', relTime:()=>'',
  escapeHtml:value=>String(value), setMode:()=>{}
};
vm.runInNewContext(renderer[0], context);
context.showResult(record);
const label = '<dt>estimated output cost (published table; excludes input/other charges)</dt>';
assert.ok(els.meta.innerHTML.includes(label+'<dd class="num">$0.134000</dd>'));
context.showResult({...record, estimated_output_cost_usd:0});
assert.ok(els.meta.innerHTML.includes(label+'<dd class="num">$0.000000</dd>'));
context.showResult({...record, estimated_output_cost_usd:null});
assert.ok(!els.meta.innerHTML.includes(label));
"""
    subprocess.run(
        ["node", "-e", script],
        input=json.dumps({"page": page, "record": record}),
        text=True,
        capture_output=True,
        check=True,
    )


async def test_unknown_estimate_is_recorded_as_null(client):
    response = await client.post("/api/generate", json={"name": "unknown", "prompt": PROMPT})
    assert response.status_code == 201
    assert response.json()["estimated_output_cost_usd"] is None
    assert response.json()["cost_usd"] is None


async def test_mcp_explicit_estimate_label_and_persistence(client, mock_gemini_result):
    mock_gemini_result.estimated_output_cost_usd = 0.134
    app = client._transport.app
    async with Client(create_mcp_server(app.state.settings)) as mcp:
        result = await mcp.call_tool("generate_image", {"name": "estimated", "prompt": PROMPT})
    assert "Estimated image output cost" in result.data
    assert "excludes input/other charges" in result.data
    assert "$0.134000" in result.data
    assert "Cost: $" not in result.data
    records = await repository.list_generations(app.state.db, user_id="anonymous")
    assert records[0].estimated_output_cost_usd == 0.134
    assert records[0].cost_usd is None


async def test_legacy_migration_keeps_estimates_unknown(tmp_path):
    db = await engine.connect(tmp_path / "legacy.db")
    try:
        await db.executescript(migrations.SCHEMA)
        await db.execute(
            "INSERT INTO generations (id,user_id,name,prompt,created_at) "
            "VALUES ('old','user','name','prompt','2026-01-01T00:00:00+00:00')"
        )
        await db.commit()
        assert (await repository.get_generation(db, "old")).estimated_output_cost_usd is None
        await migrations.run_migrations(db)
        await migrations.run_migrations(db)
        assert (await repository.get_generation(db, "old")).estimated_output_cost_usd is None
        await repository.update_generation(
            db, "old", cost_usd=0.02, estimated_output_cost_usd=0.006
        )
        record = await repository.get_generation(db, "old")
        assert record.cost_usd == 0.02
        assert record.estimated_output_cost_usd == 0.006
    finally:
        await db.close()


@pytest.mark.parametrize("estimate", [0.134, 0.0, None])
async def test_completion_log_preserves_estimate(client, mock_gemini_result, estimate):
    mock_gemini_result.estimated_output_cost_usd = estimate
    with patch("image_gen.api.generate.logger.info") as log_info:
        response = await client.post(
            "/api/generate", json={"name": "logged estimate", "prompt": PROMPT}
        )
    assert response.status_code == 201
    completed = [
        call for call in log_info.call_args_list if call.args == ("Image generation completed",)
    ]
    assert len(completed) == 1
    assert completed[0].kwargs["estimated_output_cost_usd"] == estimate
    assert completed[0].kwargs["cost_usd"] is None
