"""Published per-image table estimates for one image's output only.

Reviewed 2026-10-15. These exclude prompt/input tokens, thinking, grounding,
account discounts, taxes and other request charges. They are not billed costs.
No area scaling, model-prefix matching or unverified model aliases are used.
"""

# Google Standard image-output table (published rounded per-image estimates):
# https://ai.google.dev/gemini-api/docs/pricing#gemini-3-pro-image
# The current table names the stable model. Its preview alias is NOT assumed.
_GEMINI_OUTPUT_USD = {
    ("gemini-3-pro-image", "1K"): 0.134,
    ("gemini-3-pro-image", "2K"): 0.134,
    ("gemini-3-pro-image", "4K"): 0.24,
}

# GPT Image 2 output-only per-image table, model/quality/exact pixel size:
# https://developers.openai.com/api/docs/guides/image-generation#calculating-costs
# Custom sizes, snapshots and other models remain unknown, even if a model
# name looks related. The table is not a linear cost-per-pixel formula.
_OPENAI_OUTPUT_USD = {
    ("gpt-image-2", "low", "1024x1024"): 0.006,
    ("gpt-image-2", "medium", "1024x1024"): 0.053,
    ("gpt-image-2", "high", "1024x1024"): 0.211,
    ("gpt-image-2", "low", "1024x1536"): 0.005,
    ("gpt-image-2", "medium", "1024x1536"): 0.041,
    ("gpt-image-2", "high", "1024x1536"): 0.165,
    ("gpt-image-2", "low", "1536x1024"): 0.005,
    ("gpt-image-2", "medium", "1536x1024"): 0.041,
    ("gpt-image-2", "high", "1536x1024"): 0.165,
}


def gemini_output_estimate(model: str, resolution: str) -> float | None:
    """Return the published per-image output estimate, or unknown."""
    return _GEMINI_OUTPUT_USD.get((model, resolution))


def openai_output_estimate(model: str, quality: str, size: str) -> float | None:
    """Return a published exact-size output estimate; never interpolate."""
    return _OPENAI_OUTPUT_USD.get((model, quality, size))
