"""Lockstep tests: Python vs JS ChessMatrix decode must always agree.

Feeds identical synthetic frames to both implementations and asserts they
return the same result (including both returning None/null).

Running
-------
    .venv/bin/python -m pytest tests/test_lockstep_chessmatrix.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Allow imports from the harness directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))

from python_bridge import JsBridge  # noqa: E402

# ── fixtures ────────────────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "chessmatrix"

ROOM_CODES = ["ABCDEF", "XKCDQR", "HELLOO", "ZYXWVU", "MRBEST"]


@pytest.fixture(scope="module")
def bridge():
    """Single JS bridge for the whole module — avoids respawning Node per test."""
    b = JsBridge()
    assert b.ping() == "pong"
    yield b
    b.close()


# ── helpers ─────────────────────────────────────────────────────────────────

def bgr_to_rgba(bgr: np.ndarray) -> bytes:
    """Convert an OpenCV BGR image to raw RGBA bytes for the JS bridge."""
    rgb = bgr[:, :, ::-1]  # BGR → RGB
    alpha = np.full((*rgb.shape[:2], 1), 255, dtype=np.uint8)
    rgba = np.concatenate([rgb, alpha], axis=2)
    return rgba.tobytes()


def py_decode(frame: np.ndarray) -> str | None:
    from network.chessmatrix import decode_frame
    return decode_frame(frame)


def js_decode(bridge: JsBridge, frame: np.ndarray) -> str | None:
    h, w = frame.shape[:2]
    rgba = bgr_to_rgba(frame)
    return bridge.decode_frame(rgba, w, h)


# ── synthetic frame factories (same as test_chessmatrix_scanning.py) ────────

def _make_frame(room_code: str, cell_px: int = 20) -> np.ndarray:
    from network.chessmatrix import encode
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
    barcode = _make_frame(room_code, cell_px=cell_px)
    h, w = barcode.shape[:2]
    canvas = np.full((h + 2 * pad, w + 2 * pad, 3), 220, dtype=np.uint8)
    canvas[pad:pad + h, pad:pad + w] = barcode
    return canvas


def _make_frame_rotated(room_code: str, angle_deg: float,
                        cell_px: int = 20, pad: int = 100) -> np.ndarray:
    import cv2
    src = _make_frame_padded(room_code, cell_px=cell_px, pad=pad)
    h, w = src.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle_deg, 1.0)
    return cv2.warpAffine(src, M, (w, h),
                          borderMode=cv2.BORDER_CONSTANT,
                          borderValue=(220, 220, 220))


def _make_frame_noisy(room_code: str, sigma: float = 15.0,
                      cell_px: int = 20, pad: int = 40) -> np.ndarray:
    rng = np.random.default_rng(42)
    base = _make_frame_padded(room_code, cell_px=cell_px, pad=pad)
    noise = rng.normal(0, sigma, base.shape).astype(np.float32)
    return np.clip(base.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def _make_frame_bright(room_code: str, factor: float = 1.4,
                       cell_px: int = 20, pad: int = 40) -> np.ndarray:
    base = _make_frame_padded(room_code, cell_px=cell_px, pad=pad)
    return np.clip(base.astype(np.float32) * factor, 0, 255).astype(np.uint8)


def _make_frame_dark(room_code: str, factor: float = 0.5,
                     cell_px: int = 20, pad: int = 40) -> np.ndarray:
    base = _make_frame_padded(room_code, cell_px=cell_px, pad=pad)
    return np.clip(base.astype(np.float32) * factor, 0, 255).astype(np.uint8)


# ── test classes ────────────────────────────────────────────────────────────

class TestCleanPadded:
    """Both sides must agree on clean, padded synthetic images."""

    @pytest.mark.parametrize("code", ROOM_CODES)
    @pytest.mark.parametrize("cell_px", [16, 20, 30])
    def test_padded(self, bridge, code, cell_px):
        frame = _make_frame_padded(code, cell_px=cell_px)
        py = py_decode(frame)
        js = js_decode(bridge, frame)
        assert py == js, f"Disagreement on {code} cell_px={cell_px}: py={py!r} js={js!r}"


class TestRotated:
    """Both sides must agree on rotated images."""

    @pytest.mark.parametrize("code", ["ABCDEF", "XKCDQR"])
    @pytest.mark.parametrize("angle", [15, 30, 45, 90, 135, 180, 270])
    def test_rotated(self, bridge, code, angle):
        frame = _make_frame_rotated(code, angle)
        py = py_decode(frame)
        js = js_decode(bridge, frame)
        assert py == js, f"Disagreement on {code} rot={angle}°: py={py!r} js={js!r}"


class TestNoise:
    """Both sides must agree on noisy images."""

    @pytest.mark.parametrize("code", ["ABCDEF", "HELLOO"])
    @pytest.mark.parametrize("sigma", [10, 20, 30])
    def test_noise(self, bridge, code, sigma):
        frame = _make_frame_noisy(code, sigma=sigma)
        py = py_decode(frame)
        js = js_decode(bridge, frame)
        assert py == js, f"Disagreement on {code} sigma={sigma}: py={py!r} js={js!r}"


class TestPhotometric:
    """Both sides must agree under brightness/darkness changes."""

    @pytest.mark.parametrize("code", ["ABCDEF", "ZYXWVU"])
    def test_bright(self, bridge, code):
        frame = _make_frame_bright(code)
        py = py_decode(frame)
        js = js_decode(bridge, frame)
        assert py == js, f"Bright disagree on {code}: py={py!r} js={js!r}"

    @pytest.mark.parametrize("code", ["ABCDEF", "ZYXWVU"])
    def test_dark(self, bridge, code):
        frame = _make_frame_dark(code)
        py = py_decode(frame)
        js = js_decode(bridge, frame)
        assert py == js, f"Dark disagree on {code}: py={py!r} js={js!r}"


class TestFixtures:
    """Both sides must agree on all real-photo PNG fixtures."""

    @staticmethod
    def _fixture_files():
        if not FIXTURES_DIR.is_dir():
            return []
        return sorted(FIXTURES_DIR.glob("*.png"))

    @pytest.mark.parametrize(
        "png",
        _fixture_files.__func__(),
        ids=lambda p: p.name,
    )
    def test_fixture(self, bridge, png):
        import cv2
        frame = cv2.imread(str(png))
        if frame is None:
            pytest.skip(f"Could not read {png.name}")
        py = py_decode(frame)
        js = js_decode(bridge, frame)
        assert py == js, f"Fixture {png.name}: py={py!r} js={js!r}"
