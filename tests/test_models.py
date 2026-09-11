"""Tests for Pydantic model behavior (image_gen.models)."""

from datetime import UTC, datetime

from image_gen.models import GenerationResponse, GenerationStatus, ProviderName
from image_gen.naming import download_filename

_CREATED = datetime(2026, 6, 30, 18, 12, 36, tzinfo=UTC)


def _response(**overrides) -> GenerationResponse:
    base = {
        "id": "01KWDCK533ACFCWV6GHD511KZJ",
        "user_id": "anonymous",
        "name": "La Belle Fleur",
        "prompt": "A field of wildflowers",
        "aspect_ratio": "1:1",
        "resolution": "2K",
        "provider": ProviderName.OPENROUTER,
        "model": "openai/gpt-image-2",
        "status": GenerationStatus.COMPLETED,
        "created_at": _CREATED,
    }
    base.update(overrides)
    return GenerationResponse(**base)


def test_download_name_matches_helper() -> None:
    rec = _response()
    assert rec.download_name == download_filename(rec.name, rec.model, rec.created_at, rec.id)


def test_download_name_serializes_into_dump() -> None:
    """The computed field appears in the serialized response (UI + API consume it)."""
    rec = _response()
    dumped = rec.model_dump()
    assert dumped["download_name"] == rec.download_name


def test_download_name_handles_none_model() -> None:
    rec = _response(model=None)
    assert rec.download_name.endswith(rec.id + ".png")
    assert "-model-" in rec.download_name


def test_cost_usd_defaults_to_none() -> None:
    rec = _response()
    assert rec.cost_usd is None


def test_cost_usd_round_trips_in_dump() -> None:
    rec = _response(cost_usd=0.0042)
    assert rec.model_dump()["cost_usd"] == 0.0042
