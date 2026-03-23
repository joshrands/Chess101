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
# Local single-Pi game (no network)
sudo python3 GameManager.py
sudo python3 GameManager.py --led-rows=32 --led-cols=32 --led-chain=4
sudo python3 GameManager.py --led-gpio-mapping=adafruit-hat

# Networked: Pi hosts, Mac Sim joins (Pi is team_r)
sudo python3 GameManager.py --host
sudo python3 GameManager.py --host --port 65200

# Networked: Pi joins a Sim host (Pi is team_l)
sudo python3 GameManager.py --join 192.168.1.42
sudo python3 GameManager.py --join 192.168.1.42 --port 65200
```

In `--host` mode the Pi waits for a Mac simulator to connect. The simulator acts as the setup UI: it shows the colour-pick and Human/AI selection screens for both teams, then the Pi runs physical piece placement (`interactive_setup`) while the simulator shows a progress display.

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
.venv/bin/python -m pytest tests/test_network.py -v              # network protocol, transport + NetworkedBoard
.venv/bin/python -m pytest tests/test_networked_runner.py -v     # NetworkedGameRunner online-play fixes + relay-reconnect board-reset guards
.venv/bin/python -m pytest tests/test_online_flow.py -v          # E2E online flow: handshake → color-pick → war-games → playing
.venv/bin/python -m pytest tests/test_relay.py -v                # relay server (see modes below)
```

### Relay test modes

`test_relay.py` spins up an in-process relay by default — no Docker or network access needed:

```bash
# Default — in-process relay, fast:
.venv/bin/python -m pytest tests/test_relay.py -v

# Docker — builds chess101-relay image, runs a container for the session:
.venv/bin/python -m pytest tests/test_relay.py -v --relay-docker

# External relay — point at any running relay (local Docker or live):
docker run -d -p 8765:8765 -e RELAY_PORT=8765 chess101-relay
RELAY_URL=ws://127.0.0.1:8765 .venv/bin/python -m pytest tests/test_relay.py -v

# Post-deploy smoke test against the live relay:
RELAY_URL=wss://relay.chess101.net .venv/bin/python -m pytest tests/test_relay.py -v
```

---

## Type Checking

```bash
.venv/bin/mypy pieces/ core/ ai/ game/ hardware/ ui/ simulator/ network/
```

`requirements.txt` also includes `zeroconf>=0.131` for mDNS LAN discovery (used by Phase 2 physical-board support).

The codebase is held at **0 mypy errors**. `setup.cfg` has `ignore_missing_imports = True` so the Pi-only stubs don't cause noise on Mac.

---

## Project Layout

```
Chess101/
├── GameManager.py          # Pi entry point (supports --host / --join)
├── run_simulator.py        # Mac entry point (injects hardware fakes, parses CLI)
│
├── game/
│   ├── board.py            # Game controller (Board) and rules
│   ├── networked_board.py  # NetworkedBoard — Board + network send/receive (Pi)
│   └── rules.py            # Fifty-move rule, threefold repetition
├── pieces/                 # Pawn, Rook, Knight, Bishop, Queen, King
├── core/                   # Cell, Team, constants
├── ai/                     # Alpha-beta minimax
├── hardware/               # I2C sensor interface (Pi only)
├── ui/                     # LED renderer helpers
│
├── network/                # Multiplayer transport — LAN and internet
│   ├── protocol.py         # Message types, board serialization, hash
│   ├── server.py           # WebSocket server (asyncio daemon thread)
│   ├── client.py           # WebSocket client (asyncio daemon thread)
│   ├── discovery.py        # UDP beacon broadcast + listener
│   ├── mdns.py             # mDNS/DNS-SD advertiser + browser (zeroconf)
│   ├── relay.py            # Internet relay server (room codes, reconnect, anti-cheat)
│   ├── relay_client.py     # Relay client (wraps handshake, cold-start retry)
│   └── validator.py        # Server-side move validator (anti-cheat)
│
├── simulator/              # Mac simulator
│   ├── app.py              # GameRunner — Pygame event loop + phase state machine
│   ├── networked_runner.py # NetworkedGameRunner — multiplayer + spectator
│   ├── fake_rgbmatrix.py   # Pygame-backed LED canvas mock
│   └── sensor.py           # Click-driven reed-switch mock
│
├── plans/multiplayer/      # Design docs for multiplayer phases 1–3
└── tests/                  # pytest suite (422 tests)
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
| Phase 2 | Complete | Pi + physical board support (NetworkedBoard, mDNS, Sim-as-UI) |
| Phase 3 | Complete | Internet play via relay server (deployed to relay.chess101.net) |

See `plans/multiplayer/` for full design documents covering protocol, architecture, UX flows, and implementation steps for each phase.
