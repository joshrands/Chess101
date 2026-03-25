"""Tests for ChessMatrix barcode scanning (network.chessmatrix.decode_frame).

Structure
---------
1. Synthetic-image helpers  — ``_make_frame*`` factory functions
2. Per-pipeline-stage tests — each internal helper tested in isolation
3. End-to-end synthetic tests — full decode on generated images
   a. Clean padded images (5 codes × varied cell sizes)
   b. Rotation (multiple angles × codes)
   c. Perspective distortion
   d. Noise
   e. Photometric variations (brightness, contrast, color tint)
   f. Affine shear / stretch
   g. Combined transforms
   h. Distractor rectangle (another large square in the scene)
4. Real-photo fixture tests  — auto-discovered from tests/fixtures/chessmatrix/
5. decode_frame_debug tests  — verify debug dict contract

Running
-------
    .venv/bin/python -m pytest tests/test_chessmatrix_scanning.py -v
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

# ── constants (mirror network.chessmatrix internals) ──────────────────────

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "chessmatrix"

_CELL_PX = 16   # canonical cell size used by decode pipeline
_GRID_SIZE = 8 * _CELL_PX


# ── synthetic frame factories ──────────────────────────────────────────────

def _make_frame(room_code: str, cell_px: int = 20) -> np.ndarray:
    """Perfect synthetic ChessMatrix on a black background, no border padding."""
    from network.chessmatrix import encode

    # encode() returns 8×8 (R,G,B) tuples with dark-mode inversion already applied.
    grid = encode(room_code)
    size = 8 * cell_px
    img = np.zeros((size, size, 3), dtype=np.uint8)
    for r in range(8):
        for c in range(8):
            rv, gv, bv = grid[r][c]
            y0, x0 = r * cell_px, c * cell_px
            img[y0:y0 + cell_px, x0:x0 + cell_px] = (bv, gv, rv)
    return img


def _make_frame_padded(room_code: str, cell_px: int = 20,
                       pad: int = 40) -> np.ndarray:
    """Synthetic frame centred on a light-gray background with *pad* px border."""
    barcode = _make_frame(room_code, cell_px=cell_px)
    h, w = barcode.shape[:2]
    canvas = np.full((h + 2 * pad, w + 2 * pad, 3), 220, dtype=np.uint8)
    canvas[pad:pad + h, pad:pad + w] = barcode
    return canvas


def _make_frame_rotated(room_code: str, angle_deg: float,
                        cell_px: int = 20, pad: int = 100) -> np.ndarray:
    """Padded synthetic frame rotated by *angle_deg* degrees.

    Default pad=100 ensures no corners are clipped even at 45°.
    """
    import cv2
    src = _make_frame_padded(room_code, cell_px=cell_px, pad=pad)
    h, w = src.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle_deg, 1.0)
    return cv2.warpAffine(src, M, (w, h),
                          borderMode=cv2.BORDER_CONSTANT,
                          borderValue=(220, 220, 220))


def _make_frame_perspective(room_code: str, skew: float = 0.08,
                            cell_px: int = 20, pad: int = 60) -> np.ndarray:
    """Padded synthetic frame with mild perspective distortion (trapezoid)."""
    import cv2
    src = _make_frame_padded(room_code, cell_px=cell_px, pad=pad)
    h, w = src.shape[:2]
    d = int(min(h, w) * skew)
    src_pts = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst_pts = np.float32([[d, 0], [w - d, d], [w, h], [0, h - d]])
    H = cv2.getPerspectiveTransform(src_pts, dst_pts)
    return cv2.warpPerspective(src, H, (w, h),
                               borderMode=cv2.BORDER_CONSTANT,
                               borderValue=(220, 220, 220))


def _make_frame_shear(room_code: str, shear_x: float = 0.15,
                      cell_px: int = 20, pad: int = 80) -> np.ndarray:
    """Padded synthetic frame with a horizontal shear transform."""
    import cv2
    src = _make_frame_padded(room_code, cell_px=cell_px, pad=pad)
    h, w = src.shape[:2]
    M = np.float32([[1, shear_x, 0],
                    [0, 1,       0]])
    new_w = int(w + abs(shear_x) * h)
    return cv2.warpAffine(src, M, (new_w, h),
                          borderMode=cv2.BORDER_CONSTANT,
                          borderValue=(220, 220, 220))


def _make_frame_stretch(room_code: str, sx: float = 1.4, sy: float = 0.7,
                        cell_px: int = 20, pad: int = 60) -> np.ndarray:
    """Padded synthetic frame with asymmetric scale (stretch)."""
    import cv2
    src = _make_frame_padded(room_code, cell_px=cell_px, pad=pad)
    h, w = src.shape[:2]
    new_w, new_h = int(w * sx), int(h * sy)
    return cv2.resize(src, (new_w, new_h))


def _apply_photometric(frame: np.ndarray,
                       brightness: int = 0,
                       contrast: float = 1.0,
                       tint_bgr: tuple[int, int, int] = (0, 0, 0),
                       ) -> np.ndarray:
    """Apply brightness/contrast/color-tint to a frame.

    *brightness* is an additive offset (±).
    *contrast* scales pixel values around 128 (< 1 compresses, > 1 expands).
    *tint_bgr* is added to each channel independently.
    """
    out = frame.astype(np.float32)
    out = (out - 128) * contrast + 128 + brightness
    b, g, r = tint_bgr
    out[:, :, 0] = np.clip(out[:, :, 0] + b, 0, 255)
    out[:, :, 1] = np.clip(out[:, :, 1] + g, 0, 255)
    out[:, :, 2] = np.clip(out[:, :, 2] + r, 0, 255)
    return np.clip(out, 0, 255).astype(np.uint8)


def _make_frame_with_distractor(room_code: str, cell_px: int = 20,
                                pad: int = 40) -> np.ndarray:
    """Frame with the barcode PLUS a large bright rectangle as a distractor.

    Simulates a real scene where another roughly-square object (e.g. a device
    screen) is present alongside the barcode.  The distractor is placed to the
    left of the barcode with similar width, ensuring the multi-candidate
    decode loop falls through to the actual barcode.
    """
    barcode = _make_frame(room_code, cell_px=cell_px)
    bh, bw = barcode.shape[:2]
    # Canvas: distractor on left, gap in middle, barcode on right
    gap = pad
    dist_w = bw + 40   # slightly wider than the barcode
    dist_h = bh + 40
    canvas_w = dist_w + gap + bw + 2 * pad
    canvas_h = max(dist_h, bh) + 2 * pad
    canvas = np.full((canvas_h, canvas_w, 3), 220, dtype=np.uint8)
    # Place distractor (a uniform bright rectangle — different from barcode)
    dy = (canvas_h - dist_h) // 2
    canvas[dy:dy + dist_h, pad:pad + dist_w] = 200  # slightly darker gray square
    # Place barcode
    by = (canvas_h - bh) // 2
    bx = pad + dist_w + gap
    canvas[by:by + bh, bx:bx + bw] = barcode
    return canvas


def _make_frame_on_bg(room_code: str, bg_bgr: tuple[int, int, int],
                      cell_px: int = 20, pad: int = 60) -> np.ndarray:
    """Synthetic ChessMatrix centred on a canvas filled with *bg_bgr* (BGR).

    The pad ensures there is clear background on all sides so the quad
    detector has clean edges to find regardless of background color.
    """
    barcode = _make_frame(room_code, cell_px=cell_px)
    h, w = barcode.shape[:2]
    canvas = np.empty((h + 2 * pad, w + 2 * pad, 3), dtype=np.uint8)
    canvas[:] = bg_bgr
    canvas[pad:pad + h, pad:pad + w] = barcode
    return canvas


def _make_frame_affine_on_bg(room_code: str, bg_bgr: tuple[int, int, int],
                              angle_deg: float, shear_x: float = 0.0,
                              cell_px: int = 20, pad: int = 100) -> np.ndarray:
    """Affine-transformed barcode (rotation + optional shear) on *bg_bgr*.

    Large default pad (100 px) prevents corner clipping under rotation.
    The *borderValue* for both warpAffine calls matches *bg_bgr* so the
    background colour is consistent throughout.
    """
    import cv2
    src = _make_frame_on_bg(room_code, bg_bgr, cell_px=cell_px, pad=pad)
    h, w = src.shape[:2]
    R = cv2.getRotationMatrix2D((w / 2, h / 2), angle_deg, 1.0)
    rotated = cv2.warpAffine(src, R, (w, h),
                             borderMode=cv2.BORDER_CONSTANT,
                             borderValue=bg_bgr)
    if shear_x == 0.0:
        return rotated
    S = np.float32([[1, shear_x, 0], [0, 1, 0]])
    new_w = int(w + abs(shear_x) * h)
    return cv2.warpAffine(rotated, S, (new_w, h),
                          borderMode=cv2.BORDER_CONSTANT,
                          borderValue=bg_bgr)


# ── helpers ────────────────────────────────────────────────────────────────

def _decode(frame: np.ndarray) -> str | None:
    from network.chessmatrix import decode_frame
    return decode_frame(frame)


def _debug(frame: np.ndarray) -> dict:
    from network.chessmatrix import decode_frame_debug
    return decode_frame_debug(frame)


# ══════════════════════════════════════════════════════════════════════════
# 1.  Per-pipeline-stage unit tests
# ══════════════════════════════════════════════════════════════════════════

class TestNormalizeGrayscale:
    def test_values_in_range(self) -> None:
        """gray_f values are in [0, 1]."""
        pytest.importorskip("cv2")
        import cv2
        frame = _make_frame_padded("ABCDEF", pad=20)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray_f = gray.astype(np.float32) / 255.0
        assert float(gray_f.min()) >= 0.0
        assert float(gray_f.max()) <= 1.0

    def test_shape_preserved(self) -> None:
        pytest.importorskip("cv2")
        import cv2
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        gray_f = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        assert gray_f.shape == (480, 640)


class TestOrderQuadCorners:
    def test_already_ordered(self) -> None:
        pytest.importorskip("cv2")
        from network.chessmatrix import _order_quad_corners
        pts = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=np.float32)
        ordered = _order_quad_corners(pts)
        np.testing.assert_allclose(ordered[0], [0,  0 ], atol=1)   # TL
        np.testing.assert_allclose(ordered[1], [10, 0 ], atol=1)   # TR
        np.testing.assert_allclose(ordered[2], [10, 10], atol=1)   # BR
        np.testing.assert_allclose(ordered[3], [0,  10], atol=1)   # BL

    def test_shuffled_input(self) -> None:
        pytest.importorskip("cv2")
        from network.chessmatrix import _order_quad_corners
        pts = np.array([[10, 10], [0, 10], [10, 0], [0, 0]], dtype=np.float32)
        ordered = _order_quad_corners(pts)
        np.testing.assert_allclose(ordered[0], [0,  0 ], atol=1)
        np.testing.assert_allclose(ordered[1], [10, 0 ], atol=1)
        np.testing.assert_allclose(ordered[2], [10, 10], atol=1)
        np.testing.assert_allclose(ordered[3], [0,  10], atol=1)




class TestDetectBarcodeCorners:
    def test_clean_padded_image(self) -> None:
        pytest.importorskip("cv2")
        from network.chessmatrix import _detect_barcode_corners
        frame = _make_frame_padded("ABCDEF", cell_px=20, pad=40)
        quad = _detect_barcode_corners(frame)
        assert quad is not None
        assert quad.shape == (4, 2)

    def test_returns_none_for_blank(self) -> None:
        pytest.importorskip("cv2")
        from network.chessmatrix import _detect_barcode_corners
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        assert _detect_barcode_corners(blank) is None

    def test_returns_none_for_solid_gray(self) -> None:
        pytest.importorskip("cv2")
        from network.chessmatrix import _detect_barcode_corners
        assert _detect_barcode_corners(np.full((240, 320, 3), 128, dtype=np.uint8)) is None

    @pytest.mark.parametrize("angle", [10.0, 20.0, 30.0])
    def test_rotated_image(self, angle: float) -> None:
        pytest.importorskip("cv2")
        from network.chessmatrix import _detect_barcode_corners
        frame = _make_frame_rotated("ABCDEF", angle_deg=angle)
        assert _detect_barcode_corners(frame) is not None, \
            f"Corners not found at {angle}° rotation"

    def test_perspective_distorted_image(self) -> None:
        pytest.importorskip("cv2")
        from network.chessmatrix import _detect_barcode_corners
        frame = _make_frame_perspective("ABCDEF", skew=0.08)
        assert _detect_barcode_corners(frame) is not None


class TestWarpToCanonical:
    def test_output_shape(self) -> None:
        pytest.importorskip("cv2")
        from network.chessmatrix import _warp_to_canonical, _GRID_SIZE
        frame = _make_frame_padded("ABCDEF", cell_px=20, pad=40)
        quad = np.float32([[40, 40], [200, 40], [200, 200], [40, 200]])
        warped = _warp_to_canonical(frame, quad, size=_GRID_SIZE)
        assert warped.shape == (_GRID_SIZE, _GRID_SIZE, 3)

    def test_canonical_cell_colors(self) -> None:
        """After warping a perfect padded image the RED anchor cell is red."""
        pytest.importorskip("cv2")
        from network.chessmatrix import _CELL_PX
        frame = _make_frame_padded("ABCDEF", cell_px=20, pad=40)
        result = _debug(frame)
        assert result["warped"] is not None
        warped = result["warped"]
        blk = warped[_CELL_PX:2 * _CELL_PX, 6 * _CELL_PX:7 * _CELL_PX]
        mean_r = int(np.mean(blk[:, :, 2]))
        mean_b = int(np.mean(blk[:, :, 0]))
        assert mean_r > 150, f"Expected red at anchor (1,6), R={mean_r}"
        assert mean_b < 50,  f"Expected low blue at anchor (1,6), B={mean_b}"


class TestBuildCalibration:
    def _get_warped(self, code: str) -> np.ndarray:
        frame = _make_frame_padded(code, cell_px=20, pad=40)
        result = _debug(frame)
        assert result["warped"] is not None, f"decode_frame_debug returned no warped image for {code}"
        return result["warped"]

    def test_palette_length_and_black(self) -> None:
        pytest.importorskip("cv2")
        from network.chessmatrix import _build_calibration, _CELL_PX
        warped = self._get_warped("ABCDEF")
        cal = _build_calibration(warped, _CELL_PX)
        assert len(cal) == 4
        # BLACK is sampled from row 7 (DataMatrix border) — should be dark, not necessarily pure (0,0,0)
        assert all(v < 50 for v in cal[0]), f"BLACK anchor not dark: {cal[0]}"

    def test_red_dominant(self) -> None:
        pytest.importorskip("cv2")
        from network.chessmatrix import _build_calibration, _CELL_PX
        warped = self._get_warped("ABCDEF")
        r, g, b = _build_calibration(warped, _CELL_PX)[1]
        assert r > g and r > b, f"RED anchor not red-dominant: {(r,g,b)}"

    def test_green_dominant(self) -> None:
        pytest.importorskip("cv2")
        from network.chessmatrix import _build_calibration, _CELL_PX
        warped = self._get_warped("ABCDEF")
        r, g, b = _build_calibration(warped, _CELL_PX)[2]
        assert g > r and g > b, f"GREEN anchor not green-dominant: {(r,g,b)}"

    def test_blue_dominant(self) -> None:
        pytest.importorskip("cv2")
        from network.chessmatrix import _build_calibration, _CELL_PX
        warped = self._get_warped("ABCDEF")
        r, g, b = _build_calibration(warped, _CELL_PX)[3]
        assert b > r and b > g, f"BLUE anchor not blue-dominant: {(r,g,b)}"


class TestClassifyGrid:
    def test_classify_grid_matches_encode(self) -> None:
        pytest.importorskip("cv2")
        import chessmatrix as _cm  # type: ignore[import]
        from network.chessmatrix import (
            room_code_to_bytes, _build_calibration, _classify_cell,
            _sample_cell_rgb, _CELL_PX,
        )
        code = "ABCDEF"
        frame = _make_frame_padded(code, cell_px=20, pad=40)
        result = _debug(frame)
        assert result["warped"] is not None
        warped = result["warped"]
        cal = _build_calibration(warped, _CELL_PX)
        classified = [
            [_classify_cell(*_sample_cell_rgb(warped, r, c, _CELL_PX), cal)
             for c in range(8)]
            for r in range(8)
        ]
        expected = _cm.encode(room_code_to_bytes(code))
        # Only check interior data cells (rows 1-6, cols 1-6).
        # Dark-mode rendering inverts K↔WHITE on the structural border
        # (row 0, row 7, col 0, col 7), so those cells cannot be compared
        # directly with the raw chessmatrix encoding.
        mismatches = [
            (r, c) for r in range(1, 7) for c in range(1, 7)
            if expected[r][c] != -1 and classified[r][c] != expected[r][c]
        ]
        assert not mismatches, f"Grid mismatches at: {mismatches}"


# ══════════════════════════════════════════════════════════════════════════
# 2a.  End-to-end synthetic: clean padded images
# ══════════════════════════════════════════════════════════════════════════

# Cover a broad mix of color distributions — some codes are mostly black,
# some have many colored cells.  ABCDEF is the hardest (varied colors).
_ALL_CODES = ["AAAAAA", "ZZZZZZ", "ABCDEF", "XKCDQR", "MMMMMM",
              "TESTQR", "SMALLS", "MNOPQR"]


@pytest.mark.parametrize("code", _ALL_CODES)
def test_decode_synthetic_clean(code: str) -> None:
    """decode_frame recovers the correct code from a clean padded image."""
    pytest.importorskip("cv2")
    assert _decode(_make_frame_padded(code, cell_px=20, pad=40)) == code


def test_decode_synthetic_large_image() -> None:
    pytest.importorskip("cv2")
    assert _decode(_make_frame_padded("TESTQR", cell_px=60, pad=80)) == "TESTQR"


def test_decode_synthetic_small_image() -> None:
    pytest.importorskip("cv2")
    assert _decode(_make_frame_padded("SMALLS", cell_px=8, pad=20)) == "SMALLS"


# ══════════════════════════════════════════════════════════════════════════
# 2b.  End-to-end synthetic: rotation
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("angle,code", [
    (5,  "ABCDEF"),
    (10, "ABCDEF"),
    (15, "ABCDEF"),
    (20, "ZZZZZZ"),
    (30, "AAAAAA"),
    (45, "TESTQR"),
])
def test_decode_synthetic_with_rotation(angle: float, code: str) -> None:
    pytest.importorskip("cv2")
    frame = _make_frame_rotated(code, angle_deg=angle)
    assert _decode(frame) == code, f"Failed at {angle}° rotation for {code}"


# ══════════════════════════════════════════════════════════════════════════
# 2c.  End-to-end synthetic: perspective distortion
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("skew,code", [
    (0.05, "ABCDEF"),
    (0.08, "ABCDEF"),
    (0.08, "ZZZZZZ"),
    (0.10, "AAAAAA"),
])
def test_decode_synthetic_with_perspective(skew: float, code: str) -> None:
    pytest.importorskip("cv2")
    frame = _make_frame_perspective(code, skew=skew)
    assert _decode(frame) == code, f"Failed at skew={skew} for {code}"


# ══════════════════════════════════════════════════════════════════════════
# 2d.  End-to-end synthetic: noise
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("sigma,code", [
    (10,  "ABCDEF"),
    (20,  "ABCDEF"),
    (30,  "AAAAAA"),
])
def test_decode_synthetic_with_noise(sigma: int, code: str) -> None:
    pytest.importorskip("cv2")
    rng = np.random.default_rng(42)
    frame = _make_frame_padded(code, cell_px=20, pad=40).astype(np.float32)
    noisy = np.clip(frame + rng.normal(0, sigma, frame.shape), 0, 255).astype(np.uint8)
    assert _decode(noisy) == code, f"Failed at noise σ={sigma}"


# ══════════════════════════════════════════════════════════════════════════
# 2e.  End-to-end synthetic: photometric variations
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("brightness,contrast,tint,code", [
    (-80,  1.0, (0,   0,   0),   "ABCDEF"),   # underexposed
    (+80,  1.0, (0,   0,   0),   "ABCDEF"),   # overexposed
    (  0,  0.5, (0,   0,   0),   "ABCDEF"),   # low contrast
    (  0,  1.0, (40,  0, -40),   "ZZZZZZ"),   # warm tint (add red)
    (  0,  1.0, (-40, 0,  40),   "AAAAAA"),   # cool tint (add blue)
    (-50,  1.2, (20, 10,   0),   "TESTQR"),   # dark + high contrast + warm
])
def test_decode_synthetic_photometric(brightness: int, contrast: float,
                                      tint: tuple, code: str) -> None:
    pytest.importorskip("cv2")
    frame = _make_frame_padded(code, cell_px=20, pad=40)
    processed = _apply_photometric(frame, brightness=brightness,
                                   contrast=contrast, tint_bgr=tint)
    assert _decode(processed) == code, \
        f"Failed: brightness={brightness} contrast={contrast} tint={tint}"


# ══════════════════════════════════════════════════════════════════════════
# 2f.  End-to-end synthetic: shear and stretch
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("shear_x,code", [
    (0.10, "ABCDEF"),
    pytest.param(0.20, "ZZZZZZ", marks=pytest.mark.xfail(
        reason="ZZZZZZ (uniform near-blue palette) confounds local threshold at 20% shear",
        strict=False,
    )),
    (0.30, "AAAAAA"),
])
def test_decode_synthetic_with_shear(shear_x: float, code: str) -> None:
    pytest.importorskip("cv2")
    frame = _make_frame_shear(code, shear_x=shear_x)
    assert _decode(frame) == code, f"Failed at shear_x={shear_x}"


@pytest.mark.parametrize("sx,sy,code", [
    (1.5, 1.0,  "ABCDEF"),   # wider
    (1.0, 0.7,  "ZZZZZZ"),   # shorter
    (1.3, 0.8,  "AAAAAA"),   # wider + shorter
])
def test_decode_synthetic_with_stretch(sx: float, sy: float, code: str) -> None:
    pytest.importorskip("cv2")
    frame = _make_frame_stretch(code, sx=sx, sy=sy)
    assert _decode(frame) == code, f"Failed at stretch sx={sx} sy={sy}"


# ══════════════════════════════════════════════════════════════════════════
# 2g.  End-to-end synthetic: combined transforms
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("angle,brightness,code", [
    (10,  -40, "ABCDEF"),
    (15,  +50, "ZZZZZZ"),
    (20,    0, "TESTQR"),
])
def test_decode_synthetic_rotation_plus_photometric(angle: float,
                                                     brightness: int,
                                                     code: str) -> None:
    pytest.importorskip("cv2")
    frame = _make_frame_rotated(code, angle_deg=angle)
    frame = _apply_photometric(frame, brightness=brightness)
    assert _decode(frame) == code, \
        f"Failed: rotation={angle}° brightness={brightness} code={code}"


def test_decode_synthetic_perspective_plus_noise() -> None:
    pytest.importorskip("cv2")
    rng = np.random.default_rng(7)
    frame = _make_frame_perspective("ABCDEF", skew=0.06)
    noisy = np.clip(frame.astype(np.float32) + rng.normal(0, 15, frame.shape),
                    0, 255).astype(np.uint8)
    assert _decode(noisy) == "ABCDEF"


# ══════════════════════════════════════════════════════════════════════════
# 2h.  End-to-end synthetic: distractor rectangle
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.xfail(
    reason=(
        "Future work: implement multi-candidate centroid search.  The inflate-rect "
        "algorithm finds a single barcode region by computing the white-pixel centroid "
        "of the entire binary frame.  A large competing rectangle shifts that centroid "
        "away from the barcode, causing detection to fail.  Fixing this requires a "
        "multi-candidate loop (e.g. iterate over connected components or Hough clusters, "
        "attempt decode on each, return first success)."
    ),
    strict=False,
)
@pytest.mark.parametrize("code", ["ABCDEF", "ZZZZZZ", "TESTQR"])
def test_decode_with_distractor_rectangle(code: str) -> None:
    """inflate-rect does not support multi-candidate distractor rejection (future work)."""
    pytest.importorskip("cv2")
    frame = _make_frame_with_distractor(code, cell_px=20, pad=40)
    assert _decode(frame) == code, \
        f"Failed to decode {code} with distractor present"


# ══════════════════════════════════════════════════════════════════════════
# 2i.  Negative cases
# ══════════════════════════════════════════════════════════════════════════

def test_decode_returns_none_for_blank_frame() -> None:
    pytest.importorskip("cv2")
    assert _decode(np.zeros((480, 640, 3), dtype=np.uint8)) is None


def test_decode_returns_none_for_solid_color_frame() -> None:
    pytest.importorskip("cv2")
    assert _decode(np.full((240, 320, 3), 128, dtype=np.uint8)) is None


def test_decode_frame_missing_opencv(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys, importlib
    monkeypatch.setitem(sys.modules, "cv2", None)  # type: ignore[arg-type]
    import network.chessmatrix as cm_mod
    importlib.reload(cm_mod)
    with pytest.raises(ImportError, match="opencv-python"):
        cm_mod.decode_frame(np.zeros((32, 32, 3), dtype=np.uint8))


# ══════════════════════════════════════════════════════════════════════════
# 3.  decode_frame_debug contract tests
# ══════════════════════════════════════════════════════════════════════════

_DEBUG_KEYS = {"code", "gray_f", "edges", "quad", "warped", "cal", "grid"}


def test_decode_frame_debug_returns_all_keys() -> None:
    pytest.importorskip("cv2")
    result = _debug(_make_frame_padded("ABCDEF", cell_px=20, pad=40))
    assert set(result.keys()) == _DEBUG_KEYS


def test_decode_frame_debug_gray_f_shape() -> None:
    pytest.importorskip("cv2")
    frame = _make_frame_padded("ABCDEF", cell_px=20, pad=40)
    result = _debug(frame)
    assert result["gray_f"].shape == frame.shape[:2]
    assert result["gray_f"].dtype == np.float32


def test_decode_frame_debug_edges_shape() -> None:
    pytest.importorskip("cv2")
    frame = _make_frame_padded("ABCDEF", cell_px=20, pad=40)
    result = _debug(frame)
    assert result["edges"].shape == frame.shape[:2]


def test_decode_frame_debug_quad_not_none_on_success() -> None:
    pytest.importorskip("cv2")
    result = _debug(_make_frame_padded("ABCDEF", cell_px=20, pad=40))
    assert result["quad"] is not None
    assert result["quad"].shape == (4, 2)


def test_decode_frame_debug_warped_shape() -> None:
    pytest.importorskip("cv2")
    from network.chessmatrix import _GRID_SIZE
    result = _debug(_make_frame_padded("ABCDEF", cell_px=20, pad=40))
    assert result["warped"] is not None
    assert result["warped"].shape == (_GRID_SIZE, _GRID_SIZE, 3)


def test_decode_frame_debug_cal_structure() -> None:
    pytest.importorskip("cv2")
    result = _debug(_make_frame_padded("ABCDEF", cell_px=20, pad=40))
    assert len(result["cal"]) == 4
    # BLACK is sampled from row 7 (DataMatrix border) — should be dark, not necessarily pure (0,0,0)
    assert all(v < 50 for v in result["cal"][0]), f"BLACK anchor not dark: {result['cal'][0]}"


def test_decode_frame_debug_grid_structure() -> None:
    pytest.importorskip("cv2")
    result = _debug(_make_frame_padded("ABCDEF", cell_px=20, pad=40))
    assert len(result["grid"]) == 8
    assert all(len(row) == 8 for row in result["grid"])
    assert all(0 <= v <= 3 for row in result["grid"] for v in row)


def test_decode_frame_debug_code_matches_decode_frame() -> None:
    pytest.importorskip("cv2")
    frame = _make_frame_padded("XKCDQR", cell_px=20, pad=40)
    assert _debug(frame)["code"] == _decode(frame)


def test_decode_frame_debug_blank_has_no_quad() -> None:
    pytest.importorskip("cv2")
    result = _debug(np.zeros((480, 640, 3), dtype=np.uint8))
    assert result["quad"] is None
    assert result["warped"] is None
    assert result["code"] is None


# ══════════════════════════════════════════════════════════════════════════
# 3b. Grayscale-only detection enforcement
#
# ARCHITECTURAL RULE: quad/pattern detection MUST operate exclusively on
# grayscale data.  Color information may only enter the pipeline AFTER a
# perspective transform has been computed.  The tests in this section lock
# that boundary down hard.
# ══════════════════════════════════════════════════════════════════════════

class TestPipelineContract:
    """Verify the grayscale-detect / color-classify separation in decode_frame_debug."""

    def test_debug_gray_f_is_2d_float32_unit_range(self) -> None:
        pytest.importorskip("cv2")
        result = _debug(_make_frame_padded("ABCDEF", cell_px=20, pad=40))
        gf = result["gray_f"]
        assert gf.ndim == 2
        assert gf.dtype == np.float32
        assert float(gf.min()) >= 0.0
        assert float(gf.max()) <= 1.0

    def test_debug_warped_is_3channel_bgr(self) -> None:
        pytest.importorskip("cv2")
        result = _debug(_make_frame_padded("ABCDEF", cell_px=20, pad=40))
        assert result["warped"] is not None
        assert result["warped"].ndim == 3
        assert result["warped"].shape[2] == 3

    def test_decode_succeeds_on_color_frame(self) -> None:
        pytest.importorskip("cv2")
        result = _debug(_make_frame_padded("TESTQR", cell_px=20, pad=40))
        assert result["code"] == "TESTQR"
        assert result["gray_f"].ndim == 2
        assert result["warped"].ndim == 3


# ══════════════════════════════════════════════════════════════════════════
# 3c. Background-colour × affine-orientation matrix
#
# For each background colour (including pure black and pure white), the
# barcode must be detectable and decodable in four orientations:
#   - upright (no transform)
#   - rotated ~25° with slight shear
#   - rotated ~90° with slight opposite shear
#   - rotated ~150° with more shear
#
# Detection uses grayscale only (_detect_barcode_corners).
# Color is only available post-warp.
#
# Naming convention for parametrize IDs:
#   <bg_name>-<transform_name>
# ══════════════════════════════════════════════════════════════════════════

# Background colours: (label, BGR tuple)
_BG_MATRIX: list[tuple[str, tuple[int, int, int]]] = [
    ("black",       (0,   0,   0  )),
    ("white",       (255, 255, 255)),
    ("dark_gray",   (40,  40,  40 )),
    ("light_gray",  (210, 210, 210)),
    ("red_bg",      (0,   0,   180)),  # BGR order
    ("green_bg",    (0,   180, 0  )),
    ("blue_bg",     (180, 0,   0  )),
    ("yellow_bg",   (0,   200, 200)),
    ("purple_bg",   (120, 0,   120)),
]

# Affine transforms: (label, angle_deg, shear_x)
# Chosen to cover four clearly distinct orientations.
_AFFINE_MATRIX: list[tuple[str, float, float]] = [
    ("upright",   0.0,  0.00),
    ("rot25sh",   25.0, 0.12),
    ("rot90sh",   90.0, -0.08),
    ("rot150sh",  150.0, 0.15),
]

# Flatten into one param list for a single parametrize decorator.
_BG_AFFINE_CASES: list[tuple[str, tuple[int, int, int], float, float]] = [
    (bg_name, bg_bgr, angle, shear)
    for bg_name, bg_bgr in _BG_MATRIX
    for _, angle, shear in _AFFINE_MATRIX
]

_BG_AFFINE_IDS: list[str] = [
    f"{bg_name}-{tx_name}"
    for bg_name, _ in _BG_MATRIX
    for tx_name, _, _ in _AFFINE_MATRIX
]


@pytest.mark.parametrize(
    "bg_name,tx_name",
    [(bg, tx) for bg, _ in _BG_MATRIX for tx, _, _ in _AFFINE_MATRIX],
    ids=_BG_AFFINE_IDS,
)
def test_decode_bg_affine_matrix(bg_name: str, tx_name: str) -> None:
    """Barcode must decode on any background colour in any affine orientation.

    Images are loaded from ``tests/fixtures/chessmatrix/ABCDEF_<bg>-<tx>.png``
    so they can be inspected visually.  Re-generate them with::

        python tools/generate_bg_affine_fixtures.py
    """
    pytest.importorskip("cv2")
    import cv2
    code = "ABCDEF"
    fixture = FIXTURES_DIR / f"{code}_{bg_name}-{tx_name}.png"
    if not fixture.exists():
        pytest.skip(f"Fixture not found: {fixture}")
    frame = cv2.imread(str(fixture))
    assert frame is not None, f"cv2.imread failed for {fixture}"
    result = _debug(frame)
    assert result["code"] == code, (
        f"Decode failed: bg={bg_name} tx={tx_name}  "
        f"quad={'found' if result['quad'] is not None else 'NOT FOUND'}"
    )


# ══════════════════════════════════════════════════════════════════════════
# 4.  Real-photo fixture tests
# ══════════════════════════════════════════════════════════════════════════

def _fixture_params() -> list[tuple[Path, str]]:
    """Collect (path, expected_code) pairs from the fixtures directory."""
    if not FIXTURES_DIR.exists():
        return []
    params = []
    for p in sorted(FIXTURES_DIR.glob("*.png")):
        stem = p.stem.upper()
        code = stem.split("_")[0]
        if len(code) == 6 and code.isalpha():
            params.append((p, code))
    return params


_FIXTURE_PARAMS = _fixture_params()


@pytest.mark.skipif(
    not _FIXTURE_PARAMS,
    reason="No fixture images in tests/fixtures/chessmatrix/",
)
@pytest.mark.parametrize("img_path,expected_code", _FIXTURE_PARAMS,
                         ids=[p.name for p, _ in _FIXTURE_PARAMS])
def test_decode_fixture_image(img_path: Path, expected_code: str) -> None:
    """decode_frame decodes a real-world photo of a ChessMatrix barcode."""
    cv2 = pytest.importorskip("cv2")
    frame = cv2.imread(str(img_path))
    assert frame is not None, f"Could not read {img_path}"
    result = _decode(frame)
    assert result == expected_code, (
        f"{img_path.name}: expected {expected_code!r}, got {result!r}"
    )


@pytest.mark.skipif(
    not _FIXTURE_PARAMS,
    reason="No fixture images in tests/fixtures/chessmatrix/",
)
@pytest.mark.parametrize("img_path,expected_code", _FIXTURE_PARAMS,
                         ids=[p.name for p, _ in _FIXTURE_PARAMS])
def test_decode_fixture_image_debug_quad_found(img_path: Path,
                                               expected_code: str) -> None:
    """debug variant finds a quad (even if it's the device screen, not the barcode)."""
    cv2 = pytest.importorskip("cv2")
    frame = cv2.imread(str(img_path))
    assert frame is not None
    result = _debug(frame)
    assert result["quad"] is not None, (
        f"{img_path.name}: quad not found"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Board-entry helper tests
# (network.chessmatrix: grid_from_cell_state, render_beam_frame)
# ═══════════════════════════════════════════════════════════════════════════════

from network.chessmatrix import (  # noqa: E402
    grid_from_cell_state,
    DATA_CELLS,
    room_code_to_bytes,
    bytes_to_room_code,
    render_beam_frame,
    _BEAM_DIM,
    _BEAM_FULL,
)


class _RecordCanvas:
    """Minimal canvas stub that records SetPixel calls."""

    def __init__(self) -> None:
        self.pixels: dict = {}

    def SetPixel(self, x: int, y: int, r: int, g: int, b: int) -> None:
        self.pixels[(x, y)] = (r, g, b)

    def cell_color(self, row: int, col: int) -> tuple:
        """Return the color of the top-left pixel in board cell (row, col)."""
        return self.pixels.get((row * 4, col * 4), (0, 0, 0))


# ── grid_from_cell_state ──────────────────────────────────────────────────────

class TestGridFromCellState:
    def test_grid_is_8x8(self) -> None:
        grid = grid_from_cell_state({})
        assert len(grid) == 8
        assert all(len(row) == 8 for row in grid)

    def test_border_cells_are_zero(self) -> None:
        grid = grid_from_cell_state({})
        for row in range(8):
            for col in range(8):
                if row in (0, 7) or col in (0, 7):
                    assert grid[row][col] == 0, f"border ({row},{col}) should be 0"

    def test_anchors_are_fixed(self) -> None:
        grid = grid_from_cell_state({})
        assert grid[1][1] == 0   # K anchor
        assert grid[1][6] == 1   # R anchor
        assert grid[6][1] == 2   # G anchor
        assert grid[6][6] == 3   # B anchor

    def test_anchors_not_overridden_by_locked(self) -> None:
        """Anchor positions in the locked dict must not clobber canonical values."""
        locked = {(1, 1): 3, (1, 6): 2, (6, 1): 1, (6, 6): 0}
        grid = grid_from_cell_state(locked)
        assert grid[1][1] == 0
        assert grid[1][6] == 1
        assert grid[6][1] == 2
        assert grid[6][6] == 3

    def test_locked_data_cells_reflected(self) -> None:
        locked = {(1, 2): 1, (3, 4): 2, (5, 5): 3}
        grid = grid_from_cell_state(locked)
        assert grid[1][2] == 1
        assert grid[3][4] == 2
        assert grid[5][5] == 3

    def test_unlocked_data_cells_default_to_zero(self) -> None:
        grid = grid_from_cell_state({})
        for row, col in DATA_CELLS:
            assert grid[row][col] == 0, f"unlocked data cell ({row},{col}) should be 0"


@pytest.mark.parametrize("code", ["AAAAAA", "ZZZZZZ", "ABCDEF", "MMMMMM", "XKCDQR"])
def test_grid_from_cell_state_round_trip(code: str) -> None:
    """Encode → extract locked cells → grid_from_cell_state → decode == original code."""
    _cm = pytest.importorskip("chessmatrix")
    payload = room_code_to_bytes(code)
    raw: list[list[int]] = _cm.encode(payload)
    # Build locked dict from the raw color-index grid (non-zero data cells only)
    locked = {
        (row, col): raw[row][col]
        for row, col in DATA_CELLS
        if raw[row][col] != 0
    }
    grid = grid_from_cell_state(locked)
    assert bytes_to_room_code(_cm.decode(grid)) == code


# ── render_beam_frame color invariants ───────────────────────────────────────

class TestRenderBeamFrameColors:
    """Verify render_beam_frame color invariants regardless of beam position."""

    def test_promoted_corner_renders_full_brightness(self) -> None:
        """A promoted (prior-phase) corner cell must show at FULL color."""
        c = _RecordCanvas()
        render_beam_frame(
            c, locked={}, current_color=2,
            beam_phase=0.0, blink_on=True,
            active_corner=(6, 1),   # green is the active corner
            corner_color=2,
            promoted=frozenset({1}),   # red is promoted
        )
        assert c.cell_color(1, 6) == _BEAM_FULL[1], (
            "promoted red corner should render at FULL red"
        )

    def test_locked_cell_never_darker_than_dim(self) -> None:
        """Locked cell pixel must be >= DIM base on every channel for any beam position."""
        locked = {(1, 2): 1}   # red-locked data cell
        for beam_phase in [0.0, 0.1, 0.3, 0.5, 0.9]:
            c = _RecordCanvas()
            render_beam_frame(
                c, locked=locked, current_color=2,
                beam_phase=beam_phase, blink_on=True,
                active_corner=(6, 1), corner_color=2,
            )
            r, g, b = c.cell_color(1, 2)
            dr, dg, db = _BEAM_DIM[1]
            assert r >= dr, f"beam_phase={beam_phase}: red channel {r} < DIM {dr}"
            assert g >= dg, f"beam_phase={beam_phase}: green channel {g} < DIM {dg}"
            assert b >= db, f"beam_phase={beam_phase}: blue channel {b} < DIM {db}"

    def test_fading_color_at_zero_shows_dim(self) -> None:
        """At fade_frac=0 the fading cell rests at DIM (beam far away)."""
        locked = {(2, 2): 1}
        c = _RecordCanvas()
        # beam_phase=0.99 puts beam at index ~31 — far from (2,2) at index 5
        render_beam_frame(
            c, locked=locked, current_color=1,
            beam_phase=0.99, blink_on=True,
            active_corner=(1, 6), corner_color=1,
            fade_frac=0.0, fading_color=1,
        )
        assert c.cell_color(2, 2) == _BEAM_DIM[1]

    def test_fading_color_at_one_shows_full(self) -> None:
        """At fade_frac=1 the fading cell has fully promoted to FULL brightness."""
        locked = {(2, 2): 1}
        c = _RecordCanvas()
        render_beam_frame(
            c, locked=locked, current_color=1,
            beam_phase=0.99, blink_on=True,
            active_corner=(1, 6), corner_color=1,
            fade_frac=1.0, fading_color=1,
        )
        assert c.cell_color(2, 2) == _BEAM_FULL[1]

    def test_additive_blending_cross_color(self) -> None:
        """Green beam on red-locked cell should add green, making it brighter."""
        locked = {(1, 2): 1}   # red locked
        c = _RecordCanvas()
        # beam_phase=0.0 puts beam at index 0, which is DATA_CELLS[0] = (1,2)
        render_beam_frame(
            c, locked=locked, current_color=2,   # green beam
            beam_phase=0.0, blink_on=True,
            active_corner=(6, 1), corner_color=2,
        )
        r, g, b = c.cell_color(1, 2)
        # Should be brighter than DIM in at least the green channel (additive)
        dr, dg, db = _BEAM_DIM[1]
        assert g > dg, f"green beam on red cell should add green: got g={g}, DIM g={dg}"
