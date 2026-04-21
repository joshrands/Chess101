# HIL (Hardware-In-The-Loop)

The HIL system runs the Pi game loop (`game/board.py`) in a Docker container that approximates the Raspberry Pi 3+ environment (ARM64 Debian Jessie). It's the primary way to test the Pi code path without physical hardware.

## When to use HIL

- Testing `game/board.py`, `hardware/`, or anything that runs on the Pi
- Verifying the physical-board game flow end-to-end
- Running `harness/fuzz_hil.py` for automated game-loop regression

## Running the HIL

**Docker (recommended — closest to Pi):**
```bash
# Build and start:
docker-compose -f docker-compose.hil.yml up --build

# Background:
docker-compose -f docker-compose.hil.yml up -d
docker-compose -f docker-compose.hil.yml logs -f

# Stop:
docker-compose -f docker-compose.hil.yml down
```

**Without Docker (faster, less Pi-accurate):**
```bash
python -m hil.run_hil
python -m hil.run_hil --host-online    # connect to relay as host
python -m hil.run_hil --join-online    # connect to relay as guest
```

**View the board visually:**
Open `web/hil_visualizer.html` in a browser while the HIL is running. It connects to `ws://localhost:8766` and renders the LED frame live.

## Control interface

The HIL exposes a WebSocket JSON-RPC server on port **8766**. Use `HilBridge` from Python:

```python
from hil.client import HilBridge

with HilBridge("ws://localhost:8766") as hil:
    hil.ping()                          # True
    hil.set_starting_position()         # place all pieces at start
    hil.lift_piece(6, 4)                # simulate lifting e2
    hil.place_piece(4, 4)               # simulate placing at e4
    frame, ts, count = hil.get_frame()  # 32×32 RGB pixel array
    grid = hil.get_sensor_state()       # 8×8 reed switch grid
```

## Scripted scenarios

`harness/hil_scenarios.py` has generator functions that yield sequences of `Action` objects (LIFT, PLACE, WAIT, EXPECT) for common flows (color pick, war games, piece setup). Use these in tests rather than hardcoding raw row/col sequences.

## HIL tests

```bash
# Requires HIL running on port 8766:
bazel test //tests:test_hil
.venv/bin/python -m pytest tests/test_hil.py -v
```

## HIL fuzzer

```bash
.venv/bin/python harness/fuzz_hil.py --iterations 50
```

Plays random games through the HIL by injecting reed switch events and checking that the game loop stays consistent.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `HIL_PORT` | `8766` | WebSocket port |
| `HIL_FAST_MODE` | `0` | Set to `1` to reduce sleep durations for faster tests |
| `HIL_REAL_PI_MODE` | `1` | Enables Pi-accurate timing in Docker |

## Architecture

```
hil/run_hil.py          Entry point — injects mock rgbmatrix + smbus, starts control server
hil/control_server.py   WebSocket JSON-RPC server
hil/sensor.py           HilSensor — thread-safe injectable reed switch state
hil/rgbmatrix.py        HilRGBMatrix — captures every SwapOnVSync call as a frame
hil/client.py           HilBridge — synchronous Python client
hil/Dockerfile          ARM64 Debian Jessie with Python 3.9 built from source
docker-compose.hil.yml  Compose config (ARM64, port 8766, healthcheck)
```

The control server also exposes `chess_init` / `chess_legal_moves` / `chess_apply_move` methods for lockstep fuzzing the chess engine through the game loop.
