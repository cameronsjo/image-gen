"""Tests for download filename construction (image_gen.naming)."""

from datetime import UTC, datetime

from image_gen.naming import download_filename, slug

_CREATED = datetime(2026, 6, 30, 18, 12, 36, tzinfo=UTC)
_ULID = "01KWDCK533ACFCWV6GHD511KZJ"


# ── slug ─────────────────────────────────────────────────────────────────────


def test_slug_lowercases_and_hyphenates() -> None:
    assert slug("La Belle Fleur", 40) == "la-belle-fleur"


def test_slug_strips_path_traversal_and_separators() -> None:
    """Slashes and dot-runs collapse to hyphens — no path escape survives."""
    out = slug("../../etc/passwd", 40)
    assert "/" not in out
    assert ".." not in out
    assert out == "etc-passwd"


def test_slug_strips_quotes_newlines_semicolons() -> None:
    """Header-injection characters are removed (Content-Disposition safety)."""
    out = slug('evil"; drop\ntable', 40)
    for bad in ('"', ";", "\n"):
        assert bad not in out


def test_slug_neutralizes_unicode() -> None:
    """Non-ASCII letters are not in ``a-z0-9`` and collapse away."""
    out = slug("café déjà", 40)
    assert out == "caf-d-j"


def test_slug_truncates_without_trailing_hyphen() -> None:
    out = slug("aaaa bbbb cccc dddd", 9)
    assert len(out) <= 9
    assert not out.endswith("-")


# ── download_filename ────────────────────────────────────────────────────────


def test_download_filename_shape() -> None:
    out = download_filename("La Belle Fleur Sauvage", "openai/gpt-image-2", _CREATED, _ULID)
    assert out == ("la-belle-fleur-sauvage-openai-gpt-image-2-20260630-181236-" + _ULID + ".png")


def test_download_filename_ends_with_png() -> None:
    out = download_filename("x", "m", _CREATED, _ULID)
    assert out.endswith(".png")


def test_download_filename_handles_none_model() -> None:
    out = download_filename("sunset", None, _CREATED, _ULID)
    assert "-model-" in out
    assert out.endswith(_ULID + ".png")


def test_download_filename_uniqueness_from_ulid_tail() -> None:
    """Same name/model/timestamp but distinct ULIDs → distinct filenames."""
    a = download_filename("dup", "m", _CREATED, "01AAAAAAAAAAAAAAAAAAAAAAAA")
    b = download_filename("dup", "m", _CREATED, "01BBBBBBBBBBBBBBBBBBBBBBBB")
    assert a != b


def test_download_filename_empty_name_falls_back() -> None:
    """A name that slugs to empty still yields a usable filename."""
    out = download_filename("///", None, _CREATED, _ULID)
    assert out.startswith("image-model-")
