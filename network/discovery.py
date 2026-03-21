"""UDP beacon-based LAN game discovery for Chess101.

BeaconBroadcaster broadcasts a JSON beacon every 2 seconds so other
simulators on the same subnet can find this game automatically.

BeaconListener receives those beacons and maintains a ``games`` dict that
the Lobby screen reads each frame.  Entries older than 10 seconds are
automatically pruned.
"""
from __future__ import annotations

import json
import logging
import socket
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

_BROADCAST_PORT = 65102
_BROADCAST_INTERVAL = 2.0   # seconds between beacons
_STALE_TIMEOUT = 10.0       # seconds before a game entry expires


def _local_ip() -> str:
    """Return the machine's primary LAN IP (best-effort)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class BeaconBroadcaster:
    """Periodically sends a UDP broadcast announcing this game.

    Args:
        host_name: Display name for this host (shown in the Lobby list).
        port: WebSocket port guests should connect to (default 65101).
        state: Initial game state label, e.g. ``"lobby"`` or ``"playing"``.
    """

    def __init__(
        self,
        host_name: str,
        port: int = 65101,
        state: str = "lobby",
    ) -> None:
        self._host_name = host_name
        self._port = port
        self._state = state
        self._ip = _local_ip()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def set_state(self, state: str) -> None:
        """Update the game-state label included in future beacons."""
        self._state = state

    def start(self) -> None:
        """Start broadcasting in a daemon thread."""
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="BeaconBroadcaster"
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop broadcasting."""
        self._running = False

    def _loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            while self._running:
                payload = json.dumps({
                    "type": "chess101_beacon",
                    "version": "1",
                    "host_name": self._host_name,
                    "ip": self._ip,
                    "port": self._port,
                    "state": self._state,
                }).encode()
                try:
                    sock.sendto(payload, ("255.255.255.255", _BROADCAST_PORT))
                except Exception as exc:
                    logger.debug("Beacon send error: %s", exc)
                time.sleep(_BROADCAST_INTERVAL)
        finally:
            sock.close()


class DiscoveredGame:
    """Represents a game found via beacon.

    Attributes:
        host_name: Display name of the hosting instance.
        ip: IP address to connect to.
        port: WebSocket port.
        state: Game state label (``"lobby"``, ``"playing"``, etc.).
        last_seen: Unix timestamp of the most recent beacon.
        latency_ms: Approximate round-trip latency derived from beacon timing.
    """

    def __init__(self, host_name: str, ip: str, port: int, state: str) -> None:
        self.host_name = host_name
        self.ip = ip
        self.port = port
        self.state = state
        self.last_seen: float = time.time()
        self.latency_ms: float = 0.0

    def signal_bars(self) -> int:
        """Return a 1–4 signal quality bar count based on latency."""
        ms = self.latency_ms
        if ms < 50:
            return 4
        if ms < 100:
            return 3
        if ms < 200:
            return 2
        return 1


class BeaconListener:
    """Listens for UDP beacons and maintains a dict of discovered games.

    The ``games`` dict maps ``"ip:port"`` → ``DiscoveredGame``.  Stale
    entries (not seen for more than 10 s) are pruned automatically.

    Usage::

        listener = BeaconListener()
        listener.start()
        # each Pygame frame:
        games = listener.games   # snapshot is safe to read from main thread
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._games: dict[str, DiscoveredGame] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None

    @property
    def games(self) -> dict[str, DiscoveredGame]:
        """Thread-safe snapshot of currently discovered games."""
        with self._lock:
            return dict(self._games)

    def start(self) -> None:
        """Start listening in a daemon thread."""
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="BeaconListener"
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop listening."""
        self._running = False

    def _loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", _BROADCAST_PORT))
            sock.settimeout(1.0)
            while self._running:
                try:
                    data, addr = sock.recvfrom(1024)
                except socket.timeout:
                    self._prune()
                    continue
                try:
                    msg = json.loads(data.decode())
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if msg.get("type") != "chess101_beacon":
                    continue
                if msg.get("version") != "1":
                    continue
                recv_time = time.time()
                key = f"{msg['ip']}:{msg['port']}"
                with self._lock:
                    existing = self._games.get(key)
                    if existing:
                        # Estimate latency from inter-beacon gap vs expected
                        gap = recv_time - existing.last_seen
                        latency = abs(gap - _BROADCAST_INTERVAL) * 1000
                        existing.last_seen = recv_time
                        existing.state = msg.get("state", existing.state)
                        existing.latency_ms = latency
                    else:
                        game = DiscoveredGame(
                            host_name=msg.get("host_name", addr[0]),
                            ip=msg["ip"],
                            port=int(msg["port"]),
                            state=msg.get("state", "lobby"),
                        )
                        self._games[key] = game
                        logger.info("Discovered game: %s at %s", game.host_name, key)
                self._prune()
        finally:
            sock.close()

    def _prune(self) -> None:
        """Remove entries not seen recently."""
        cutoff = time.time() - _STALE_TIMEOUT
        with self._lock:
            stale = [k for k, g in self._games.items() if g.last_seen < cutoff]
            for k in stale:
                logger.debug("Pruning stale game: %s", k)
                del self._games[k]
