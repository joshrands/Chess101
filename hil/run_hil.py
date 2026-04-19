#!/usr/bin/env python3
"""Entry point for the Chess101 HIL Docker container.

Injects mock hardware modules before any game imports, starts the
WebSocket control server, then runs the Pi game loop. External tests
can control the game via the WebSocket JSON-RPC interface.

Run with:
    python -m hil.run_hil
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import types

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── 1. Import HIL mocks FIRST (before injecting into sys.modules) ────────────
from hil.sensor import HilSensor
from hil.rgbmatrix import HilRGBMatrix, HilFrameCanvas, HilRGBMatrixOptions

# Create shared instances that will be used by the game and control server
_hil_sensor = HilSensor()
_hil_matrix = HilRGBMatrix()

# ── 2. Inject fake rgbmatrix BEFORE any game module imports it ────────────────
_rmod = types.ModuleType("rgbmatrix")
_rmod.RGBMatrix = lambda options=None: _hil_matrix  # Return shared instance
_rmod.RGBMatrixOptions = HilRGBMatrixOptions
_rmod.FrameCanvas = HilFrameCanvas
sys.modules["rgbmatrix"] = sys.modules["rgbmatrix.core"] = _rmod

# ── 3. Inject stub smbus (hardware/master.py imports it at module level) ─────
_smbus = types.ModuleType("smbus")


class _SMBus:
    def __init__(self, *a, **kw) -> None:
        pass

    def read_byte(self, *a, **kw) -> int:
        return 0

    def write_byte(self, *a, **kw) -> None:
        pass


_smbus.SMBus = _SMBus
sys.modules["smbus"] = _smbus

# ── 4. Now safe to import game code ───────────────────────────────────────────
from game.board import Board  # noqa: E402
from hil.control_server import ControlServer  # noqa: E402


def _patch_board_sensor() -> None:
    """Monkey-patch Board to use HilSensor by default.

    The Board.__init__ accepts sensor= kwarg but GameManager.py calls
    Board() with no arguments. This patch makes HilSensor the default.
    """
    original_init = Board.__init__

    def patched_init(self, *args, sensor=None, **kwargs):
        if sensor is None:
            sensor = _hil_sensor
        original_init(self, *args, sensor=sensor, **kwargs)

    Board.__init__ = patched_init
    logger.info("Patched Board to use HilSensor")


def main() -> None:
    """Start the HIL control server and run the game loop."""
    port = int(os.environ.get("HIL_PORT", "8766"))
    fast_mode = os.environ.get("HIL_FAST_MODE", "0") == "1"

    if fast_mode:
        logger.info("HIL_FAST_MODE enabled - reducing sleep durations")
        # TODO: Patch time.sleep to reduce delays

    # Apply Board monkey-patch
    _patch_board_sensor()

    # Start control server in daemon thread
    control = ControlServer(_hil_sensor, _hil_matrix, port=port)
    control_thread = threading.Thread(target=control.run, daemon=True)
    control_thread.start()
    logger.info("ControlServer started on port %d", port)

    # Give server time to bind
    import time
    time.sleep(0.5)

    # Run the game loop (same as GameManager.main but with our injected hardware)
    logger.info("Starting game loop...")
    try:
        while True:
            board = Board()
            board.process()
            logger.info("Game ended, starting new game...")
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    main()
