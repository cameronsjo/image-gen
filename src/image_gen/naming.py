"""Download filename construction.

A single source of truth for the *suggested save name* a client offers when
downloading a generated image.  Both the web UI and the server's
``Content-Disposition`` header derive the name from :func:`download_filename`,
so they agree with zero duplication.

The on-disk layout is unrelated: stored files keep their ``{ULID}.png`` names
(already unique).  Only the suggested download name is made descriptive here.
"""

import re
from datetime import datetime

# Length caps keep the assembled filename well under filesystem limits while
# leaving the timestamp + ULID tail (the uniqueness guarantee) intact.
_NAME_MAX = 40
_MODEL_MAX = 40


def slug(value: str, max_length: int) -> str:
    """Lowercase *value* to a filesystem- and header-safe ``a-z0-9-`` slug.

    Collapses every run of non-alphanumeric characters to a single hyphen and
    trims leading/trailing hyphens, then truncates to *max_length* (re-trimming
    so the result never ends on a hyphen).  This sanitizes the user-controlled
    name — stripping ``/``, ``..``, quotes, newlines, ``;`` — which also
    neutralizes any ``Content-Disposition`` header-injection risk.
    """
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned[:max_length].strip("-")


def download_filename(
    name: str,
    model: str | None,
    created_at: datetime,
    ulid: str,
) -> str:
    """Build a descriptive, collision-free ``.png`` download filename.

    Shape: ``{name}-{model}-{YYYYMMDD-HHMMSS}-{ULID}.png``.  The ULID tail
    guarantees uniqueness (no overwrites when saving many images); the timestamp
    is human-readable.  *model* may be ``None`` (non-OpenRouter providers), in
    which case it slugs to ``model``.

    e.g. ``la-belle-fleur-sauvage-openai-gpt-image-2-20260630-181236-01KWDC….png``
    """
    name_part = slug(name, _NAME_MAX) or "image"
    model_part = slug(model or "model", _MODEL_MAX) or "model"
    stamp = created_at.strftime("%Y%m%d-%H%M%S")
    return f"{name_part}-{model_part}-{stamp}-{ulid}.png"
