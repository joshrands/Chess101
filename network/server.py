"""WebSocket game server for Chess101 LAN multiplayer.

Runs an asyncio event loop in a daemon thread.  The main (Pygame) thread
communicates via:
  - ``send(msg)``  — thread-safe outbound queue
  - ``set_message_handler(cb)``  — callback invoked for every inbound message

Accepts exactly one opponent connection.  A second connection attempt is
rejected with an error message.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# websockets is a runtime dependency; import lazily so the module can be
# imported even if the library isn't installed yet (tests will mock it).
try:
    import websockets
    import websockets.server
    import websockets.exceptions
except ImportError:  # pragma: no cover
    websockets = None  # type: ignore[assignment]


class GameServer:
    """Async WebSocket server that accepts exactly one opponent.

    Args:
        host: Interface to bind to (default ``"0.0.0.0"``).
        port: TCP port to listen on (default 65101).
        on_connected: Called (in the network thread) when a client connects.
        on_disconnected: Called (in the network thread) when the client
            disconnects.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 65101,
        on_connected: Optional[Callable[[], None]] = None,
        on_disconnected: Optional[Callable[[], None]] = None,
    ) -> None:
        self._host = host
        self._port = port
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected

        self._handler: Optional[Callable[[dict], None]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws: Optional[object] = None   # the active WebSocket connection
        self._send_queue: asyncio.Queue = None  # type: ignore[assignment]
        self._thread: Optional[threading.Thread] = None
        self._started = threading.Event()
        self._bound = False

    # ------------------------------------------------------------------
    # Public API (called from the main / Pygame thread)
    # ------------------------------------------------------------------

    def set_message_handler(self, handler: Callable[[dict], None]) -> None:
        """Register the callback invoked for every inbound JSON message.

        The callback is called from the network thread — use a lock if you
        need to mutate Pygame state.
        """
        self._handler = handler

    def send(self, msg: dict) -> None:
        """Queue a message to be sent to the connected client.

        Thread-safe.  Silently drops the message if no client is connected.
        """
        if self._loop is None or self._send_queue is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._send_queue.put(json.dumps(msg)), self._loop
        )

    def start(self) -> bool:
        """Start the asyncio server in a daemon thread and wait until bound.

        Returns:
            True if the server successfully bound to the port, False otherwise.
        """
        self._thread = threading.Thread(target=self._run, daemon=True, name="GameServer")
        self._thread.start()
        bound = self._started.wait(timeout=5.0)
        if not bound:
            logger.error("GameServer failed to start within 5 s — is the port in use?")
        return bound and self._bound

    def stop(self) -> None:
        """Signal the server to stop."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)

    @property
    def port(self) -> int:
        return self._port

    # ------------------------------------------------------------------
    # Internal asyncio implementation (runs in daemon thread)
    # ------------------------------------------------------------------

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._send_queue = asyncio.Queue()
        self._loop.run_until_complete(self._serve())

    async def _serve(self) -> None:
        if websockets is None:
            logger.error(
                "websockets library not installed. "
                "Run: pip install 'websockets>=12.0'"
            )
            self._started.set()
            return
        try:
            server_cm = websockets.serve(self._accept, self._host, self._port)  # type: ignore[attr-defined]
            async with server_cm:
                self._bound = True
                self._started.set()
                logger.info("GameServer listening on %s:%d", self._host, self._port)
                await asyncio.Future()  # run forever
        except OSError as exc:
            logger.error("GameServer could not bind to %s:%d — %s", self._host, self._port, exc)
            self._started.set()

    async def _accept(self, ws) -> None:
        """Handle an incoming WebSocket connection."""
        if self._ws is not None:
            # Already have a player — reject
            await ws.send(json.dumps({"type": "error", "code": "room_full"}))
            await ws.close()
            return

        self._ws = ws
        logger.info("Opponent connected from %s", ws.remote_address)
        if self._on_connected:
            self._on_connected()

        try:
            await asyncio.gather(
                self._recv_loop(ws),
                self._send_loop(ws),
            )
        except Exception:
            pass
        finally:
            self._ws = None
            # Drain send queue so stale messages aren't delivered to the next client.
            while not self._send_queue.empty():
                try:
                    self._send_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            logger.info("Opponent disconnected")
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
