"""Protocol and JWT isolation checks through the mounted Streamable HTTP endpoint."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from mcp.types import CLIENT_CAPABILITIES_META_KEY, PROTOCOL_VERSION_META_KEY

from image_gen.app import create_app
from image_gen.db import repository
from image_gen.mcp.server import SubjectJWTVerifier

TOOL_NAMES = {"generate_image", "list_images", "get_quota_status"}
MODERN_VERSION = "2026-07-28"
LEGACY_VERSION = "2025-03-26"
# Test-only signing material; no external issuer or credentials are used.
SIGNING_KEY = "image-gen-test-signing-key-for-transport-tests-only"


def _request(method, params=None, *, modern=True):
    params = dict(params or {})
    if modern:
        params["_meta"] = {
            PROTOCOL_VERSION_META_KEY: MODERN_VERSION,
            CLIENT_CAPABILITIES_META_KEY: {},
        }
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}


def _headers(method, *, modern=True, name=None, token=None):
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MODERN_VERSION if modern else LEGACY_VERSION,
    }
    if modern:
        headers["Mcp-Method"] = method
        if name:
            headers["Mcp-Name"] = name
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def test_modern_tools_list_without_handshake_or_session(client):
    response = await client.post(
        "/mcp", json=_request("tools/list"), headers=_headers("tools/list")
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert "mcp-session-id" not in response.headers
    assert {tool["name"] for tool in response.json()["result"]["tools"]} == TOOL_NAMES


async def test_legacy_client_can_initialize_and_list_without_session(client):
    response = await client.post(
        "/mcp",
        json=_request(
            "initialize",
            {
                "protocolVersion": LEGACY_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "legacy-test", "version": "1"},
            },
            modern=False,
        ),
        headers=_headers("initialize", modern=False),
    )
    assert response.status_code == 200, response.text
    assert "mcp-session-id" not in response.headers
    response = await client.post(
        "/mcp",
        json=_request("tools/list", modern=False),
        headers=_headers("tools/list", modern=False),
    )
    assert response.status_code == 200, response.text
    assert {tool["name"] for tool in response.json()["result"]["tools"]} == TOOL_NAMES


@pytest.fixture
async def authenticated_client(settings):
    settings = settings.model_copy(update={"auth_enabled": True})

    def test_verifier(**kwargs):
        # Exercise the real factory's issuer/audience policy with local signing
        # material instead of fetching production JWKS.
        assert kwargs.pop("jwks_uri") == f"{settings.oidc_issuer}/jwks.json"
        return SubjectJWTVerifier(public_key=SIGNING_KEY, algorithm="HS256", **kwargs)

    with (
        patch("image_gen.mcp.server.SubjectJWTVerifier", side_effect=test_verifier),
        patch("image_gen.services.gemini.genai.Client", return_value=MagicMock()),
        patch(
            "image_gen.services.gemini.GeminiProvider.list_models",
            new=AsyncMock(return_value=[settings.gemini_model]),
        ),
    ):
        app = create_app(settings)
        async with LifespanManager(app):
            for user in ("alice", "bob"):
                await repository.create_generation(
                    app.state.db,
                    user_id=user,
                    name=f"{user}-private",
                    prompt="test",
                    aspect_ratio="1:1",
                    resolution="2K",
                )
            await app.state.quota.consume_token("alice")
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                yield client, settings


def _token(settings, *, user="alice", **overrides):
    claims = {
        "iss": settings.oidc_issuer,
        "aud": settings.oidc_client_id,
        "exp": int(time.time()) + 60,
    }
    if user is not None:
        claims["sub"] = user
    claims.update(overrides)
    return jwt.encode(claims, SIGNING_KEY, algorithm="HS256")


@pytest.mark.parametrize("modern", [True, False])
async def test_verified_subject_scopes_images_and_quota(authenticated_client, modern):
    client, settings = authenticated_client
    for user, remaining in (("alice", "9.0/10"), ("bob", "10.0/10")):
        for tool in ("list_images", "get_quota_status"):
            response = await client.post(
                "/mcp",
                json=_request("tools/call", {"name": tool, "arguments": {}}, modern=modern),
                headers=_headers(
                    "tools/call", modern=modern, name=tool, token=_token(settings, user=user)
                ),
            )
            assert response.status_code == 200, response.text
            result = response.json()["result"]
            assert not result.get("isError", False), result
            text = result["content"][0]["text"]
            if tool == "list_images":
                assert f"{user}-private" in text
                assert f"{'bob' if user == 'alice' else 'alice'}-private" not in text
            else:
                assert remaining in text


@pytest.mark.parametrize("modern", [True, False])
@pytest.mark.parametrize(
    "invalid",
    [
        "missing",
        "malformed",
        "issuer",
        "audience",
        "expired",
        "subject-missing",
        "subject-empty",
        "subject-whitespace",
    ],
)
async def test_invalid_jwt_rejected_before_tool_listing(authenticated_client, modern, invalid):
    client, settings = authenticated_client
    tokens = {
        "missing": None,
        "malformed": "invalid-jwt",
        "issuer": _token(settings, iss="https://wrong-issuer.test"),
        "audience": _token(settings, aud="wrong-audience"),
        "expired": _token(settings, exp=int(time.time()) - 60),
        "subject-missing": _token(settings, user=None),
        "subject-empty": _token(settings, user=""),
        "subject-whitespace": _token(settings, user=" \t "),
    }
    response = await client.post(
        "/mcp",
        json=_request("tools/list", modern=modern),
        headers=_headers("tools/list", modern=modern, token=tokens[invalid]),
    )
    assert response.status_code == 401, response.text
    assert "WWW-Authenticate" in response.headers
