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
from simulator.app import GameRunner  # noqa: E402

if __name__ == "__main__":
    GameRunner().run()
