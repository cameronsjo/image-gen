"""Tests for prompt parsing and validation."""

import pytest

from image_gen.services.prompt import ParsedPrompt, parse_prompt, validate_prompt

LONG_BODY = " ".join(["word"] * 60)


def test_parse_prompt_with_frontmatter() -> None:
    text = "---\nname: test\naspect_ratio: '16:9'\nresolution: 4K\n---\n" + LONG_BODY
    result = parse_prompt(text)
    assert result.name == "test"
    assert result.aspect_ratio == "16:9"
    assert result.resolution == "4K"
    assert result.body == LONG_BODY


def test_parse_prompt_missing_frontmatter() -> None:
    with pytest.raises(ValueError, match="frontmatter"):
        parse_prompt("no frontmatter here")


def test_parse_prompt_defaults() -> None:
    text = "---\n---\n" + LONG_BODY
    result = parse_prompt(text)
    assert result.name == "untitled"
    assert result.aspect_ratio == "1:1"
    assert result.resolution == "2K"


def test_validate_prompt_valid() -> None:
    prompt = ParsedPrompt(name="ok", body=LONG_BODY, aspect_ratio="1:1", resolution="2K")
    assert validate_prompt(prompt) == []


def test_validate_prompt_too_short() -> None:
    prompt = ParsedPrompt(name="bad", body="too short", aspect_ratio="1:1", resolution="2K")
    errors = validate_prompt(prompt)
    assert len(errors) == 1
    assert "too short" in errors[0].lower()


def test_validate_prompt_empty_body() -> None:
    prompt = ParsedPrompt(name="bad", body="", aspect_ratio="1:1", resolution="2K")
    errors = validate_prompt(prompt)
    assert any("empty" in e.lower() for e in errors)


def test_validate_prompt_invalid_aspect_ratio() -> None:
    prompt = ParsedPrompt(name="bad", body=LONG_BODY, aspect_ratio="7:3", resolution="2K")
    errors = validate_prompt(prompt)
    assert any("aspect_ratio" in e for e in errors)


def test_validate_prompt_invalid_resolution() -> None:
    prompt = ParsedPrompt(name="bad", body=LONG_BODY, aspect_ratio="1:1", resolution="8K")
    errors = validate_prompt(prompt)
    assert any("resolution" in e for e in errors)
