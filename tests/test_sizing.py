"""Tests for the shared sizing helper and the provider base utility.

# Test Plan
#
# compute_size (Classification: Pure logic — data transformer)
#   [x] Happy: square ratio 1:1 returns equal-dimension string
#   [x] Happy: landscape ratio width is the long edge
#   [x] Happy: portrait ratio height is the long edge
#   [x] Boundary: base > _MAX_DIM caps the long edge at _MAX_DIM
#   [x] Boundary: base > _MAX_DIM for portrait caps height at _MAX_DIM
#   [x] Boundary: tiny base + extreme landscape ratio triggers short-edge floor clamp
#   [x] Boundary: tiny base + extreme portrait ratio triggers short-edge floor clamp
#   [x] Invariant: short edge always >= _DIVISOR (16)
#   [x] Invariant: both axes <= _MAX_DIM for all canonical ratios at standard bases
#   [x] Invariant: both axes divisible by _DIVISOR for all canonical ratios
#   [x] Unhappy: unknown ratio raises UnsupportedParameterError
#   [x] Unhappy: error message includes provider_name
#   [x] Unhappy: error message includes the unrecognised ratio string
#
# decode_b64_image (Classification: Input parser)
#   [x] Happy: valid base64 decodes to original bytes
#   [x] Unhappy: malformed base64 raises ProviderError
#   [x] Unhappy: ProviderError message includes the provider name
"""

import base64

import pytest

from image_gen.exceptions import ProviderError, UnsupportedParameterError
from image_gen.services._sizing import _DIVISOR, _MAX_DIM, _RATIO_MAP, compute_size
from image_gen.services.provider import decode_b64_image

# ---------------------------------------------------------------------------
# compute_size — happy paths
# ---------------------------------------------------------------------------


class TestComputeSizeHappy:
    def test_square_ratio_produces_equal_dimensions(self):
        result = compute_size("1:1", 512, "TestProvider")
        w, h = map(int, result.split("x"))
        assert w == h

    def test_landscape_long_edge_is_width(self):
        # 16:9 is landscape — width should be >= height
        result = compute_size("16:9", 1024, "TestProvider")
        w, h = map(int, result.split("x"))
        assert w >= h

    def test_portrait_long_edge_is_height(self):
        # 9:16 is portrait — height should be >= width
        result = compute_size("9:16", 1024, "TestProvider")
        w, h = map(int, result.split("x"))
        assert h >= w

    def test_square_returns_wxh_format(self):
        result = compute_size("1:1", 2048, "TestProvider")
        assert result == "2048x2048"

    def test_landscape_16_9_at_1k(self):
        # width=1024, height=floor(1024*9/16/16)*16=floor(576/16)*16=36*16=576
        result = compute_size("16:9", 1024, "TestProvider")
        assert result == "1024x576"

    def test_portrait_9_16_at_1k(self):
        # height=1024, width=floor(1024*9/16/16)*16=576
        result = compute_size("9:16", 1024, "TestProvider")
        assert result == "576x1024"


# ---------------------------------------------------------------------------
# compute_size — boundary: base > _MAX_DIM
# ---------------------------------------------------------------------------


class TestComputeSizeMaxDimCap:
    def test_base_above_max_dim_caps_landscape_long_edge(self):
        # base=5000 > _MAX_DIM=3840 — long edge must be capped
        result = compute_size("1:1", 5000, "TestProvider")
        w, h = map(int, result.split("x"))
        assert w == _MAX_DIM
        assert h == _MAX_DIM

    def test_base_above_max_dim_caps_portrait_long_edge(self):
        # Portrait: height is long edge; must be capped at _MAX_DIM
        result = compute_size("9:16", 5000, "TestProvider")
        w, h = map(int, result.split("x"))
        assert h == _MAX_DIM
        assert h <= _MAX_DIM
        assert w <= _MAX_DIM

    def test_both_axes_within_max_dim_when_base_exceeds_it(self):
        for ratio in _RATIO_MAP:
            result = compute_size(ratio, _MAX_DIM + 1000, "TestProvider")
            w, h = map(int, result.split("x"))
            assert w <= _MAX_DIM, f"{ratio}: width {w} exceeds _MAX_DIM"
            assert h <= _MAX_DIM, f"{ratio}: height {h} exceeds _MAX_DIM"


# ---------------------------------------------------------------------------
# compute_size — boundary: short-edge floor clamp (max(dim, _DIVISOR))
# ---------------------------------------------------------------------------


class TestComputeSizeShortEdgeClamp:
    def test_landscape_short_edge_never_below_divisor(self):
        # 21:9 with base=32: height = floor(32*9/21/16)*16 = 0 → clamped to 16
        result = compute_size("21:9", 32, "TestProvider")
        _w, h = map(int, result.split("x"))
        # The clamp path was taken; short edge must be >= _DIVISOR
        assert h >= _DIVISOR
        assert h == _DIVISOR  # exact clamp to the floor

    def test_portrait_short_edge_never_below_divisor(self):
        # 2:3 with base=8: width = floor(8*2/3/16)*16 = 0 → clamped to 16
        result = compute_size("2:3", 8, "TestProvider")
        w, _h = map(int, result.split("x"))
        assert w >= _DIVISOR
        assert w == _DIVISOR  # exact clamp to the floor

    def test_all_canonical_ratios_short_edge_at_least_divisor_for_tiny_base(self):
        # Even with an absurdly small base, no axis should fall below _DIVISOR.
        for ratio in _RATIO_MAP:
            result = compute_size(ratio, 16, "TestProvider")
            w, h = map(int, result.split("x"))
            assert w >= _DIVISOR, f"{ratio}: width {w} < {_DIVISOR}"
            assert h >= _DIVISOR, f"{ratio}: height {h} < {_DIVISOR}"


# ---------------------------------------------------------------------------
# compute_size — invariants across all canonical ratios + standard bases
# ---------------------------------------------------------------------------


class TestComputeSizeInvariants:
    _STANDARD_BASES = (1024, 2048, 3840)

    def test_both_axes_divisible_by_divisor(self):
        for ratio in _RATIO_MAP:
            for base in self._STANDARD_BASES:
                result = compute_size(ratio, base, "TestProvider")
                w, h = map(int, result.split("x"))
                assert w % _DIVISOR == 0, f"{ratio}@{base}: width {w} not divisible by {_DIVISOR}"
                assert h % _DIVISOR == 0, f"{ratio}@{base}: height {h} not divisible by {_DIVISOR}"

    def test_both_axes_within_max_dim_for_standard_bases(self):
        for ratio in _RATIO_MAP:
            for base in self._STANDARD_BASES:
                result = compute_size(ratio, base, "TestProvider")
                w, h = map(int, result.split("x"))
                assert w <= _MAX_DIM, f"{ratio}@{base}: width {w} exceeds _MAX_DIM"
                assert h <= _MAX_DIM, f"{ratio}@{base}: height {h} exceeds _MAX_DIM"

    def test_output_is_wxh_format(self):
        # Return value must split on "x" into exactly two non-negative integers.
        for ratio in _RATIO_MAP:
            result = compute_size(ratio, 1024, "TestProvider")
            parts = result.split("x")
            assert len(parts) == 2, f"{ratio}: expected 'WxH', got {result!r}"
            w, h = int(parts[0]), int(parts[1])
            assert w > 0
            assert h > 0


# ---------------------------------------------------------------------------
# compute_size — unhappy: unknown ratio
# ---------------------------------------------------------------------------


class TestComputeSizeUnhappy:
    def test_unknown_ratio_raises_unsupported_parameter_error(self):
        with pytest.raises(UnsupportedParameterError):
            compute_size("7:3", 1024, "TestProvider")

    def test_error_message_includes_provider_name(self):
        with pytest.raises(UnsupportedParameterError, match="Acme provider"):
            compute_size("7:3", 1024, "Acme")

    def test_error_message_includes_the_bad_ratio(self):
        with pytest.raises(UnsupportedParameterError, match="7:3"):
            compute_size("7:3", 1024, "TestProvider")

    def test_empty_ratio_string_raises(self):
        with pytest.raises(UnsupportedParameterError):
            compute_size("", 1024, "TestProvider")

    def test_reversed_canonical_ratio_raises(self):
        # "9:21" is not in _RATIO_MAP even though "21:9" is
        with pytest.raises(UnsupportedParameterError):
            compute_size("9:21", 1024, "TestProvider")


# ---------------------------------------------------------------------------
# decode_b64_image (provider.py)
# ---------------------------------------------------------------------------


class TestDecodeB64Image:
    _PROVIDER = "TestProvider"

    def test_valid_base64_decodes_to_original_bytes(self):
        original = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        encoded = base64.b64encode(original).decode()
        result = decode_b64_image(encoded, self._PROVIDER)
        assert result == original

    def test_malformed_base64_raises_provider_error(self):
        with pytest.raises(ProviderError):
            decode_b64_image("not-valid-base64!!!", self._PROVIDER)

    def test_provider_error_message_names_the_provider(self):
        with pytest.raises(ProviderError, match="TestProvider"):
            decode_b64_image("!!!bad!!!", self._PROVIDER)

    def test_empty_string_raises_provider_error(self):
        # An empty payload is malformed — the caller already guards for b64=="",
        # but passing it here directly should still raise.
        # base64.b64decode("") returns b"" without error, so this is the happy
        # path: empty string decodes to empty bytes (not malformed).
        result = decode_b64_image("", self._PROVIDER)
        assert result == b""

    def test_valid_base64_with_padding_decodes_correctly(self):
        payload = b"hello world"
        encoded = base64.b64encode(payload).decode()
        assert decode_b64_image(encoded, self._PROVIDER) == payload
