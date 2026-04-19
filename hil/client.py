"""Client library for controlling the HIL Docker container.

HilBridge provides a synchronous Python API for injecting reed switch
events and reading LED frames from the HIL container.
"""
from __future__ import annotations

import json
import time
from typing import Any, Tuple

# gazelle:ignore websocket
try:
    from websocket import WebSocket, create_connection
except ImportError:
    WebSocket = None  # type: ignore


class HilBridge:
    """Synchronous client for the HIL container's WebSocket control interface.

    Usage:
        bridge = HilBridge("ws://localhost:8766")
        bridge.connect()
        bridge.lift_piece(6, 4)  # Lift piece at e2
        bridge.place_piece(4, 4)  # Place at e4
        frame = bridge.get_frame()
        bridge.close()
    """

    def __init__(self, url: str = "ws://localhost:8766", timeout: float = 10.0):
        """Initialize the bridge.

        Args:
            url: WebSocket URL of the HIL container.
            timeout: Connection and operation timeout in seconds.
        """
        if WebSocket is None:
            raise ImportError("websocket-client package required for HilBridge")
        self._url = url
        self._timeout = timeout
        self._ws: WebSocket | None = None
        self._req_id = 0

    def connect(self, retries: int = 5, delay: float = 1.0) -> None:
        """Connect to the HIL container with retries.

        Args:
            retries: Number of connection attempts.
            delay: Delay between retries in seconds.

        Raises:
            ConnectionError: If connection fails after all retries.
        """
        for attempt in range(retries):
            try:
                self._ws = create_connection(self._url, timeout=self._timeout)
                return
            except Exception as e:
                if attempt == retries - 1:
                    raise ConnectionError(
                        f"Failed to connect to HIL at {self._url}: {e}"
                    ) from e
                time.sleep(delay)

    def close(self) -> None:
        """Close the WebSocket connection."""
        if self._ws:
            self._ws.close()
            self._ws = None

    def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send a JSON-RPC request and return the result.

        Args:
            method: RPC method name.
            params: Method parameters.

        Returns:
            The "result" field from the response.

        Raises:
            RuntimeError: If not connected or RPC returns an error.
        """
        if self._ws is None:
            raise RuntimeError("Not connected to HIL container")

        self._req_id += 1
        req = {"method": method, "params": params or {}, "id": self._req_id}
        self._ws.send(json.dumps(req))

        resp_text = self._ws.recv()
        resp = json.loads(resp_text)

        if "error" in resp:
            raise RuntimeError(f"HIL RPC error: {resp['error']}")

        return resp.get("result")

    def lift_piece(self, row: int, col: int) -> None:
        """Simulate lifting a piece from a cell (reed switch → empty).

        Args:
            row: Board row (0-7).
            col: Board column (0-7).
        """
        self._call("reed_switch", {"row": row, "col": col, "state": "lifted"})

    def place_piece(self, row: int, col: int) -> None:
        """Simulate placing a piece on a cell (reed switch → occupied).

        Args:
            row: Board row (0-7).
            col: Board column (0-7).
        """
        self._call("reed_switch", {"row": row, "col": col, "state": "placed"})

    def get_frame(self) -> tuple[list[list[Tuple[int, int, int]]] | None, float, int]:
        """Get the current LED frame.

        Returns:
            Tuple of (pixels, timestamp, frame_count).
            pixels is a 32x32 list of (r, g, b) tuples, or None if no frame yet.
        """
        result = self._call("get_frame")
        if result is None:
            return None, 0.0, 0
        pixels = result.get("pixels")
        if pixels:
            pixels = [[tuple(p) for p in row] for row in pixels]
        return pixels, result.get("timestamp", 0.0), result.get("frame_count", 0)

    def get_sensor_state(self) -> list[list[int]]:
        """Get the current reed switch grid state.

        Returns:
            8x8 list of occupancy values (0=piece present, 1=empty).
        """
        result = self._call("get_sensor_state")
        return result.get("grid", [])

    def set_starting_position(self) -> None:
        """Set reed switches to standard chess starting position."""
        self._call("set_starting_position")

    def ping(self) -> bool:
        """Check if the container is responsive.

        Returns:
            True if ping succeeded.
        """
        try:
            result = self._call("ping")
            return result == "pong"
        except Exception:
            return False

    def __enter__(self) -> "HilBridge":
        """Context manager entry - connect to container."""
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager exit - close connection."""
        self.close()
