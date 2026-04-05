# Chess101 Test Suite

All tests run on Mac without Pi hardware. `conftest.py` stubs `rgbmatrix`, `smbus`, and `RPi.GPIO` before any game code is imported, so the full suite works in a standard Python venv.

---

## Quick start

```bash
# All Python tests
.venv/bin/python -m pytest tests/ -q

# Verbose — shows every test name
.venv/bin/python -m pytest tests/ -v

# JS tests (Node.js, no npm install required)
node tests/test_chessmatrix_js.js
node tests/test_chessmatrix_js.js --verbose
```

---

## Running individual suites

| Suite | Command |
|---|---|
| Chess logic (pieces + GameRunner) | `.venv/bin/python -m pytest tests/test_gameplay.py -v` |
| Simulator phase state machine | `.venv/bin/python -m pytest tests/test_simulator.py -v` |
| Board controller (Pi) | `.venv/bin/python -m pytest tests/test_board.py -v` |
| Network protocol + transport | `.venv/bin/python -m pytest tests/test_network.py -v` |
| NetworkedGameRunner | `.venv/bin/python -m pytest tests/test_networked_runner.py -v` |
| E2E online flow | `.venv/bin/python -m pytest tests/test_online_flow.py -v` |
| Relay server | `.venv/bin/python -m pytest tests/test_relay.py -v` |
| ChessMatrix scanner (Python) | `.venv/bin/python -m pytest tests/test_chessmatrix_scanning.py -v` |
| ChessMatrix pipeline (OpenCV) | `.venv/bin/python -m pytest tests/test_chessmatrix_pipeline.py -v` |
| Piece logic | `.venv/bin/python -m pytest tests/test_pieces.py tests/test_king.py -v` |
| Primitives (Cell, Team, Piece ABC) | `.venv/bin/python -m pytest tests/test_primitives.py -v` |
| AI / alpha-beta | `.venv/bin/python -m pytest tests/test_ai_tree.py -v` |
| SimSensor + FakeRGBMatrix | `.venv/bin/python -m pytest tests/test_simulator_extras.py -v` |
| JsBridge (subprocess mock) | `.venv/bin/python -m pytest tests/test_python_bridge.py -v` |
| RoomValidator unit tests | `.venv/bin/python -m pytest tests/test_validator_unit.py -v` |

---

## Relay test modes

`test_relay.py` and `test_online_flow.py` need a relay server. Three modes are available:

```bash
# Default — in-process relay, no Docker, fastest:
.venv/bin/python -m pytest tests/test_relay.py -v

# Docker — builds chess101-relay image, runs a container for the session:
.venv/bin/python -m pytest tests/test_relay.py -v --relay-docker

# External relay — point at any running relay (local Docker or live):
docker run -d -p 8765:8765 -e RELAY_PORT=8765 chess101-relay
RELAY_URL=ws://127.0.0.1:8765 .venv/bin/python -m pytest tests/test_relay.py -v

# Smoke test against the live relay:
RELAY_URL=wss://relay.chess101.net .venv/bin/python -m pytest tests/test_relay.py -v
```

The `relay_url` fixture (in `conftest.py`) selects the mode automatically: `RELAY_URL` env var → `--relay-docker` flag → in-process default. The in-process relay resets its `_rooms` dict between tests so each test starts with a clean state.

---

## File index

| File | What it tests | Lines |
|---|---|---|
| `conftest.py` | Shared fixtures and hardware stubs | 228 |
| `test_gameplay.py` | Pawn logic + GameRunner move execution (headless) | 343 |
| `test_simulator.py` | GameRunner regression tests (9 bugs + eval bar, trails, kibitzer, themes) | 947 |
| `test_board.py` | Board controller: init, piece placement, rules, rendering | 584 |
| `test_pieces.py` | Pawn, Bishop, Rook, Knight, Queen | 698 |
| `test_king.py` | King: walk, check detection, castling, pin logic | 558 |
| `test_primitives.py` | Cell, Team, Piece ABC | 192 |
| `test_ai_tree.py` | Tree utility + alpha-beta minimax | 283 |
| `test_network.py` | Protocol encode/decode, beacon discovery, transport | 761 |
| `test_networked_runner.py` | NetworkedGameRunner: reconnect, CODE_SCAN_BOARD, LOCAL mode, AI suppression | ~1280 |
| `test_online_flow.py` | E2E: relay handshake → color-pick → war-games → playing | 459 |
| `test_relay.py` | Relay protocol, forwarding, reconnect, anti-cheat | 1116 |
| `fuzz_relay.py` (harness) | Relay delivery fuzzer: ordering, completeness, reconnect, spectator | 437 |
| `test_chessmatrix_scanning.py` | ChessMatrix scanner: all pipeline stages + E2E (Python) | 1159 |
| `test_chessmatrix_pipeline.py` | ChessMatrix pipeline via OpenCV debug tools | 190 |
| `test_chessmatrix_js.js` | ChessMatrix scanner (JavaScript / Node.js) | 442 |
| `test_lockstep_chessmatrix.py` | Python↔JS ChessMatrix lockstep: both decoders must agree on every frame | 193 |
| `test_lockstep_chess.py` | Python↔JS chess engine lockstep: legal moves + board hash parity | ~340 |
| `test_lockstep_networked.py` | Python↔JS↔Spectator three-way lockstep: move application + board sync | ~310 |
| `test_sim_js.js` | Web sim logic: ping/pong, AI gating, color pick guards, render (JS) | ~360 |
| `test_simulator_extras.py` | SimSensor, FakeRGBMatrix, FakeFrameCanvas unit tests | ~110 |
| `test_python_bridge.py` | JsBridge subprocess error paths (mocked) | ~90 |
| `test_validator_unit.py` | RoomValidator: guards, sky_fall, promotion, castling, en-passant | ~170 |

---

## File descriptions

### `conftest.py` — shared infrastructure

Provides hardware stubs and pytest fixtures used across the whole suite.

**Hardware stubs** are inserted into `sys.modules` at module scope — before pytest collects any test file — because `Board.py` and `samplebase.py` do module-level imports of `rgbmatrix`, and `Master.py` imports `smbus`. Late patching would miss these.

Stubs:
- `rgbmatrix` / `rgbmatrix.core` — `MagicMock()`
- `smbus` — `MagicMock()` with `read_byte` returning `0` (arithmetic in `Master.update_row_states` requires an int)
- `RPi` / `RPi.GPIO` — `MagicMock()`
- `Master` / `hardware.master` — `MagicMock()`

Fixtures:

| Fixture | Scope | Description |
|---|---|---|
| `team_r` | function | `Team(64, 180, 232)` — blue, matching Board defaults |
| `team_l` | function | `Team(255, 140, 0)` — orange, matching Board defaults |
| `empty_board` | function | 8×8 `[[None]*8 …]` |
| `make_board` | function | Factory: `make_board({(row,col): piece, …})` → populated 8×8 grid |
| `board_instance` | function | `Board()` with `canvas`, `matrix`, and `master` replaced by MagicMocks |
| `relay_url` | function | Relay WebSocket URL (mode auto-selected; see Relay test modes above) |
| `relay_docker_url` | session | Session-scoped Docker relay container (used by `relay_url` with `--relay-docker`) |

**Note for simulator tests**: files that test `GameRunner` or `NetworkedGameRunner` override the conftest MagicMock stub with the real `FakeRGBMatrix` at the top of the file, so rendering code actually executes:

```python
import simulator.fake_rgbmatrix as _frm
_rmod = types.ModuleType("rgbmatrix")
_rmod.RGBMatrix = _frm.FakeRGBMatrix
...
sys.modules["rgbmatrix"] = sys.modules["rgbmatrix.core"] = _rmod
```

This pattern appears in `test_gameplay.py`, `test_simulator.py`, `test_networked_runner.py`, and `test_online_flow.py`.

---

### `test_gameplay.py` — chess logic + GameRunner integration

Two layers of coverage:
1. **Pure chess logic** — `Pawn.calc_targets`, `move()`, en passant. No display, no Pygame.
2. **GameRunner integration** — full move execution through `_apply_move()` with a headless Pygame window.

Test classes:

| Class | What it verifies |
|---|---|
| `TestPawnCapture` | Diagonal captures, forward-blocking rule, friendly-piece blocking, column edge guards |
| `TestPawnMoveState` | Grid state after capture, `piece.row/col` consistency, en passant removal |
| `TestGameRunnerMoves` | Opening grid correctness, pawn target generation, move execution, grid-coord invariant |

**BUG LOCK-IN**: `test_direction_set_by_row_not_team` documents that `Pawn.direction` is determined by the constructor row (row 6 → −1, any other row → +1), not by team. Tests that need a `team_l` pawn in the middle of the board must initialise at row 6 then update `.row`.

---

### `test_simulator.py` — GameRunner regression tests

Each test class is anchored to a specific bug. Tests are intentionally narrow so a regression points directly at the cause.

| Class | Bug | What it verifies |
|---|---|---|
| `TestWarGamesLayout` | Bug 1 | Row 3: left=Human/right=AI; row 4: left=AI/right=Human (kitty-corner) |
| `TestPieceDeselection` | Bug 2 | Clicking the selected piece deselects it, does not re-select |
| `TestAIThinkingBlocksInput` | Bug 3 | Mouse clicks are silently ignored while the AI thread is running |
| `TestWinAnimationThrottle` | Bug 4 | Win animation color refresh throttled to ≥ 50 ms (was every frame) |
| `TestAIThreading` | Bug 5 | `_execute_ai_move` returns immediately; AI runs in a daemon thread |
| `TestPhaseTransitions` | Bug 6 | `COLOR_PICK → WAR_GAMES → PLAYING → GAME_OVER` state machine |
| `TestPeaceTimeTracking` | Bug 7 | Capture resets `peace_time` to 0; non-capture increments by 1 |
| `TestNextTurnCleanup` | Bug 8 | `_next_turn` clears selected piece, check state, flips active team |
| `TestLogging` | Bug 9 | Key game events emitted at correct log levels (INFO / DEBUG) |
| `TestPieceOverlaySelectedPiece` | Feature | Selected-piece overlay renders without crash |
| `TestPieceImageLoading` | Feature | SVG piece images load and fallback to glyphs correctly |
| `TestEvalBar` | Feature | `_calc_eval()` returns 0 at start; correct deltas after captures |
| `TestMoveTrails` | Feature | Trail includes from-cell; rook gets intermediates; knight doesn't; reset clears |
| `TestKibitzer` | Feature | Capture/check comments logged with 💡; toggled off = no log |
| `TestBoardThemes` | Feature | 5 themes exist with distinct names; T cycles theme; K toggles kibitzer |

Helpers:
- `_click(row, col)` — synthesises a `MOUSEBUTTONDOWN` at the centre pixel of a board cell
- `_keydown(key)` — synthesises a `KEYDOWN` event

Fixtures: `fresh` (COLOR_PICK phase), `in_war_games`, `playing_hh` (human vs human), `playing_ha` (human vs AI).

---

### `test_board.py` — Board controller

Tests `Board` with all hardware mocked via the `board_instance` fixture.

| Class | What it verifies |
|---|---|
| `TestBoardInit` | Default team colours, grid shape, initial field values |
| `TestInitializeGameBoard` | Standard starting position: piece types and coordinates |
| `TestGetTeamPieces` | Team identification; red-channel-only comparison (BUG-03 lock-in) |
| `TestCheckFiftyMoveRule` | Fires at 50 half-moves — BUG-04 lock-in (correct threshold is 100) |
| `TestCheckThreefoldRepetition` | State history; type-only comparison lock-in (BUG-05) |
| `TestLightCell` | Pixel coordinates for each board cell's 8×8 LED block |
| `TestAddNodes` | AI tree populated at depth 1 and 2; pruning + node counts |
| `TestLightCheckerTown` | Checkerboard background colour parameter |
| `TestChooseLightCheckerTown` | Brightness-scaled colour selection |
| `TestRunSkipSetup` | `skip_setup` and `init_num` quick-start flags |
| `TestDetectMismatch` | Red background + yellow pieces when physical/virtual boards diverge |

---

### `test_pieces.py` — piece logic (all except King)

Builds minimal board positions and verifies `calc_targets()`, `get_value()`, `move()`, and `filter_to_king_escape()` (sky fall / pin detection) for each piece type.

| Class | Piece | Key areas |
|---|---|---|
| `TestPawn` | Pawn | Direction (BUG-01 lock-in), forward/diagonal targets, en passant, promotion |
| `TestBishop` | Bishop | Diagonal rays, friendly/enemy blocking |
| `TestRook` | Rook | Horizontal/vertical rays, blocking, castling side-effect |
| `TestKnight` | Knight | L-shape movement, no ray-blocking |
| `TestQueen` | Queen | Combined Bishop + Rook behaviour |

---

### `test_king.py` — King logic

| Class | What it verifies |
|---|---|
| `TestKingInit` | Direction from row, `god_save_the_king` initialised empty, `touched` flag |
| `TestWalk` | Adjacent squares reachable; board boundary respected |
| `TestCalcTargets` | Non-capture moves, self-check filtering, castling (both sides) |
| `TestFindAttacker` | Attacker detection for Pawn, Rook, Bishop, Knight, Queen |
| `TestDetermineDirection` | Returns `0.0` float — BUG-06 lock-in |
| `TestBuildCheckEscapePath` | `god_save_the_king` populated with correct escape cells |
| `TestCriticalMan` | Pin detection: pinned piece cannot expose king |
| `TestMove` | Castling: `Rook.move()` called, returns `True`; normal move returns `False` |

---

### `test_primitives.py` — Cell, Team, Piece ABC

| Class | What it verifies |
|---|---|
| `TestCell` | Default init, custom `(row, col)`, attribute names (not `x`/`y`) |
| `TestTeam` | RGB storage, default name "Wendy" (BUG-15 lock-in), instance independence |
| `TestPieceBase` (via Rook) | `touched`, `critical`, `targets`; `move()`, `get_targets()`, `sky_fall()`, `critical_man()`, `_kingsman()` ray-casting |

---

### `test_ai_tree.py` — Tree + alpha-beta AI

| Class | What it verifies |
|---|---|
| `TestTree` | Board reference stored without deep copy (BUG-11 lock-in), team value copying, child management, `get_utility()` with red-channel-only comparison (BUG-10 lock-in) |
| `TestAI` | Tree construction, terminal node detection, `get_successors()`, `min_value`/`max_value`, `alpha_beta_search()` on 1-level and 2-level trees, pruning behaviour |

---

### `test_network.py` — network protocol + transport

| Area | What it verifies |
|---|---|
| `encode_grid` / `decode_grid` | Round-trip for all 6 piece types; full starting position |
| `board_hash` | Deterministic for same board; changes on piece move |
| `MoveFlags` | Serialisation round-trip for en passant, castling, promotion flags |
| `build_move_msg` | Message structure and required fields |
| `BeaconBroadcaster` / `BeaconListener` | UDP LAN discovery round-trip; stale-entry pruning |
| `GameServer` / `GameClient` | WebSocket connect, send, receive |
| `NetworkedBoard` | Pi-side networked game: `color_chosen`, `war_games_choice`, `game_start`, `move`, `move_ack` message flow |

---

### `test_networked_runner.py` — NetworkedGameRunner

| Area | What it verifies |
|---|---|
| `TestOnHelloRejoinDetection` | `_on_hello` sends `rejoin_sync` when phase is `PLAYING`; sends `game_setup` during pre-game phases |
| `TestOnRejoinSync` | Restores team colours, board grid, counters, and `net_seq` from sync payload |
| `_remote_last_move` tracking | Set by `_apply_remote_move`, cleared by `_next_turn` on the local player's next move |
| `TestCodeScanBoardStateMachine` | Corner-click transitions, data-cell toggle/untoggle, fading-cell ignored, ESC/T shortcuts, typing sub-mode (buffer fill, backspace, cap at 6, non-alpha ignored, C to buffer not camera, Enter advances), decode round-trip to NAME_ENTRY, three-color sequence, `_render_panel_extra` smoke test |
| `TestLocalColorPick` | LOCAL mode (`_local_team_key=="both"`) delegates color pick to base GameRunner: row 2/5 clicks work, no peer required, advances to WAR_GAMES |
| `TestLocalWarGames` | LOCAL mode delegates war-games to base handler: both rows 3/4 work, advances to PLAYING |
| `TestNetworkedAISuppression` | AI suppressed on remote team's turn (`_ai_thinking=False`); AI runs on local team's turn |

Factories: `_make_host()` and `_make_guest()` return ready-to-use `NetworkedGameRunner` instances with mocked WebSocket transport.

---

### `test_online_flow.py` — E2E online game flow

Spins up two real `NetworkedGameRunner` instances connected through the in-process relay (via `relay_url` fixture). Tests the complete protocol lifecycle:

- `test_handshake_completes` — hello exchange, peer name set, `game_setup` received
- `test_color_pick_flow` — both sides choose colours; both advance to WAR_GAMES
- `test_war_games_flow` — both sides choose Human/AI; HOST sends `game_start`
- `test_move_exchange` — move sent by one side, applied by the other; board hashes match
- Spectator tests — spectator receives board state, cannot make moves

These tests catch bugs that unit tests with manually injected state cannot detect — particularly anything that depends on the hello exchange actually happening (phase gating, peer-name guards, relay-history replay).

Helper: `_pump_until(condition, timeout)` drives both event loops until a condition is true or the timeout expires.

---

### `test_relay.py` — relay server

Low-level helpers: `_open()`, `_send()`, `_recv()`, `_drain()`.
Higher-level helpers: `_do_host()`, `_do_guest()`, `_do_spectate()`, `_do_reconnect()`.

| Area | What it verifies |
|---|---|
| Room lifecycle | Create, join, leave, spectate; `room_full` rejection for a third player |
| Message forwarding | HOST → GUEST, GUEST → HOST, broadcast to spectators |
| Reconnect | Client reconnects mid-game; relay replays history; game resumes |
| Anti-cheat | Server-side `validator.py` rejects illegal moves |
| `RelayClient` | High-level wrapper: handshake, cold-start retry, reconnect guard |
| Health endpoint | `GET /health` returns 200 for Docker readiness probe |

For randomised stress-testing beyond these unit tests, see [`harness/fuzz_relay.py`](#fuzz_relaypy--relay-delivery-fuzzer) below.

---

### `fuzz_relay.py` — relay delivery fuzzer

Standalone fuzzer in `harness/fuzz_relay.py`. Generates random sequences of create / join / send / disconnect / reconnect operations and verifies delivery invariants after each scenario. Does not require pytest — run directly.

```bash
# In-process relay (default, no external deps):
.venv/bin/python harness/fuzz_relay.py --iterations 100

# Against an external or live relay:
RELAY_URL=ws://127.0.0.1:8765 .venv/bin/python harness/fuzz_relay.py --iterations 100
RELAY_URL=wss://relay.chess101.net .venv/bin/python harness/fuzz_relay.py --iterations 50

# Via Bazel:
bazel run //harness:fuzz_relay -- --iterations 100
```

Invariants checked per scenario:

| Scenario | Weight | What it verifies |
|---|---|---|
| `basic_forward` | 40 | Messages arrive in send order; none dropped |
| `spectator` | 20 | Spectator receives all forwarded messages; per-sender order preserved |
| `reconnect` | 20 | Reconnecting player receives full history replay |
| `rapid_join_leave` | 10 | Server survives rapid create/close cycles; still responds afterward |
| `invalid_codes` | 5 | Bad room code → `room_not_found`; bad token → `bad_token` |
| `burst_messages` | 5 | 50–200 messages sent with no pacing; all arrive |

`_rooms.clear()` is called between iterations so accumulated rooms don't trigger `server_full` errors.

---

### `test_chessmatrix_scanning.py` — ChessMatrix scanner (Python)

Tests `network.chessmatrix.decode_frame` at both per-stage and end-to-end levels.

**Synthetic frame factories:**

| Factory | What it produces |
|---|---|
| `_make_frame(code, cell_px)` | Perfect barcode on a black background |
| `_make_frame_padded(code, cell_px, pad)` | Centred barcode with a gray border |
| `_make_frame_rotated(code, angle)` | Rotated at an arbitrary angle |
| `_make_frame_perspective(code)` | Trapezoid perspective distortion |
| `_make_frame_shear(code, shear_x)` | Horizontal shear transform |

**Per-stage tests** verify each of the 15 pipeline steps in isolation (grayscale, normalize, blur, binarize, centroid, Hough axes, unshear, inflate rect, back-transform, perspective warp, orientation, channel normalization, calibration debug, color calibration, decode).

**Timing-strip guard** — `_timing_strip_ok` unit tests: rejects uniform-gray and solid-white warped images; verifies that *both* strips must alternate (each tested independently); checks below-threshold (4/7 pairs) rejects and at-threshold (5/7 pairs) accepts; confirms that an all-black warped image is rejected (AAAAAA false-positive regression). Also verifies that a real AAAAAA barcode still decodes correctly (valid code, not just a false positive).

**End-to-end tests:**

| Section | Coverage |
|---|---|
| Clean padded | 5 codes × varied cell sizes |
| Rotation | Multiple angles (0°, 15°, 30°, 45°, 90°, 135°, 180°) × codes |
| Perspective | Trapezoid distortion |
| Noise | Gaussian and salt-and-pepper noise |
| Photometric | Brightness, contrast, color tint variations |
| Affine | Shear and stretch |
| Combined | Rotation + perspective + noise together |
| Distractors | A second large square visible in the scene |

**Real-photo fixtures** are auto-discovered from `tests/fixtures/chessmatrix/`. Any `.png` file there is tested automatically — add new photos by dropping them in the directory.

**Debug dict tests** verify the contract of `decode_frame(..., debug=True)`: all expected stage keys present, pixel arrays have the right shape, no stage silently skipped.

**Board-entry helpers** (tested in `TestGridFromCellState` and `TestRenderBeamFrameColors`):
- `grid_from_cell_state` — border / anchor / data cell correctness; encode → lock → decode round-trip
- `render_beam_frame` — promoted corners at FULL brightness; locked cells never below DIM; `fading_color` lerps DIM → FULL; additive cross-color blending; beam visible near head, dark when far, killed at `fade_frac=1`

---

### `test_chessmatrix_pipeline.py` — ChessMatrix pipeline (OpenCV)

Requires `opencv-python` (`pip install opencv-python`). Uses helpers from `tools/debug_quad_detection.py` to test individual pipeline stages against both fixture images and synthetic frames.

```bash
# Skip automatically if opencv-python is not installed:
.venv/bin/python -m pytest tests/test_chessmatrix_pipeline.py -v
```

---

### `test_chessmatrix_js.js` — ChessMatrix scanner (JavaScript)

Node.js test runner for `web/chessmatrix-scanner.js`. No npm install required — uses only Node.js built-ins. Includes a minimal PNG decoder (Paeth predictor, DEFLATE via `zlib`) so fixture images can be loaded without any external library.

```bash
node tests/test_chessmatrix_js.js            # summary output
node tests/test_chessmatrix_js.js --verbose  # per-test output
```

Covers the same pipeline stages as the Python scanner: synthetic clean frames, rotation, perspective, noise, and real-photo fixtures. Also includes a **timing-strip guard** section with adversarial unit tests (uniform gray/white rejected, both strips required independently, below/at threshold boundary cases, AAAAAA false-positive regression, real AAAAAA decodes correctly, center-pixel corruption survived via patch averaging) and a **cell sampling robustness** section that verifies `calibrateAndDecode` survives corrupted and inverted center pixels (regression tests for the single-pixel sampling bug).

### `test_lockstep_chessmatrix.py` — Python↔JS ChessMatrix lockstep

Feeds identical synthetic and real-photo frames to both the Python (`network.chessmatrix.decode_frame`) and JavaScript (`web/chessmatrix-scanner.js::decodeFrame`) decoders and asserts they always agree — including both returning None/null.

Uses a persistent `JsBridge` subprocess (`harness/python_bridge.py` → `harness/js_bridge.js`) for cross-language calls. Converts between BGR numpy (Python) and RGBA bytes (JS) automatically.

| Class | What it verifies |
|---|---|
| `TestCleanPadded` | 5 room codes × 3 cell sizes — clean synthetic images |
| `TestRotated` | 2 codes × 7 rotation angles (15° – 270°) |
| `TestNoise` | 2 codes × 3 noise levels (sigma 10–30) |
| `TestPhotometric` | Brightness (1.4×) and darkness (0.5×) variations |
| `TestFixtures` | All `.png` files in `tests/fixtures/chessmatrix/` (auto-discovered) |

Related: `harness/fuzz_chessmatrix.py` is a standalone fuzzer that generates random mutated frames (rotation, noise, perspective, brightness, salt-pepper) and saves disagreements to `harness/crashes/chessmatrix/`.

```bash
# Run lockstep tests:
bazel test //tests:test_lockstep_chessmatrix

# Run the fuzzer (1000 iterations by default):
bazel run //harness:fuzz_chessmatrix -- --iterations 1000

# Replay a crash image through both decoders with debug output:
bazel run //harness:replay_crash -- "$PWD/harness/crashes/chessmatrix/disagree_000042_ABCDEF.png" --stages
# --stages dumps all 15 Python pipeline stage PNGs alongside the input image
# --js prints a hint for opening the JS browser-based pipeline debugger
```

---

### `test_lockstep_chess.py` — Python↔JS chess engine lockstep

Plays random games from the starting position, comparing legal move sets and board hashes at each step between the Python engine (`pieces/*.py`) and the JS engine (`web/chess-engine.js`).

Uses the same `JsBridge` subprocess as the ChessMatrix lockstep tests. Grid state is serialized to JSON for cross-language comparison.

| Class | What it verifies |
|---|---|
| `TestBoardHashParity` | board_hash identical on both sides for starting position and after e4 |
| `TestLegalMovesParity` | Legal move sets agree at starting position for both teams |
| `TestRandomGames` | 10 seeded random games (80 plies each): legal moves + board hashes agree at every step |

Related: `harness/fuzz_chess.py` is a standalone fuzzer that plays random games and saves disagreements with full move history to `harness/crashes/chess/`.

```bash
bazel test //tests:test_lockstep_chess
bazel run //harness:fuzz_chess -- --iterations 100
```

---

### `test_lockstep_networked.py` — Python↔JS↔Spectator three-way lockstep

Plays random games from the starting position, applying each move on all three implementations: the Python chess engine, the JS chess engine (`web/chess-engine.js`), and the JS spectator engine (`web/spectator-engine.js`). After every move, all three grids must agree on piece types and team ownership.

Also tests the `board_sync` path: `encode_grid` on the Python side → `applyGrid` on the JS spectator side → verify the resulting grid matches.

Uses the same `JsBridge` subprocess as the other lockstep tests.

| Class | What it verifies |
|---|---|
| `TestSpectatorInit` | Spectator starting position matches Python standard board |
| `TestSpectatorApplyGrid` | `encode_grid` → spectator `applyGrid` round-trip (starting + mid-game) |
| `TestSpectatorApplyMove` | Simple pawn move, castling (rook_from/rook_to flags), promotion (is_promotion flag) |
| `TestSpectatorRandomGames` | 10 seeded games (80 plies): spectator stays in sync; 5 board_sync recovery tests |
| `TestThreeWayParity` | 5 seeded games: Python engine, JS engine, and JS spectator all agree at every ply |

Related: `harness/fuzz_networked.py` is a standalone three-way fuzzer. `harness/BUGS.md` documents all bugs found by the fuzz testing harness.

```bash
bazel test //tests:test_lockstep_networked
bazel run //harness:fuzz_networked -- --iterations 100
```

---

### `test_sim_js.js` — Web sim logic regression tests (JavaScript)

Node.js test runner for game logic extracted from `web/sim.html`. Uses `vm` module to evaluate the sim's script blocks in a sandboxed context with mocked DOM/browser APIs.

```bash
node tests/test_sim_js.js            # summary output
node tests/test_sim_js.js --verbose  # per-test output
```

| Area | What it verifies |
|---|---|
| Ping/pong | `handleRelayMsg` responds to `{type:'ping'}` with `{type:'pong'}` including `seq` |
| AI gating | `beginTurn` does not launch AI for the remote team's turn in networked play; does launch for local team; local mode runs AI for any team |
| Color pick guards | HOST cannot pick row 5 (team_l); GUEST cannot pick row 2 (team_r); HOST can pick row 2 and sends `color_chosen` |
| Color pick rendering | `renderColorPick` dims unselected cells on the correct row (not cross-referencing the other team's selection) |

---

### `test_simulator_extras.py` — SimSensor + FakeRGBMatrix unit tests

Targets the uncovered lines in `simulator/sensor.py` and `simulator/fake_rgbmatrix.py`.

| Class | What it verifies |
|---|---|
| `TestSimSensor` | All 64 cells initialised to `EMPTY`; `read_data` is a no-op; `get_cell_state` and `set_state` round-trip correctly |
| `TestFakeFrameCanvas` | `SetPixel` in-bounds writes without error; out-of-bounds calls are silently ignored; `Clear` fills surface with black |
| `TestFakeRGBMatrix` | `SwapOnVSync` returns the same canvas; `blit_to_screen` returns early when `_screen` is `None`; `blit_to_screen` calls `screen.blit` when screen is set; `flip` calls both `blit_to_screen` and `pygame.display.flip` |

Uses headless SDL (`SDL_VIDEODRIVER=dummy`) and a module-scoped `pygame.init()` fixture.

---

### `test_python_bridge.py` — JsBridge subprocess mock tests

Covers error paths in `harness/python_bridge.py` using `unittest.mock.patch` on `subprocess.Popen`. No real Node.js process is required.

| Class | What it verifies |
|---|---|
| `TestJsBridgeClose` | `close()` calls `stdin.close()`; `__exit__` (context manager) also calls `close()` |
| `TestJsBridgeCall` | `_call()` raises `RuntimeError("JS bridge died")` when stdout returns an empty line; error message includes stderr content |
| `TestJsBridgePing` | `ping()` raises `RuntimeError` on an `{"error": ...}` response; returns `result` on success |
| `TestJsBridgeDecodeFrame` | `decode_frame()` raises `RuntimeError` on an `{"error": ...}` response; returns `None` when result is null |

---

### `test_validator_unit.py` — RoomValidator edge cases

Unit tests for `network/validator.py` that target guard conditions and special move handling not exercised by the integration-level relay tests.

| Class | What it verifies |
|---|---|
| `TestValidateAndApplyGuards` | Not-yet-initialized validator allows any move; missing coordinate fields rejected; `_current_team=None` rejected; empty from-square rejected; wrong team's piece rejected; missing king rejected |
| `TestSkyFallOnCheck` | `sky_fall()` is called for a non-King piece when the king is in check; a move that doesn't resolve check is correctly rejected |
| `TestApplyPawnPromotion` | A team_r pawn reaching row 7 is replaced with a `Queen` in `_apply()` |
| `TestApplyCastling` | After queenside castling, king moves to (0,2) and rook moves to (0,3); old rook square is cleared |
| `TestApplyEnPassant` | After an en-passant capture, the captured pawn is removed from its row (not the capture destination) |

---

## Adding new tests

**Where to put them:**

| New code | Test file |
|---|---|
| `pieces/*.py` | `test_pieces.py` or `test_king.py` |
| `core/` | `test_primitives.py` |
| `ai/` | `test_ai_tree.py` |
| `game/board.py` | `test_board.py` |
| `simulator/app.py` (GameRunner) | `test_simulator.py` or `test_gameplay.py` |
| `simulator/networked_runner.py` | `test_networked_runner.py` |
| `simulator/sensor.py`, `simulator/fake_rgbmatrix.py` | `test_simulator_extras.py` |
| `harness/python_bridge.py` | `test_python_bridge.py` |
| `network/protocol.py`, `server.py`, `client.py`, `discovery.py` | `test_network.py` |
| `network/relay.py` | `test_relay.py` |
| `network/validator.py` | `test_validator_unit.py` or `test_relay.py` |
| `network/chessmatrix.py` | `test_chessmatrix_scanning.py` |
| `web/chessmatrix-scanner.js` | `test_chessmatrix_js.js` |
| `web/sim.html` (game logic) | `test_sim_js.js` |
| Full online flow | `test_online_flow.py` |
| Python↔JS parity (ChessMatrix) | `test_lockstep_chessmatrix.py` |
| Python↔JS parity (chess engine) | `test_lockstep_chess.py` |
| Python↔JS↔Spectator parity | `test_lockstep_networked.py` |
| `web/spectator-engine.js` | `test_lockstep_networked.py` |

**Minimal piece test pattern:**

```python
def test_rook_blocked_by_friendly(make_board, team_r, team_l):
    rook = Rook(4, 4, team_r)
    blocker = Pawn(4, 6, team_r)   # friendly — should stop ray
    board = make_board({(4, 4): rook, (4, 6): blocker})
    rook.calc_targets(board)
    targets = {(c.row, c.col) for c in rook.targets}
    assert (4, 6) not in targets, "Rook must not capture friendly piece"
    assert (4, 7) not in targets, "Rook must not pass through friendly piece"
```

**Headless Pygame (for GameRunner tests):** set `SDL_VIDEODRIVER=dummy` and `SDL_AUDIODRIVER=dummy` at the top of the file before importing `pygame`.

**BUG LOCK-IN pattern:** when a test deliberately exercises a known bug to prevent silent regression, add:

```python
# BUG LOCK-IN (BUG-XX): <one-line description of the bug>
assert <known-wrong-but-stable-value>
```

This makes it obvious the assertion matches current behaviour intentionally, not by mistake. See `bug_report.md` for the full bug list.

---

## Fixtures directory

`tests/fixtures/chessmatrix/` holds PNG images used by the scanner tests:
- **Real photos** — actual phone photos of the ChessMatrix barcode printed or displayed
- **Synthetic PNGs** — generated reference images committed for regression testing

Any `.png` file added here is automatically picked up by `test_chessmatrix_scanning.py` and `test_chessmatrix_js.js`. For pipeline debugging at a specific stage, see `tools/debug_quad_detection.py`.
