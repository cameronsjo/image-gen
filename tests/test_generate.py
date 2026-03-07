"""Tests for the image generation endpoint."""

from unittest.mock import AsyncMock

from httpx import AsyncClient

VALID_PROMPT = (
    "A photorealistic image of a single red cube sitting on a clean white surface "
    "with soft studio lighting. The cube has slightly rounded edges and a matte finish. "
    "The background is a pure white gradient that fades gently, creating a minimal and "
    "elegant composition. Light reflects subtly off the surface beneath the cube, casting "
    "a soft shadow to the right. The overall aesthetic is clean, modern, and suitable for "
    "product photography or design reference material."
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


async def test_generate_handles_gemini_failure(client: AsyncClient) -> None:
    # Access the app through the transport to patch the live instance
    app = client._transport.app  # type: ignore[attr-defined]
    app.state.gemini.generate_image = AsyncMock(side_effect=RuntimeError("Gemini exploded"))
    resp = await client.post(
        "/api/generate",
        json={"name": "fail-test", "prompt": VALID_PROMPT},
    )
    assert resp.status_code == 500
    assert "Gemini exploded" in resp.json()["detail"]["error"]
