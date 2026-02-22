"""Local file storage for generated images."""

from pathlib import Path

import structlog

from image_gen.config import Settings

logger = structlog.get_logger()


class StorageService:
    """Saves and retrieves images from the local filesystem."""

    def __init__(self, settings: Settings) -> None:
        self._images_dir = settings.images_dir
        self._images_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Storage initialized", images_dir=str(self._images_dir))

    async def save_image(self, image_data: bytes, image_id: str) -> Path:
        """Save image bytes to disk and return the file path."""
        file_path = self._images_dir / f"{image_id}.png"
        file_path.write_bytes(image_data)
        logger.info(
            "Image saved",
            image_id=image_id,
            file_path=str(file_path),
            file_size=len(image_data),
        )
        return file_path

    def get_image_path(self, image_id: str) -> Path:
        """Return the expected path for an image ID."""
        return self._images_dir / f"{image_id}.png"

    def image_exists(self, image_id: str) -> bool:
        """Check if an image file exists on disk."""
        return self.get_image_path(image_id).exists()
