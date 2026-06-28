"""Tests for app lifespan teardown — error-tolerant provider shutdown.

# Test Plan
#
# lifespan (Classification: State machine / I/O boundary)
#   [x] Behavioral: one provider's aclose raising does not prevent others from being closed
#   [x] Behavioral: lifespan teardown does not propagate provider aclose exceptions
#   [x] Behavioral: all providers are attempted even when an earlier one raises
"""

from unittest.mock import AsyncMock, MagicMock, patch

from asgi_lifespan import LifespanManager

from image_gen.app import create_app
from image_gen.config import Settings


def _settings(tmp_path, **kwargs) -> Settings:
    return Settings(
        google_api_key="test-key",
        auth_enabled=False,
        data_dir=tmp_path / "data",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Error-tolerant provider teardown
# ---------------------------------------------------------------------------


async def test_provider_aclose_error_does_not_strand_other_providers(tmp_path):
    """One provider's aclose raising must not strand the remaining providers.

    The lifespan loop wraps each close in a try/except; verifying that a
    subsequent provider's aclose is still called proves the loop continues
    past the failure.
    """
    settings = _settings(tmp_path)
    with patch("image_gen.services.gemini.genai.Client", return_value=MagicMock()):
        app = create_app(settings)
        async with LifespanManager(app):
            # Replace the provider registry with two controlled fakes.
            # Insertion order is preserved (Python 3.7+): failing runs first.
            failing = AsyncMock()
            failing.aclose = AsyncMock(side_effect=RuntimeError("socket died on close"))
            safe = AsyncMock()
            safe.aclose = AsyncMock()
            app.state.provider_registry.clear()
            app.state.provider_registry["failing"] = failing
            app.state.provider_registry["safe"] = safe

    # Assertions run after LifespanManager.__aexit__, so after teardown.
    failing.aclose.assert_awaited_once()
    safe.aclose.assert_awaited_once()


async def test_lifespan_teardown_does_not_propagate_provider_aclose_exception(tmp_path):
    """Exceptions from provider aclose must be swallowed (logged as warnings),
    not re-raised through the lifespan — otherwise a single bad close would
    prevent the DB handle from being released."""
    settings = _settings(tmp_path)
    with patch("image_gen.services.gemini.genai.Client", return_value=MagicMock()):
        app = create_app(settings)
        # If an aclose exception propagated, LifespanManager would raise here.
        async with LifespanManager(app):
            loud_provider = AsyncMock()
            loud_provider.aclose = AsyncMock(side_effect=RuntimeError("boom"))
            app.state.provider_registry.clear()
            app.state.provider_registry["loud"] = loud_provider

    # Reaching this line proves no exception escaped the lifespan context.


async def test_all_providers_attempted_when_multiple_raise(tmp_path):
    """Every provider in the registry must be attempted even when all of them
    fail: the loop must not short-circuit on the first exception."""
    settings = _settings(tmp_path)
    with patch("image_gen.services.gemini.genai.Client", return_value=MagicMock()):
        app = create_app(settings)
        async with LifespanManager(app):
            providers = {}
            for name in ("alpha", "beta", "gamma"):
                p = AsyncMock()
                p.aclose = AsyncMock(side_effect=RuntimeError(f"{name} failed"))
                providers[name] = p
            app.state.provider_registry.clear()
            app.state.provider_registry.update(providers)

    for name, provider in providers.items():
        provider.aclose.assert_awaited_once(), f"provider {name!r} was skipped"
