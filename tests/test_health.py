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
