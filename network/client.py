"""WebSocket game client for Chess101 LAN multiplayer.

Uses ``websockets.sync.client`` (blocking sockets, no asyncio) so the
connection works reliably on macOS where asyncio's kqueue selector can
return EHOSTUNREACH for non-blocking connects even when the host is
reachable via blocking sockets.

The receive loop runs in the daemon thread started by ``connect()``.
A second daemon thread drains the outbound queue.  The main (Pygame)
thread communicates via ``send()`` and the registered message handler.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

try:
    from websockets.sync.client import connect as _ws_connect
    import websockets.exceptions as _ws_exc
except ImportError:  # pragma: no cover
    _ws_connect = None  # type: ignore[assignment]
    _ws_exc = None      # type: ignore[assignment]


class GameClient:
    """Blocking WebSocket client that connects to a GameServer.

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
        self._ws: Optional[object] = None
        self._send_queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._connected = threading.Event()
        self._stop = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """True if currently connected and not stopping."""
        return self._ws is not None and self._connected.is_set() and not self._stop.is_set()

    def set_message_handler(self, handler: Callable[[dict], None]) -> None:
        """Register the callback invoked for every inbound JSON message."""
        self._handler = handler

    def send(self, msg: dict) -> None:
        """Queue a message to be sent to the server. Thread-safe."""
        self._send_queue.put(json.dumps(msg))

    def connect(self, timeout: float = 10.0) -> bool:
        """Start the client thread and wait until connected.

        Returns:
            True if connected within *timeout* seconds, False otherwise.
        """
        self._thread = threading.Thread(target=self._run, daemon=True, name="GameClient")
        self._thread.start()
        return self._connected.wait(timeout=timeout)

    def stop(self) -> None:
        """Signal the client to disconnect and stop reconnecting."""
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()  # type: ignore[attr-defined]
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal (runs in daemon thread)
    # ------------------------------------------------------------------

    def _run(self) -> None:
        if _ws_connect is None:
            logger.error(
                "websockets library not installed. "
                "Run: pip install 'websockets>=12.0'"
            )
            self._connected.set()
            return

        uri = f"ws://{self._host_ip}:{self._port}"

        # Initial connect — give up immediately on failure (host not found).
        try:
            ws = _ws_connect(uri, open_timeout=10.0)
        except Exception as exc:
            logger.error("Connection to %s failed: %s", uri, exc)
            self._connected.set()
            return

        self._ws = ws
        self._connected.set()

        # Session loop — reconnect automatically after drops.
        while not self._stop.is_set():
            logger.info("Connected to server at %s", uri)
            if self._on_connected:
                self._on_connected()

            send_thread = threading.Thread(
                target=self._send_loop, args=(ws,), daemon=True, name="GameClientSend"
            )
            send_thread.start()
            self._recv_loop(ws)  # blocks until connection drops

            self._ws = None
            try:
                ws.close()  # type: ignore[attr-defined]
            except Exception:
                pass

            logger.info("Disconnected from server")
            if self._on_disconnected:
                self._on_disconnected()

            if self._stop.is_set():
                break

            # Drain stale outbound messages before the new session starts.
            while not self._send_queue.empty():
                try:
                    self._send_queue.get_nowait()
                except Exception:
                    break

            # Retry until reconnected or stopped.
            self._stop.wait(2.0)
            while not self._stop.is_set():
                try:
                    ws = _ws_connect(uri, open_timeout=5.0)
                    self._ws = ws
                    logger.info("Reconnected to %s", uri)
                    break
                except Exception:
                    logger.debug("Reconnect to %s failed, retrying in 2s", uri)
                    self._stop.wait(2.0)

    def _recv_loop(self, ws) -> None:
        try:
            while True:
                raw = ws.recv()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Received non-JSON message: %r", raw)
                    continue
                if self._handler:
                    self._handler(msg)
        except Exception:
            pass  # connection closed — exit loop

    def _send_loop(self, ws) -> None:
        try:
            while True:
                raw = self._send_queue.get()
                if raw is None:     # stop signal
                    break
                ws.send(raw)
        except Exception as exc:
            logger.warning("Send failed: %s", exc)
