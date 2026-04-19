#!/usr/bin/env python3
"""Entry point for the Chess101 HIL Docker container.

Injects mock hardware modules before any game imports, starts the
WebSocket control server, then runs the Pi game loop. External tests
can control the game via the WebSocket JSON-RPC interface.

Run with:
    python -m hil.run_hil
    python -m hil.run_hil --host-online --board-rotation 270
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
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
    """Monkey-patch Board to use HilSensor by default."""
    original_init = Board.__init__

    def patched_init(self, *args, sensor=None, **kwargs):
        if sensor is None:
            sensor = _hil_sensor
        original_init(self, *args, sensor=sensor, **kwargs)

    Board.__init__ = patched_init
    logger.info("Patched Board to use HilSensor")


def _build_board(args) -> Board:
    """Build Board or NetworkedBoard based on CLI flags (mirrors GameManager)."""
    if args.host_online or args.join_online:
        from game.networked_board import NetworkedBoard
        from network.relay_client import RelayClient

        relay_url = args.relay_url
        if args.host_online:
            relay = RelayClient(relay_url=relay_url, role="host", player_name="HIL")
            board = NetworkedBoard(
                net=relay, local_team_key="r", relay=relay,
                rotation=args.board_rotation, sensor=_hil_sensor,
            )
            relay.set_message_handler(board._on_network_message)
            relay.on_connected = board.on_connected
            relay.on_disconnected = board.on_disconnected
            logger.info("Online host mode — relay: %s", relay_url)
        else:
            relay = RelayClient(relay_url=relay_url, role="guest", player_name="HIL")
            board = NetworkedBoard(
                net=relay, local_team_key="l", relay=relay,
                rotation=args.board_rotation, sensor=_hil_sensor,
            )
            relay.set_message_handler(board._on_network_message)
            relay.on_connected = board.on_connected
            relay.on_disconnected = board.on_disconnected
            logger.info("Online guest mode — relay: %s", relay_url)
        return board

    return Board(rotation=args.board_rotation, sensor=_hil_sensor)


def main() -> None:
    """Start the HIL control server and run the game loop."""
    parser = argparse.ArgumentParser(description="Chess101 HIL container")
    parser.add_argument("--host-online", action="store_true",
                        help="Internet host via relay server")
    parser.add_argument("--join-online", action="store_true",
                        help="Internet guest via relay server")
    parser.add_argument("--relay-url", default="wss://relay.chess101.net",
                        help="Relay server WebSocket URL")
    parser.add_argument("--board-rotation", type=int, default=0,
                        choices=[0, 90, 180, 270],
                        help="Board rotation (degrees CW)")
    args = parser.parse_args()

    port = int(os.environ.get("HIL_PORT", "8766"))
    fast_mode = os.environ.get("HIL_FAST_MODE", "0") == "1"

    if fast_mode:
        logger.info("HIL_FAST_MODE enabled - reducing sleep durations")

    # Apply Board monkey-patch (for plain Board() calls)
    _patch_board_sensor()

    # Start control server in daemon thread
    control = ControlServer(_hil_sensor, _hil_matrix, port=port)
    control_thread = threading.Thread(target=control.run, daemon=True)
    control_thread.start()
    logger.info("ControlServer started on port %d", port)

    time.sleep(0.5)

    logger.info("Starting game loop (rotation=%d)...", args.board_rotation)
    try:
        while True:
            board = _build_board(args)
            board.process()
            logger.info("Game ended, starting new game...")
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    main()
