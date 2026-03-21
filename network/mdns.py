"""mDNS/DNS-SD discovery for Chess101 LAN games.

Advertises a game service under ``_chess101._tcp.local.`` so that other
devices on the same subnet can find it automatically without typing an IP
address.  Uses the pure-Python ``zeroconf`` library (no compiled extensions).

Usage
~~~~~
**Advertising (Pi or Sim host):**

    from network.mdns import MdnsAdvertiser
    adv = MdnsAdvertiser(host_name="Alice", port=65101)
    adv.start()
    # ... game runs ...
    adv.stop()

**Browsing (Sim join screen):**

    from network.mdns import MdnsListener
    listener = MdnsListener()
    listener.start()
    # poll listener.games — dict[str, DiscoveredMdnsGame]
    listener.stop()
"""
from __future__ import annotations

import logging
import socket
import threading
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_SERVICE_TYPE = "_chess101._tcp.local."
_PROTOCOL_VERSION = "1"


def _get_local_ip() -> str:
    """Return the machine's primary outbound IPv4 address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


@dataclass
class DiscoveredMdnsGame:
    """A Chess101 game discovered via mDNS.

    Attributes:
        name: Human-readable display name of the host (e.g. ``"Alice"``).
        host_ip: IPv4 address of the host.
        port: WebSocket port.
        state: Game state string from the TXT record (e.g. ``"lobby"``).
        version: Protocol version string.
    """
    name: str
    host_ip: str
    port: int
    state: str = "lobby"
    version: str = _PROTOCOL_VERSION


class MdnsAdvertiser:
    """Advertise a Chess101 game over mDNS.

    Registers a ``_chess101._tcp.local.`` service with the Zeroconf daemon
    until ``stop()`` is called.

    Args:
        host_name: Display name shown to browsers.
        port: WebSocket port (default 65101).
        state: Initial game state string included in TXT record.
    """

    def __init__(
        self,
        host_name: str,
        port: int = 65101,
        state: str = "lobby",
    ) -> None:
        self._host_name = host_name
        self._port      = port
        self._state     = state
        self._zc        = None
        self._info      = None

    def start(self) -> None:
        """Register the mDNS service.  No-op if ``zeroconf`` is not installed."""
        try:
            from zeroconf import ServiceInfo, Zeroconf  # type: ignore[import]
        except ImportError:
            logger.warning("zeroconf not installed — mDNS advertising unavailable")
            return

        ip = _get_local_ip()
        service_name = f"{self._host_name}.{_SERVICE_TYPE}"
        self._info = ServiceInfo(
            _SERVICE_TYPE,
            service_name,
            addresses=[socket.inet_aton(ip)],
            port=self._port,
            properties={
                "game_state": self._state,
                "version":    _PROTOCOL_VERSION,
                "host_name":  self._host_name,
            },
        )
        zc = Zeroconf()
        self._zc = zc
        zc.register_service(self._info)
        logger.info("mDNS: advertising %r at %s:%d", service_name, ip, self._port)

    def update_state(self, state: str) -> None:
        """Update the game_state TXT property in the existing registration."""
        if self._zc is None or self._info is None:
            return
        try:
            from zeroconf import ServiceInfo, Zeroconf  # type: ignore[import]
        except ImportError:
            return
        self._state = state
        self._info.properties[b"game_state"] = state.encode()
        self._zc.update_service(self._info)

    def stop(self) -> None:
        """Unregister the service and close the Zeroconf instance."""
        if self._zc is not None and self._info is not None:
            try:
                self._zc.unregister_service(self._info)
            except Exception:
                pass
            self._zc.close()
            self._zc = None
            self._info = None
            logger.info("mDNS: advertising stopped")


class MdnsListener:
    """Browse for Chess101 games on the LAN via mDNS.

    Maintains ``self.games`` — a ``dict[str, DiscoveredMdnsGame]`` keyed by
    service name.  The dict is updated in a background thread; callers on
    the main thread should read it without taking a lock (Python GIL makes
    dict reads safe for simple polling).

    Args:
        timeout_s: How long ``start()`` blocks while waiting for initial
            browse results (0 = return immediately after registering).
    """

    def __init__(self, timeout_s: float = 0.0) -> None:
        self._timeout_s  = timeout_s
        self._zc         = None
        self._browser    = None
        self._lock       = threading.Lock()
        self.games: dict[str, DiscoveredMdnsGame] = {}

    def start(self) -> None:
        """Start browsing.  No-op if ``zeroconf`` is not installed."""
        try:
            from zeroconf import ServiceBrowser, Zeroconf  # type: ignore[import]
        except ImportError:
            logger.warning("zeroconf not installed — mDNS browsing unavailable")
            return

        self._zc      = Zeroconf()
        self._browser = ServiceBrowser(self._zc, _SERVICE_TYPE, self)
        logger.info("mDNS: browsing for %s", _SERVICE_TYPE)
        if self._timeout_s > 0:
            import time
            time.sleep(self._timeout_s)

    def stop(self) -> None:
        """Stop browsing and close the Zeroconf instance."""
        if self._zc is not None:
            self._zc.close()
            self._zc = None
            logger.info("mDNS: browsing stopped")

    # ── ServiceBrowser callbacks ───────────────────────────────────────────────

    def add_service(self, zc, type_: str, name: str) -> None:
        """Called when a new service is found."""
        info = zc.get_service_info(type_, name)
        if info is None:
            return
        try:
            ip = socket.inet_ntoa(info.addresses[0])
        except (IndexError, OSError):
            return
        props = {
            k.decode() if isinstance(k, bytes) else k:
            v.decode() if isinstance(v, bytes) else v
            for k, v in (info.properties or {}).items()
        }
        game = DiscoveredMdnsGame(
            name     = props.get("host_name", name),
            host_ip  = ip,
            port     = info.port,
            state    = props.get("game_state", "lobby"),
            version  = props.get("version", _PROTOCOL_VERSION),
        )
        with self._lock:
            self.games[name] = game
        logger.info("mDNS: found game %r at %s:%d", game.name, ip, info.port)

    def remove_service(self, zc, type_: str, name: str) -> None:
        """Called when a service disappears."""
        with self._lock:
            self.games.pop(name, None)
        logger.info("mDNS: game %r removed", name)

    def update_service(self, zc, type_: str, name: str) -> None:
        """Called when a service's TXT record changes."""
        self.add_service(zc, type_, name)
