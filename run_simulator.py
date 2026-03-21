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

from simulator.app import GameRunner  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chess101 Simulator")
    parser.add_argument("--local",    action="store_true",
                        help="Skip Lobby and go straight to COLOR_PICK")
    parser.add_argument("--host",     action="store_true",
                        help="Host a networked game immediately")
    parser.add_argument("--join",     metavar="IP",
                        help="Join a networked game at the given IP")
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
    elif args.join:
        from simulator.networked_runner import NetworkedGameRunner, NetworkRole
        NetworkedGameRunner(
            role=NetworkRole.GUEST,
            host_ip=args.join,
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
