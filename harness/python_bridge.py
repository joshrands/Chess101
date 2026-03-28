"""Python wrapper for the Node.js lockstep bridge.

Usage::

    bridge = JsBridge()
    result = bridge.decode_frame(rgba_bytes, width, height)
    bridge.close()

Or as a context manager::

    with JsBridge() as bridge:
        result = bridge.decode_frame(rgba_bytes, width, height)
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

_BRIDGE_JS = Path(__file__).parent / "js_bridge.js"


class JsBridge:
    """Persistent Node.js subprocess for calling JS functions."""

    def __init__(self) -> None:
        self._proc = subprocess.Popen(
            ["node", str(_BRIDGE_JS)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(Path(__file__).resolve().parent.parent),
        )

    # ── lifecycle ───────────────────────────────────────────────────────

    def close(self) -> None:
        if self._proc.stdin:
            self._proc.stdin.close()
        self._proc.wait(timeout=5)

    def __enter__(self) -> "JsBridge":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── low-level RPC ───────────────────────────────────────────────────

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
            raise RuntimeError(f"JS bridge died. stderr: {stderr}")
        return json.loads(line)

    # ── typed methods ───────────────────────────────────────────────────

    def ping(self) -> str:
        resp = self._call({"op": "ping"})
        if "error" in resp:
            raise RuntimeError(resp["error"])
        return resp["result"]

    def decode_frame(self, rgba: bytes, w: int, h: int) -> str | None:
        """Decode an RGBA frame via the JS ChessMatrix scanner."""
        resp = self._call({
            "op": "decode_frame",
            "rgba_b64": base64.b64encode(rgba).decode("ascii"),
            "w": w,
            "h": h,
        })
        if "error" in resp:
            raise RuntimeError(resp["error"])
        return resp["result"]

    # ── chess ops ───────────────────────────────────────────────────────

    def chess_init(self, team_r: tuple, team_l: tuple) -> list:
        """Initialize the JS starting position. Returns grid JSON."""
        resp = self._call({
            "op": "chess_init",
            "team_r": list(team_r),
            "team_l": list(team_l),
        })
        if "error" in resp:
            raise RuntimeError(resp["error"])
        return resp["result"]["grid"]

    def chess_legal_moves(
        self, grid_json: list, team_r: tuple, team_l: tuple,
        active_team_key: str,
    ) -> list:
        """Get legal moves from the JS engine. Returns [[fr,fc,tr,tc], ...]."""
        resp = self._call({
            "op": "chess_legal_moves",
            "grid": grid_json,
            "team_r": list(team_r),
            "team_l": list(team_l),
            "active_team_key": active_team_key,
        })
        if "error" in resp:
            raise RuntimeError(resp["error"])
        return resp["result"]

    def chess_apply_move(
        self, grid_json: list, team_r: tuple, team_l: tuple,
        fr: int, fc: int, tr: int, tc: int,
        active_team_key: str, next_team_key: str,
        peace_time: int,
    ) -> dict:
        """Apply a move on the JS side. Returns {grid, board_hash, status, flags}."""
        resp = self._call({
            "op": "chess_apply_move",
            "grid": grid_json,
            "team_r": list(team_r),
            "team_l": list(team_l),
            "fr": fr, "fc": fc, "tr": tr, "tc": tc,
            "active_team_key": active_team_key,
            "next_team_key": next_team_key,
            "peace_time": peace_time,
        })
        if "error" in resp:
            raise RuntimeError(resp["error"])
        return resp["result"]

    def chess_board_hash(
        self, grid_json: list, team_r: tuple, team_l: tuple,
        peace_time: int, current_team_key: str,
    ) -> str:
        """Compute board_hash on the JS side."""
        resp = self._call({
            "op": "chess_board_hash",
            "grid": grid_json,
            "team_r": list(team_r),
            "team_l": list(team_l),
            "peace_time": peace_time,
            "current_team_key": current_team_key,
        })
        if "error" in resp:
            raise RuntimeError(resp["error"])
        return resp["result"]
