"""Real HTTPX streaming transport exercises bounded reads and resource closure."""

from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import ValidationError

from image_gen.config import Settings
from image_gen.exceptions import ProviderError
from image_gen.services.comfyui_provider import ComfyUIProvider


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.reads = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    async def aclose(self):
        self.closed = True


@asynccontextmanager
async def response(chunks, headers=None, status=200, limit=8):
    stream = Chunks(chunks)
    provider = ComfyUIProvider(
        Settings(comfyui_url="http://127.0.0.1:8188", comfyui_max_image_bytes=limit)
    )
    await provider._client.aclose()

    def handler(request):
        assert request.url.path == "/view"
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(status, headers=headers, stream=stream)

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        yield provider, stream
    finally:
        await provider.aclose()


@pytest.mark.parametrize("headers", [{}, {"Content-Length": "1"}, {"Content-Length": "invalid"}])
async def test_actual_stream_limit_rejects_oversize(headers):
    async with response([b"abcd"] * 10, headers=headers) as (provider, stream):
        with pytest.raises(ProviderError, match="response-size limit"):
            await provider._fetch_image({"filename": "test.png"})
        assert stream.closed
        assert stream.reads < 10


@pytest.mark.parametrize("payload", [[], [b"1234"], [b"1234", b"5678"]])
async def test_small_and_exact_limit_payloads_work(payload):
    async with response(payload) as (provider, stream):
        assert await provider._fetch_image({"filename": "test.png"}) == b"".join(payload)
        assert stream.closed


async def test_declared_oversize_is_rejected_without_read():
    async with response([b"x"], headers={"Content-Length": "999"}) as (provider, stream):
        with pytest.raises(ProviderError, match="response-size limit"):
            await provider._fetch_image({"filename": "test.png"})
        assert stream.reads == 0
        assert stream.closed


async def test_limit_is_configurable():
    async with response([b"123456789"], limit=9) as (provider, _):
        assert await provider._fetch_image({"filename": "test.png"}) == b"123456789"


@pytest.mark.parametrize("status", [400, 404, 500])
async def test_error_response_is_closed_without_buffering(status):
    async with response([b"large-error-body"] * 10, status=status) as (provider, stream):
        with pytest.raises(ProviderError, match=f"HTTP {status}"):
            await provider._fetch_image({"filename": "test.png"})
        assert stream.reads == 0
        assert stream.closed


async def test_compressed_response_rejected_before_expansion():
    async with response([b"compressed"], headers={"Content-Encoding": "gzip"}) as (
        provider,
        stream,
    ):
        with pytest.raises(ProviderError, match="Content-Encoding"):
            await provider._fetch_image({"filename": "test.png"})
        assert stream.reads == 0
        assert stream.closed


@pytest.mark.parametrize("limit", [0, -1])
def test_nonpositive_limits_rejected(limit):
    with pytest.raises(ValidationError):
        Settings(comfyui_max_image_bytes=limit)
