"""WebSocket JSON-RPC control server for HIL testing.

Provides external control of the HIL container via JSON-RPC over WebSocket.
Clients can inject reed switch events, read LED frames, and query game state.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hil.sensor import HilSensor
    from hil.rgbmatrix import HilRGBMatrix

try:
    import websockets
    from websockets.server import serve, WebSocketServerProtocol
except ImportError:
    websockets = None  # type: ignore

logger = logging.getLogger(__name__)


class ControlServer:
    """WebSocket JSON-RPC server for HIL control.

    Exposes methods:
        - reed_switch(row, col, state) - inject piece lift/place
        - get_frame() - poll current LED state
        - subscribe_frames(fps) - stream frames at given FPS
        - get_sensor_state() - get 8x8 reed switch grid
        - ping() - keepalive
    """

    def __init__(
        self,
        sensor: HilSensor,
        matrix: HilRGBMatrix,
        port: int = 8766,
    ) -> None:
        """Initialize the control server.

        Args:
            sensor: HilSensor instance to control.
            matrix: HilRGBMatrix instance to read frames from.
            port: WebSocket port to bind (default 8766).
        """
        self._sensor = sensor
        self._matrix = matrix
        self._port = port
        self._clients: set[WebSocketServerProtocol] = set()
        self._frame_subscribers: dict[WebSocketServerProtocol, float] = {}
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None

    async def _handle_client(self, ws: WebSocketServerProtocol) -> None:
        """Handle a single WebSocket client connection."""
        self._clients.add(ws)
        logger.info("HIL client connected: %s", ws.remote_address)
        try:
            async for message in ws:
                try:
                    req = json.loads(message)
                    resp = await self._handle_request(ws, req)
                    await ws.send(json.dumps(resp))
                except json.JSONDecodeError:
                    await ws.send(json.dumps({
                        "error": "Invalid JSON",
                        "id": None,
                    }))
                except Exception as e:
                    logger.exception("Error handling request")
                    await ws.send(json.dumps({
                        "error": str(e),
                        "id": req.get("id") if isinstance(req, dict) else None,
                    }))
        finally:
            self._clients.discard(ws)
            self._frame_subscribers.pop(ws, None)
            logger.info("HIL client disconnected: %s", ws.remote_address)

    async def _handle_request(
        self, ws: WebSocketServerProtocol, req: dict[str, Any]
    ) -> dict[str, Any]:
        """Dispatch a JSON-RPC request to the appropriate handler."""
        method = req.get("method", "")
        params = req.get("params", {})
        req_id = req.get("id")

        if method == "reed_switch":
            row = params.get("row", 0)
            col = params.get("col", 0)
            state = params.get("state", "lifted")
            occupied = state == "placed"
            self._sensor.inject_state(row, col, occupied)
            return {"result": "ok", "id": req_id}

        elif method == "get_frame":
            frame, timestamp = self._matrix.get_last_frame()
            if frame is None:
                return {"result": None, "id": req_id}
            return {
                "result": {
                    "pixels": frame,
                    "timestamp": timestamp,
                    "frame_count": self._matrix.get_frame_count(),
                },
                "id": req_id,
            }

        elif method == "subscribe_frames":
            fps = params.get("fps", 30)
            self._frame_subscribers[ws] = 1.0 / max(1, fps)
            asyncio.create_task(self._stream_frames(ws))
            return {"result": "subscribed", "id": req_id}

        elif method == "unsubscribe_frames":
            self._frame_subscribers.pop(ws, None)
            return {"result": "unsubscribed", "id": req_id}

        elif method == "get_sensor_state":
            grid = self._sensor.get_grid_snapshot()
            return {"result": {"grid": grid}, "id": req_id}

        elif method == "set_starting_position":
            self._sensor.set_starting_position()
            return {"result": "ok", "id": req_id}

        elif method == "ping":
            return {"result": "pong", "id": req_id}

        else:
            return {"error": f"Unknown method: {method}", "id": req_id}

    async def _stream_frames(self, ws: WebSocketServerProtocol) -> None:
        """Stream frames to a subscribed client at their requested FPS."""
        last_frame_count = 0
        while ws in self._frame_subscribers:
            interval = self._frame_subscribers.get(ws, 0.033)
            frame, timestamp = self._matrix.get_last_frame()
            frame_count = self._matrix.get_frame_count()

            if frame is not None and frame_count != last_frame_count:
                last_frame_count = frame_count
                try:
                    await ws.send(json.dumps({
                        "event": "frame",
                        "pixels": frame,
                        "timestamp": timestamp,
                        "frame_count": frame_count,
                    }))
                except Exception:
                    break

            await asyncio.sleep(interval)

    async def _serve(self) -> None:
        """Start the WebSocket server."""
        if websockets is None:
            raise ImportError("websockets package required for ControlServer")

        logger.info("HIL ControlServer starting on port %d", self._port)
        async with serve(self._handle_client, "0.0.0.0", self._port):
            self._running = True
            await asyncio.Future()

    def run(self) -> None:
        """Run the control server (blocking). Call from a thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception:
            logger.exception("ControlServer error")
        finally:
            self._running = False

    def is_running(self) -> bool:
        """Return True if the server is currently running."""
        return self._running
