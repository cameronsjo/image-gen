"""Tests for health and readiness endpoints."""

from httpx import AsyncClient


async def test_health_returns_ok(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_ready_returns_provider_info(client: AsyncClient) -> None:
    resp = await client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"
    assert "default_provider" in data
    assert data["default_provider"] == "gemini"
    assert "providers" in data
    assert isinstance(data["providers"], list)
    assert "gemini" in data["providers"]


async def test_ready_includes_discovered_models(client: AsyncClient) -> None:
    """/ready surfaces per-provider models so the UI dropdown can populate.

    The test gemini client is a MagicMock (discovery finds nothing), so the
    provider degrades to its configured default — which must always be present.
    """
    resp = await client.get("/ready")
    assert resp.status_code == 200
    models = resp.json()["models"]
    assert "gemini" in models
    assert models["gemini"] == ["gemini-3-pro-image-preview"]
