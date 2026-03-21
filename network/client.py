"""WebSocket game client for Chess101 LAN multiplayer.

Mirrors the GameServer interface so NetworkedGameRunner can treat both
host and guest symmetrically.

The asyncio loop runs in a daemon thread.  The main (Pygame) thread
communicates via ``send()`` and the registered message handler callback.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

try:
    import websockets
    import websockets.exceptions
except ImportError:  # pragma: no cover
    websockets = None  # type: ignore[assignment]


class GameClient:
    """Async WebSocket client that connects to a GameServer.

    Args:
        host_ip: IP address or hostname of the server.
        port: TCP port (default 65101).
        on_connected: Called (network thread) once the connection is open.
        on_disconnected: Called (network thread) when the connection closes.
    """

    def __init__(
        self,
        host_ip: str,
        port: int = 65101,
        on_connected: Optional[Callable[[], None]] = None,
        on_disconnected: Optional[Callable[[], None]] = None,
    ) -> None:
        self._host_ip = host_ip
        self._port = port
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected

        self._handler: Optional[Callable[[dict], None]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._send_queue: asyncio.Queue = None  # type: ignore[assignment]
        self._thread: Optional[threading.Thread] = None
        self._connected = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_message_handler(self, handler: Callable[[dict], None]) -> None:
        """Register the callback invoked for every inbound JSON message."""
        self._handler = handler

    def send(self, msg: dict) -> None:
        """Queue a message to be sent to the server. Thread-safe."""
        if self._loop is None or self._send_queue is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._send_queue.put(json.dumps(msg)), self._loop
        )

    def connect(self, timeout: float = 10.0) -> bool:
        """Start the client thread and wait until connected.

        Returns:
            True if connected within *timeout* seconds, False otherwise.
        """
        self._thread = threading.Thread(target=self._run, daemon=True, name="GameClient")
        self._thread.start()
        return self._connected.wait(timeout=timeout)

    def stop(self) -> None:
        """Signal the client to disconnect."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)

    # ------------------------------------------------------------------
    # Internal asyncio implementation
    # ------------------------------------------------------------------

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._send_queue = asyncio.Queue()
        self._loop.run_until_complete(self._connect())

    async def _connect(self) -> None:
        if websockets is None:
            logger.error(
                "websockets library not installed. "
                "Run: pip install 'websockets>=12.0'"
            )
            return
        uri = f"ws://{self._host_ip}:{self._port}"
        try:
            async with websockets.connect(uri) as ws:  # type: ignore[attr-defined]
                self._connected.set()
                logger.info("Connected to server at %s", uri)
                if self._on_connected:
                    self._on_connected()
                try:
                    await asyncio.gather(
                        self._recv_loop(ws),
                        self._send_loop(ws),
                    )
                except Exception:
                    pass
        except Exception as exc:
            logger.error("Connection to %s failed: %s", uri, exc)
        finally:
            self._connected.set()  # unblock connect() even on failure
            logger.info("Disconnected from server")
            if self._on_disconnected:
                self._on_disconnected()

    async def _recv_loop(self, ws) -> None:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Received non-JSON message: %r", raw)
                continue
            if self._handler:
                self._handler(msg)

    async def _send_loop(self, ws) -> None:
        while True:
            raw = await self._send_queue.get()
            try:
                await ws.send(raw)
            except Exception as exc:
                logger.warning("Send failed: %s", exc)
                break
