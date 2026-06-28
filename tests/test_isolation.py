"""Multi-tenant user-isolation regression tests (auth ENABLED).

These fail against the pre-fix endpoints — which ignored the caller and let any
authenticated user read any image — and pass once list/get/file enforce
per-user ownership. Identity is supplied per request via the ``Remote-User``
forward-auth header (Authelia/Traefik style).
"""

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from image_gen.app import create_app
from image_gen.config import Settings
from image_gen.services.provider import ProviderResult

VALID_PROMPT = (
    "A photorealistic image of a single red cube sitting on a clean white surface "
    "with soft studio lighting. The cube has slightly rounded edges and a matte finish. "
    "The background is a pure white gradient that fades gently, creating a minimal and "
    "elegant composition. Light reflects subtly off the surface beneath the cube, casting "
    "a soft shadow to the right. The overall aesthetic is clean, modern, and suitable for "
    "product photography or design reference material."
)

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
    b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
async def auth_client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    """Auth-enabled client; per-request identity comes from Remote-User headers."""
    settings = Settings(
        google_api_key="test-key",
        auth_enabled=True,
        data_dir=tmp_path / "data",
    )
    result = ProviderResult(image_data=PNG_BYTES, mime_type="image/png")
    with patch("image_gen.services.gemini.genai.Client", return_value=MagicMock()):
        app = create_app(settings)
        async with LifespanManager(app):
            app.state.provider_registry["gemini"].generate_image = AsyncMock(return_value=result)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client


def _headers(user: str) -> dict[str, str]:
    return {
        "Remote-User": user,
        "Remote-Name": user,
        "Remote-Email": f"{user}@example.com",
    }


async def _create_as(client: AsyncClient, user: str) -> dict:
    resp = await client.post(
        "/api/generate",
        json={"name": f"{user}-image", "prompt": VALID_PROMPT},
        headers=_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_list_only_returns_callers_own_images(auth_client: AsyncClient) -> None:
    alice_img = await _create_as(auth_client, "alice")

    # Bob lists — sees nothing of Alice's.
    bob_list = await auth_client.get("/api/images", headers=_headers("bob"))
    assert bob_list.status_code == 200
    assert bob_list.json() == []

    # Alice lists — sees only her own.
    alice_list = await auth_client.get("/api/images", headers=_headers("alice"))
    assert alice_list.status_code == 200
    assert [img["id"] for img in alice_list.json()] == [alice_img["id"]]


async def test_cannot_read_another_users_metadata(auth_client: AsyncClient) -> None:
    alice_img = await _create_as(auth_client, "alice")

    bob_get = await auth_client.get(f"/api/images/{alice_img['id']}", headers=_headers("bob"))
    assert bob_get.status_code == 404

    alice_get = await auth_client.get(f"/api/images/{alice_img['id']}", headers=_headers("alice"))
    assert alice_get.status_code == 200
    assert alice_get.json()["id"] == alice_img["id"]


async def test_cannot_download_another_users_file(auth_client: AsyncClient) -> None:
    alice_img = await _create_as(auth_client, "alice")

    bob_file = await auth_client.get(f"/api/images/{alice_img['id']}/file", headers=_headers("bob"))
    assert bob_file.status_code == 404

    alice_file = await auth_client.get(
        f"/api/images/{alice_img['id']}/file", headers=_headers("alice")
    )
    assert alice_file.status_code == 200
    assert alice_file.headers["content-type"] == "image/png"
    assert len(alice_file.content) > 0


async def test_unowned_and_missing_return_identical_404(auth_client: AsyncClient) -> None:
    """A non-owner and a non-existent id must be indistinguishable (no existence leak)."""
    alice_img = await _create_as(auth_client, "alice")

    unowned = await auth_client.get(f"/api/images/{alice_img['id']}", headers=_headers("bob"))
    missing = await auth_client.get(
        "/api/images/01HZXDOESNOTEXIST00000000", headers=_headers("bob")
    )

    assert unowned.status_code == missing.status_code == 404
    assert unowned.json() == missing.json()
