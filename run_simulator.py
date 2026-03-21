#!/usr/bin/env python3
"""Entry point for the Chess101 Mac Pygame simulator.

Injects fake hardware modules before any game imports, then starts the
simulator's non-blocking game loop.

Run with:
    .venv/bin/python run_simulator.py
"""
import sys
import types

# ── 1. Inject fake rgbmatrix BEFORE any game module imports it ─────────────
import simulator.fake_rgbmatrix as _frm

_rmod = types.ModuleType("rgbmatrix")
_rmod.RGBMatrix = _frm.FakeRGBMatrix
_rmod.RGBMatrixOptions = _frm.FakeRGBMatrixOptions
_rmod.FrameCanvas = _frm.FakeFrameCanvas
sys.modules["rgbmatrix"] = sys.modules["rgbmatrix.core"] = _rmod

# ── 2. Inject stub smbus (hardware/master.py imports it at module level) ───
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

# ── 3. Now safe to import Board-dependent code ─────────────────────────────
import argparse  # noqa: E402
import time      # noqa: E402
from typing import Optional  # noqa: E402

from simulator.app import GameRunner  # noqa: E402


def _auto_discover(port: int, timeout: float = 8.0) -> Optional[str]:
    """Block until a game beacon is found on the LAN, then return its IP.

    Prints progress to stderr so the user knows something is happening.
    Returns None if nothing is found within *timeout* seconds.
    """
    from network.discovery import BeaconListener
    print(f"Scanning for games on the network (up to {int(timeout)}s)...",
          flush=True)
    listener = BeaconListener()
    listener.start()
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            for game in listener.games.values():
                if game.port == port:
                    print(f"Found game: {game.host_name} at {game.ip}:{game.port}",
                          flush=True)
                    return game.ip
            time.sleep(0.25)
    finally:
        listener.stop()
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chess101 Simulator")
    parser.add_argument("--local",    action="store_true",
                        help="Skip Lobby and go straight to COLOR_PICK")
    parser.add_argument("--host",     action="store_true",
                        help="Host a networked game immediately")
    parser.add_argument("--join",     nargs="?", const="", metavar="IP",
                        help="Join a networked game (auto-discover if no IP given)")
    parser.add_argument("--spectate", metavar="IP",
                        help="Spectate a networked game at the given IP")
    parser.add_argument("--port",     type=int, default=65101,
                        help="WebSocket port (default 65101)")
    args = parser.parse_args()

    if args.local:
        GameRunner(skip_lobby=True).run()
    elif args.host:
        from simulator.networked_runner import NetworkedGameRunner, NetworkRole
        NetworkedGameRunner(
            role=NetworkRole.HOST,
            port=args.port,
            player_name="Host",
        ).run()
    elif args.join is not None:
        from simulator.networked_runner import NetworkedGameRunner, NetworkRole
        host_ip = args.join or _auto_discover(args.port)
        if host_ip is None:
            print("ERROR: No games found on the network. "
                  "Make sure the host is running: run_simulator.py --host",
                  file=sys.stderr)
            sys.exit(1)
        NetworkedGameRunner(
            role=NetworkRole.GUEST,
            host_ip=host_ip,
            port=args.port,
            player_name="Guest",
        ).run()
    elif args.spectate:
        from simulator.networked_runner import NetworkedGameRunner, NetworkRole
        NetworkedGameRunner(
            role=NetworkRole.SPECTATOR,
            host_ip=args.spectate,
            port=args.port,
            player_name="Spectator",
        ).run()
    else:
        GameRunner().run()
