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
    """Return 4 corners in (TL, TR, BR, BL) order via angular CW sort.

    Sorts corners clockwise from centroid (atan2 from north), then picks the
    starting corner as the one with minimum (x+y), breaking ties by minimum y.
    This handles both axis-aligned rectangles and 45° diamonds correctly.

    Args:
        pts: (4, 2) array of corner coordinates (x, y).

    Returns:
        (4, 2) float32 array ordered [TL, TR, BR, BL].
    """
    import numpy as np
    pts = pts.reshape(4, 2).astype(np.float32)
    cx, cy = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 0] - cx, cy - pts[:, 1])  # CW from north
    cw_idx = np.argsort(angles)
    cw = pts[cw_idx]
    # Find TL: smallest (x+y), break ties by smallest y (handles diamonds)
    top_i = int(np.lexsort((cw[:, 1], cw[:, 0] + cw[:, 1]))[0])
    idx = [(top_i + i) % 4 for i in range(4)]
    return cw[idx]  # TL, TR, BR, BL


# ── Inflate-rect detection pipeline ──────────────────────────────────────────

def _inflate_rect(
    binary: "np.ndarray",
    cx: float,
    cy: float,
    tolerance: float = 0.08,
) -> "tuple[int, int, int, int]":
    """Grow an axis-aligned rect from (cx, cy) until each edge hits white content.

    Expands one pixel at a time in each direction, stopping a side when the
    fraction of white pixels on that edge reaches *tolerance*.

    Returns:
        (left, top, right, bottom) pixel coordinates.
    """
    h, w = binary.shape
    top = bottom = int(cy)
    left = right = int(cx)

    def _wf_h(row: int, l: int, r: int) -> float:
        return float(binary[row, l:r + 1].mean()) / 255.0

    def _wf_v(col: int, t: int, b: int) -> float:
        return float(binary[t:b + 1, col].mean()) / 255.0

    changed = True
    while changed:
        changed = False
        if top > 0 and _wf_h(top - 1, left, right) < tolerance:
            top -= 1;    changed = True
        if bottom < h - 1 and _wf_h(bottom + 1, left, right) < tolerance:
            bottom += 1; changed = True
        if left > 0 and _wf_v(left - 1, top, bottom) < tolerance:
            left -= 1;   changed = True
        if right < w - 1 and _wf_v(right + 1, top, bottom) < tolerance:
            right += 1;  changed = True

    return left, top, right, bottom


def _hough_axes(binary: "np.ndarray") -> "tuple[float, float] | None":
    """Return (angle1_deg, angle2_deg) dominant perpendicular axes, or None.

    Runs probabilistic Hough on Canny edges of *binary*, buckets segment angles
    into 1° bins weighted by length, folds to [0°, 90°), and returns the peak
    bin plus its perpendicular.
    """
    import cv2
    import numpy as np

    edges = cv2.Canny(binary, 30, 100)
    lines = cv2.HoughLinesP(edges, rho=1, theta=np.pi / 180,
                            threshold=20, minLineLength=10, maxLineGap=5)
    if lines is None:
        return None

    hist = np.zeros(180, dtype=np.float32)
    for x1, y1, x2, y2 in lines[:, 0]:
        angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180)
        hist[int(angle)] += float(np.hypot(x2 - x1, y2 - y1))

    folded = hist[:90] + hist[90:]
    a1 = int(np.argmax(folded))
    return float(a1), float((a1 + 90) % 180)


def _detect_barcode_corners(frame: "np.ndarray") -> "np.ndarray | None":
    """Run the inflate-rect pipeline and return outer (4/3-scaled) corners.

    Pipeline:
      1. Simple-average grayscale → contrast-normalize → adaptive blur
      2. Local mean-variance binarize
      3. White-pixel centroid
      4. Probabilistic Hough to find dominant axes
      5. Rotate binary to axis-aligned, inflate rect from centroid
      6. Un-rotate corners, scale 4/3 outward from inner centroid
      7. Angular-sort → TL/TR/BR/BL order

    Args:
        frame: BGR uint8 image (H×W×3).

    Returns:
        (4, 2) float32 corner array in (TL, TR, BR, BL) order, or ``None``.
    """
    import cv2
    import numpy as np

    gray_avg = np.mean(frame.astype(np.float32), axis=2)
    norm = cv2.normalize(gray_avg, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
    h, w = norm.shape
    k = max(3, int(min(h, w) * 0.015)) | 1
    blurred = cv2.GaussianBlur(norm, (k, k), 0)
    binary = _local_threshold(blurred)

    white = np.argwhere(binary > 0)
    if len(white) == 0:
        return None
    cy_c, cx_c = white.mean(axis=0)
    cx_c, cy_c = float(cx_c), float(cy_c)

    axes = _hough_axes(binary)
    if axes is None:
        return None

    a1, _ = axes
    align = a1 - 90.0
    M = cv2.getRotationMatrix2D((cx_c, cy_c), align, 1.0)
    rot = cv2.warpAffine(binary, M, (w, h), flags=cv2.INTER_NEAREST)
    l, t, r, b = _inflate_rect(rot, cx_c, cy_c)

    M_inv = cv2.getRotationMatrix2D((cx_c, cy_c), -align, 1.0)
    corners_rot = np.float32([[l, t], [r, t], [r, b], [l, b]])
    corners = (M_inv @ np.hstack([corners_rot,
                                  np.ones((4, 1), dtype=np.float32)]).T).T  # (4, 2)

    center = corners.mean(axis=0)
    outer = (corners - center) * (4.0 / 3.0) + center
    return _order_quad_corners(outer)


# ── Post-detection pipeline: warp → orient → calibrate → classify ────────────

# Anchor cell positions in the canonical oriented image (L-finder at BL).
# (row, col) for: K=black, R=red, G=green, B=blue
_CAL_ANCHORS: "list[tuple[int, int]]" = [(1, 1), (1, 6), (6, 1), (6, 6)]


def _warp_to_canonical(
    frame: "np.ndarray",
    corners: "np.ndarray",
    size: int = _GRID_SIZE,
) -> "np.ndarray | None":
    """Perspective-warp *frame* using *corners*, then orient so L-finder is at BL.

    Args:
        frame:   BGR uint8 image.
        corners: (4, 2) float32 in TL/TR/BR/BL order.
        size:    Output square side length (default ``_GRID_SIZE`` = 128).

    Returns:
        (*size*, *size*, 3) uint8 BGR image with the L-finder at bottom-left,
        or ``None`` if orientation cannot be determined.
    """
    import cv2
    import numpy as np

    n = float(size)
    dst = np.float32([[0, 0], [n - 1, 0], [n - 1, n - 1], [0, n - 1]])
    H = cv2.getPerspectiveTransform(corners.astype(np.float32), dst)
    warped_color = cv2.warpPerspective(frame, H, (size, size))

    # Recompute binary from frame for orientation detection
    gray_avg = np.mean(frame.astype(np.float32), axis=2)
    norm = cv2.normalize(gray_avg, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
    h_f, w_f = norm.shape
    k = max(3, int(min(h_f, w_f) * 0.015)) | 1
    blurred = cv2.GaussianBlur(norm, (k, k), 0)
    binary = _local_threshold(blurred)
    warped_binary = cv2.warpPerspective(binary, H, (size, size),
                                        flags=cv2.INTER_NEAREST)

    white = np.argwhere(warped_binary > 0)
    if len(white) == 0:
        return None
    ry, rx = white.mean(axis=0)
    cp = {'TL': (0.0, 0.0), 'TR': (n, 0.0), 'BL': (0.0, n), 'BR': (n, n)}
    l_corner = min(cp, key=lambda name: (rx - cp[name][0]) ** 2
                                      + (ry - cp[name][1]) ** 2)
    k_rot = {'TL': 1, 'TR': 2, 'BL': 0, 'BR': 3}[l_corner]
    return np.ascontiguousarray(np.rot90(warped_color, k=k_rot))


def _sample_cell_rgb(
    warped: "np.ndarray",
    row: int,
    col: int,
    cell_px: int,
    patch: int = 5,
) -> "tuple[int, int, int]":
    """Return mean (R, G, B) of a *patch*×*patch* region at the cell centre."""
    import numpy as np
    cx = col * cell_px + cell_px // 2
    cy = row * cell_px + cell_px // 2
    r = patch // 2
    bgr = warped[cy - r:cy + r + 1, cx - r:cx + r + 1].astype(np.float32).mean(axis=(0, 1))
    return int(bgr[2]), int(bgr[1]), int(bgr[0])  # R, G, B


def _build_calibration(
    warped: "np.ndarray",
    cell_px: int,
) -> "list[tuple[int, int, int]]":
    """Sample the four fixed-color anchor cells; return [(R,G,B)] for K, R, G, B."""
    return [_sample_cell_rgb(warped, r, c, cell_px) for r, c in _CAL_ANCHORS]


def _classify_cell(
    r: int,
    g: int,
    b: int,
    cal: "list[tuple[int, int, int]]",
) -> int:
    """Return 0–3 (K/R/G/B) for the nearest calibration color (L2 distance)."""
    best_d, best_i = float('inf'), 0
    for i, (cr, cg, cb) in enumerate(cal):
        d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if d < best_d:
            best_d, best_i = d, i
    return best_i


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
    """Detect and decode a ChessMatrix barcode, returning intermediate data.

    Pipeline:
        1. Assert BGR uint8 input.
        2. Grayscale (luminance) → float32 [0, 1] for ``gray_f`` / ``edges``.
        3. Inflate-rect detection → outer ``quad`` corners.
        4. Perspective warp + L-finder orientation → ``warped`` (128×128 BGR).
        5. 4-color calibration from anchor cells → ``cal``.
        6. Cell classification + RS decode → ``grid``, ``code``.

    Returns a dict with keys:
        ``code``   – 6-char room code string, or None
        ``gray_f`` – float32 H×W array normalised to [0, 1]
        ``edges``  – uint8 H×W Canny edge map
        ``quad``   – (4,2) float32 outer corner array (TL/TR/BR/BL), or None
        ``warped`` – (_GRID_SIZE, _GRID_SIZE, 3) BGR canonical image, or None
        ``cal``    – list of 4 (R,G,B) tuples [K,R,G,B], or None
        ``grid``   – 8×8 list[list[int]] (0–3), or None
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
    assert frame.dtype == np.uint8, "frame must be uint8"

    gray   = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray_f = gray.astype(np.float32) / 255.0

    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    binary  = _local_threshold(blurred)
    edges   = cv2.Canny(binary, 30, 100)

    quad   = _detect_barcode_corners(frame)
    warped = None
    cal    = None
    grid   = None
    code   = None

    if quad is not None:
        warped = _warp_to_canonical(frame, quad)
        if warped is not None:
            cal  = _build_calibration(warped, _CELL_PX)
            grid = [
                [_classify_cell(*_sample_cell_rgb(warped, r, c, _CELL_PX), cal)
                 for c in range(8)]
                for r in range(8)
            ]
            try:
                import chessmatrix as _cm  # type: ignore[import]
                code = bytes_to_room_code(_cm.decode(grid))
            except Exception:
                code = None

    return {
        "code":   code,
        "gray_f": gray_f,
        "edges":  edges,
        "quad":   quad,
        "warped": warped,
        "cal":    cal,
        "grid":   grid,
    }
