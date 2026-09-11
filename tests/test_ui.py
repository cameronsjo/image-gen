"""Tests for the static web UI mount.

These guard the mount wiring (StaticFiles + root redirect), not the page
content — the assertions stay content-agnostic so they survive a rewrite of
``static/index.html``.
"""

from httpx import AsyncClient


async def test_ui_serves_index_html(client: AsyncClient) -> None:
    resp = await client.get("/ui/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "<html" in resp.text.lower()


async def test_root_redirects_to_ui(client: AsyncClient) -> None:
    # The test client does not follow redirects, so we see the 307 directly.
    resp = await client.get("/")
    assert resp.status_code == 307
    assert resp.headers["location"] == "/ui/"


async def test_vendored_artificer_css_is_served(client: AsyncClient) -> None:
    # The page links the vendored npm design system (@cameronsjo/artificer);
    # guard that the asset ships and the mount serves it with a CSS type.
    resp = await client.get("/ui/vendor/artificer/artificer.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]
