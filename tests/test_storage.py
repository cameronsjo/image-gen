"""Tests for local image storage and path containment.

The containment checks (a traversal id must not escape the images directory)
are the security-critical part — they fail against the pre-fix StorageService
that joined the raw id onto the storage dir without resolving/validating it.
"""

from pathlib import Path

import pytest

from image_gen.config import Settings
from image_gen.exceptions import StorageError
from image_gen.services.storage import StorageService

# A minimal valid 1x1 PNG.
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
    b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _storage(tmp_path: Path) -> StorageService:
    settings = Settings(
        google_api_key="test-key",
        auth_enabled=False,
        data_dir=tmp_path / "data",
    )
    return StorageService(settings)


async def test_save_and_read_round_trip(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    image_id = "01HZXVALIDULID0000000000"

    saved_path = await storage.save_image(PNG_BYTES, image_id)

    assert saved_path.exists()
    assert storage.image_exists(image_id) is True
    assert storage.get_image_path(image_id) == saved_path
    assert saved_path.read_bytes() == PNG_BYTES


def test_image_exists_false_for_unknown_id(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    assert storage.image_exists("01HZXNOTSAVED00000000000") is False


def test_get_image_path_stays_within_images_dir(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    images_dir = (tmp_path / "data" / "images").resolve()
    path = storage.get_image_path("01HZXVALIDULID0000000000")
    # The resolved path must be contained by the images directory.
    assert path.resolve().is_relative_to(images_dir)


@pytest.mark.parametrize(
    "evil_id",
    [
        "../../etc/passwd",
        "../../../tmp/escape",
        "/etc/passwd",
        "subdir/../../escape",
    ],
)
def test_get_image_path_rejects_traversal(tmp_path: Path, evil_id: str) -> None:
    storage = _storage(tmp_path)
    with pytest.raises(StorageError):
        storage.get_image_path(evil_id)


def test_image_exists_rejects_traversal(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    # image_exists routes through the contained path, so a traversal id raises
    # rather than silently probing arbitrary filesystem locations.
    with pytest.raises(StorageError):
        storage.image_exists("../../etc/passwd")
