# Phase 3 ChessMatrix — Hardware Implementation

Picks up where `phase-3-internet.md` + the simulator work left off.  The
simulator side is complete (all-alpha room codes, ChessMatrix display, camera
scanner, web app scanners, relay keepalive).  Everything below is **hardware
only** and has **not** been implemented.

---

## 1. Hardware Host — display ChessMatrix on LED matrix

Almost free because the simulator already did the work.

`network/chessmatrix.render_to_led(grid, canvas)` is hardware-agnostic: it
calls `canvas.SetPixel(x, y, r, g, b)` which works identically on the real
`FrameCanvas`.  The only change needed is in `game/networked_board.py`:

```python
# After relay.create_room() returns a code:
from network import chessmatrix as _chessmatrix
grid = _chessmatrix.encode(self._room_code)
_chessmatrix.render_to_led(grid, self.canvas)
self.matrix.SwapOnVSync(self.canvas)
# Hold here (poll reed switches / keepalive) until relay_peer_connected
```

Keep the canvas refreshed (re-blit every few seconds) so the display doesn't
go stale while waiting.

---

## 2. Hardware Guest — ChessMatrix input UX

This is the main hardware deliverable.  The physical board has no keyboard;
the guest must input the host's ChessMatrix code using chess pieces on the
reed-switch grid.

### Entry point

Triggered when the user selects "Join Online" from the hardware lobby
(see §4).  Implemented as `_chessmatrix_input_ux()` in
`game/networked_board.py`.

### Step 0 — Clear the board

- Display the ChessMatrix **outer anchor / timing pattern** on the board.
  These are the fixed border cells (28 of 64).  The inner 7×7 is left dark.
- Use the existing "invalid pieces" UX: any reed switch that reads `PIECE`
  lights up that cell in a warning color to prompt removal.
- Poll until all cells read `EMPTY`.

### Step 1 — Red entry

1. **Blink** the red calibration corner cell using the same blink pattern as
   piece-placement prompts during chess setup (existing `interactive_setup`
   behavior).
2. User places a piece on the blinking red corner → enter **red entry state**.
3. **Raster beam animation**: scan across the 32 variable data cells one row
   at a time in red, repeating continuously.
   - Unoccupied variable cells: beam color at ~30 % brightness as it passes.
   - Occupied variable cells ("locked candidate"): cell glows solidly at
     ~80 % red.  As the beam passes, briefly ramp to 100 % red ("excitation"),
     then return to 80 %.
4. User lifts piece from the red corner → red corner begins a **5-second slow
   fade** from solid red to black.
5. If the piece is replaced during the 5-second window → cancel fade, resume
   red entry.
6. After 5 seconds with the piece absent → red entry **locked in**.
   - Red corner goes black.
   - All occupied cells are now permanently locked as red for the remainder of
     the ChessMatrix input process.

### Step 2 — Green entry

Same mechanic as red entry, but:

- **Green calibration corner** blinks.  User places piece → **green entry
  state**.
- Raster beam color is green.
- When the beam passes a locked-red cell: additive color blend
  (`R + G = yellow` at full brightness briefly).  Think of the beam as adding
  its color to whatever is already in a cell.
- Same 5-second fade / lock-in on green corner removal.

### Step 3 — Blue entry

Same mechanic again:

- **Blue calibration corner** blinks.  User places piece → **blue entry
  state**.
- Raster beam color is blue.
- Additive blending on locked cells:
  - Locked red + blue beam → magenta flash.
  - Locked green + blue beam → cyan flash.
- Same fade / lock-in.

### Step 4 — Decode

After all three color entries are locked in:

1. Read the 32-cell color state.  Each data cell is one of:
   `BLACK` (00), `RED` (01), `GREEN` (10), `BLUE` (11).
2. Reconstruct the 8×8 ChessMatrix grid from the locked color state plus
   the fixed border/anchor cells.
3. Call `chessmatrix.decode(grid)` → 4 bytes.
4. Call `network.chessmatrix.bytes_to_room_code(data)` → 6-char room code.
5. Connect to relay with `relay.join_room(room_code)`.

If decode fails (e.g. Reed-Solomon couldn't correct errors), flash an error
pattern and restart from Step 0.

### Calibration corner positions

The four calibration anchor cells are at fixed positions defined by the
ChessMatrix format spec.  Their locations must be confirmed against the
`chessmatrix` library documentation / source.  They are **not** data cells
and are **not** user-entered.

---

## 3. Raster beam animation — implementation notes

The raster beam needs a frame-rate-independent timer.  Suggested approach:

```python
_BEAM_PERIOD_S = 0.8   # seconds to sweep all 32 variable cells
_BEAM_EXCITE_S = 0.06  # how long a cell glows at 100% as beam passes

# In the animation loop:
t = time.time()
beam_pos = (t % _BEAM_PERIOD_S) / _BEAM_PERIOD_S  # 0.0 → 1.0
beam_cell_idx = int(beam_pos * 32)   # which of the 32 variable cells is "lit"
```

Render each variable cell:
- If `beam_cell_idx == cell_idx` and cell is occupied: 100 % brightness
- If cell is occupied: 80 % brightness
- Otherwise: beam color at 30 % brightness × gaussian(distance, sigma=1.5)
  for a soft glow

---

## 4. Simulator equivalent of the hardware guest UX

When the hardware guest flow is implemented, **the simulator must get a
matching simulation of it** — not just the OpenCV camera fallback.  The camera
scanner (`Phase.CODE_SCAN`) is a fallback of last resort, equivalent to the
keyboard text-entry fallback.  The primary simulator experience should
faithfully replicate the raster-beam entry UX so that:

1. The UX can be developed and tested entirely on Mac without Pi hardware.
2. The simulator remains a genuine simulation of the board, not a separate
   standalone client with its own joining mechanism.

### How it works in the simulator

When "Join Online" is selected, before opening the camera, the simulator
enters a new `Phase.CODE_SCAN_BOARD` state that mirrors the hardware flow:

- The LED canvas shows the same ChessMatrix anchor/timing pattern on the
  outer border, inner grid dark.
- **Red entry**: the red calibration corner blinks.  The user **clicks** the
  blinking cell to "place a piece" on it.  Clicking variable cells during red
  entry toggles them as red candidates (click = place piece / click again =
  lift piece).  Clicking the red corner again starts the 5-second fade and
  lock-in — same logic as hardware, driven by mouse events instead of reed
  switches.
- **Green entry** and **Blue entry**: same click-driven mechanic.
- After blue is locked in, decode and connect exactly as hardware would.

### Input hierarchy for simulator GUEST joining online

Priority order (highest first):

1. **Board simulation** (`Phase.CODE_SCAN_BOARD`) — click-driven raster-beam
   entry on the LED canvas.  Primary path; always available.
2. **Camera scanner** (`Phase.CODE_SCAN`) — OpenCV webcam scan.  Fallback when
   the user wants to scan a real physical board's display instead of clicking.
3. **Keyboard text entry** — 6-char manual input in the side panel.  Last
   resort; always available regardless of camera/opencv availability.

The Lobby "Join Online" flow should offer the board simulation by default,
with the camera and keyboard options accessible via the side panel.

### Implementation notes

- `Phase.CODE_SCAN_BOARD` lives in `simulator/networked_runner.py` just like
  `Phase.CODE_SCAN`.
- The raster beam animation runs on the LED canvas using `SetPixel` —
  identical render path to the hardware implementation in
  `game/networked_board.py`.  Extract the animation logic into a shared
  helper (e.g. `network/chessmatrix.py` or `ui/renderer.py`) so both call
  the same code.
- Mouse click → board cell mapping already exists: `_px_to_cell(px, py)` in
  `simulator/app.py`.  A click on cell `(row, col)` maps to a variable data
  cell index if that cell is one of the 32 variable ChessMatrix positions.
- The 5-second fade timer is driven by `pygame.time.get_ticks()` on the
  simulator side, and `time.time()` on the Pi side.
- Add `Phase.CODE_SCAN_BOARD = auto()` to the `Phase` enum in
  `simulator/app.py` alongside the existing `CODE_SCAN`.

---

## 6. Hardware lobby — "Join Online" and "Host Online" options

The physical lobby (currently handled by `game/board.py`) needs two new
options.  This was explicitly deferred ("put a pin in that for now") but is
required for Phase 2 to be reachable.

Suggested additions to `Board.color_picker()` or a new `lobby()` method:
- **Host Online** → connect to relay, display ChessMatrix (§1 above).
- **Join Online** → run `_chessmatrix_input_ux()` (§2 above).

The existing hardware lobby displays options as colored LED rows, same as
the simulator's `_render_lobby`.

---

## 7. Files to create / modify

| File | Change |
|---|---|
| `game/networked_board.py` | Add `_chessmatrix_input_ux()`, hook into `run()` for both host and guest online flows |
| `game/board.py` | Add "Host Online" / "Join Online" to hardware lobby |
| `ui/renderer.py` | Raster beam animation helpers shared between Pi and sim |
| `network/chessmatrix.py` | Confirm calibration corner cell positions; add grid-from-cell-state reconstruction helper if needed |
| `simulator/networked_runner.py` | Add `Phase.CODE_SCAN_BOARD` click-driven entry; update "Join Online" default to board simulation |
| `simulator/app.py` | Add `Phase.CODE_SCAN_BOARD = auto()` to Phase enum |

---

## 8. Testing

- Unit test `bytes_to_room_code(room_code_to_bytes(code)) == code` for all
  edge cases (already done in `tests/test_network.py::TestChessMatrix`).
- Integration: mock reed switches to simulate piece placement sequence;
  verify decoded room code matches the encoded input.
- End-to-end: Pi HOST displays ChessMatrix → sim GUEST camera scans it →
  game connects.  Then Pi GUEST inputs ChessMatrix via reed switches → Pi
  HOST waits → game connects.
