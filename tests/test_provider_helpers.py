"""Tests for provider helper functions and discovery edge cases not covered elsewhere.

Covers:
- ``models_with_default`` (pure function): deduplication, empty discovery, order
- ``discover_models``: empty registry
- Generate endpoint: empty ``provider_models`` entry (degraded discovery) accepts any model
"""

from unittest.mock import AsyncMock

from httpx import AsyncClient

from image_gen.services.provider import models_with_default
from image_gen.services.registry import discover_models

# Long enough to pass the prompt validator; same pattern as test_generate.py.
_VALID_PROMPT = (
    "A photorealistic image of a single red cube sitting on a clean white surface "
    "with soft studio lighting. The cube has slightly rounded edges and a matte finish. "
    "The background is a pure white gradient that fades gently, creating a minimal and "
    "elegant composition. Light reflects subtly off the surface beneath the cube, casting "
    "a soft shadow to the right. The overall aesthetic is clean, modern, and suitable for "
    "product photography or design reference material."
)


# ---------------------------------------------------------------------------
# models_with_default — pure function, no I/O
# ---------------------------------------------------------------------------


class TestModelsWithDefault:
    def test_default_prepended_when_absent_from_discovered(self):
        """Default leads the result even when discovery never surfaced it."""
        result = models_with_default("x", ["a", "b"])
        assert result == ["x", "a", "b"]

    def test_default_deduplicated_when_discovery_surfaces_it(self):
        """Default that appears in the discovered list is not listed twice."""
        result = models_with_default("x", ["x", "a", "b"])
        assert result.count("x") == 1
        assert result[0] == "x"
        assert result == ["x", "a", "b"]

    def test_empty_discovered_degrades_to_default_only(self):
        """Empty discovery (failure path) degrades gracefully to [default]."""
        result = models_with_default("my-model", [])
        assert result == ["my-model"]

    def test_discovered_order_is_preserved_after_default(self):
        """Models after the default keep their original discovery order."""
        result = models_with_default("a", ["b", "c", "d"])
        assert result == ["a", "b", "c", "d"]

    def test_multiple_default_duplicates_in_discovered_collapse_to_one(self):
        """Several copies of the default in discovered still yield a single entry."""
        result = models_with_default("x", ["x", "a", "x", "b"])
        assert result.count("x") == 1
        assert result[0] == "x"
        # Non-default models appear in their original relative order
        assert result.index("a") < result.index("b")

    def test_default_at_tail_of_discovered_moves_to_front(self):
        """Default sitting at the end of the discovered list still leads."""
        result = models_with_default("z", ["a", "b", "z"])
        assert result[0] == "z"
        assert result.count("z") == 1
        assert "a" in result
        assert "b" in result


# ---------------------------------------------------------------------------
# discover_models — empty-registry edge case
# ---------------------------------------------------------------------------


async def test_discover_models_empty_registry_returns_empty_dict():
    """An empty provider registry produces an empty discovery mapping."""
    result = await discover_models({}, timeout=5.0)
    assert result == {}


# ---------------------------------------------------------------------------
# Generate endpoint — degraded-discovery path (empty available_models)
# ---------------------------------------------------------------------------


async def test_generate_accepts_explicit_model_when_discovery_degraded(
    client: AsyncClient,
) -> None:
    """When ``provider_models`` holds an empty list for a provider (total discovery
    failure), the endpoint trusts the caller and accepts any explicit model name
    rather than returning 422.

    The code path under test:
        available_models = request.app.state.provider_models.get(provider_name, [])
        if body.model and available_models and body.model not in available_models:
            raise HTTPException(422, ...)  # ← NOT reached when available_models is []
    """
    from image_gen.services.provider import ProviderResult

    app = client._transport.app  # type: ignore[attr-defined]
    original_models = app.state.provider_models.get("gemini", [])

    # Simulate total discovery failure: discovery produced nothing for gemini.
    app.state.provider_models["gemini"] = []

    # Also make the provider return a successful result for the unknown model.
    fake_png = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
        b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
        b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    app.state.provider_registry["gemini"].generate_image = AsyncMock(
        return_value=ProviderResult(image_data=fake_png, mime_type="image/png")
    )

    try:
        resp = await client.post(
            "/api/generate",
            json={
                "name": "degraded-discovery",
                "prompt": _VALID_PROMPT,
                "model": "gemini-unknown-future-model",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["model"] == "gemini-unknown-future-model"
    finally:
        app.state.provider_models["gemini"] = original_models
