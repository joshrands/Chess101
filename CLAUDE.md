# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Chess101 is a physical chess board running on a Raspberry Pi. An 8×8 RGB LED matrix displays the board, eight Arduinos connected via I2C detect piece positions using reed switches (one Arduino per row), and Python implements chess logic with an optional alpha-beta AI opponent.

A Mac simulator (`run_simulator.py`) lets you develop and test without any Pi hardware by substituting a Pygame window for the LED matrix and click events for reed-switch reads.

## Setup (Mac / development)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # pygame, numpy, websockets
.venv/bin/python run_simulator.py           # launch the simulator (Lobby screen)
```

## Running the Game

**Simulator (Mac) — local play:**
```bash
.venv/bin/python run_simulator.py           # Lobby screen (arrow keys / click to select)
.venv/bin/python run_simulator.py --local   # skip Lobby, go straight to COLOR_PICK
```

**Simulator — networked play (Phase 1: LAN):**
```bash
# Machine A: host
.venv/bin/python run_simulator.py --host

# Machine B: join (IP auto-discovered via UDP beacon, or specify manually)
.venv/bin/python run_simulator.py --join 192.168.1.42

# Optional spectator
.venv/bin/python run_simulator.py --spectate 192.168.1.42

# Custom port (default 65101)
.venv/bin/python run_simulator.py --host --port 65200
```

**Raspberry Pi (requires sudo for LED matrix access):**
```bash
# Local game (no network)
sudo python3 GameManager.py
sudo python3 GameManager.py --led-rows=32 --led-cols=32 --led-chain=4

# Networked: Pi hosts (team_r), Sim joins and drives setup UI
sudo python3 GameManager.py --host
sudo python3 GameManager.py --host --port 65200

# Networked: Pi joins a Sim host (team_l)
sudo python3 GameManager.py --join 192.168.1.42
```

## Running Tests

```bash
.venv/bin/python -m pytest tests/ -q          # all tests
.venv/bin/python -m pytest tests/ -v          # verbose
.venv/bin/python -m pytest tests/test_gameplay.py -v            # chess logic only
.venv/bin/python -m pytest tests/test_simulator.py -v           # simulator only
.venv/bin/python -m pytest tests/test_board.py -v               # Board-level tests
.venv/bin/python -m pytest tests/test_network.py -v             # network protocol tests
.venv/bin/python -m pytest tests/test_networked_runner.py -v    # NetworkedGameRunner: online-play fixes, relay-reconnect guards, CODE_SCAN_BOARD state machine
.venv/bin/python -m pytest tests/test_online_flow.py -v         # E2E online flow: handshake → color-pick → war-games → playing
.venv/bin/python -m pytest tests/test_relay.py -v               # relay server tests (see below)
.venv/bin/python -m pytest tests/test_chessmatrix_scanning.py -v  # ChessMatrix barcode scanner + board-entry helpers (grid_from_cell_state, render_beam_frame)

# JS scanner — runs under Node.js, no npm install needed:
node tests/test_chessmatrix_js.js
node tests/test_chessmatrix_js.js --verbose
```

`conftest.py` stubs out `rgbmatrix` and `smbus` so all test files run on Mac without Pi hardware.

### Relay tests — three run modes

`test_relay.py` spins up an in-process relay by default (no Docker required):

```bash
# Default — fast, in-process relay, no external dependencies:
.venv/bin/python -m pytest tests/test_relay.py -v

# Docker — builds chess101-relay image, runs a container for the session:
.venv/bin/python -m pytest tests/test_relay.py -v --relay-docker

# External relay — point at any running relay (local Docker or live):
docker run -d -p 8765:8765 -e RELAY_PORT=8765 chess101-relay
RELAY_URL=ws://127.0.0.1:8765 .venv/bin/python -m pytest tests/test_relay.py -v

# Post-deploy smoke test against the live relay:
RELAY_URL=wss://relay.chess101.net .venv/bin/python -m pytest tests/test_relay.py -v
```

## Type Checking

```bash
.venv/bin/mypy pieces/ core/ ai/ game/ hardware/ ui/ simulator/ network/
```

Config is in `setup.cfg` (`[mypy]` section). `ignore_missing_imports = True` is set so the Pi-only stubs (`rgbmatrix`, `smbus`) don't produce errors. The codebase should stay at **0 mypy errors**.

## Package Structure

```
Chess101/
├── GameManager.py          # Pi entry point — game loop over Board instances
├── run_simulator.py        # Mac entry point — injects fakes, launches GameRunner
├── samplebase.py           # Base class: parses LED flags, creates RGBMatrix
│
├── game/
│   ├── board.py            # Central controller: color-pick, setup, turns, rendering
│   └── rules.py            # Fifty-move rule, threefold repetition (duck-typed onto Board)
│
├── pieces/
│   ├── piece.py            # Abstract base: targets, pin/check filtering (sky_fall, critical_man)
│   ├── pawn.py             # En passant, promotion (auto-Queen), direction quirk (see BUG-01)
│   ├── rook.py             # Ray-casting; castling side effect inside King
│   ├── bishop.py
│   ├── knight.py
│   ├── queen.py
│   └── king.py             # Check detection (am_i_gonna_die), castling, god_save_the_king
│
├── core/
│   ├── cell.py             # (row, col) coordinate struct
│   ├── team.py             # RGB colour identity; comparison is .r-only (see BUG-03)
│   └── constants.py        # PieceValue, CellOccupancy enums
│
├── ai/
│   ├── ai.py               # Alpha-beta minimax (alpha_beta_search, max_value, min_value)
│   └── tree.py             # Game-tree node: board snapshot, move, children, get_utility
│
├── hardware/
│   ├── master.py           # I2C polling of 8 Arduinos (addresses 0x04–0x0b)
│   ├── sensor.py           # BoardSensor ABC: get_cell_state, read_data
│   └── led_matrix.py       # LEDDisplay ABC: set_pixel, clear, swap
│
├── ui/
│   └── renderer.py         # light_cell() — paints one 8×8 LED block per board cell
│
├── game/
│   ├── board.py            # Board — adds _on_local_move + _on_game_over hooks
│   ├── networked_board.py  # NetworkedBoard(Board) — Pi-side networked game (Phase 2)
│   └── rules.py
│
├── network/                # LAN multiplayer — WebSocket transport + discovery
│   ├── __init__.py
│   ├── protocol.py         # MoveFlags, encode_grid, decode_grid, board_hash, build_move_msg
│   ├── server.py           # GameServer — asyncio WebSocket server in daemon thread
│   ├── client.py           # GameClient — asyncio WebSocket client in daemon thread
│   ├── discovery.py        # BeaconBroadcaster + BeaconListener — UDP LAN discovery
│   ├── mdns.py             # MdnsAdvertiser + MdnsListener — mDNS/DNS-SD via zeroconf
│   └── chessmatrix.py      # ChessMatrix 8×8 four-color barcode: encode/render/decode_frame
│
├── simulator/
│   ├── app.py              # GameRunner: Pygame event loop, phase state machine + Lobby
│   ├── networked_runner.py # NetworkedGameRunner: multiplayer + SPECTATOR + physical_host
│   ├── fake_rgbmatrix.py   # FakeFrameCanvas / FakeRGBMatrix backed by pygame.Surface
│   └── sensor.py           # SimSensor(BoardSensor) — click-driven, no I2C
│
├── web/
│   ├── sim.html            # Simulator web UI
│   ├── spectator.html      # Spectator web UI
│   └── chessmatrix-scanner.js  # Browser/Node.js ChessMatrix decoder (no dependencies)
│
├── tools/
│   ├── debug_quad_detection.py  # Python: renders pipeline stages to PNG for every fixture
│   └── pipeline_debug.html      # Browser: interactive step-by-step JS pipeline debugger
│
├── plans/multiplayer/      # Design docs for all multiplayer phases
│   ├── README.md           # Overview, 7 modes, 3-phase roadmap
│   ├── protocol.md         # Full wire protocol spec (all message types + board hash)
│   ├── architecture.md     # Code structure and class design
│   ├── ux.md               # UX flows for all modes
│   ├── phase-1-lan-sim.md  # Phase 1 step-by-step (COMPLETE)
│   ├── phase-2-physical.md # Phase 2: Pi + physical board support
│   └── phase-3-internet.md # Phase 3: relay server + internet play
│
└── tests/
    ├── conftest.py                  # Stubs rgbmatrix and smbus for all non-Pi tests
    ├── test_gameplay.py             # Pure chess logic + GameRunner integration (headless)
    ├── test_simulator.py            # Simulator-specific bug regression tests
    ├── test_board.py                # Board-level tests (runs on Mac via conftest stubs)
    ├── test_network.py              # Network protocol, beacon, and transport tests
    ├── test_networked_runner.py     # NetworkedGameRunner online-play bug fixes
    ├── test_online_flow.py          # E2E online flow over in-process relay (handshake → playing)
    ├── test_relay.py                # Relay server protocol, reconnect, and anti-cheat tests
    ├── test_chessmatrix_scanning.py # ChessMatrix scanning pipeline (Python) + board-entry helpers
    ├── test_chessmatrix_js.js       # ChessMatrix scanning pipeline (Node.js)
    └── fixtures/chessmatrix/        # PNG fixtures: real phone photos + synthetics

    # test_chessmatrix_scanning.py board-entry sections:
    #   TestGridFromCellState     — grid_from_cell_state: border/anchor/data cell correctness
    #   test_grid_from_cell_state_round_trip — encode→locked→grid_from_cell_state→decode round-trip
    #   TestRenderBeamFrameColors — promoted corners/data cells at FULL, locked cells never below DIM,
    #                               fading_color lerp DIM→FULL, additive cross-color blending,
    #                               beam visible near head, dark when far, killed at fade_frac=1

    # test_networked_runner.py CODE_SCAN_BOARD section:
    #   TestCodeScanBoardStateMachine — all six corner-click transitions, wrong corner ignored,
    #                                   data cell toggle/untoggle/fading-ignored, ESC/T shortcuts,
    #                                   typing sub-mode (buffer fill, cap at 6, backspace,
    #                                   non-alpha ignored, C to buffer not camera, Enter advances),
    #                                   decode round-trip to NAME_ENTRY, three-color sequence
```

## Architecture

### Entry Points

- **`GameManager.py`** — Pi entry point. Supports `--host` / `--join IP` / `--port`. Without flags, loops `Board().process()` indefinitely. With network flags, instantiates `NetworkedBoard` (wraps a `GameServer` or `GameClient`), runs one networked game, then loops. Catches SIGINT/SIGTERM for graceful shutdown.
- **`run_simulator.py`** — Mac entry point. Injects `FakeRGBMatrix` and a stub `smbus` into `sys.modules` before importing game code. Parses CLI flags (`--local`, `--host`, `--join`, `--spectate`, `--port`) and launches `GameRunner` (local) or `NetworkedGameRunner` (networked).

### Game Controller (`game/board.py`)

`Board(SampleBase)` owns the full Pi game lifecycle:

1. `color_picker()` — players choose team colours from an 8-option palette
2. `war_games()` — players choose Human or AI for each team
3. `create_players()` — assigns team display names
4. `interactive_setup(team)` — waits for all 16 pieces to be physically placed
5. `do_turn(team)` / `computer_move(team)` — human turn (lift/land detection) or AI turn
6. `declare_victory()` / `declare_stalemate()` — end-game LED animations

### Mac Simulator (`simulator/app.py`)

`GameRunner` reimplements the same logical flow without blocking calls. It runs a 60-fps Pygame loop through five phases:

```
LOBBY → COLOR_PICK → WAR_GAMES → PLAYING → GAME_OVER
                                                ↑
                                      N key resets to LOBBY
```

Pass `skip_lobby=True` (or `--local` CLI flag) to start directly at COLOR_PICK. Each phase has a `_handle_*` method (click/key events) and a `_render_*` method (draws to the LED canvas). `_render()` calls `blit_to_screen()` then `_render_panel()` then a single `pygame.display.flip()`.

**Lobby** (`Phase.LOBBY`): 4 options shown as colored row pairs — Play Locally / Host a Game / Join a Game / Watch a Game. Arrow keys or mouse to select, Enter/click to confirm. "Play Locally" advances to COLOR_PICK; the network options are wired to `NetworkedGameRunner`.

**Side panel** (`_render_panel`): shows current phase, active team with colour swatch, move count, peace-time bar, check/AI alerts, and a scrolling log feed capturing all Python `logging` records via `_PanelLogHandler`. Subclasses can inject extra rows via `_render_panel_extra()`.

**AI threading**: `_execute_ai_move` launches the alpha-beta search in a `daemon` thread. The Pygame loop stays responsive. Mouse input is blocked during AI thinking. `_add_nodes` updates `_ai_display_board` under a lock so the board animates through candidate positions while the AI thinks.

### Networked Play (`simulator/networked_runner.py`)

`NetworkedGameRunner(GameRunner)` adds WebSocket multiplayer on top of `GameRunner`. The asyncio event loop runs in a daemon thread; the Pygame loop stays on the main thread. Thread-safe communication via an `_incoming` deque (network → main) and `send()` queues (main → network).

**Roles**: `NetworkRole.HOST` (binds server, broadcasts UDP beacon), `NetworkRole.GUEST` (connect to host IP), `NetworkRole.SPECTATOR` (receive-only; `_is_my_turn()` always False).

**Message flow**:
1. Connect → `hello` (includes `role` field; version check)
2. HOST sends `game_setup` → both advance to COLOR_PICK. If peer is a spectator, HOST sends `board_sync` instead. If mode is `"physical_host"` (Pi HOST), Sim GUEST picks both rows.
3. COLOR_PICK: each side clicks their row, sends `color_chosen`; both advance on receipt
4. WAR_GAMES: each side sends `war_games_choice`; HOST sends `game_start` when both received
5. PLAYING: moves sent as `move` + `board_hash`; receiver sends `move_ack` (ok / desync); on desync, `board_sync_request` / `board_sync` recovery. Remote game_event (checkmate/stalemate from Pi) sets GAME_OVER.
6. Keepalive: `ping` every 10 s; no `pong` in 30 s → disconnect overlay shown

**Physical-host mode** (`_is_physical_host_mode`): Pi sends `game_setup` with `mode: "physical_host"`. Sim (GUEST) then picks colours and Human/AI for *both* teams (rows 2 and 5 in COLOR_PICK; rows 3 and 4 in WAR_GAMES). Pi receives `color_chosen` and `war_games_choice` for both teams via `NetworkedBoard`, then sends `game_start`. Pi runs physical `interactive_setup`, sending `setup_status` as pieces are placed. Sim shows setup progress and sends `setup_complete` immediately after `game_start`.

**Thread safety**: all inbound messages are queued in `_incoming` and drained on the main thread in `_update()`. Outbound messages use `asyncio.run_coroutine_threadsafe` to the daemon loop.

### Pi NetworkedBoard (`game/networked_board.py`)

`NetworkedBoard(Board)` is the Pi-side counterpart to `NetworkedGameRunner`. It takes a `GameServer` or `GameClient` plus a `local_team_key` ("r" for HOST, "l" for GUEST).

**Key methods**:
- `run()` — overrides `Board.run()`. Skips `color_picker` / `war_games` (handled by Sim-as-UI). Waits for config (`color_chosen` × 2 + `war_games_choice` × 2), sends `game_start`, runs `interactive_setup`, waits for `setup_complete`, then enters the alternating turn loop.
- `_do_turn_networked(team)` — if local team, calls `do_turn()` (which fires `_on_local_move`); otherwise calls `_wait_for_remote_move()`.
- `_on_local_move(fr, fc, tr, tc, pre_capture)` — hook called by `Board.do_turn` after each physical move. Builds `MoveFlags`, sends `move` message, waits for `move_ack`.
- `_wait_for_remote_move()` — polls `_incoming` until a `move` message arrives or timeout (5 min). Sets `game_over = True` on timeout.
- `_on_game_over(event, losing_team)` — hook called by `Board.do_turn` on checkmate/stalemate. Sends `game_event` to peer.

**Hook extension points in `Board`**: `_on_local_move` and `_on_game_over` are no-op methods on the base `Board` class, called at the right moments in `do_turn`. `NetworkedBoard` overrides both.

### Network Layer (`network/`)

- **`protocol.py`** — `MoveFlags` (en passant, castling, promotion flags), `encode_grid` / `decode_grid` (JSON-serialisable 8×8 grid), `board_hash` (SHA-256 of canonical piece string for desync detection), `build_move_msg`.
- **`server.py`** / **`client.py`** — `GameServer` / `GameClient`: asyncio WebSocket transport in daemon threads. Both expose `send(msg: dict)` and `set_message_handler(cb)`.
- **`discovery.py`** — `BeaconBroadcaster` sends a UDP broadcast every 2 s on port 65102. `BeaconListener` receives beacons, maintains a `games` dict, and prunes stale entries after 10 s.
- **`mdns.py`** — `MdnsAdvertiser` registers a `_chess101._tcp.local.` mDNS service (via `zeroconf`). `MdnsListener` browses for services, maintaining `listener.games: dict[str, DiscoveredMdnsGame]`. Both degrade gracefully if `zeroconf` is not installed.

### ChessMatrix Barcode (`network/chessmatrix.py`)

ChessMatrix is a custom 8×8 four-color barcode used to share room codes between devices without typing.  Each cell is one of four colors (black, red, green, blue = dibit 0–3).  The 6-char room code (30 bits) is packed into 4 data bytes and protected by RS(8,4) Reed–Solomon ECC, giving 4 error-correction bytes and the ability to recover up to 2 wrong cells.

**Encoding pipeline** (`encode(room_code) → 8×8 RGB grid`):
1. `room_code_to_bytes` packs the 6-char all-alpha code into 4 bytes (5 bits per char, big-endian).
2. `rs_encode` appends 4 RS parity bytes → 8-byte codeword.
3. Each byte is split into 4 dibits; the 32 dibits fill the non-structural cells of the 8×8 grid.
4. Structural cells (border finders, timing strips, anchor corners) are fixed.
5. `render_to_led` / `render_to_canvas` write the grid to an LED matrix or Pygame surface.

**Decoding pipeline** (`decode_frame(rgba, w, h) → room_code | None`):
1. **Grayscale + normalize** — simple channel average, stretched to [0, 255].
2. **Adaptive blur** — Gaussian blur with kernel scaled to image size.
3. **Local binarize** (`_local_threshold`) — mean–variance threshold per region.
4. **Centroid** — white-pixel centroid locates the barcode roughly.
5. **Hough axes** — Python (`_hough_axes`): box-blurred binary → Canny → probabilistic Hough lines, two dominant peaks in unfolded [0°, 180°) histogram.  JS (`houghAxes`): Sobel gradients on normalised grayscale → [0°, 180°) magnitude-weighted histogram, two independent peaks.  Both find the two dominant axis angles robustly for upright, rotated, and sheared barcodes.
6. **Affine unshear** — builds basis matrix A = [u1 | u2] from the two axis unit vectors (both in [0°, 180°) so the first-quadrant direction is always used directly).  `applyAffineBin` with A as inverse mapping unshears the binary; both axis families become axis-aligned.
7. **Inflate rect** (`_inflate_rect`) — grows an AABB from the centroid until each edge accumulates white pixels, finding the barcode bounds in unsheared space.
8. **Back-transform + scale** — corners are mapped back to original image space, then scaled outward 4/3× to include the full border.
9. **Perspective warp** (`_warp_to_canonical`) — four-point warp to a 128×128 canonical square; tries all four 90° rotations and picks the one where the bottom-left corner is the L-finder (solid black 2×2).
10. **Calibration** (`_calibrate_and_decode`) — samples the 5 anchor cells (K, R, G, B, W) to build a color map; rejects frames where the luminance spread across anchors is < 60 (prevents all-zero false positives when the scene is uniform).
11. **Classify + ECC** — each data cell is mapped to the nearest calibration color; 32 dibits → 8 bytes → RS decode → 4 data bytes → room code string.

The JS implementation in `web/chessmatrix-scanner.js` follows the same pipeline with equivalent logic (no external dependencies, runs in browser and Node.js).

**Debug tools:**

`tools/debug_quad_detection.py` — renders any pipeline stage to PNG for every fixture image.  Pass `--step N` (1–15) and optionally `--synth`.  Output goes to `tests/fixtures/chessmatrix_debug/`.

```bash
.venv/bin/python tools/debug_quad_detection.py --step 7        # oriented inflate-rect
.venv/bin/python tools/debug_quad_detection.py --step 6 --synth # Hough axes on synthetics
.venv/bin/python tools/debug_quad_detection.py                  # all stages (step 15 = decode)
```

`tools/pipeline_debug.html` — interactive browser-based step-by-step debugger for the JS pipeline.  Load any image or use a live camera frame; shows each stage (binary, axes, unshear, inflated rect, outer corners, warp, orientation, calibration, decode).

Stage map: 1 grayscale · 2 normalize · 3 blur · 4 binarize · 5 centroid · 6 Hough axes · 7 oriented inflate · 8 outer rect · 9 rectify-binary · 10 rectify-color · 11 orient · 12 channel-norm · 13 cal-debug · 14 color-calibrate · 15 decode.

### Hardware Interface

- **`hardware/master.py`** (`Master`) — polls all 8 Arduinos each turn; `get_cell_state(row, col)` returns `CellOccupancy.PIECE` (0) or `CellOccupancy.EMPTY` (1).
- **`samplebase.py`** (`SampleBase`) — parses CLI LED flags and constructs `RGBMatrix`. All rendering classes inherit from it on the Pi.
- **`rgbmatrix/`** — compiled Cython bindings for `rpi-rgb-led-matrix`. Must be built on the target Pi.

### Chess Logic

- **`pieces/piece.py`** — Abstract base. `calc_targets(board)` populates `self.targets`. `sky_fall()` restricts moves when the king is in check; `critical_man()` restricts moves when the piece is pinned.
- **`pieces/king.py`** — `am_i_gonna_die()` scans all 8 directions + knight offsets for attackers. `god_save_the_king` holds the set of cells that would resolve a check.
- **`pieces/pawn.py`** — Direction determined by constructor row (`row == 6` → `-1`, else `+1`), not by team — see **BUG-01**.
- **`ai/ai.py`** — `alpha_beta_search()` picks the best child of the root node. `max_value` / `min_value` implement standard alpha-beta pruning.
- **`ai/tree.py`** — `get_utility()` returns material balance (positive = favours `team_r`).

### Board Coordinate System

`board.grid[row][col]` — 8×8 list of `Piece | None`. Row 0 is `team_r`'s back rank; row 7 is `team_l`'s. Each cell maps to a 4×4 pixel block on the 32×32 LED matrix, rendered as a 120×120 px square in the simulator (`SCALE = 30`).

Mouse click → board cell:
```
col = px // (4 * 30)   # 120 px per cell
row = py // (4 * 30)
```

## Known Bugs

See `bug_report.md` for the full list. Key items:

| ID | Severity | Summary |
|---|---|---|
| BUG-01 | Medium | Pawn direction set by row number, not team |
| BUG-02 | Low | `team_r.r += 1` after colour selection — consistent, no mismatch |
| BUG-03 | Low | Team identity by red channel only — palette reds are all unique |
| BUG-04 | High | Fifty-move rule fires at 50 half-moves instead of 100 |
| BUG-05 | Low | Threefold repetition compares piece type, not team — false match impossible in legal play |
| BUG-06 | Low | `determine_direction` returns `0.0` float — `==` comparison still works |
| BUG-07 | High | Double check only tracks first attacker; second allows illegal blocking moves |
| BUG-08 | Low | `King.get_value()` always 0 — kings are never traded so value is irrelevant |
| BUG-09 | Medium | `filter_to_king_escape` re-appends en passant target even when it doesn't resolve check |
| BUG-10 | Low | `Tree.get_utility()` uses red channel only — same palette safety as BUG-03 |
| BUG-11 | Low | `Tree` stores board reference without deep copy — callers always copy first |
| BUG-12 | Low | `en_passantable` only set from `starting_row` — unreachable in legal play |
| BUG-13 | Low | Promotion formula `(starting_row + 6) % 12` — opaque but correct for rows 1 and 6 |
| BUG-14 | Low | Promotion mutates board in place — callers deep-copy for AI evaluation |
| BUG-15 | Low | Default `Team.name` is "Wendy" — cosmetic, overwritten at colour-pick time |

## Hardware Dependencies (Pi Only)

- `smbus` — I2C communication with Arduinos
- `rgbmatrix` — Compiled Cython library (build on the Pi)
- `RPi.GPIO` — GPIO access

## Other Files

- **`grid.py`** — Standalone LED matrix grid render test
- **`soundtest.py`** — Standalone sound test
- **`PiControl/ReedSwitchTest.py`** — Standalone reed-switch GPIO test
- **`include (trash)/`** — Old versions of Board; not used
- **`python_from_the_pi_sorry_messy/`** — Original Pi copy kept for reference
