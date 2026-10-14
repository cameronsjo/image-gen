"""Verify subjectless-JWT rejection using test tokens and temporary data.

Run with ``uv run --locked python scripts/probe-mcp-subject.py``. This diagnostic
asserts the approved 401 rejection policy. It makes no calls to a real issuer
or image provider.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

# The probe deliberately reuses the mounted-transport test harness.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_mcp_transport import (
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
            for subject, modern in (
                (subject, modern) for subject in (None, "", " \t ") for modern in (True, False)
            ):
                token = _token(configured, user=subject)
                response = await client.post(
                    "/mcp",
                    json=_request(
                        "tools/call", {"name": "list_images", "arguments": {}}, modern=modern
                    ),
                    headers=_headers("tools/call", modern=modern, name="list_images", token=token),
                )
                observation = {
                    "modern": modern,
                    "subject": subject,
                    "status": response.status_code,
                    "anonymous_record_visible": "anonymous-private" in response.text,
                }
                observed.append(observation)
                print(observation, flush=True)
    assert len(observed) == 6 and all(
        item["status"] == 401 and not item["anonymous_record_visible"] for item in observed
    ), "Missing or blank JWT subjects must be rejected before shared anonymous access"


if __name__ == "__main__":
    asyncio.run(probe())
