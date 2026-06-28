"""MCP per-user scoping tests.

Covers two things:
  1. ``_resolve_user`` pulls identity from the access-token subject and falls
     back to ``"anonymous"`` — never the old hardcoded ``"mcp-user"``.
  2. The ``list_images`` and ``get_quota_status`` tools scope to the resolved
     user, so a caller only sees their own images and their own quota.

Tools are driven through FastMCP's in-memory client; identity is injected by
patching ``_resolve_user`` (the access-token plumbing has no real token in a
unit test, so we control the resolved id directly).
"""

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from asgi_lifespan import LifespanManager
from fastmcp import Client, FastMCP

from image_gen.app import create_app
from image_gen.config import Settings
from image_gen.db import repository
from image_gen.mcp.server import create_mcp_server
from image_gen.mcp.tools import _resolve_user

RESOLVE_TARGET = "image_gen.mcp.tools._resolve_user"


# --- _resolve_user unit tests -------------------------------------------------


def test_resolve_user_reads_token_subject() -> None:
    ctx = SimpleNamespace(
        request_context=SimpleNamespace(access_token=SimpleNamespace(sub="carol"))
    )
    assert _resolve_user(ctx) == "carol"


def test_resolve_user_falls_back_to_anonymous() -> None:
    assert _resolve_user(None) == "anonymous"
    no_token = SimpleNamespace(request_context=SimpleNamespace(access_token=None))
    assert _resolve_user(no_token) == "anonymous"


def test_resolve_user_never_returns_hardcoded_mcp_user() -> None:
    ctx = SimpleNamespace(request_context=SimpleNamespace(access_token=SimpleNamespace(sub="dave")))
    assert _resolve_user(ctx) == "dave"
    assert _resolve_user(ctx) != "mcp-user"


# --- per-user scoping via the in-memory MCP client ----------------------------


def _text(result: object) -> str:
    """Extract the tool's string return from a CallToolResult."""
    data = getattr(result, "data", None)
    if isinstance(data, str):
        return data
    content = getattr(result, "content", None)
    if content:
        return content[0].text  # type: ignore[no-any-return]
    return str(result)


@pytest.fixture
async def mcp_env(tmp_path: Path) -> AsyncIterator[tuple[object, FastMCP]]:
    """A live app (state wired, app_ref set) plus a fresh MCP server to drive."""
    settings = Settings(
        google_api_key="test-key",
        auth_enabled=False,
        data_dir=tmp_path / "data",
    )
    with patch("image_gen.services.gemini.genai.Client", return_value=MagicMock()):
        app = create_app(settings)
        async with LifespanManager(app):
            # Tools read the module-global app ref that the lifespan just set.
            mcp = create_mcp_server(settings)
            yield app, mcp


async def test_list_images_scoped_to_resolved_user(mcp_env: tuple[object, FastMCP]) -> None:
    app, mcp = mcp_env
    db = app.state.db  # type: ignore[attr-defined]
    await repository.create_generation(
        db, user_id="alice", name="alice-only", prompt="p", aspect_ratio="1:1", resolution="2K"
    )
    await repository.create_generation(
        db, user_id="bob", name="bob-only", prompt="p", aspect_ratio="1:1", resolution="2K"
    )

    async with Client(mcp) as client:
        with patch(RESOLVE_TARGET, return_value="alice"):
            alice_view = _text(await client.call_tool("list_images", {}))
        with patch(RESOLVE_TARGET, return_value="bob"):
            bob_view = _text(await client.call_tool("list_images", {}))

    assert "alice-only" in alice_view
    assert "bob-only" not in alice_view
    assert "bob-only" in bob_view
    assert "alice-only" not in bob_view


async def test_quota_status_scoped_to_resolved_user(mcp_env: tuple[object, FastMCP]) -> None:
    app, mcp = mcp_env
    quota = app.state.quota  # type: ignore[attr-defined]
    # Alice spends two tokens; bob spends none.
    assert await quota.consume_token("alice") is True
    assert await quota.consume_token("alice") is True

    async with Client(mcp) as client:
        with patch(RESOLVE_TARGET, return_value="alice"):
            alice_status = _text(await client.call_tool("get_quota_status", {}))
        with patch(RESOLVE_TARGET, return_value="bob"):
            bob_status = _text(await client.call_tool("get_quota_status", {}))

    # Default capacity is 10; alice consumed 2, bob is untouched.
    assert "8.0/10" in alice_status
    assert "10.0/10" in bob_status
