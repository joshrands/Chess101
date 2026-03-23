"""ChessMatrix encode/decode helpers for Chess101 internet multiplayer.

ChessMatrix is an 8×8 four-color 2D barcode that encodes 4 bytes of payload
(with Reed-Solomon RS(8,4) error correction).  This module provides:

  - ``room_code_to_bytes`` / ``bytes_to_room_code`` — base-26 pack/unpack for
    6-character all-alpha room codes into 4 big-endian bytes.
  - ``encode`` — convert a room code into an 8×8 RGB grid suitable for
    rendering on the LED matrix.
  - ``render_to_led`` — paint an encoded grid onto any LED interface that
    exposes ``SetPixel(x, y, r, g, b)``.  Works with both ``FakeRGBMatrix``
    (simulator) and the real Pi ``RGBMatrix`` canvas (Phase 2).
  - ``decode_frame`` — detect and decode a ChessMatrix in an OpenCV BGR frame,
    returning the room code string or ``None``.

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
# Maps color index (0-3) returned by the chessmatrix library to (R, G, B).
# BLACK=0, RED=1, GREEN=2, BLUE=3
_CM_RGB: dict[int, tuple[int, int, int]] = {
    0: (0,   0,   0),    # BLACK
    1: (220, 0,   0),    # RED
    2: (0,   180, 0),    # GREEN
    3: (0,   0,   220),  # BLUE
}


# ── Base-26 room code pack / unpack ────────────────────────────────────────

def room_code_to_bytes(code: str) -> bytes:
    """Encode a 6-character all-alpha room code into 4 big-endian bytes.

    Args:
        code: Exactly 6 uppercase letters (A-Z).

    Returns:
        4-byte big-endian representation of the base-26 value.

    Raises:
        ValueError: If *code* is not exactly 6 uppercase letters.
    """
    if len(code) != 6 or not code.isalpha():
        raise ValueError(f"Room code must be exactly 6 alpha characters, got {code!r}")
    code = code.upper()
    value = 0
    for ch in code:
        value = value * 26 + (ord(ch) - ord('A'))
    return struct.pack(">I", value)   # big-endian uint32


def bytes_to_room_code(data: bytes) -> str:
    """Decode 4 big-endian bytes back into a 6-character all-alpha room code.

    Args:
        data: Exactly 4 bytes.

    Returns:
        A 6-character uppercase room code.

    Raises:
        ValueError: If *data* is not exactly 4 bytes or represents a value
            outside the valid range.
    """
    if len(data) != 4:
        raise ValueError(f"Expected 4 bytes, got {len(data)}")
    value: int = struct.unpack(">I", data)[0]
    max_value = 26 ** 6 - 1   # 308 915 775
    if value > max_value:
        raise ValueError(f"Value {value} out of range for 6-char alpha code")
    chars: list[str] = []
    for _ in range(6):
        value, rem = divmod(value, 26)
        chars.append(chr(ord('A') + rem))
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
    # chessmatrix.encode returns an 8×8 structure of color indices (0-3).
    raw = _cm.encode(payload)   # list[list[int]] or flat list[int]

    # Normalise: accept both flat (64 ints) and 8×8 nested lists.
    # Flat layout is assumed to be row-major (row-first), same as nested.
    if raw and not isinstance(raw[0], (list, tuple)):
        raw = [raw[i * 8:(i + 1) * 8] for i in range(8)]

    # The library returns row-major: raw[row][col].  No transpose needed —
    # pass through directly so grid[row][col] matches what decode() expects.
    return [[_CM_RGB.get(int(raw[r][c]), (255, 255, 255)) for c in range(8)]
            for r in range(8)]


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


# ── Decode from camera frame ────────────────────────────────────────────────

def decode_frame(frame: "np.ndarray") -> str | None:
    """Detect and decode a ChessMatrix barcode in an OpenCV BGR frame.

    Args:
        frame: An OpenCV BGR image as a NumPy array (shape H×W×3, dtype uint8).

    Returns:
        The decoded 6-character room code string, or ``None`` if no valid
        ChessMatrix is found in the frame.

    Raises:
        ImportError: If the ``chessmatrix`` package is not installed.
    """
    try:
        import chessmatrix as _cm  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "chessmatrix package not found — run: pip install chessmatrix"
        ) from exc

    result = _cm.decode(frame)   # bytes | None
    if result is None:
        return None
    try:
        return bytes_to_room_code(result)
    except (ValueError, struct.error):
        return None
