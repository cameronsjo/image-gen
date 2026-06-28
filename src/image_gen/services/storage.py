"""Local file storage for generated images."""

from pathlib import Path

import structlog

from image_gen.config import Settings
from image_gen.exceptions import StorageError

logger = structlog.get_logger()


class StorageService:
    """Saves and retrieves images from the local filesystem."""

    def __init__(self, settings: Settings) -> None:
        self._images_dir = settings.images_dir
        self._images_dir.mkdir(parents=True, exist_ok=True)
        # Resolve once — the directory is fixed for the service's lifetime.
        self._images_dir_resolved = self._images_dir.resolve()
        logger.info("Storage initialized", images_dir=str(self._images_dir))

    async def save_image(self, image_data: bytes, image_id: str) -> Path:
        """Save image bytes to disk and return the file path."""
        file_path = self.get_image_path(image_id)
        file_path.write_bytes(image_data)
        logger.info(
            "Image saved",
            image_id=image_id,
            file_path=str(file_path),
            file_size=len(image_data),
        )
        return file_path

    def get_image_path(self, image_id: str) -> Path:
        """Return the contained path for an image ID.

        Resolves the candidate path and verifies it stays inside the images
        directory, defeating path-traversal ids such as ``../../etc/passwd``.
        Raises :class:`StorageError` if the id escapes containment.
        """
        images_dir = self._images_dir_resolved
        candidate = (images_dir / f"{image_id}.png").resolve()
        try:
            candidate.relative_to(images_dir)
        except ValueError as exc:
            logger.warning(
                "Rejected image path outside storage directory",
                image_id=image_id,
                candidate=str(candidate),
                images_dir=str(images_dir),
            )
            msg = f"Image id escapes storage containment: {image_id!r}"
            raise StorageError(msg) from exc
        return candidate

    def image_exists(self, image_id: str) -> bool:
        """Check if an image file exists on disk, within containment.

        Routes through :meth:`get_image_path`, so a traversal id raises
        :class:`StorageError` rather than probing arbitrary filesystem paths.
        """
        return self.get_image_path(image_id).exists()
