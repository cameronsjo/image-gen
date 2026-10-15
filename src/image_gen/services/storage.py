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

    async def save_image(
        self, image_data: bytes, image_id: str, *, filename: str | None = None
    ) -> Path:
        """Save image bytes to disk and return the file path."""
        if filename is None:
            file_path = self.get_image_path(image_id)
        else:
            # New names must be basenames. Slugging is useful for presentation,
            # but containment is independently enforced at the write boundary.
            if not filename or Path(filename).name != filename or Path(filename).is_absolute():
                raise StorageError("Stored image filename must be a basename")
            file_path = self._contained_path(self._images_dir_resolved / filename)
        # Refuse collisions and pre-existing symlinks instead of overwriting.
        try:
            with file_path.open("xb") as output:
                output.write(image_data)
        except OSError as exc:
            raise StorageError("Unable to create image file") from exc
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
        return self._contained_path(self._images_dir_resolved / f"{image_id}.png")

    def resolve_stored_path(self, file_path: str) -> Path:
        """Validate the persisted path before serving it.

        Old relative paths were recorded relative to the process working
        directory; retain that interpretation. New writes return absolute paths.
        """
        return self._contained_path(Path(file_path))

    def _contained_path(self, path: Path) -> Path:
        images_dir = self._images_dir_resolved
        candidate = path.resolve()
        try:
            candidate.relative_to(images_dir)
        except ValueError as exc:
            logger.warning(
                "Rejected image path outside storage directory", candidate=str(candidate)
            )
            raise StorageError("Image path escapes storage containment") from exc
        return candidate

    def image_exists(self, image_id: str) -> bool:
        """Check if an image file exists on disk, within containment.

        Routes through :meth:`get_image_path`, so a traversal id raises
        :class:`StorageError` rather than probing arbitrary filesystem paths.
        """
        return self.get_image_path(image_id).exists()
