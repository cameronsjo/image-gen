"""Custom exception hierarchy for image-gen.

A single base (:class:`ImageGenError`) lets callers catch any domain error, while
the specific subclasses let the API and MCP layers *categorize* failures —
provider vs. quota vs. storage — and map each to the right status code and
user-facing message instead of swallowing everything into one opaque 500.
"""


class ImageGenError(Exception):
    """Base class for all image-gen domain errors."""


class ProviderError(ImageGenError):
    """An image provider failed to generate an image."""


class ProviderNotConfiguredError(ImageGenError):
    """The requested provider has no API key configured."""


class UnsupportedParameterError(ImageGenError):
    """A provider cannot honor the requested aspect-ratio / resolution combination."""


class QuotaExceededError(ImageGenError):
    """The user's token bucket is empty."""


class StorageError(ImageGenError):
    """A filesystem I/O operation failed (save, read, or path containment)."""
