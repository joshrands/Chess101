# CLAUDE.md

Guidance for Claude Code when working in this repository.

---

## Git commits

Commit messages must be concise and terse — one short line describing what changed. Do not include Claude as a co-author. No "Co-Authored-By" trailers.

---

## Critical principles

### 1. The Three-Platform Rule
Chess logic lives in **three engines that must stay in sync**:
- **Python** — `pieces/`, `game/`, `core/` (the canonical source)
- **JavaScript** — `web/chess-engine.js` (used by browser sim and spectator)
- **Swift** — `Chess101iOS/Sources/Chess101Engine/` (used by iOS app)

Any chess logic change (legal moves, board hash, move encoding) must be reflected in **all three**. The lockstep fuzzers (`harness/fuzz_lockstep.py`, `harness/fuzz_networked.py`) verify parity — run them after engine changes.

### 2. The Physical Board Is the Real Target
All code runs on a Raspberry Pi with:
- 8×8 RGB LED matrix (32×32 pixels total, 4×4 per cell)
- 8 Arduinos via I2C (one per row), detecting reed switches
- `sudo` required on Pi for LED matrix access

Never break the Pi code path. Use the HIL container (`hil/`) to test the Pi game loop without physical hardware — see `hil/CLAUDE.md`.

### 3. Bazel Is the Canonical Test Runner
Always run tests via Bazel, not pytest directly. See "Running Tests" below.

### 4. Always Add Regression Tests
Every bug fix and feature change needs a regression test. If the fix touches:
- Python simulator/networking → add to the relevant `tests/test_*.py`
- `web/chess-engine.js` or `web/sim.html` → add to `tests/test_sim_js.js`
- `Chess101iOS/Sources/Chess101Engine/` → add to `Chess101iOS/Tests/`

### 5. Fuzzers Must Use Real Game Code
Fuzzers should exercise as much actual game code as possible. Don't create parallel implementations or mock the game layer — run the real `NetworkedGameRunner`, `NetworkedBoard`, `GameServer`, `GameClient`, etc. If a fix goes into game code, the fuzzer must run that code to verify the fix works.

---

## Shell notes

**Never `cd` into the project root** — the working directory is already the project root.

**Always run Gazelle** after adding/removing Python files or changing imports:
```bash
bazel run //:gazelle
```
Review the diff before committing — Gazelle may incorrectly expand pre-seeded BUILD files (`hardware/BUILD`, `harness/BUILD.bazel`). Revert those and keep only valid additions.

---

## Running the Game

**Mac simulator (local play):**
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run_simulator.py           # Lobby screen
.venv/bin/python run_simulator.py --local   # skip Lobby → COLOR_PICK
```

**Mac simulator (networked):**
```bash
.venv/bin/python run_simulator.py --host
.venv/bin/python run_simulator.py --join 192.168.1.42
.venv/bin/python run_simulator.py --spectate 192.168.1.42
.venv/bin/python run_simulator.py --replay harness/crashes/chess/<file>.corpus.json
```

**Raspberry Pi:**
```bash
sudo python3 GameManager.py
sudo python3 GameManager.py --host
sudo python3 GameManager.py --join 192.168.1.42
sudo python3 GameManager.py --led-rows=32 --led-cols=32 --led-chain=4
```

**HIL container (Pi-approximate, no Pi hardware needed):**
```bash
docker-compose -f docker-compose.hil.yml up --build
# Then open web/hil_visualizer.html in a browser (connects to ws://localhost:8766)
# Or run without Docker:
python -m hil.run_hil
```
See `hil/CLAUDE.md` for details.

---

## Running Tests

**Always prefer Bazel:**
```bash
# Full suite (Python + JS + Swift):
bazel test //tests/... //Chess101iOS:Chess101IOSTests

# Single Python test with verbose output:
bazel test //tests:test_board --test_output=streamed --test_arg=-v

# JS tests:
bazel test //tests:test_chessmatrix_js
bazel test //tests:test_sim_js

# Swift tests:
bazel test //Chess101iOS:Chess101IOSTests

# HIL tests (requires running HIL container on port 8766):
bazel test //tests:test_hil
```

**Without Bazel (faster for iteration):**
```bash
.venv/bin/python -m pytest tests/ -q            # all Python
node tests/test_chessmatrix_js.js               # ChessMatrix JS
node tests/test_sim_js.js                       # web sim JS
cd Chess101iOS && swift test && cd ..           # Swift
```

**Lockstep fuzzers** (save disagreements to `harness/crashes/`):
```bash
bazel run //harness:fuzz_lockstep -- --iterations 100
bazel run //harness:fuzz_lockstep -- --iterations 100 --engines python,js
bazel run //harness:fuzz_lockstep -- --hil-url ws://localhost:8766
bazel run //harness:fuzz_networked -- --iterations 100
bazel run //harness:fuzz_chessmatrix -- --iterations 1000
bazel run //harness:fuzz_relay -- --iterations 100
.venv/bin/python harness/fuzz_lockstep.py --iterations 100   # Python+JS+Swift
.venv/bin/python harness/fuzz_hil.py --iterations 50         # HIL game loop
```

**Relay tests** need a relay server (Docker by default):
```bash
.venv/bin/python -m pytest tests/test_relay.py -v
RELAY_URL=wss://relay.chess101.net .venv/bin/python -m pytest tests/test_relay.py -v
```

The canonical test documentation is in `tests/README.md`.

---

## Keeping test documentation current

`tests/README.md` is the canonical test reference — update it whenever tests change (new file, new class, new relay mode). See the "Keeping test documentation current" table in that file.

---

## Package Structure

```
Chess101/
├── GameManager.py          # Pi entry point
├── run_simulator.py        # Mac entry point
├── samplebase.py           # LED matrix base class (SampleBase)
│
├── game/
│   ├── board.py            # Central controller (color-pick → setup → turns)
│   ├── networked_board.py  # Pi-side networked game (wraps GameServer/RelayClient)
│   └── rules.py            # Fifty-move rule, threefold repetition
│
├── pieces/                 # Chess logic — Python engine (must stay in sync with JS + Swift)
│   ├── piece.py            # Abstract base: targets, pin/check filtering
│   ├── pawn.py, rook.py, bishop.py, knight.py, queen.py, king.py
│
├── core/
│   ├── cell.py             # (row, col) coordinate struct
│   ├── team.py             # RGB colour identity
│   └── constants.py        # PieceValue, CellOccupancy enums
│
├── ai/
│   ├── ai.py               # Alpha-beta minimax
│   └── tree.py             # Game-tree node
│
├── hardware/
│   ├── master.py           # I2C polling of 8 Arduinos
│   ├── sensor.py           # BoardSensor ABC
│   ├── led_matrix.py       # LEDDisplay ABC
│   └── rotation.py         # RotatingMatrix — board rotation (0/90/180/270°)
│
├── ui/
│   └── renderer.py         # light_cell() — paints one 8×8 LED block per cell
│
├── network/
│   ├── protocol.py         # MoveFlags, encode_grid, decode_grid, board_hash
│   ├── server.py           # GameServer — asyncio WebSocket server (LAN host)
│   ├── client.py           # GameClient — asyncio WebSocket client (LAN guest)
│   ├── relay_client.py     # RelayClient — internet play via relay server
│   ├── relay.py            # Relay server (brokers games, room codes, reconnect)
│   ├── validator.py        # Server-side move validator (anti-cheat, used by relay)
│   ├── discovery.py        # BeaconBroadcaster + BeaconListener (UDP LAN discovery)
│   ├── mdns.py             # MdnsAdvertiser + MdnsListener (mDNS/DNS-SD)
│   └── chessmatrix.py      # ChessMatrix 8×8 four-color barcode: encode/render/decode
│
├── simulator/
│   ├── app.py              # GameRunner: Pygame loop, phase state machine + Lobby
│   ├── networked_runner.py # NetworkedGameRunner: multiplayer + SPECTATOR
│   ├── replay_runner.py    # ReplayRunner: corpus file interactive replay
│   ├── display.py          # SimDisplay: board/sidebar rendering helpers
│   ├── fake_rgbmatrix.py   # FakeFrameCanvas / FakeRGBMatrix (pygame.Surface)
│   └── sensor.py           # SimSensor(BoardSensor) — click-driven, no I2C
│
├── hil/                    # Hardware-in-the-Loop — see hil/CLAUDE.md
│   ├── run_hil.py          # Entry point: injects mocks, starts control server
│   ├── control_server.py   # WebSocket JSON-RPC server (port 8766)
│   ├── sensor.py           # HilSensor — injectable reed switch state
│   ├── rgbmatrix.py        # HilRGBMatrix — captures LED frames
│   ├── client.py           # HilBridge — Python client for the control server
│   └── Dockerfile          # ARM64 Debian Jessie (Pi-approximate environment)
│
├── web/                    # See web/CLAUDE.md
│   ├── chess-engine.js     # JS chess engine (must stay in sync with Python + Swift)
│   ├── spectator-engine.js # JS spectator move logic
│   ├── chessmatrix-scanner.js  # ChessMatrix decoder (browser + Node.js)
│   ├── sim.html            # Simulator web UI
│   ├── spectator.html      # Spectator web UI
│   ├── hil_visualizer.html # Visual display for the HIL container
│   └── index.html          # Landing page
│
├── Chess101iOS/            # See Chess101iOS/CLAUDE.md
│   ├── Sources/
│   │   ├── Chess101Engine/ # Pure Swift chess logic (must stay in sync with Python + JS)
│   │   ├── Chess101iOS/    # SwiftUI app
│   │   └── SwiftBridge/    # macOS CLI bridge for lockstep fuzzing
│   └── Tests/Chess101IOSTests/
│
├── harness/
│   ├── fuzz_lockstep.py        # Unified lockstep fuzzer (Python↔JS↔Swift↔HIL)
│   ├── fuzz_networked.py       # Three-way networked lockstep fuzzer
│   ├── fuzz_chessmatrix.py     # ChessMatrix lockstep fuzzer
│   ├── fuzz_relay.py           # Relay delivery fuzzer
│   ├── fuzz_hil.py             # HIL game loop fuzzer
│   ├── hil_scenarios.py        # Scripted HIL test scenarios (reed switch sequences)
│   ├── js_bridge.js            # Node.js stdio bridge for lockstep testing
│   ├── python_bridge.py        # JsBridge Python wrapper
│   ├── swift_bridge.py         # SwiftBridge Python wrapper
│   ├── chess_helpers.py        # Shared Python chess helpers
│   ├── corpus.py               # Corpus file save/load/discover
│   ├── replay.py               # ReplayEngine: step-by-step corpus replay
│   └── replay_crash.py         # Replay crash PNG through both decoders
│
├── tools/
│   ├── debug_quad_detection.py # Render ChessMatrix pipeline stages to PNG
│   └── pipeline_debug.html     # Interactive JS pipeline debugger
│
└── tests/                  # See tests/README.md
    ├── conftest.py          # Stubs rgbmatrix, smbus, RPi.GPIO for all tests
    └── test_*.py / *.js     # Test files — see tests/README.md for full index
```

---

## Architecture overview

### Entry points
- **`GameManager.py`** — Pi. `--host`/`--join`/`--port`. Without flags loops `Board().process()`. With network flags uses `NetworkedBoard` + `RelayClient`.
- **`run_simulator.py`** — Mac. `--local`, `--host`, `--join`, `--spectate`, `--port`, `--replay`.
- **`python -m hil.run_hil`** — headless Pi-approximate loop with WebSocket control.

### Game phases (simulator)
```
LOBBY → COLOR_PICK → WAR_GAMES → PLAYING → GAME_OVER → (N resets to LOBBY)
```

### Internet play flow
1. Host creates room via `RelayClient.create_room()` — gets 6-char code
2. Code displayed as ChessMatrix barcode; guest scans with iOS/web camera
3. Guest calls `RelayClient.join_room(code)`
4. Relay forwards all game messages transparently; validates moves server-side via `validator.py`

### Board coordinate system
`board.grid[row][col]` — 8×8, row 0 = `team_r` back rank, row 7 = `team_l` back rank. Each cell = 4×4 LED pixels on the Pi, 120×120 px in simulator (`SCALE = 30`).

### ChessMatrix barcode
Custom 8×8 four-color barcode for room codes. RS(8,4) Reed-Solomon ECC (recovers up to 2 wrong cells). Decoded by Python (`network/chessmatrix.py`), JS (`web/chessmatrix-scanner.js`), and Swift (`Chess101iOS/Sources/Chess101iOS/Network/ChessMatrix/`).

---

## Bazel build system

```bash
bazel test //tests/...                     # all Python + JS tests
bazel test //Chess101iOS:Chess101IOSTests  # Swift tests
bazel build //...                          # build everything
bazel run //:gazelle                       # regenerate BUILD files
```

Key files: `MODULE.bazel`, root `BUILD`, `requirements_lock.txt`, `.bazelrc`.

Pre-seeded BUILD files Gazelle cannot auto-generate:
- `hardware/BUILD` — Pi-only deps
- `tools/BUILD` — self-referential imports
- `harness/BUILD.bazel` — JS bridge data deps

---

## Type checking

```bash
.venv/bin/mypy pieces/ core/ ai/ game/ hardware/ ui/ simulator/ network/
```

Config in `setup.cfg`. `ignore_missing_imports = True` for Pi-only stubs. Target: **0 mypy errors**.

---

## Known Bugs

See `bug_report.md`. Key items:

| ID | Severity | Summary |
|---|---|---|
| BUG-01 | Medium | Pawn direction set by row number, not team |
| BUG-04 | High | Fifty-move rule fires at 50 half-moves instead of 100 |
| BUG-07 | High | Double check only tracks first attacker |
| BUG-09 | Medium | `filter_to_king_escape` re-appends en passant target when it shouldn't |

---

## Hardware dependencies (Pi only)

- `smbus` — I2C to Arduinos
- `rgbmatrix` — compiled Cython library (build on Pi)
- `RPi.GPIO` — GPIO access

All three are stubbed by `tests/conftest.py` and `hil/run_hil.py` so tests and HIL run on Mac.
