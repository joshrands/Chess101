# Chess101

A physical chess board built on a Raspberry Pi. An 8×8 RGB LED matrix shows the board, eight Arduinos detect piece positions via reed switches, and Python handles all chess logic with an optional alpha-beta AI opponent.

A Mac simulator lets you play and develop without any Pi hardware — it opens a Pygame window and maps mouse clicks to piece moves.

---

## Requirements

- Python 3.9+
- Mac (for the simulator) or Raspberry Pi (for the physical board)
- No external services required for local play

---

## Setup

```bash
# Clone the repo and enter the project directory
cd Chess101

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Mac/Linux
# .venv\Scripts\activate           # Windows (not tested)

# Install dependencies
pip install -r requirements.txt
```

`requirements.txt` includes `pygame`, `numpy`, and `websockets`. The Pi-specific packages (`smbus`, `RPi.GPIO`, `rgbmatrix`) are not installed on Mac — the simulator stubs them out automatically.

---

## Running the Simulator (Mac)

### Local play

```bash
.venv/bin/python run_simulator.py           # opens the Lobby screen
.venv/bin/python run_simulator.py --local   # skip Lobby, go straight to color pick
```

**Lobby navigation:** arrow keys or mouse click to highlight an option, Enter or click to select.

### Networked play (LAN — two Macs on the same Wi-Fi)

**Machine A — host:**
```bash
.venv/bin/python run_simulator.py --host
```

The host's IP address is shown in the side panel. Games on the same subnet are auto-discovered via UDP beacon, so the guest usually does not need to type an IP.

**Machine B — join:**
```bash
.venv/bin/python run_simulator.py --join 192.168.1.42   # replace with host IP if needed
```

**Spectator:**
```bash
.venv/bin/python run_simulator.py --spectate 192.168.1.42
```

**Custom port** (default is 65101):
```bash
.venv/bin/python run_simulator.py --host --port 65200
.venv/bin/python run_simulator.py --join 192.168.1.42 --port 65200
```

### Game controls

| Action | Input |
|---|---|
| Select a piece | Left-click |
| Move the selected piece | Left-click a highlighted target square |
| Deselect | Left-click the selected piece again, or click empty space |
| New game (after game over) | Press `N` |

---

## Running on the Raspberry Pi

The Pi game requires `sudo` for LED matrix GPIO access.

```bash
sudo python3 GameManager.py
sudo python3 GameManager.py --led-rows=32 --led-cols=32 --led-chain=4
sudo python3 GameManager.py --led-gpio-mapping=adafruit-hat
```

The `rgbmatrix` library must be compiled on the Pi from source — see [rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix).

---

## Running Tests

All tests run on Mac without Pi hardware. The test suite uses `conftest.py` to stub `rgbmatrix` and `smbus` before any game code is imported.

```bash
# Run everything
.venv/bin/python -m pytest tests/ -q

# Verbose output
.venv/bin/python -m pytest tests/ -v

# Specific suites
.venv/bin/python -m pytest tests/test_gameplay.py -v    # chess logic
.venv/bin/python -m pytest tests/test_simulator.py -v   # simulator phase state machine
.venv/bin/python -m pytest tests/test_board.py -v       # Board-level (Pi controller)
.venv/bin/python -m pytest tests/test_network.py -v     # network protocol + transport
```

Expected result: **280 passed, 1 skipped** (the skipped test is a UDP broadcast test that is unreliable on loopback — the underlying logic is covered by adjacent tests).

---

## Type Checking

```bash
.venv/bin/mypy pieces/ core/ ai/ game/ hardware/ ui/ simulator/ network/
```

The codebase is held at **0 mypy errors**. `setup.cfg` has `ignore_missing_imports = True` so the Pi-only stubs don't cause noise on Mac.

---

## Project Layout

```
Chess101/
├── GameManager.py          # Pi entry point
├── run_simulator.py        # Mac entry point (injects hardware fakes, parses CLI)
│
├── game/                   # Game controller (Board) and rules
├── pieces/                 # Pawn, Rook, Knight, Bishop, Queen, King
├── core/                   # Cell, Team, constants
├── ai/                     # Alpha-beta minimax
├── hardware/               # I2C sensor interface (Pi only)
├── ui/                     # LED renderer helpers
│
├── network/                # LAN multiplayer transport
│   ├── protocol.py         # Message types, board serialization, hash
│   ├── server.py           # WebSocket server (asyncio daemon thread)
│   ├── client.py           # WebSocket client (asyncio daemon thread)
│   └── discovery.py        # UDP beacon broadcast + listener
│
├── simulator/              # Mac simulator
│   ├── app.py              # GameRunner — Pygame event loop + phase state machine
│   ├── networked_runner.py # NetworkedGameRunner — multiplayer extension
│   ├── fake_rgbmatrix.py   # Pygame-backed LED canvas mock
│   └── sensor.py           # Click-driven reed-switch mock
│
├── plans/multiplayer/      # Design docs for multiplayer phases 1–3
└── tests/                  # pytest suite (280 tests)
```

---

## Known Bugs

A full list with severity ratings is in `bug_report.md`. The two high-severity items:

- **BUG-04** — Fifty-move rule fires at 50 half-moves instead of the correct 100 (50 full moves).
- **BUG-07** — Double check only tracks the first attacker; the second allows illegal blocking moves.

All bugs are locked in by tests so they do not regress accidentally.

---

## Multiplayer Roadmap

| Phase | Status | Description |
|---|---|---|
| Phase 1 | Complete | LAN Sim vs Sim over WebSocket |
| Phase 2 | Planned | Pi + physical board support |
| Phase 3 | Planned | Internet play via relay server |

See `plans/multiplayer/` for full design documents covering protocol, architecture, UX flows, and implementation steps for each phase.
