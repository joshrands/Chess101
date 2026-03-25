# Phase 3 ChessMatrix — Hardware Implementation

Status as of 2026-03-24:
- **§1 Hardware Host (display ChessMatrix)** — COMPLETE
- **§2 Hardware Guest (`_chessmatrix_input_ux`)** — COMPLETE
- **§3 Raster beam animation** — COMPLETE (see implementation notes below)
- **§4 Simulator `CODE_SCAN_BOARD`** — COMPLETE
- **§5 Unit tests** — COMPLETE
- **§6 Hardware lobby** — TODO (deferred)

---

## 1. Hardware Host — display ChessMatrix on LED matrix ✓

Implemented in `game/networked_board.py`:

- `_show_chessmatrix_waiting(room_code)` — encodes the room code via
  `network.chessmatrix.encode()`, renders to the LED canvas, and blocks until
  `relay._peer_joined` fires (or keepalive timeout).  Re-blits every 5 s so
  the display stays fresh.
- Called from `NetworkedBoard.run()` immediately after `relay.create_room()`
  returns a code.

---

## 2. Hardware Guest — ChessMatrix input UX ✓

Implemented as `NetworkedBoard._chessmatrix_input_ux() -> str | None` in
`game/networked_board.py`.

Mirrors the simulator's `CODE_SCAN_BOARD` state machine but uses
reed-switch polling (`self.master.get_cell_state(row, col)`) instead of
mouse clicks.  Edge-detection on piece placement/removal drives state
transitions.  Three retries on decode failure before returning `None`.
An orange warning lights cells that have pieces on them at startup (prompts
removal before entry begins).

Called from `NetworkedBoard.run()` when role is ONLINE_GUEST.

---

## 3. Raster beam animation ✓

Shared helper `render_beam_frame()` in `network/chessmatrix.py` is used by
both the simulator and the Pi hardware.  The final implementation diverges
from the original spec in several ways (all improvements):

### Beam trail — time-based decay
Each cell's excitation decays based on how long ago the beam swept past it,
not a fixed spatial window:

```python
trail_cells = (beam_idx_float - i) % 32
age_s = trail_cells * (0.8 / 32)   # seconds since beam passed
frac = min(age_s / 0.5, 1.0)       # 0=just hit, 1=fully faded
```

This gives a smooth, physically-motivated trail rather than a hard cutoff.

### Locked cell blending — additive, never darker
The beam additively adds its color to a locked cell and clamps at 255.
The cell lerps from the clamped peak back to `_BEAM_DIM` over 0.5 s:

```python
peak = clamp(base + beam_full)
result = lerp(peak, base, frac)
```

The cell can never go darker than its `_BEAM_DIM` base.  Cross-color
blending (green beam on red cell → yellow peak) emerges naturally from
the addition.

### Promoted cells — DIM→FULL on corner fade, then permanently FULL
When a color phase completes (corner fades out), cells locked in that phase
animate from `_BEAM_DIM` to `_BEAM_FULL` over the 3-second corner fade.
After that they remain at `_BEAM_FULL` for the rest of the entry process
(`promoted` set tracks completed phases).

### Beam fades with corner
During the 3-second corner fade, `_beam_scale = 1.0 - fade_frac` scales the
beam brightness on unoccupied cells (locked cells are unaffected — they hold
their base color through the transition).

### Corner blink / pulse / fade logic
- **Wait state**: hard blink (250 ms on/off).
- **Active state, < 5 s since last toggle**: solid full brightness.
- **Active state, ≥ 5 s since last toggle**: slow sine pulse
  (`0.7 + 0.3 * sin(2π * t)`) — inactivity hint to remove corner.
- **Fading state**: straight linear fade to black over 3 s — no pulse, no blink.

---

## 4. Simulator CODE_SCAN_BOARD ✓

`Phase.CODE_SCAN_BOARD` implemented in `simulator/networked_runner.py` and
`simulator/app.py`.

"Join Online" in the lobby now goes directly to `CODE_SCAN_BOARD` (the
click-driven board simulation) as the primary path.  From there:

- **T** — enter keyboard text-entry sub-mode (type 6-char code manually).
  While in text mode, all alpha keys including C go to the buffer.
- **C** — switch to camera fallback (`Phase.CODE_SCAN`).  Only available in
  board mode, not text mode.
- **ESC** — return to lobby (board mode) or back to board mode (text mode).

State machine: `red_wait → red_active → red_fading → green_wait →
green_active → green_fading → blue_wait → blue_active → blue_fading →
decoding`.

---

## 5. Unit tests ✓

### `tests/test_chessmatrix_scanning.py`

**`TestGridFromCellState`** (6 tests)
- Grid is 8×8.
- Border cells (row 0, row 7, col 0, col 7) are always 0.
- Calibration anchors K/R/G/B are fixed regardless of locked dict.
- Anchor positions in the locked dict do not override canonical values.
- Locked data cells appear in the grid at the right color index.
- Unlocked data cells default to 0 (BLACK).

**`test_grid_from_cell_state_round_trip`** (5 parametrized codes)
- Full round-trip: `encode(code)` → extract locked cells → `grid_from_cell_state`
  → `chessmatrix.decode()` → original code.

**`TestRenderBeamFrameColors`** (9 tests)
- Promoted corner renders at `_BEAM_FULL`.
- Locked cell is never darker than `_BEAM_DIM` for any beam position.
- `fading_color` cell at `fade_frac=0` shows `_BEAM_DIM`.
- `fading_color` cell at `fade_frac=1` shows `_BEAM_FULL`.
- Green beam on red-locked cell adds green (additive blending).
- Unoccupied cell directly under beam head is visibly lit.
- Unoccupied cell is fully dark when beam is beyond the 0.5 s trail window.
- All unoccupied cells are black at `fade_frac=1` (beam killed by corner fade).
- Promoted data cell rests at `_BEAM_FULL` base (distinct code path from fading lerp).

### `tests/test_networked_runner.py`

**`TestCodeScanBoardStateMachine`** (23 tests)
- All six corner-click transitions (wait→active, active→fading, fading→active cancel)
  for all three colors.
- Wrong corner in wait state does nothing (no phase skip).
- Data cell click adds to pending; second click removes; activity timer updated.
- Data cell click in wait state ignored.
- Data cell click in fading state ignored (cells locked while phase is committing).
- ESC→lobby; T→typing mode.
- Typing mode: ESC exits without going to lobby; alpha fills buffer; buffer capped
  at 6 chars (7th dropped); backspace removes last char; digits/spaces ignored;
  C goes to buffer not camera; Enter with 6 chars → NAME_ENTRY; Enter with short
  code ignored.
- Full decode round-trip: encode a known code → build locked dict →
  `_cs_do_decode()` → `Phase.NAME_ENTRY` with correct `_room_code` and role.
- Three-color corner sequence walks all six transitions end-to-end.

---

## 6. Hardware lobby — TODO

The physical lobby (in `game/board.py`) still needs "Host Online" and
"Join Online" options to make the Pi online flow reachable without CLI flags.
Deferred; currently accessible via `GameManager.py --host-online` /
`--join-online`.

---

## Files modified

| File | Changes |
|---|---|
| `simulator/app.py` | Added `Phase.CODE_SCAN_BOARD = auto()` |
| `simulator/networked_runner.py` | Full `CODE_SCAN_BOARD` phase: state vars, handle/render, lobby routing, decode, error flash, panel extras |
| `network/chessmatrix.py` | Added `DATA_CELLS`, `render_border_only()`, `render_beam_frame()`, `grid_from_cell_state()` |
| `game/networked_board.py` | Added `_show_chessmatrix_waiting()`, `_chessmatrix_input_ux()`, relay preamble in `run()` |
| `GameManager.py` | Added `--host-online`, `--join-online`, `--relay-url` CLI flags; online branch in `_build_board()` |
| `tests/test_chessmatrix_scanning.py` | Added `TestGridFromCellState`, `test_grid_from_cell_state_round_trip`, `TestRenderBeamFrameColors` |
| `tests/test_networked_runner.py` | Added `TestCodeScanBoardStateMachine` |
| `bug_report.md` | Added OPEN-06: ChessMatrix scanner false positives |
