"""Shared aspect-ratio → pixel-size computation for image providers.

The OpenAI and OpenRouter providers map a canonical aspect ratio plus a long-edge
pixel base onto a ``WxH`` string with identical math: scale so the long edge equals
the base, floor each axis to a multiple of 16, and cap each axis at 3840. Keeping a
single copy means a new :class:`~image_gen.models.AspectRatio` entry is added in
exactly one place — previously the ratio map and sizing math were duplicated nearly
verbatim across both providers, so an addition could silently diverge.

Each provider keeps its own resolution → (quality, base) map because the quality
literals differ between the two APIs; only the ratio map and the size math are shared.
"""

import math

from image_gen.exceptions import UnsupportedParameterError

# Canonical aspect-ratio string → (width_parts, height_parts)
_RATIO_MAP: dict[str, tuple[int, int]] = {
    "1:1": (1, 1),
    "2:3": (2, 3),
    "3:2": (3, 2),
    "3:4": (3, 4),
    "4:3": (4, 3),
    "4:5": (4, 5),
    "5:4": (5, 4),
    "9:16": (9, 16),
    "16:9": (16, 9),
    "21:9": (21, 9),
}

_DIVISOR = 16
_MAX_DIM = 3840  # max for any single dimension (OpenAI and OpenRouter share this limit)


def compute_size(aspect_ratio: str, base: int, provider_name: str) -> str:
    """Return a ``WxH`` size string for *aspect_ratio* scaled so the long edge is *base*.

    Width and height are floored to a multiple of 16 and capped at ``_MAX_DIM`` per
    axis. The long edge is capped first and the short edge is always <= the long edge,
    so both axes stay within the limit by construction.

    Args:
        aspect_ratio: Canonical ratio string (e.g. ``"16:9"``).
        base: Long-edge pixel target for the chosen resolution tier.
        provider_name: Used only in the error message so callers can attribute it.

    Raises:
        UnsupportedParameterError: If *aspect_ratio* is not a canonical ratio.
    """
    if aspect_ratio not in _RATIO_MAP:
        msg = f"{provider_name} provider does not recognise aspect ratio {aspect_ratio!r}"
        raise UnsupportedParameterError(msg)

    w_parts, h_parts = _RATIO_MAP[aspect_ratio]

    if w_parts >= h_parts:
        width = min(base, _MAX_DIM)
        height = math.floor(width * h_parts / w_parts / _DIVISOR) * _DIVISOR
        height = max(height, _DIVISOR)
    else:
        height = min(base, _MAX_DIM)
        width = math.floor(height * w_parts / h_parts / _DIVISOR) * _DIVISOR
        width = max(width, _DIVISOR)

    return f"{width}x{height}"
