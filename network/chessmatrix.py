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

import math as _math
import struct
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

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
                    canvas.SetPixel(col * 4 + dj, row * 4 + di, r, g, b)  # type: ignore[attr-defined]


# ── Board-entry helpers ─────────────────────────────────────────────────────

# Variable data cell positions (row-major, interior 6×6 minus the 4 anchors).
# Index in this list maps to beam position 0–31.
DATA_CELLS: list[tuple[int, int]] = [
    (r, c) for r in range(1, 7) for c in range(1, 7)
    if (r, c) not in {(1, 1), (1, 6), (6, 1), (6, 6)}
]

# Calibration anchor positions: K=black(0), R=red(1), G=green(2), B=blue(3).
# Row/col indices are fixed by the ChessMatrix spec (L-finder at BL orientation).
_CAL_ANCHORS: list[tuple[int, int]] = [(1, 1), (1, 6), (6, 1), (6, 6)]
_ANCHOR_IDX: dict[tuple[int, int], int] = {pos: i for i, pos in enumerate(_CAL_ANCHORS)}


def _set_cell(canvas: object, row: int, col: int, r: int, g: int, b: int) -> None:
    """Paint a single 4×4 LED block for board cell (row, col)."""
    for di in range(4):
        for dj in range(4):
            canvas.SetPixel(col * 4 + dj, row * 4 + di, r, g, b)  # type: ignore[attr-defined]


def render_border_only(canvas: object) -> None:
    """Paint the 28-cell structural border in dark-mode ChessMatrix colors.

    The outer ring (row 0, row 7, col 0, col 7) is rendered with the
    dark-mode inversion used by ``encode()``: original-BLACK cells become
    bright white, original-WHITE/-1 cells become near-black.  The interior
    6×6 is painted black (off).

    This shows the fixed ChessMatrix anchor/timing pattern without needing
    a room code — used during CODE_SCAN_BOARD before any data is entered.
    """
    try:
        import chessmatrix as _cm  # type: ignore[import]
    except ImportError:
        # No chessmatrix package — paint a simple white border as fallback
        for row in range(8):
            for col in range(8):
                if row in (0, 7) or col in (0, 7):
                    _set_cell(canvas, row, col, 235, 235, 235)
                else:
                    _set_cell(canvas, row, col, 0, 0, 0)
        return

    # Use the canonical border from any encoded payload (border is payload-independent).
    _DUMMY_PAYLOAD = b"\x00\x00\x00\x00"
    raw: list[list[int]] = _cm.encode(_DUMMY_PAYLOAD)
    _WHITE_RGB = (235, 235, 235)
    _K_RGB     = (10,  10,  10)

    for row in range(8):
        for col in range(8):
            if row in (0, 7) or col in (0, 7):
                cell = raw[row][col]
                rgb = _WHITE_RGB if cell == 0 else _K_RGB
            else:
                rgb = (0, 0, 0)
            _set_cell(canvas, row, col, *rgb)


# Color palette for beam rendering — full saturation and ~80% dim base
_BEAM_FULL: dict[int, tuple[int, int, int]] = {
    1: (255, 0,   0),    # RED
    2: (0,   255, 0),    # GREEN
    3: (0,   0,   255),  # BLUE
}
_BEAM_DIM: dict[int, tuple[int, int, int]] = {
    1: (200, 0,   0),    # RED   ~80%
    2: (0,   200, 0),    # GREEN ~80%
    3: (0,   0,   200),  # BLUE  ~80%
}


class BarcodeColor(int, Enum):
    """Color indices used by the ChessMatrix spec.

    Inherits from ``int`` so members compare equal to their integer values
    and can index ``_BEAM_FULL`` / ``_BEAM_DIM`` without conversion.
    """
    BLACK = 0
    RED   = 1
    GREEN = 2
    BLUE  = 3


def _add_colors(
    a: tuple[int, int, int],
    b: tuple[int, int, int],
) -> tuple[int, int, int]:
    """Channel-wise additive blend of two RGB tuples, clamped to [0, 255]."""
    return (min(a[0] + b[0], 255), min(a[1] + b[1], 255), min(a[2] + b[2], 255))


# ── Animation timing and brightness constants ──────────────────────────────────
# Beam sweep: 32 data cells visited in one cycle
_BEAM_SWEEP_S: float          = 0.8        # full cycle duration (seconds)
_CELL_PERIOD_S: float         = 0.8 / 32   # seconds per cell
_TRAIL_FADE_S: float          = 0.5        # beam trail decay (seconds)
_EXCITE_FLASH_S: float        = 0.15       # toggle-on flash duration (seconds)
_BEAM_HEAD_BRIGHTNESS: float  = 0.5        # peak brightness multiplier on unoccupied cells

# Corner animation
_CORNER_FADE_S: float         = 3.0        # corner piece fade-out duration (seconds)
_BLINK_PERIOD_S: float        = 0.5        # wait-state corner blink period (seconds)
_INACTIVITY_S: float          = 5.0        # idle time before inactivity pulse (seconds)
_PULSE_BASE: float            = 0.7        # sine pulse floor
_PULSE_AMP: float             = 0.3        # sine pulse amplitude


# ── Scan phase state machine ────────────────────────────────────────────────────

class ScanPhase(str, Enum):
    """Sub-states for the CODE_SCAN_BOARD board-entry UX.

    Inherits from ``str`` so members compare equal to their string values,
    keeping existing string-comparison code compatible without changes.

    The three color phases each have three modes — wait (corner not yet
    placed), active (corner placed, user toggles data cells), and fading
    (corner removed, 3-second commit countdown) — followed by decoding.
    """
    RED_WAIT     = "red_wait"
    RED_ACTIVE   = "red_active"
    RED_FADING   = "red_fading"
    GREEN_WAIT   = "green_wait"
    GREEN_ACTIVE = "green_active"
    GREEN_FADING = "green_fading"
    BLUE_WAIT    = "blue_wait"
    BLUE_ACTIVE  = "blue_active"
    BLUE_FADING  = "blue_fading"
    DECODING     = "decoding"

    @property
    def color(self) -> BarcodeColor:
        """The barcode color associated with this phase."""
        _map = {"red": BarcodeColor.RED, "green": BarcodeColor.GREEN,
                "blue": BarcodeColor.BLUE}
        return _map.get(self.value.split("_")[0], BarcodeColor.BLACK)

    @property
    def corner(self) -> "tuple[int, int] | None":
        """Board cell (row, col) of the phase's entry corner, or None."""
        _map: dict[str, tuple[int, int]] = {
            "red": (1, 6), "green": (6, 1), "blue": (6, 6),
        }
        return _map.get(self.value.split("_")[0])

    @property
    def is_wait(self) -> bool:
        """True when waiting for the user to place the corner piece."""
        return self.value.endswith("_wait")

    @property
    def is_active(self) -> bool:
        """True when the corner is placed and data cells can be toggled."""
        return self.value.endswith("_active")

    @property
    def is_fading(self) -> bool:
        """True during the 3-second commit countdown after corner removal."""
        return self.value.endswith("_fading")

    @property
    def next_phase(self) -> "ScanPhase":
        """The phase that follows this fading state after commit."""
        _next: dict[ScanPhase, ScanPhase] = {
            ScanPhase.RED_FADING:   ScanPhase.GREEN_WAIT,
            ScanPhase.GREEN_FADING: ScanPhase.BLUE_WAIT,
            ScanPhase.BLUE_FADING:  ScanPhase.DECODING,
        }
        return _next[self]


# Colors that have been fully committed (promoted) at each phase.
# Promoted colors render their data cells at FULL brightness (vs. DIM).
_PROMOTED_SET: dict[ScanPhase, "frozenset[int]"] = {
    ScanPhase.GREEN_WAIT:    frozenset({BarcodeColor.RED}),
    ScanPhase.GREEN_ACTIVE:  frozenset({BarcodeColor.RED}),
    ScanPhase.GREEN_FADING:  frozenset({BarcodeColor.RED}),
    ScanPhase.BLUE_WAIT:     frozenset({BarcodeColor.RED,   BarcodeColor.GREEN}),
    ScanPhase.BLUE_ACTIVE:   frozenset({BarcodeColor.RED,   BarcodeColor.GREEN}),
    ScanPhase.BLUE_FADING:   frozenset({BarcodeColor.RED,   BarcodeColor.GREEN}),
    ScanPhase.DECODING:      frozenset({BarcodeColor.RED,   BarcodeColor.GREEN,
                                        BarcodeColor.BLUE}),
}


# ── Board-entry state and render parameter types ────────────────────────────────

@dataclass
class CodeScanState:
    """All mutable state for the CODE_SCAN_BOARD board-entry UX.

    A single instance replaces the seven loose ``_cs_*`` instance variables
    previously scattered across ``NetworkedGameRunner``.
    """
    phase: ScanPhase = ScanPhase.RED_WAIT
    locked: "dict[tuple[int, int], int]" = field(default_factory=dict)
    pending: "set[tuple[int, int]]"      = field(default_factory=set)
    fade_start: "Optional[float]"        = None
    last_activity: "Optional[float]"     = None
    excite_times: "dict[tuple[int, int], float]" = field(default_factory=dict)
    typing: bool = False

    def reset(self) -> None:
        """Restore to the initial red_wait state."""
        self.phase         = ScanPhase.RED_WAIT
        self.locked        = {}
        self.pending       = set()
        self.fade_start    = None
        self.last_activity = None
        self.excite_times  = {}
        self.typing        = False


@dataclass
class BeamRenderParams:
    """All parameters needed to draw one frame of the beam-entry animation.

    Build with ``from_scan_state`` to derive all values from a ``CodeScanState``
    at a given timestamp, then pass to ``render_beam_frame_from_params``.
    """
    locked: "dict[tuple[int, int], int]"
    current_color: int
    beam_phase: float
    blink_on: bool
    active_corner: "tuple[int, int] | None"     = None
    fade_frac: float                             = 0.0
    corner_color: int                            = 0
    corner_pulsing: bool                         = False
    pulse_t: float                               = 0.0
    extra_excite: "frozenset[tuple[int, int]]"   = field(default_factory=frozenset)
    fading_color: int                            = 0
    promoted: "frozenset[int]"                   = field(default_factory=frozenset)

    @classmethod
    def from_scan_state(cls, cs: CodeScanState, now: float) -> "BeamRenderParams":
        """Derive all render parameters from *cs* at timestamp *now*."""
        phase = ScanPhase(cs.phase)

        fade_frac, fading_color = 0.0, 0
        if phase.is_fading and cs.fade_start is not None:
            fade_frac    = min((now - cs.fade_start) / _CORNER_FADE_S, 1.0)
            fading_color = int(phase.color)

        active_color = int(phase.color) if (phase.is_active or phase.is_fading) else 0
        display_locked: "dict[tuple[int, int], int]" = dict(cs.locked)
        if active_color:
            for cell in cs.pending:
                display_locked[cell] = active_color

        blink_on = (
            (now % _BLINK_PERIOD_S) < _BLINK_PERIOD_S / 2
            if phase.is_wait else True
        )
        corner_pulsing = (
            phase.is_active
            and cs.last_activity is not None
            and (now - cs.last_activity) >= _INACTIVITY_S
        )
        extra_excite: frozenset[tuple[int, int]] = frozenset(
            cell for cell, t in cs.excite_times.items()
            if now - t < _EXCITE_FLASH_S
        )

        return cls(
            locked        = display_locked,
            current_color = active_color,
            beam_phase    = (now % _BEAM_SWEEP_S) / _BEAM_SWEEP_S,
            blink_on      = blink_on,
            active_corner = phase.corner,
            fade_frac     = fade_frac,
            corner_color  = int(phase.color),
            corner_pulsing= corner_pulsing,
            pulse_t       = now,
            extra_excite  = extra_excite,
            fading_color  = fading_color,
            promoted      = _PROMOTED_SET.get(phase, frozenset()),
        )


def render_beam_frame(
    canvas: object,
    locked: dict,
    current_color: int,
    beam_phase: float,
    blink_on: bool,
    active_corner: "tuple[int,int] | None" = None,
    fade_frac: float = 0.0,
    corner_color: int = 0,
    corner_pulsing: bool = False,
    pulse_t: float = 0.0,
    extra_excite: "frozenset | set" = frozenset(),
    fading_color: int = 0,
    promoted: "frozenset | set" = frozenset(),
) -> None:
    """Render one animation frame for the board-entry ChessMatrix UX.

    Corner rendering modes (mutually exclusive, checked in order):
      - fade_frac > 0  → straight linear fade to black (no blink, no pulse)
      - corner_pulsing → slow sine-wave pulse (inactivity hint)
      - blink_on       → hard on/off blink (wait state, action required)
      - otherwise      → solid full brightness (active, recently used)
    """
    _corner_color = corner_color or current_color
    render_border_only(canvas)

    # K anchor (1,1) — always off
    _set_cell(canvas, 1, 1, 0, 0, 0)

    # Fixed anchor cells (R/G/B corners)
    for (arow, acol), acolor in (((1, 6), 1), ((6, 1), 2), ((6, 6), 3)):
        if (arow, acol) == active_corner and _corner_color:
            br = _BEAM_FULL[_corner_color]
            if fade_frac > 0.0:
                # Fading out: straight linear fade, no pulse or blink
                brightness = 1.0 - fade_frac
            elif corner_pulsing:
                # Inactivity hint: slow sine pulse
                brightness = _PULSE_BASE + _PULSE_AMP * _math.sin(2.0 * _math.pi * pulse_t)
            elif not blink_on:
                # Wait state blink: off half
                brightness = 0.0
            else:
                # Wait state blink: on half, OR active/solid (blink_on=True by default)
                brightness = 1.0
            _set_cell(canvas, arow, acol,
                      int(br[0] * max(brightness, 0.0)),
                      int(br[1] * max(brightness, 0.0)),
                      int(br[2] * max(brightness, 0.0)))
        elif (arow, acol) == active_corner:
            _set_cell(canvas, arow, acol, 0, 0, 0)
        elif acolor in promoted:
            _set_cell(canvas, arow, acol, *_BEAM_FULL[acolor])
        elif acolor in locked.values():
            dim = _BEAM_DIM[acolor]
            _set_cell(canvas, arow, acol, *dim)
        else:
            _set_cell(canvas, arow, acol, 0, 0, 0)

    # Data cells — time-based decaying trail
    # The beam sweeps all 32 cells in _BEAM_SWEEP_S → _CELL_PERIOD_S per cell.
    # For each cell, compute how long ago the beam passed it; lerp from excite
    # color down to base (locked) or off (unlocked) over _TRAIL_FADE_S seconds.
    # All brightness is scaled by (1 - fade_frac) so the beam dims in sync with
    # the corner during the phase-transition fade.
    beam_idx_float = beam_phase * 32
    _beam_scale    = 1.0 - fade_frac   # applied to every data cell

    for i, (row, col) in enumerate(DATA_CELLS):
        cell_lock = locked.get((row, col), 0)

        # Recently toggled-on: flash at full brightness (ignores fade_frac
        # intentionally — toggle feedback should punch through the fade)
        if (row, col) in extra_excite:
            if cell_lock:
                excite_rgb = (
                    _add_colors(_BEAM_FULL[cell_lock], _BEAM_FULL[current_color])
                    if current_color else _BEAM_FULL[cell_lock]
                )
            else:
                excite_rgb = _BEAM_FULL[current_color] if current_color else (200, 200, 200)
            _set_cell(canvas, row, col, *excite_rgb)
            continue

        # How many seconds ago did the beam pass this cell?
        trail_cells = (beam_idx_float - i) % 32
        age_s = trail_cells * _CELL_PERIOD_S
        frac = min(age_s / _TRAIL_FADE_S, 1.0)   # 0 = just hit, 1 = fully faded

        if cell_lock:
            # Locked cells are always at least their base color.
            # Promoted cells (prior phase completed) → permanently at FULL brightness.
            # Fading-color cells → lerp DIM→FULL as the corner fades out (fade_frac 0→1).
            # All others → DIM.
            if cell_lock in promoted:
                base_rgb = _BEAM_FULL[cell_lock]
            elif cell_lock == fading_color:
                dim = _BEAM_DIM[cell_lock]
                full = _BEAM_FULL[cell_lock]
                base_rgb = (
                    int(dim[0] + (full[0] - dim[0]) * fade_frac),
                    int(dim[1] + (full[1] - dim[1]) * fade_frac),
                    int(dim[2] + (full[2] - dim[2]) * fade_frac),
                )
            else:
                base_rgb = _BEAM_DIM[cell_lock]
            if current_color and age_s < _TRAIL_FADE_S:
                beam_rgb = _BEAM_FULL[current_color]
                peak_r = min(255, base_rgb[0] + int(beam_rgb[0] * _BEAM_HEAD_BRIGHTNESS))
                peak_g = min(255, base_rgb[1] + int(beam_rgb[1] * _BEAM_HEAD_BRIGHTNESS))
                peak_b = min(255, base_rgb[2] + int(beam_rgb[2] * _BEAM_HEAD_BRIGHTNESS))
                r = int(peak_r * (1 - frac) + base_rgb[0] * frac)
                g = int(peak_g * (1 - frac) + base_rgb[1] * frac)
                b = int(peak_b * (1 - frac) + base_rgb[2] * frac)
            else:
                r, g, b = base_rgb
            _set_cell(canvas, row, col, r, g, b)
        elif current_color and age_s < _TRAIL_FADE_S:
            # Unoccupied: bright head fading to black over _TRAIL_FADE_S
            fc = _BEAM_FULL[current_color]
            brightness = _BEAM_HEAD_BRIGHTNESS * (1.0 - frac) * _beam_scale
            _set_cell(canvas, row, col,
                      int(fc[0] * brightness),
                      int(fc[1] * brightness),
                      int(fc[2] * brightness))
        else:
            _set_cell(canvas, row, col, 0, 0, 0)


def render_beam_frame_from_params(canvas: object, params: BeamRenderParams) -> None:
    """Render one animation frame from a :class:`BeamRenderParams` bundle.

    Thin wrapper around :func:`render_beam_frame` for callers that build
    parameters via ``BeamRenderParams.from_scan_state`` rather than passing
    each argument individually.
    """
    render_beam_frame(
        canvas,
        params.locked,
        params.current_color,
        params.beam_phase,
        params.blink_on,
        active_corner  = params.active_corner,
        fade_frac      = params.fade_frac,
        corner_color   = params.corner_color,
        corner_pulsing = params.corner_pulsing,
        pulse_t        = params.pulse_t,
        extra_excite   = params.extra_excite,
        fading_color   = params.fading_color,
        promoted       = params.promoted,
    )


def grid_from_cell_state(locked: dict) -> "list[list[int]]":
    """Build an 8×8 color-index grid from user-entered cell state.

    Border cells are set to 0 (the library ignores structural cells during
    payload decode).  Calibration anchor cells use their fixed indices
    (K=0, R=1, G=2, B=3).  Variable data cells are filled from *locked*
    (0 = BLACK if absent).

    Args:
        locked: Dict mapping (row, col) → color index (1=R, 2=G, 3=B)
                for cells the user has marked.

    Returns:
        An 8×8 ``list[list[int]]`` with values 0–3 suitable for
        ``chessmatrix.decode()``.
    """
    grid: list[list[int]] = [[0] * 8 for _ in range(8)]
    for row in range(1, 7):
        for col in range(1, 7):
            if (row, col) in _ANCHOR_IDX:
                grid[row][col] = _ANCHOR_IDX[(row, col)]
            else:
                grid[row][col] = locked.get((row, col), 0)
    return grid


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


def _sobel_axes(norm: "np.ndarray") -> "tuple[float, float] | None":
    """Return (angle1_deg, angle2_deg) via Sobel gradients on normalized grayscale.

    Runs on the contrast-normalized grayscale (uint8) *before* binarization.
    Binary images have staircase artifacts that alias small rotations to 0°/90°,
    so grayscale preserves the true edge orientation.

    Builds a magnitude-weighted angle histogram in [0, 180).  After finding a1
    (the global peak), its ±15° neighbourhood is suppressed and a2 is the next
    largest peak.
    """
    import cv2
    import numpy as np

    gx = cv2.Sobel(norm, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(norm, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(gx * gx + gy * gy)

    mask = mag >= 100
    gx_sel = gx[mask]
    gy_sel = gy[mask]
    mag_sel = mag[mask]

    if len(mag_sel) == 0:
        return None

    # Gradient direction via arctan2(gy, gx), then +90° to get line direction
    # (line is perpendicular to its gradient).
    angles = (np.degrees(np.arctan2(gy_sel, gx_sel)) + 90) % 180
    bins = np.clip(angles.astype(np.int32), 0, 179)

    hist = np.zeros(180, dtype=np.float32)
    np.add.at(hist, bins, mag_sel)

    a1 = int(np.argmax(hist))
    if hist[a1] == 0:
        return None

    suppressed = hist.copy()
    for d in range(-15, 16):
        suppressed[(a1 + d) % 180] = 0
    a2 = int(np.argmax(suppressed))
    return float(a1), float(a2)


def _hough_axes(binary: "np.ndarray") -> "tuple[float, float] | None":
    """Return (angle1_deg, angle2_deg) via probabilistic Hough line segments.

    Kept as a fallback — see ``_sobel_axes`` for the preferred approach.

    Angles are in [0, 180).  The two peaks are found independently in the
    full unfolded histogram so that genuinely non-perpendicular axes (shear)
    are detected correctly.  After finding a1 (the global peak), its ±15°
    neighbourhood is suppressed and a2 is the next largest peak.
    """
    import cv2
    import numpy as np

    h, w = binary.shape
    k = max(3, min(int(min(h, w) * 0.015), 15)) | 1
    smoothed = cv2.boxFilter(binary, -1, (k, k))
    edges = cv2.Canny(smoothed, 30, 100)
    lines = cv2.HoughLinesP(edges, rho=1, theta=np.pi / 180,
                            threshold=20, minLineLength=10, maxLineGap=5)
    if lines is None:
        return None

    hist = np.zeros(180, dtype=np.float32)
    for x1, y1, x2, y2 in lines[:, 0]:
        angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180)
        hist[int(angle)] += float(np.hypot(x2 - x1, y2 - y1))

    # Find two dominant peaks in the full [0,180) space (no folding),
    # so sheared axes that are not 90° apart are captured correctly.
    a1 = int(np.argmax(hist))
    suppressed = hist.copy()
    for d in range(-15, 16):
        suppressed[(a1 + d) % 180] = 0
    a2 = int(np.argmax(suppressed))
    return float(a1), float(a2)


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

    axes = _sobel_axes(norm)
    if axes is None:
        return None

    a1, a2 = axes
    a1_rad = np.radians(a1)
    a2_rad = np.radians(a2)
    # u1 is the direction we want to map to vertical (0,1)
    # u2 is the direction we want to map to horizontal (1,0)
    u1 = np.array([np.cos(a1_rad), np.sin(a1_rad)], dtype=np.float64)
    u2 = np.array([np.cos(a2_rad), np.sin(a2_rad)], dtype=np.float64)
    # A maps (1,0)→u2, (0,1)→u1  so  A^{-1} maps u2→(1,0), u1→(0,1)
    A = np.column_stack([u2, u1])
    if abs(np.linalg.det(A)) < 0.05:
        # Degenerate (axes nearly parallel): assume u2 is perpendicular to u1
        u2 = np.array([-np.sin(a1_rad), np.cos(a1_rad)], dtype=np.float64)
        A = np.column_stack([u2, u1])
    M2 = np.linalg.inv(A)
    # Build 2×3 affine matrices centered at (cx_c, cy_c)
    def _affine2x3(m2x2, cx, cy):
        return np.float32([
            [m2x2[0, 0], m2x2[0, 1], cx - m2x2[0, 0] * cx - m2x2[0, 1] * cy],
            [m2x2[1, 0], m2x2[1, 1], cy - m2x2[1, 0] * cx - m2x2[1, 1] * cy],
        ])
    M_fwd = _affine2x3(M2, cx_c, cy_c)   # original → unsheared
    M_inv = _affine2x3(A,  cx_c, cy_c)   # unsheared → original
    unsheared = cv2.warpAffine(binary, M_fwd, (w, h), flags=cv2.INTER_NEAREST)
    l, t, r, b = _inflate_rect(unsheared, cx_c, cy_c)

    corners_rot = np.float32([[l, t], [r, t], [r, b], [l, b]])
    corners = (M_inv @ np.hstack([corners_rot,
                                  np.ones((4, 1), dtype=np.float32)]).T).T  # (4, 2)

    center = corners.mean(axis=0)
    outer = (corners - center) * (4.0 / 3.0) + center
    return _order_quad_corners(outer)


# ── Post-detection pipeline: warp → orient → calibrate → classify ────────────


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
    patch: int = 3,
) -> "tuple[int, int, int]":
    """Return mean (R, G, B) sampled from four off-center quadrant midpoints.

    Samples at the ¼ and ¾ positions within the cell (avoiding the center
    where the physical reed switch is visible through the white plastic surface).
    """
    import numpy as np
    q = cell_px // 4
    r = patch // 2
    y0 = row * cell_px
    x0 = col * cell_px
    patches = []
    for qy in (q, 3 * q):
        for qx in (q, 3 * q):
            cy, cx = y0 + qy, x0 + qx
            patches.append(warped[cy - r:cy + r + 1, cx - r:cx + r + 1])
    mean_bgr = (
        np.concatenate([p.reshape(-1, p.shape[-1]) for p in patches], axis=0)
        .astype(np.float32)
        .mean(axis=0)
    )
    return int(mean_bgr[2]), int(mean_bgr[1]), int(mean_bgr[0])  # R, G, B


def _timing_strip_ok(warped: "np.ndarray", cell_px: int) -> bool:
    """Return True if the timing strips in the oriented warped image alternate.

    Row 0 (top) and column 7 (right) of a ChessMatrix always carry an
    alternating black/white pattern.  Checking this before colour calibration
    rejects non-barcode images that accidentally produce a valid perspective
    warp.  Requires ≥5 of 7 adjacent cell pairs to differ (tolerates noise).
    """
    def bright(r: int, c: int) -> bool:
        sr, sg, sb = _sample_cell_rgb(warped, r, c, cell_px)
        return (sr + sg + sb) / 3 > 127.0

    row0 = [bright(0, c) for c in range(8)]
    col7 = [bright(r, 7) for r in range(8)]

    def alternates(seq: "list[bool]") -> bool:
        pairs = sum(seq[i] != seq[i + 1] for i in range(len(seq) - 1))
        return pairs >= 5  # ≥5/7 adjacent pairs must differ

    return alternates(row0) and alternates(col7)


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
            if _timing_strip_ok(warped, _CELL_PX):
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
