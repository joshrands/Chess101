"""Python wrapper for the Swift chess engine bridge.

Launches the compiled SwiftBridge executable as a subprocess and speaks the
same JSON line-protocol as JsBridge in python_bridge.py.

Usage::

    bridge = SwiftBridge()
    assert bridge.ping() == "pong"
    grid  = bridge.chess_init(TEAM_R_RGB, TEAM_L_RGB)["grid"]
    moves = bridge.chess_legal_moves(grid, TEAM_R_RGB, TEAM_L_RGB, "r")
    bridge.close()
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

_PKG_PATH = Path(__file__).parent.parent / "Chess101iOS"


def _ensure_built() -> Path:
    """Build the SwiftBridge if it isn't already present."""
    bin_path = _PKG_PATH / ".build" / "debug" / "SwiftBridge"
    if not bin_path.exists():
        print("Building SwiftBridge…", flush=True)
        subprocess.run(["swift", "build"], cwd=str(_PKG_PATH), check=True)
    return bin_path


class SwiftBridge:
    """Persistent SwiftBridge subprocess for lockstep testing."""

    def __init__(self) -> None:
        bin_path = _ensure_built()
        self._proc = subprocess.Popen(
            [str(bin_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    # ── lifecycle ──────────────────────────────────────────────────────────

    def close(self) -> None:
        if self._proc.stdin:
            self._proc.stdin.close()
        self._proc.wait(timeout=10)

    def __enter__(self) -> "SwiftBridge":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── low-level RPC ──────────────────────────────────────────────────────

    def _call(self, msg: dict) -> dict:
        payload = json.dumps(msg) + "\n"
        assert self._proc.stdin is not None
        assert self._proc.stdout is not None
        self._proc.stdin.write(payload.encode())
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            stderr = ""
            if self._proc.stderr:
                stderr = self._proc.stderr.read().decode(errors="replace")
            raise RuntimeError(f"SwiftBridge died. stderr: {stderr}")
        resp = json.loads(line)
        if "error" in resp:
            raise RuntimeError(f"SwiftBridge error: {resp['error']}")
        return resp

    # ── typed methods ──────────────────────────────────────────────────────

    def ping(self) -> str:
        return self._call({"op": "ping"})["result"]

    def chess_init(self, team_r: tuple, team_l: tuple) -> list:
        """Returns an 8×8 grid list (same shape as JsBridge.chess_init)."""
        return self._call({
            "op": "chess_init",
            "team_r": list(team_r),
            "team_l": list(team_l),
        })["result"]["grid"]

    def chess_legal_moves(
        self, grid: list, team_r: tuple, team_l: tuple,
        active_team_key: str,
    ) -> list:
        """Returns [[fr, fc, tr, tc], ...]."""
        return self._call({
            "op": "chess_legal_moves",
            "grid": grid,
            "team_r": list(team_r),
            "team_l": list(team_l),
            "active_team_key": active_team_key,
        })["result"]

    def chess_apply_move(
        self, grid: list, team_r: tuple, team_l: tuple,
        fr: int, fc: int, tr: int, tc: int,
        active_team_key: str, next_team_key: str,
        peace_time: int,
    ) -> dict:
        """Returns {"grid": ..., "board_hash": str, "status": str}."""
        return self._call({
            "op": "chess_apply_move",
            "grid": grid,
            "team_r": list(team_r),
            "team_l": list(team_l),
            "fr": fr, "fc": fc, "tr": tr, "tc": tc,
            "active_team_key": active_team_key,
            "next_team_key": next_team_key,
            "peace_time": peace_time,
        })["result"]

    def chess_board_hash(
        self, grid: list, team_r: tuple, team_l: tuple,
        peace_time: int, current_team_key: str,
    ) -> str:
        return self._call({
            "op": "chess_board_hash",
            "grid": grid,
            "team_r": list(team_r),
            "team_l": list(team_l),
            "peace_time": peace_time,
            "current_team_key": current_team_key,
        })["result"]
