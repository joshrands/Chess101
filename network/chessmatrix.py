"""ChessMatrix encode/decode helpers for Chess101 internet multiplayer.

ChessMatrix is an 8×8 four-color 2D barcode that encodes 4 bytes of payload
(with Reed-Solomon RS(8,4) error correction).  This module provides:

  - ``room_code_to_bytes`` / ``bytes_to_room_code`` — base-26 pack/unpack for
    6-character all-alpha room codes into 4 big-endian bytes.
  - ``encode`` — convert a room code into an 8×8 RGB grid suitable for
    rendering on the LED matrix.
  - ``render_to_led`` — paint an encoded grid onto any LED interface that
    exposes ``SetPixel(x, y, r, g, b)``.  Works with both ``FakeRGBMatrix``
    (simulator) and the real Pi ``FrameCanvas`` (Phase 2).
  - ``decode_frame`` — detect and decode a ChessMatrix in an OpenCV BGR frame,
    returning the room code string or ``None``.
  - ``decode_frame_debug`` — same as ``decode_frame`` but returns a dict of
    intermediate pipeline data for visualisation and testing.

The ``chessmatrix`` PyPI package (``pip install chessmatrix``) is required for
encoding and decoding.  ``opencv-python`` is required for ``decode_frame``.

Room code encoding convention
------------------------------
A 6-character uppercase alpha room code (A-Z only) is treated as a base-26
number with the leftmost character as the most significant digit:

    value = sum(ord(ch) - ord('A')) * 26^(5-i)  for i, ch in enumerate(code))

This value fits in a uint32 (max 26^6 - 1 = 308 915 775 < 2^32) and is
stored as 4 big-endian bytes, which become the ChessMatrix payload.
"""
from __future__ import annotations

import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

# ── ChessMatrix color table ────────────────────────────────────────────────
# Maps color index returned by the chessmatrix library to (R, G, B).
# -1=WHITE (timing / quiet-zone cells), 0=BLACK, 1=RED, 2=GREEN, 3=BLUE
# Colors match chessmatrix v1.1.0 (dark-mode palette).
_CM_RGB: dict[int, tuple[int, int, int]] = {
    -1: (235, 235, 235),  # WHITE  (timing / quiet-zone sentinel)
    0:  (10,  10,  10),   # BLACK
    1:  (220, 40,  40),   # RED
    2:  (40,  180, 40),   # GREEN
    3:  (40,  40,  220),  # BLUE
}


# ── 5-bit room code pack / unpack ──────────────────────────────────────────
# Each letter A-Z maps to 0-25.  Six letters × 5 bits = 30 bits, stored in
# the high 30 bits of a big-endian uint32 (low 2 bits are zero padding).
# This matches the npm ``chessmatrix`` package's ``lettersToBytes`` encoding.

def room_code_to_bytes(code: str) -> bytes:
    """Encode a 6-character all-alpha room code into 4 big-endian bytes.

    Uses 5-bit packing: each letter A-Z is stored as a 5-bit value (0-25)
    in the high 30 bits of a 32-bit word (low 2 bits are zero padding).
    This matches the npm ``chessmatrix`` package encoding.

    Args:
        code: Exactly 6 uppercase letters (A-Z).

    Returns:
        4-byte big-endian representation.

    Raises:
        ValueError: If *code* is not exactly 6 uppercase letters.
    """
    if len(code) != 6 or not code.isalpha():
        raise ValueError(f"Room code must be exactly 6 alpha characters, got {code!r}")
    code = code.upper()
    value = 0
    for ch in code:
        value = (value << 5) | (ord(ch) - ord('A'))
    return struct.pack(">I", value << 2)   # shift 2 for padding bits


def bytes_to_room_code(data: bytes) -> str:
    """Decode 4 big-endian bytes back into a 6-character all-alpha room code.

    Reverses ``room_code_to_bytes``: strips the 2 low padding bits then
    unpacks six 5-bit values into letters A-Z.

    Args:
        data: Exactly 4 bytes.

    Returns:
        A 6-character uppercase room code.

    Raises:
        ValueError: If *data* is not exactly 4 bytes or contains an
            out-of-range 5-bit group (> 25).
    """
    if len(data) != 4:
        raise ValueError(f"Expected 4 bytes, got {len(data)}")
    value: int = struct.unpack(">I", data)[0]
    value >>= 2   # remove 2 padding bits
    chars: list[str] = []
    for _ in range(6):
        n = value & 0x1F   # 5 LSBs
        if n > 25:
            raise ValueError(f"Room code bytes contain invalid letter index {n}")
        chars.append(chr(ord('A') + n))
        value >>= 5
    return "".join(reversed(chars))


# ── Encode ─────────────────────────────────────────────────────────────────

def encode(code: str) -> list[list[tuple[int, int, int]]]:
    """Encode a room code into an 8×8 grid of (R, G, B) tuples.

    Each cell in the returned grid corresponds to one ChessMatrix cell
    (one 4×4 LED block on the board).  Colors are drawn from ``_CM_RGB``.

    Args:
        code: A 6-character all-alpha room code.

    Returns:
        An 8×8 list of lists of (R, G, B) tuples.

    Raises:
        ImportError: If the ``chessmatrix`` package is not installed.
    """
    try:
        import chessmatrix as _cm  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "chessmatrix package not found — run: pip install chessmatrix"
        ) from exc

    payload = room_code_to_bytes(code)
    # chessmatrix v1.1.0 encode() returns an 8×8 Grid (List[List[int]]).
    # Values: 0=BLACK, 1=RED, 2=GREEN, 3=BLUE, -1=WHITE (timing cells).
    raw: list[list[int]] = _cm.encode(payload)

    # Dark mode: invert structural cells (row 0, row 7, col 0, col 7) so the
    # L-shaped finder bar and timing strips are visible on a dark LED background.
    #   K (0)  → white (235, 235, 235)
    #   WHITE (-1) → near-black (10, 10, 10)
    # Data/anchor cells in the interior (rows 1-6, cols 1-6) are unchanged.
    _WHITE_RGB = (235, 235, 235)
    _K_RGB     = (10,  10,  10)

    def _cell_rgb(r: int, c: int) -> tuple[int, int, int]:
        cell = raw[r][c]
        if r == 0 or r == 7 or c == 0 or c == 7:
            return _WHITE_RGB if cell == 0 else _K_RGB
        return _CM_RGB[cell]

    return [[_cell_rgb(r, c) for c in range(8)] for r in range(8)]


# ── Render to LED ──────────────────────────────────────────────────────────

def render_to_led(grid: list[list[tuple[int, int, int]]], canvas: object) -> None:
    """Paint an 8×8 RGB grid onto an LED canvas.

    Each cell (row, col) is rendered as a 4×4 block of identically-colored
    LED pixels.  The *canvas* object must expose ``SetPixel(x, y, r, g, b)``
    where *x* is the column pixel index (0-31) and *y* is the row pixel
    index (0-31).

    This function is hardware-agnostic: it works with ``FakeFrameCanvas``
    (simulator) and the real Pi ``FrameCanvas`` (Phase 2).

    The codebase-wide ``SetPixel`` convention is ``SetPixel(x=row_pixel,
    y=col_pixel)``, matching ``light_cell()`` in ``ui/renderer.py`` and the
    ``FakeFrameCanvas`` implementation.

    Args:
        grid: An 8×8 list of (R, G, B) tuples, e.g. from ``encode()``.
        canvas: Any object with ``SetPixel(x, y, r, g, b)``.
    """
    for row in range(8):
        for col in range(8):
            r, g, b = grid[row][col]
            for di in range(4):
                for dj in range(4):
                    # Codebase convention: SetPixel(x=row_pixel, y=col_pixel)
                    # matches light_cell() in ui/renderer.py and FakeFrameCanvas.
                    canvas.SetPixel(row * 4 + di, col * 4 + dj, r, g, b)  # type: ignore[attr-defined]


# ── CV constants ────────────────────────────────────────────────────────────

_CELL_PX   = 16          # pixels per cell in the canonical warped image
_GRID_SIZE = 8 * _CELL_PX  # canonical warped image side length (128 px)


# ── Private CV helpers ───────────────────────────────────────────────────────

def _local_threshold(
    gray_u8: "np.ndarray",
    window: int = 31,
    k1: float = 0.15,
    k2: float = 200.0,
) -> "np.ndarray":
    """Binarize a grayscale image using local mean–variance thresholding.

    For each pixel, the threshold is::

        T(x,y) = max(m(x,y) - k1 * s²(x,y),  k2)

    where *m* and *s²* are the local mean and variance computed over a
    sliding *window* × *window* neighbourhood.  Pixels brighter than T are
    set to 255 (foreground / white); all others to 0.

    This avoids the uniform-threshold pitfall where global illumination
    differences (e.g. a bright background vs. a dark LED matrix) cause the
    binarizer to treat one region as entirely foreground or background.

    Args:
        gray_u8: 2-D uint8 grayscale image.
        window:  Side length of the local neighbourhood (must be odd; default 31).
        k1:      Variance weight — higher values make the threshold more
                 sensitive to local contrast.
        k2:      Minimum threshold floor (prevents thresholding near-uniform
                 regions to noise).

    Returns:
        2-D uint8 binary image (0 or 255).
    """
    import cv2
    import numpy as np

    f = gray_u8.astype(np.float32)

    ksize = (window, window)
    mean    = cv2.boxFilter(f,     -1, ksize, normalize=True)
    mean_sq = cv2.boxFilter(f * f, -1, ksize, normalize=True)
    var     = np.maximum(mean_sq - mean * mean, 0.0)   # clamp rounding errors

    T = np.maximum(mean - k1 * var, k2)
    return np.where(f > T, np.uint8(255), np.uint8(0)).astype(np.uint8)


def _order_quad_corners(pts: "np.ndarray") -> "np.ndarray":
    """Return 4 corners in (TL, TR, BR, BL) order.

    TL has the smallest x+y sum; BR has the largest.
    TR has the smallest y-x difference; BL has the largest.

    Args:
        pts: (4, 2) array of corner coordinates (x, y).

    Returns:
        (4, 2) float32 array ordered [TL, TR, BR, BL].
    """
    import numpy as np
    pts = pts.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).flatten()
    ordered = np.zeros((4, 2), dtype=np.float32)
    ordered[0] = pts[np.argmin(s)]   # TL: smallest x+y
    ordered[2] = pts[np.argmax(s)]   # BR: largest x+y
    ordered[1] = pts[np.argmin(d)]   # TR: smallest y-x
    ordered[3] = pts[np.argmax(d)]   # BL: largest y-x
    return ordered


def _fix_timing_notch(pts: "np.ndarray") -> "np.ndarray | None":
    """Collapse a 5-corner timing-strip notch into a true 4-corner quad.

    The ChessMatrix timing strip creates a small step at one corner,
    causing contour approximation to return a 5-point polygon.  If exactly
    one edge is substantially shorter than the remaining four (< 40% of their
    mean length), that edge is the notch; its bounding lines are extended to
    their intersection to recover the true corner.

    Args:
        pts: (5, 2) float32 array.

    Returns:
        (4, 2) float32 array with the notch collapsed, or ``None`` if no
        clear notch edge is found.
    """
    import numpy as np

    if len(pts) != 5:
        return None

    pts = pts.reshape(5, 2).astype(np.float32)

    edges = np.array([
        float(np.linalg.norm(pts[(i + 1) % 5] - pts[i]))
        for i in range(5)
    ])

    min_idx  = int(np.argmin(edges))
    min_len  = edges[min_idx]
    other_mean = (edges.sum() - min_len) / 4.0

    if min_len >= other_mean * 0.4:
        return None   # no clear notch — genuine pentagon

    # Extend the edge *before* the notch and the edge *after* it; intersect.
    p_before     = pts[(min_idx - 1) % 5]
    p_notch_end  = pts[(min_idx + 1) % 5]
    p_after      = pts[(min_idx + 2) % 5]

    d1 = pts[min_idx] - p_before          # direction: edge leading into notch
    d2 = p_after - p_notch_end            # direction: edge leaving notch

    A = np.array([[d1[0], -d2[0]],
                  [d1[1], -d2[1]]], dtype=np.float64)
    b = (p_notch_end - p_before).astype(np.float64)

    try:
        t = np.linalg.solve(A, b)[0]
    except np.linalg.LinAlgError:
        return None

    true_corner = (p_before + t * d1).astype(np.float32)

    return np.array([
        p_before,
        true_corner,
        p_after,
        pts[(min_idx + 3) % 5],
    ], dtype=np.float32)


def _find_chessmatrix_quads(gray_f: "np.ndarray") -> list:
    """Return a list of quad candidates found in a grayscale image.

    Applies Canny edge detection then searches contours for quadrilaterals
    (or 5-corner polygons with a timing-strip notch).  Candidates are
    returned in descending area order.

    Args:
        gray_f: 2-D float32 array normalised to [0, 1].

    Returns:
        List of (4, 2) float32 corner arrays in (TL, TR, BR, BL) order.

    Raises:
        ValueError: If *gray_f* is not a 2-D array (e.g. a color image was
            passed).  The error message contains "grayscale".
    """
    import cv2
    import numpy as np

    if gray_f.ndim != 2:
        raise ValueError(
            f"_find_chessmatrix_quads requires a 2-D grayscale array; "
            f"got shape {gray_f.shape}.  Convert to grayscale first."
        )

    gray_u8 = (np.clip(gray_f, 0.0, 1.0) * 255).astype(np.uint8)
    h, w    = gray_u8.shape
    k       = max(3, int(min(h, w) * 0.015)) | 1   # adaptive radius, must be odd
    blurred = cv2.GaussianBlur(gray_u8, (k, k), 0)
    binary  = _local_threshold(blurred)
    edges    = cv2.Canny(binary, 30, 100)

    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    img_area = gray_f.shape[0] * gray_f.shape[1]
    min_area = img_area * 0.01

    quads: list = []
    for cnt in sorted(contours, key=cv2.contourArea, reverse=True):
        if cv2.contourArea(cnt) < min_area:
            break
        peri   = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
        n = len(approx)
        if n == 4:
            quads.append(_order_quad_corners(
                approx.reshape(4, 2).astype(np.float32)
            ))
        elif n == 5:
            fixed = _fix_timing_notch(approx.reshape(5, 2).astype(np.float32))
            if fixed is not None:
                quads.append(_order_quad_corners(fixed))
    return quads


def _find_chessmatrix_quad(gray_f: "np.ndarray") -> "np.ndarray | None":
    """Return the best quad candidate, or ``None`` if none found.

    Delegates to :func:`_find_chessmatrix_quads` and returns the first
    (largest-area) result.

    Args:
        gray_f: 2-D float32 array normalised to [0, 1].

    Returns:
        (4, 2) float32 corner array in (TL, TR, BR, BL) order, or ``None``.

    Raises:
        ValueError: If *gray_f* is not 2-D (proxied from
            :func:`_find_chessmatrix_quads`).
    """
    quads = _find_chessmatrix_quads(gray_f)
    return quads[0] if quads else None


# ── Public decode API ────────────────────────────────────────────────────────

def decode_frame(frame: "np.ndarray") -> "str | None":
    """Detect and decode a ChessMatrix barcode in an OpenCV BGR frame.

    Args:
        frame: An OpenCV BGR image (H×W×3, uint8).

    Returns:
        The decoded 6-character room code string, or ``None``.
    """
    return decode_frame_debug(frame)["code"]


def decode_frame_debug(frame: "np.ndarray") -> dict:
    """Detect a ChessMatrix barcode and return intermediate pipeline data.

    Pipeline (step 1 — detection only):
        1. Assert BGR uint8 input.
        2. Convert to float32 grayscale normalised to [0, 1] (``gray_f``).
        3. Canny edge detection (``edges``).
        4. Contour-based quad search (``quad``).

    Returns a dict with keys:
        ``code``   – str | None
        ``gray_f`` – float32 H×W array normalised to [0, 1]
        ``edges``  – uint8 H×W Canny edge map
        ``quad``   – (4,2) float32 corner array (TL/TR/BR/BL), or None
        ``warped`` – 128×128 BGR canonical image, or None (not yet impl.)
        ``cal``    – list of 4 (R,G,B) tuples, or None (not yet impl.)
        ``grid``   – 8×8 list[list[int]], or None (not yet impl.)
    """
    try:
        import cv2
    except ImportError as exc:
        raise ImportError(
            "opencv-python is required: pip install opencv-python"
        ) from exc

    import numpy as np

    assert frame.ndim == 3 and frame.shape[2] == 3, \
        "frame must be a 3-channel BGR uint8 image"
    assert frame.dtype == np.uint8, \
        "frame must be uint8"

    gray   = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    assert gray.ndim == 2 and gray.dtype == np.uint8

    gray_f = gray.astype(np.float32) / 255.0
    assert gray_f.dtype == np.float32
    assert gray_f.ndim == 2

    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    binary  = _local_threshold(blurred)
    edges   = cv2.Canny(binary, 30, 100)

    quad = _find_chessmatrix_quad(gray_f)

    return {
        "code":   None,
        "gray_f": gray_f,
        "edges":  edges,
        "quad":   quad,
        "warped": None,
        "cal":    None,
        "grid":   None,
    }
