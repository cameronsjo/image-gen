"""YAML frontmatter + freeform prompt parser.

Parses prompt files in the format:
    ---
    name: my-image
    aspect_ratio: "16:9"
    resolution: 2K
    ---
    The actual prompt text goes here...
"""

from dataclasses import dataclass

import yaml

from image_gen.models import AspectRatio, Resolution

VALID_ASPECT_RATIOS: set[str] = {r.value for r in AspectRatio}
VALID_RESOLUTIONS: set[str] = {r.value for r in Resolution}
MIN_PROMPT_WORDS = 50


@dataclass(frozen=True)
class ParsedPrompt:
    """A parsed prompt with frontmatter metadata and body text."""

    name: str
    body: str
    aspect_ratio: str
    resolution: str


def parse_prompt(text: str) -> ParsedPrompt:
    """Parse a YAML frontmatter prompt string into structured data.

    Raises ValueError if the frontmatter delimiters are missing.
    """
    parts = text.split("---", 2)
    if len(parts) < 3:
        msg = "Prompt must contain YAML frontmatter between --- delimiters"
        raise ValueError(msg)

    frontmatter: dict[str, str] = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()

    return ParsedPrompt(
        name=frontmatter.get("name", "untitled"),
        body=body,
        aspect_ratio=frontmatter.get("aspect_ratio", "1:1"),
        resolution=frontmatter.get("resolution", "2K"),
    )


def validate_prompt(prompt: ParsedPrompt) -> list[str]:
    """Pre-flight validation before expensive image generation.

    Returns a list of error strings (empty if valid).
    """
    errors: list[str] = []

    if not prompt.body:
        errors.append("Empty prompt body")
    elif len(prompt.body.split()) < MIN_PROMPT_WORDS:
        word_count = len(prompt.body.split())
        errors.append(f"Prompt too short ({word_count} words, minimum {MIN_PROMPT_WORDS})")

    if prompt.aspect_ratio not in VALID_ASPECT_RATIOS:
        errors.append(f"Invalid aspect_ratio '{prompt.aspect_ratio}'")

    if prompt.resolution not in VALID_RESOLUTIONS:
        errors.append(f"Invalid resolution '{prompt.resolution}'")

    return errors
