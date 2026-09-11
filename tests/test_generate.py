"""Tests for the image generation endpoint."""

from unittest.mock import AsyncMock

from httpx import AsyncClient

from image_gen.services.provider import ProviderResult

VALID_PROMPT = (
    "A photorealistic image of a single red cube sitting on a clean white surface "
    "with soft studio lighting. The cube has slightly rounded edges and a matte finish. "
    "The background is a pure white gradient that fades gently, creating a minimal and "
    "elegant composition. Light reflects subtly off the surface beneath the cube, casting "
    "a soft shadow to the right. The overall aesthetic is clean, modern, and suitable for "
    "product photography or design reference material."
)

_FAKE_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
    b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def test_generate_creates_image(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/generate",
        json={"name": "test-cube", "prompt": VALID_PROMPT},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "completed"
    assert data["name"] == "test-cube"
    assert data["user_id"] == "anonymous"
    assert data["file_size"] is not None
    assert data["file_size"] > 0
    assert data["provider"] == "gemini"


async def test_generate_includes_provider_in_response(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/generate",
        json={"name": "with-provider", "prompt": VALID_PROMPT, "provider": "gemini"},
    )
    assert resp.status_code == 201
    assert resp.json()["provider"] == "gemini"


async def test_generate_unknown_provider_returns_422(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/generate",
        json={"name": "bad-provider", "prompt": VALID_PROMPT, "provider": "unknown"},
    )
    assert resp.status_code == 422


async def test_generate_unconfigured_provider_returns_422(client: AsyncClient) -> None:
    """openai / openrouter are not in the test registry (no API keys) → 422."""
    resp = await client.post(
        "/api/generate",
        json={"name": "no-openai", "prompt": VALID_PROMPT, "provider": "openai"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "not configured" in detail["error"]
    assert "available_providers" in detail


async def test_generate_per_request_provider_selection(client: AsyncClient) -> None:
    """A mock openai provider in the registry is selected correctly, and a cost
    reported by the provider is captured and echoed in the response."""
    app = client._transport.app  # type: ignore[attr-defined]
    fake_result = ProviderResult(image_data=_FAKE_PNG, mime_type="image/png", cost_usd=0.0042)
    mock_openai = AsyncMock(return_value=fake_result)

    # Inject a mock openai provider into the registry
    from unittest.mock import MagicMock

    openai_provider = MagicMock()
    openai_provider.name = "openai"
    openai_provider.model_name = "openai/gpt-image-2"
    openai_provider.generate_image = mock_openai
    app.state.provider_registry["openai"] = openai_provider

    resp = await client.post(
        "/api/generate",
        json={"name": "openai-test", "prompt": VALID_PROMPT, "provider": "openai"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["provider"] == "openai"
    # The provider-reported cost round-trips through update_generation → the response.
    assert body["cost_usd"] == 0.0042
    # The descriptive download name is serialized for the UI / Content-Disposition.
    assert body["download_name"].endswith(body["id"] + ".png")
    mock_openai.assert_awaited_once()

    # Cleanup
    del app.state.provider_registry["openai"]


async def test_generate_cost_usd_none_when_provider_omits(client: AsyncClient) -> None:
    """The default gemini mock reports no cost → cost_usd is null in the response."""
    resp = await client.post(
        "/api/generate",
        json={"name": "no-cost", "prompt": VALID_PROMPT},
    )
    assert resp.status_code == 201
    assert resp.json()["cost_usd"] is None


async def test_generate_defaults_model_to_provider_default(client: AsyncClient) -> None:
    """Omitting model uses the provider default — persisted and echoed back.

    The response is re-read from the DB (get_generation), so the echoed model
    also proves the value round-tripped through the new column.
    """
    resp = await client.post(
        "/api/generate",
        json={"name": "default-model", "prompt": VALID_PROMPT},
    )
    assert resp.status_code == 201
    assert resp.json()["model"] == "gemini-3-pro-image-preview"


async def test_generate_echoes_explicit_model(client: AsyncClient) -> None:
    """A model in the provider's discovered list is accepted and echoed."""
    resp = await client.post(
        "/api/generate",
        json={
            "name": "explicit-model",
            "prompt": VALID_PROMPT,
            "model": "gemini-3-pro-image-preview",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["model"] == "gemini-3-pro-image-preview"


async def test_generate_unknown_model_returns_422(client: AsyncClient) -> None:
    """A model absent from the provider's non-empty list → 422 + available_models."""
    resp = await client.post(
        "/api/generate",
        json={"name": "bad-model", "prompt": VALID_PROMPT, "model": "made-up-model-xyz"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "available_models" in detail
    assert "gemini-3-pro-image-preview" in detail["available_models"]


async def test_generate_rejects_short_prompt(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/generate",
        json={"name": "bad", "prompt": "too short"},
    )
    assert resp.status_code == 422
    errors = resp.json()["detail"]["validation_errors"]
    assert any("too short" in e.lower() for e in errors)


async def test_generate_rejects_invalid_aspect_ratio(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/generate",
        json={"name": "bad", "prompt": VALID_PROMPT, "aspect_ratio": "7:3"},
    )
    assert resp.status_code == 422


async def test_generate_rejects_invalid_resolution(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/generate",
        json={"name": "bad", "prompt": VALID_PROMPT, "resolution": "8K"},
    )
    assert resp.status_code == 422


async def test_generate_handles_provider_failure(client: AsyncClient) -> None:
    app = client._transport.app  # type: ignore[attr-defined]
    app.state.provider_registry["gemini"].generate_image = AsyncMock(
        side_effect=RuntimeError("Provider exploded")
    )
    resp = await client.post(
        "/api/generate",
        json={"name": "fail-test", "prompt": VALID_PROMPT},
    )
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    # The raw exception text must NOT leak to the client...
    assert "Provider exploded" not in str(detail)
    assert "unexpected error" in detail["error"].lower()
    # ...but the caller gets the generation id to correlate with server-side logs.
    assert detail["generation_id"]
