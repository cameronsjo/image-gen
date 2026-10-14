"""Reproduce the held subjectless-JWT decision using test tokens and temporary data.

Run with ``uv run --locked python scripts/probe-mcp-subject.py``. This diagnostic
intentionally fails until Cameron approves and Codex implements the proposed
401 rejection policy. It makes no calls to a real issuer or image provider.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

import jwt

# The probe deliberately reuses the mounted-transport test harness.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_mcp_transport import (
    SIGNING_KEY,
    _headers,
    _request,
    _token,
    authenticated_client,
)

from image_gen.config import Settings
from image_gen.db import repository


async def probe() -> None:
    observed = []
    with tempfile.TemporaryDirectory(prefix="image-gen-subject-probe-") as tmp:
        settings = Settings(google_api_key="test-only", auth_enabled=False, data_dir=Path(tmp))
        async for client, configured in authenticated_client.__wrapped__(settings):
            await repository.create_generation(
                client._transport.app.state.db,
                user_id="anonymous",
                name="anonymous-private",
                prompt="test",
                aspect_ratio="1:1",
                resolution="2K",
            )
            claims = jwt.decode(
                _token(configured),
                SIGNING_KEY,
                algorithms=["HS256"],
                audience=configured.oidc_client_id,
            )
            claims.pop("sub")
            token = jwt.encode(claims, SIGNING_KEY, algorithm="HS256")
            for modern in (True, False):
                response = await client.post(
                    "/mcp",
                    json=_request(
                        "tools/call", {"name": "list_images", "arguments": {}}, modern=modern
                    ),
                    headers=_headers("tools/call", modern=modern, name="list_images", token=token),
                )
                observation = {
                    "modern": modern,
                    "status": response.status_code,
                    "anonymous_record_visible": "anonymous-private" in response.text,
                }
                observed.append(observation)
                print(observation, flush=True)
    assert all(item["status"] == 401 for item in observed), (
        "Subjectless JWTs reach shared anonymous records over both protocol eras"
    )


if __name__ == "__main__":
    asyncio.run(probe())
