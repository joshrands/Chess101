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
        """Decode an RGBA frame via the JS ChessMatrix scanner.

        Parameters
        ----------
        rgba : bytes
            Raw RGBA pixel data (4 bytes per pixel, row-major).
        w, h : int
            Image dimensions.

        Returns
        -------
        str | None
            6-char room code, or None if decoding failed.
        """
        resp = self._call({
            "op": "decode_frame",
            "rgba_b64": base64.b64encode(rgba).decode("ascii"),
            "w": w,
            "h": h,
        })
        if "error" in resp:
            raise RuntimeError(resp["error"])
        return resp["result"]
