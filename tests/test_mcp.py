"""Tests for MCP endpoint routing."""

from httpx import AsyncClient


async def test_mcp_post_no_trailing_slash_not_redirected(client: AsyncClient) -> None:
    """POST /mcp must not return a 307 trailing-slash redirect."""
    resp = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        },
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        follow_redirects=False,
    )
    assert resp.status_code != 307, f"Got 307 redirect to {resp.headers.get('location')}"
    assert resp.status_code == 200


async def test_mcp_post_with_trailing_slash_works(client: AsyncClient) -> None:
    """POST /mcp/ should also work (canonical mount path)."""
    resp = await client.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        },
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        follow_redirects=False,
    )
    assert resp.status_code != 307
    assert resp.status_code == 200
