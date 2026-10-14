"""Start image-gen and list its tools over real HTTP and stdio, without paid API calls.

Run with ``uv run --locked python scripts/smoke-mcp.py``. Provider discovery is
stubbed; the application, database, SDK, and transports are real.
"""

import argparse
import asyncio
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import structlog
import uvicorn
from asgi_lifespan import LifespanManager
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from image_gen.app import create_app
from image_gen.config import Settings
from image_gen.mcp.server import create_mcp_server

TOOL_NAMES = {"generate_image", "list_images", "get_quota_status"}
ROOT = Path(__file__).resolve().parents[1]


async def serve(args: argparse.Namespace) -> None:
    settings = Settings(
        google_api_key="smoke-test-no-provider-requests",
        openai_api_key=None,
        openrouter_api_key=None,
        comfyui_url=None,
        default_provider="gemini",
        auth_enabled=False,
        data_dir=Path(args.data_dir),
    )
    with (
        patch("image_gen.services.gemini.genai.Client", return_value=MagicMock()),
        patch(
            "image_gen.services.gemini.GeminiProvider.list_models",
            new=AsyncMock(return_value=[settings.gemini_model]),
        ),
    ):
        app = create_app(settings)
        # Keep application startup logs off the stdio protocol wire.
        structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))
        if args.serve_stdio:
            async with LifespanManager(app):
                await create_mcp_server(settings).run_async(transport="stdio", show_banner=False)
        else:
            server = uvicorn.Server(uvicorn.Config(app, fd=args.fd, log_level="warning"))
            await server.serve()


async def list_tools(transport, mode: str, label: str) -> None:
    async with Client(transport, mode=mode, timeout=30, init_timeout=60) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert names == TOOL_NAMES, names
        if mode == "2026-07-28":
            assert client.protocol_version == mode, client.protocol_version
        if label == "HTTP":
            assert client.transport.get_session_id() is None
        result = await client.call_tool("list_images", {})
        assert result.data == "No images found.", result
        print(f"{label} {client.protocol_version}: listed {sorted(names)}; list_images passed")


async def smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="image-gen-mcp-smoke-") as tmp:
        with (
            socket.socket() as listener,
            (Path(tmp) / "http.log").open("w+") as server_log,
        ):
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--serve-http",
                    "--fd",
                    str(listener.fileno()),
                    "--data-dir",
                    str(Path(tmp) / "http-data"),
                ],
                cwd=ROOT,
                pass_fds=(listener.fileno(),),
                stdout=server_log,
                stderr=subprocess.STDOUT,
            )
            try:
                url = f"http://127.0.0.1:{port}"
                async with httpx.AsyncClient(trust_env=False, timeout=2) as http:
                    async with asyncio.timeout(90):
                        while True:
                            if process.poll() is not None:
                                server_log.seek(0)
                                raise RuntimeError(server_log.read())
                            try:
                                response = await http.get(f"{url}/health")
                                response.raise_for_status()
                                break
                            except httpx.TransportError:
                                await asyncio.sleep(0.25)
                for mode in ("2026-07-28", "legacy"):
                    await list_tools(f"{url}/mcp", mode, "HTTP")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        for mode in ("2026-07-28", "legacy"):
            transport = StdioTransport(
                command=sys.executable,
                args=[str(Path(__file__).resolve()), "--serve-stdio", "--data-dir", tmp],
                cwd=str(ROOT),
            )
            await list_tools(transport, mode, "stdio")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve-http", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--serve-stdio", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--fd", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--data-dir", help=argparse.SUPPRESS)
    args = parser.parse_args()
    asyncio.run(serve(args) if args.serve_http or args.serve_stdio else smoke())


if __name__ == "__main__":
    main()
