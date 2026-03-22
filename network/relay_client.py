"""Client-side relay connector for Chess101 internet play.

``RelayClient`` wraps a plain WebSocket connection to the Chess101 relay
server.  It performs the relay handshake (relay_create / relay_join /
relay_spectate / relay_reconnect), intercepts ``relay_*`` messages
internally, and delivers only game-protocol messages to the registered
handler — making it a transparent drop-in for ``GameServer`` / ``GameClient``
from the point of view of ``NetworkedGameRunner``.

Usage
-----
    # HOST side
    rc = RelayClient("wss://chess101.net", role="host", player_name="Seth")
    rc.set_message_handler(my_handler)
    room_code = rc.create_room()   # blocks until room is ready or timeout
    # display room_code to the user…
    rc.wait_for_peer()             # blocks until opponent joins

    # GUEST side
    rc = RelayClient("wss://chess101.net", role="guest", player_name="Alex")
    rc.set_message_handler(my_handler)
    ok = rc.join_room("XKCD42")   # blocks until joined

    # Both sides then call rc.send(msg) exactly like GameServer.send()
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
    _ws_connect = None   # type: ignore[assignment]
    _ws_exc     = None   # type: ignore[assignment]

_DEFAULT_RELAY_URL = "wss://chess101.net"


class RelayClient:
    """Connects to the Chess101 relay server and wraps the handshake.

    After the handshake, the relay is protocol-transparent: all game
    messages sent via ``send()`` are forwarded to the peer; all inbound
    game messages are delivered to the registered handler.

    Args:
        relay_url: WebSocket URL of the relay server.
        role: ``"host"``, ``"guest"``, or ``"spectator"``.
        player_name: Display name sent during the handshake.
        on_peer_connected: Called (on network thread) when the peer joins.
        on_peer_disconnected: Called (on network thread) when the peer drops.
    """

    def __init__(
        self,
        relay_url:            str = _DEFAULT_RELAY_URL,
        role:                 str = "host",
        player_name:          str = "Player",
        on_peer_connected:    Optional[Callable[[], None]] = None,
        on_peer_disconnected: Optional[Callable[[], None]] = None,
    ) -> None:
        self._relay_url            = relay_url
        self._role                 = role
        self._player_name          = player_name
        self._on_peer_connected    = on_peer_connected
        self._on_peer_disconnected = on_peer_disconnected

        self._handler:    Optional[Callable[[dict], None]] = None
        self._ws:         Optional[object] = None
        self._send_queue: queue.Queue      = queue.Queue()
        self._stop        = threading.Event()

        self._room_code:  Optional[str] = None
        self._token:      Optional[str] = None

        # Events for blocking calls
        self._room_ready  = threading.Event()   # set when relay_created received
        self._peer_joined = threading.Event()   # set when relay_peer_connected

        # Set to the relay error code when relay_error is received; lets reconnect()
        # distinguish a server-side rejection from a network timeout.
        self._last_relay_error: Optional[str] = None

        self._thread: Optional[threading.Thread] = None

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def room_code(self) -> Optional[str]:
        return self._room_code

    @property
    def token(self) -> Optional[str]:
        return self._token

    @property
    def connected(self) -> bool:
        return self._ws is not None

    # ── Public API (same interface as GameServer / GameClient) ─────────────────

    def set_message_handler(self, handler: Callable[[dict], None]) -> None:
        """Register the callback invoked for every inbound game message."""
        self._handler = handler

    def send(self, msg: dict) -> None:
        """Queue a game message to be forwarded through the relay. Thread-safe."""
        self._send_queue.put(json.dumps(msg))

    def stop(self) -> None:
        """Signal the client to disconnect and stop."""
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()  # type: ignore[attr-defined]
            except Exception:
                pass

    # ── Blocking connect methods (call from main thread before game starts) ────

    def create_room(self, timeout: float = 60.0) -> Optional[str]:
        """Connect to the relay and create a new room.

        Blocks until the room code is assigned or *timeout* seconds elapse.

        Returns:
            The 6-character room code, or ``None`` on failure.
        """
        self._start_thread()
        if self._room_ready.wait(timeout=timeout) and self._room_code:
            return self._room_code
        logger.error("Timed out waiting for relay room creation")
        return None

    def join_room(self, room_code: str, timeout: float = 60.0) -> bool:
        """Connect to the relay and join an existing room.

        Args:
            room_code: The 6-character code the HOST shared.
            timeout: Seconds to wait for the join to succeed.

        Returns:
            ``True`` if joined successfully.
        """
        self._room_code = room_code.upper()
        self._start_thread()
        ok = self._room_ready.wait(timeout=timeout)
        if not ok:
            logger.error("Timed out joining relay room %s", room_code)
        return ok

    def spectate_room(self, room_code: str, timeout: float = 60.0) -> bool:
        """Connect to the relay as a spectator of an existing room."""
        self._room_code = room_code.upper()
        self._start_thread()
        ok = self._room_ready.wait(timeout=timeout)
        if not ok:
            logger.error("Timed out joining relay room %s as spectator", room_code)
        return ok

    def wait_for_peer(self, timeout: float = 300.0) -> bool:
        """Block until the opponent joins the room (HOST use).

        Returns:
            ``True`` if the peer joined within *timeout* seconds.
        """
        return self._peer_joined.wait(timeout=timeout)

    # ── Internal thread ────────────────────────────────────────────────────────

    def _start_thread(self) -> None:
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="RelayClient"
        )
        self._thread.start()

    def _run(self) -> None:
        if _ws_connect is None:
            logger.error(
                "websockets library not installed — "
                "run: pip install 'websockets>=12.0'"
            )
            self._room_ready.set()
            return

        # Retry with backoff to tolerate cold starts on the free hosting tier
        # (a spun-down relay can take ~30 s to wake up).
        _MAX_ATTEMPTS  = 5
        _RETRY_DELAYS  = (3, 5, 10, 15)   # seconds between attempts

        ws = None
        for attempt in range(_MAX_ATTEMPTS):
            if self._stop.is_set():
                self._room_ready.set()
                return
            try:
                ws = _ws_connect(self._relay_url, open_timeout=15.0)
                break
            except Exception as exc:
                if attempt < _MAX_ATTEMPTS - 1:
                    delay = _RETRY_DELAYS[attempt]
                    logger.warning(
                        "Relay connect attempt %d/%d failed (%s) — retrying in %ds",
                        attempt + 1, _MAX_ATTEMPTS, exc, delay,
                    )
                    self._stop.wait(timeout=delay)
        else:
            logger.error(
                "Relay connection to %s failed after %d attempts",
                self._relay_url, _MAX_ATTEMPTS,
            )
            self._room_ready.set()
            return

        self._ws = ws
        logger.info("Connected to relay at %s", self._relay_url)

        # Send the appropriate handshake message.
        try:
            if self._role == "host":
                ws.send(json.dumps({  # type: ignore[attr-defined]
                    "type": "relay_create",
                    "player_name": self._player_name,
                    "version": "1",
                }))
            elif self._role == "guest":
                ws.send(json.dumps({  # type: ignore[attr-defined]
                    "type": "relay_join",
                    "room_code": self._room_code or "",
                    "player_name": self._player_name,
                    "version": "1",
                }))
            elif self._role == "spectator":
                ws.send(json.dumps({  # type: ignore[attr-defined]
                    "type": "relay_spectate",
                    "room_code": self._room_code or "",
                }))
        except Exception as exc:
            logger.error("Relay handshake send failed: %s", exc)
            self._room_ready.set()
            return

        # Start the send thread.
        send_thread = threading.Thread(
            target=self._send_loop, args=(ws,), daemon=True, name="RelayClientSend"
        )
        send_thread.start()

        # Receive loop.
        self._recv_loop(ws)

        self._ws = None
        try:
            ws.close()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _recv_loop(self, ws) -> None:
        try:
            while not self._stop.is_set():
                raw = ws.recv()  # type: ignore[attr-defined]
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Non-JSON from relay: %r", raw)
                    continue
                self._dispatch(msg, raw)
        except Exception:
            pass   # connection closed

    def _send_loop(self, ws) -> None:
        try:
            while not self._stop.is_set():
                raw = self._send_queue.get()
                if raw is None:
                    break
                ws.send(raw)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("Relay send failed: %s", exc)

    def _dispatch(self, msg: dict, raw: str) -> None:
        """Handle relay-protocol messages internally; deliver game messages to handler."""
        t = msg.get("type", "")

        if t == "relay_created":
            self._room_code = msg.get("room_code")
            self._token     = msg.get("token")
            logger.info("Relay room ready: %s", self._room_code)
            self._room_ready.set()

        elif t == "relay_spectating":
            self._room_code = msg.get("room_code")
            logger.info("Spectating relay room: %s", self._room_code)
            self._room_ready.set()

        elif t == "relay_reconnected":
            logger.info("Relay reconnection confirmed for room %s", msg.get("room_code"))
            self._room_ready.set()

        elif t == "relay_peer_connected":
            peer = msg.get("peer_name", "Opponent")
            logger.info("Relay peer connected: %r", peer)
            self._peer_joined.set()
            if self._on_peer_connected:
                self._on_peer_connected()

        elif t == "relay_peer_disconnected":
            peer = msg.get("peer_name", "Opponent")
            logger.info("Relay peer disconnected: %r", peer)
            if self._on_peer_disconnected:
                self._on_peer_disconnected()

        elif t == "relay_error":
            code = msg.get("code", "unknown")
            logger.error("Relay error: %s", code)
            self._last_relay_error = code
            # Unblock any waiting caller so they can surface the error.
            self._room_ready.set()

        elif t.startswith("relay_"):
            # Unknown relay control message — log and ignore.
            logger.debug("Unknown relay message: %s", t)

        else:
            # Game-protocol message — deliver to handler.
            if self._handler:
                self._handler(msg)

    def reconnect(self, timeout: float = 15.0) -> bool:
        """Attempt to reconnect to the relay using the stored token.

        Returns:
            ``True`` if reconnection succeeded.
        """
        if not self._room_code or not self._token:
            return False

        self._room_ready.clear()
        self._last_relay_error = None
        self._stop.clear()

        def _reconnect_run() -> None:
            if _ws_connect is None:
                self._room_ready.set()
                return
            try:
                ws = _ws_connect(self._relay_url, open_timeout=15.0)
            except Exception as exc:
                logger.error("Relay reconnect to %s failed: %s", self._relay_url, exc)
                self._room_ready.set()
                return

            self._ws = ws
            try:
                ws.send(json.dumps({
                    "type": "relay_reconnect",
                    "room_code": self._room_code,
                    "token": self._token,
                }))
            except Exception as exc:
                logger.error("Relay reconnect handshake failed: %s", exc)
                self._room_ready.set()
                return

            send_thread = threading.Thread(
                target=self._send_loop, args=(ws,),
                daemon=True, name="RelayClientSend",
            )
            send_thread.start()
            self._recv_loop(ws)
            self._ws = None

        thread = threading.Thread(target=_reconnect_run, daemon=True, name="RelayClientReconnect")
        thread.start()
        if not self._room_ready.wait(timeout=timeout):
            logger.error("Relay reconnect timed out")
            return False
        if self._last_relay_error:
            # relay_error means the server restarted and the room is gone —
            # not a transient network blip.
            logger.error("Relay reconnect rejected: %s", self._last_relay_error)
            return False
        return True
