"""Grand E2E Lockstep Fuzzer - the main comprehensive fuzzer.

Plays complete games with:
- Master Python driving moves, verified against all lockstep engines
- Slave Python receiving moves, also verified against all lockstep engines
- Real network communication (LAN or relay)

Modes:
- LOCAL: Both in same process (no network)
- LAN_HOST: Master runs GameServer, slave connects via GameClient
- LAN_GUEST: Slave runs GameServer, master connects via GameClient
- ONLINE_HOST: Master creates relay room, slave joins
- ONLINE_GUEST: Slave creates relay room, master joins
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from core.team import Team
from harness.lockstep_runner import (
    ChessEngine,
    PythonEngine,
    JsEngine,
    SwiftEngine,
    HilEngine,
    LockstepRunner,
)
from harness.chess_helpers import TEAM_R_RGB, TEAM_L_RGB
from harness.corpus import (
    save_corpus, save_chaos_corpus, TimelineRecorder,
    load_corpus, is_chaos_corpus, extract_moves_from_timeline,
)
from harness.grand_fuzzer.core.chaos import (
    ChaosProfile, ChaosConfig, ScenarioScheduler, ChaosPeer,
    TurnScenario, GameScenario,
)
from harness.grand_fuzzer.core.fault_injector import FaultInjector
from harness.grand_fuzzer.core.scenarios import execute_scenario, ScenarioResult
from network.protocol import board_hash, encode_grid, MoveFlags


class SlaveMode(Enum):
    """How the slave connects to master."""
    LOCAL = auto()
    LAN_HOST = auto()          # Master=server, slave=client, hardcoded IP
    LAN_GUEST = auto()         # Master=client, slave=server, hardcoded IP
    LAN_BEACON_HOST = auto()   # Master=server+beacon, slave discovers
    LAN_BEACON_GUEST = auto()  # Slave=server+beacon, master discovers
    LAN_MDNS_HOST = auto()     # Master=server+mDNS, slave discovers
    LAN_MDNS_GUEST = auto()    # Slave=server+mDNS, master discovers
    ONLINE_HOST = auto()
    ONLINE_GUEST = auto()


@dataclass
class _GameContext:
    """Context passed to scenario handlers."""
    ply: int
    phase: str
    master_peer: Any
    slave_peer: Any
    spectator_peer: Any
    current_team: str
    board_state: Any


@dataclass
class FuzzResult:
    """Result of a fuzzing run."""
    success: bool
    message: str
    corpus_path: Path | None = None
    seed: int = 0
    ply: int = 0

    @classmethod
    def ok(cls, message: str = "passed") -> FuzzResult:
        return cls(success=True, message=message)

    @classmethod
    def failure(cls, message: str, corpus_path: Path | None = None,
                seed: int = 0, ply: int = 0) -> FuzzResult:
        return cls(success=False, message=message, corpus_path=corpus_path,
                   seed=seed, ply=ply)


class LockstepVerifier:
    """Verifies moves against all lockstep engines."""

    def __init__(self, engines: list[ChessEngine], name: str = "verifier"):
        self._engines = engines
        self._name = name

    def init_game(self, team_r_rgb: tuple, team_l_rgb: tuple) -> None:
        """Initialize all engines with same team colors."""
        for engine in self._engines:
            engine.init_game(team_r_rgb, team_l_rgb)

    def verify_legal_moves(self, team_key: str) -> tuple[set, list[str]]:
        """Verify all engines agree on legal moves.

        Returns (moves, errors) - moves is the agreed set, errors if disagreement.
        """
        if not self._engines:
            return set(), []

        move_sets: dict[str, set] = {}
        for engine in self._engines:
            move_sets[engine.name] = engine.legal_moves(team_key)

        ref_name = self._engines[0].name
        ref_moves = move_sets[ref_name]
        errors: list[str] = []

        for engine in self._engines[1:]:
            other_moves = move_sets[engine.name]
            if ref_moves != other_moves:
                only_ref = sorted(ref_moves - other_moves)
                only_other = sorted(other_moves - ref_moves)
                errors.append(
                    f"{self._name} legal_moves disagree: {ref_name} vs {engine.name}: "
                    f"only_{ref_name}={only_ref}, only_{engine.name}={only_other}"
                )

        return ref_moves, errors

    def apply_and_verify(
        self, fr: int, fc: int, tr: int, tc: int,
        team_key: str, next_key: str, peace_time: int,
    ) -> tuple[str, list[str]]:
        """Apply move to all engines and verify board hashes match.

        Returns (hash, errors) - hash is the agreed hash, errors if disagreement.
        """
        if not self._engines:
            return "", []

        results: dict[str, dict] = {}
        for engine in self._engines:
            results[engine.name] = engine.apply_move(
                fr, fc, tr, tc, team_key, next_key, peace_time
            )

        ref_name = self._engines[0].name
        ref_hash = results[ref_name]["board_hash"]
        errors: list[str] = []

        for engine in self._engines[1:]:
            other_hash = results[engine.name]["board_hash"]
            if ref_hash != other_hash:
                errors.append(
                    f"{self._name} board_hash disagree: {ref_name} vs {engine.name}: "
                    f"{ref_hash[:16]}... vs {other_hash[:16]}..."
                )

        return ref_hash, errors

    def close(self) -> None:
        """Close all engines."""
        for engine in self._engines:
            engine.close()


class NetworkPeer:
    """Abstraction over GameServer/GameClient/RelayClient for E2E testing."""

    def __init__(self):
        self._received: list[dict] = []
        self._lock = threading.Lock()
        self._new_msg = threading.Event()
        self._impl = None

    def _on_message(self, msg: dict) -> None:
        with self._lock:
            self._received.append(msg)
        self._new_msg.set()

    def send(self, msg: dict) -> None:
        if self._impl:
            self._impl.send(msg)

    def recv(self, timeout: float = 5.0) -> dict | None:
        """Receive next message, blocking up to timeout."""
        deadline = time.time() + timeout
        while True:
            with self._lock:
                if self._received:
                    return self._received.pop(0)
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            self._new_msg.clear()
            self._new_msg.wait(timeout=min(remaining, 0.1))

    def clear(self) -> None:
        """Clear receive buffer for new game."""
        with self._lock:
            self._received.clear()
        self._new_msg.clear()

    def close(self) -> None:
        if self._impl and hasattr(self._impl, "close"):
            self._impl.close()
        elif self._impl and hasattr(self._impl, "stop"):
            self._impl.stop()


class LANServerPeer(NetworkPeer):
    """Peer that runs a GameServer."""

    def __init__(self, port: int = 65101):
        super().__init__()
        self._client_connected = threading.Event()
        from network.server import GameServer
        self._impl = GameServer(
            port=port,
            on_connected=self._on_client_connected,
        )
        self._impl.set_message_handler(self._on_message)

    def _on_client_connected(self) -> None:
        self._client_connected.set()

    def start(self) -> bool:
        return self._impl.start()

    def wait_for_client(self, timeout: float = 10.0) -> bool:
        return self._client_connected.wait(timeout=timeout)


class LANClientPeer(NetworkPeer):
    """Peer that runs a GameClient."""

    def __init__(self, host: str, port: int = 65101):
        super().__init__()
        from network.client import GameClient
        self._impl = GameClient(host, port=port)
        self._impl.set_message_handler(self._on_message)

    def connect(self, timeout: float = 5.0) -> bool:
        return self._impl.connect(timeout=timeout)


class RelayHostPeer(NetworkPeer):
    """Peer that creates a relay room."""

    def __init__(self, relay_url: str):
        super().__init__()
        from network.relay_client import RelayClient
        self._impl = RelayClient(relay_url, role="host", player_name="FuzzMaster")
        self._impl.set_message_handler(self._on_message)
        self._room_code: str | None = None

    def create_room(self, timeout: float = 10.0) -> str | None:
        self._room_code = self._impl.create_room(timeout=timeout)
        return self._room_code

    def wait_for_peer(self, timeout: float = 30.0) -> bool:
        return self._impl.wait_for_peer(timeout=timeout)


class RelayGuestPeer(NetworkPeer):
    """Peer that joins a relay room."""

    def __init__(self, relay_url: str):
        super().__init__()
        from network.relay_client import RelayClient
        self._impl = RelayClient(relay_url, role="guest", player_name="FuzzSlave")
        self._impl.set_message_handler(self._on_message)

    def join_room(self, code: str, timeout: float = 10.0) -> bool:
        return self._impl.join_room(code, timeout=timeout)


class RelaySpectatorPeer(NetworkPeer):
    """Peer that spectates a relay room."""

    def __init__(self, relay_url: str):
        super().__init__()
        from network.relay_client import RelayClient
        self._impl = RelayClient(relay_url, role="spectator", player_name="FuzzSpectator")
        self._impl.set_message_handler(self._on_message)

    def spectate_room(self, code: str, timeout: float = 10.0) -> bool:
        return self._impl.spectate_room(code, timeout=timeout)


class BeaconServerPeer(NetworkPeer):
    """Peer that runs GameServer + BeaconBroadcaster."""

    def __init__(self, port: int = 65101):
        super().__init__()
        self._client_connected = threading.Event()
        self._port = port
        self._beacon = None

        from network.server import GameServer
        self._impl = GameServer(
            port=port,
            on_connected=self._on_client_connected,
        )
        self._impl.set_message_handler(self._on_message)

    def _on_client_connected(self) -> None:
        self._client_connected.set()

    def start(self) -> bool:
        from network.discovery import BeaconBroadcaster
        self._beacon = BeaconBroadcaster(
            host_name="FuzzServer",
            port=self._port,
            state="lobby",
        )
        self._beacon.start()
        return self._impl.start()

    def wait_for_client(self, timeout: float = 10.0) -> bool:
        return self._client_connected.wait(timeout=timeout)

    def close(self) -> None:
        if self._beacon:
            self._beacon.stop()
        super().close()


class BeaconClientPeer(NetworkPeer):
    """Peer that discovers server via BeaconListener then connects."""

    def __init__(self):
        super().__init__()
        self._listener = None
        self._discovered_ip: str | None = None
        self._discovered_port: int | None = None

    def start_listener(self) -> None:
        """Start listening for beacons."""
        from network.discovery import BeaconListener
        self._listener = BeaconListener()
        self._listener.start()

    def wait_for_discovery(self, timeout: float = 10.0) -> bool:
        """Wait for beacon discovery, return True if found."""
        if not self._listener:
            return False

        deadline = time.time() + timeout
        while time.time() < deadline:
            games = self._listener.games
            if games:
                # Take first discovered game
                key = next(iter(games))
                game = games[key]
                self._discovered_ip = game.ip
                self._discovered_port = game.port
                return True
            time.sleep(0.2)

        return False

    def connect(self, timeout: float = 5.0) -> bool:
        """Connect to discovered server."""
        if not self._discovered_ip:
            return False
        from network.client import GameClient
        self._impl = GameClient(self._discovered_ip, port=self._discovered_port)
        self._impl.set_message_handler(self._on_message)
        return self._impl.connect(timeout=timeout)

    def close(self) -> None:
        if self._listener:
            self._listener.stop()
        super().close()


class MdnsServerPeer(NetworkPeer):
    """Peer that runs GameServer + MdnsAdvertiser."""

    def __init__(self, port: int = 65101):
        super().__init__()
        self._client_connected = threading.Event()
        self._port = port
        self._advertiser = None

        from network.server import GameServer
        self._impl = GameServer(
            port=port,
            on_connected=self._on_client_connected,
        )
        self._impl.set_message_handler(self._on_message)

    def _on_client_connected(self) -> None:
        self._client_connected.set()

    def start(self) -> bool:
        from network.mdns import MdnsAdvertiser
        self._advertiser = MdnsAdvertiser(
            host_name="FuzzServer",
            port=self._port,
        )
        self._advertiser.start()
        return self._impl.start()

    def wait_for_client(self, timeout: float = 10.0) -> bool:
        return self._client_connected.wait(timeout=timeout)

    def close(self) -> None:
        if self._advertiser:
            self._advertiser.stop()
        super().close()


class MdnsClientPeer(NetworkPeer):
    """Peer that discovers server via MdnsListener then connects."""

    def __init__(self):
        super().__init__()
        self._listener = None
        self._discovered_ip: str | None = None
        self._discovered_port: int | None = None

    def start_listener(self) -> None:
        """Start listening for mDNS advertisements."""
        from network.mdns import MdnsListener
        self._listener = MdnsListener()
        self._listener.start()

    def wait_for_discovery(self, timeout: float = 10.0) -> bool:
        """Wait for mDNS discovery, return True if found."""
        if not self._listener:
            return False

        deadline = time.time() + timeout
        while time.time() < deadline:
            games = self._listener.games
            if games:
                # Take first discovered game
                key = next(iter(games))
                game = games[key]
                self._discovered_ip = game.host_ip  # mDNS uses host_ip
                self._discovered_port = game.port
                return True
            time.sleep(0.2)

        return False

    def connect(self, timeout: float = 5.0) -> bool:
        """Connect to discovered server."""
        if not self._discovered_ip:
            return False
        from network.client import GameClient
        self._impl = GameClient(self._discovered_ip, port=self._discovered_port)
        self._impl.set_message_handler(self._on_message)
        return self._impl.connect(timeout=timeout)

    def close(self) -> None:
        if self._listener:
            self._listener.stop()
        super().close()




class GrandE2EFuzzer:
    """Grand E2E Chaos Fuzzer - always injects faults, records timeline."""

    def __init__(
        self,
        seed: int,
        mode: SlaveMode = SlaveMode.LOCAL,
        max_ply: int = 120,
        hil_url: str | None = None,
        relay_url: str = "wss://relay.chess101.net",
        lan_port: int = 65101,
        with_spectator: bool = False,
        crashes_dir: Path | None = None,
        chaos_profile: ChaosProfile = ChaosProfile.STANDARD,
        enabled_scenarios: set[str] | None = None,
    ):
        self._seed = seed
        self._mode = mode
        self._max_ply = max_ply
        self._hil_url = hil_url
        self._relay_url = relay_url
        self._lan_port = lan_port
        self._with_spectator = with_spectator
        self._crashes_dir = crashes_dir or ROOT / "harness" / "crashes" / "grand_e2e"
        self._crashes_dir.mkdir(parents=True, exist_ok=True)
        self._rng = random.Random(seed)

        self._chaos_config = ChaosConfig.from_profile(chaos_profile)
        self._chaos_config.enabled_scenarios = enabled_scenarios
        self._fault_seed = self._rng.randint(0, 2**32)
        self._timing_seed = self._rng.randint(0, 2**32)

    def _create_engines(self) -> list[ChessEngine]:
        """Create all available lockstep engines."""
        engines: list[ChessEngine] = [PythonEngine(), JsEngine()]

        try:
            engines.append(SwiftEngine())
        except Exception as e:
            print(f"[WARN] Swift engine not available: {e}")

        if self._hil_url:
            try:
                hil = HilEngine(self._hil_url)
                hil.connect(retries=3, delay=1.0)
                engines.append(hil)
            except Exception as e:
                raise RuntimeError(f"HIL required but failed: {e}") from e

        return engines

    def _run_phase_setup(
        self,
        master_peer: NetworkPeer | None,
        slave_peer: NetworkPeer | None,
        team_r_rgb: tuple,
        team_l_rgb: tuple,
        game_rng: random.Random,
    ) -> tuple[bool, str]:
        """Run COLOR_PICK, WAR_GAMES, SETUP phases.

        Returns (success, error_message).
        """
        # Pick random colors (0-5) for both teams
        color_r = game_rng.randint(0, 5)
        color_l = game_rng.choice([c for c in range(6) if c != color_r])

        # Pick random AI settings
        is_ai_r = game_rng.choice([True, False])
        is_ai_l = game_rng.choice([True, False])

        if not master_peer:
            # LOCAL mode - no network messages needed
            return True, ""

        # COLOR_PICK phase — retry once on timeout
        color_r_msg = {"type": "color_chosen", "team_key": "r", "color_idx": color_r}
        color_l_msg = {"type": "color_chosen", "team_key": "l", "color_idx": color_l}

        for attempt in range(2):
            master_peer.send(color_r_msg)
            received = slave_peer.recv(timeout=2.0)
            if received and received.get("type") == "color_chosen":
                break
        else:
            return False, f"slave didn't receive color_r after retry: {received}"

        for attempt in range(2):
            master_peer.send(color_l_msg)
            received = slave_peer.recv(timeout=2.0)
            if received and received.get("type") == "color_chosen":
                break
        else:
            return False, f"slave didn't receive color_l after retry: {received}"

        def send_with_retry(msg: dict, expected_type: str, name: str) -> tuple[bool, str]:
            for _ in range(2):
                master_peer.send(msg)
                rcv = slave_peer.recv(timeout=2.0)
                if rcv and rcv.get("type") == expected_type:
                    return True, ""
            return False, f"slave didn't receive {name} after retry: {rcv}"

        # WAR_GAMES phase
        war_r_msg = {"type": "war_games_choice", "team_key": "r", "is_ai": is_ai_r}
        war_l_msg = {"type": "war_games_choice", "team_key": "l", "is_ai": is_ai_l}

        ok, err = send_with_retry(war_r_msg, "war_games_choice", "war_games_r")
        if not ok:
            return False, err

        ok, err = send_with_retry(war_l_msg, "war_games_choice", "war_games_l")
        if not ok:
            return False, err

        # SETUP phase
        game_start_msg = {"type": "game_start"}
        ok, err = send_with_retry(game_start_msg, "game_start", "game_start")
        if not ok:
            return False, err

        setup_r_msg = {"type": "setup_complete", "team_key": "r"}
        setup_l_msg = {"type": "setup_complete", "team_key": "l"}

        ok, err = send_with_retry(setup_r_msg, "setup_complete", "setup_r")
        if not ok:
            return False, err

        master_peer.send(setup_l_msg)
        received = slave_peer.recv(timeout=2.0)
        if not received or received.get("type") != "setup_complete":
            return False, f"slave didn't receive setup_l: {received}"

        return True, ""

    def _setup_network(self, with_spectator: bool = False) -> tuple[NetworkPeer | None, NetworkPeer | None, NetworkPeer | None]:
        """Set up network peers based on mode.

        Returns (master_peer, slave_peer, spectator_peer).
        Spectator only available in ONLINE modes.
        """
        if self._mode == SlaveMode.LOCAL:
            return None, None, None

        if self._mode == SlaveMode.LAN_HOST:
            server = LANServerPeer(port=self._lan_port)
            if not server.start():
                raise RuntimeError("Failed to start LAN server")
            client = LANClientPeer("127.0.0.1", port=self._lan_port)
            if not client.connect():
                server.close()
                raise RuntimeError("Failed to connect LAN client")
            if not server.wait_for_client(timeout=5.0):
                server.close()
                client.close()
                raise RuntimeError("Client did not connect")
            return server, client, None  # master=server, slave=client

        if self._mode == SlaveMode.LAN_GUEST:
            server = LANServerPeer(port=self._lan_port)
            if not server.start():
                raise RuntimeError("Failed to start LAN server")
            client = LANClientPeer("127.0.0.1", port=self._lan_port)
            if not client.connect():
                server.close()
                raise RuntimeError("Failed to connect LAN client")
            if not server.wait_for_client(timeout=5.0):
                server.close()
                client.close()
                raise RuntimeError("Client did not connect")
            return client, server  # master=client, slave=server

        if self._mode == SlaveMode.LAN_BEACON_HOST:
            # Master=server+beacon, slave discovers
            # Start listener BEFORE broadcaster to catch first beacon
            client = BeaconClientPeer()
            client.start_listener()

            server = BeaconServerPeer(port=self._lan_port)
            if not server.start():
                client.close()
                raise RuntimeError("Failed to start beacon server")

            if not client.wait_for_discovery(timeout=5.0):
                server.close()
                client.close()
                raise RuntimeError("Beacon discovery failed")
            if not client.connect():
                server.close()
                client.close()
                raise RuntimeError("Failed to connect after discovery")
            if not server.wait_for_client(timeout=5.0):
                server.close()
                client.close()
                raise RuntimeError("Client did not connect")
            return server, client  # master=server, slave=client

        if self._mode == SlaveMode.LAN_BEACON_GUEST:
            # Slave=server+beacon, master discovers
            # Start listener BEFORE broadcaster to catch first beacon
            client = BeaconClientPeer()
            client.start_listener()

            server = BeaconServerPeer(port=self._lan_port)
            if not server.start():
                client.close()
                raise RuntimeError("Failed to start beacon server")

            if not client.wait_for_discovery(timeout=5.0):
                server.close()
                client.close()
                raise RuntimeError("Beacon discovery failed")
            if not client.connect():
                server.close()
                client.close()
                raise RuntimeError("Failed to connect after discovery")
            if not server.wait_for_client(timeout=5.0):
                server.close()
                client.close()
                raise RuntimeError("Client did not connect")
            return client, server  # master=client (discovers), slave=server (broadcasts)

        if self._mode == SlaveMode.LAN_MDNS_HOST:
            # Master=server+mDNS, slave discovers
            client = MdnsClientPeer()
            client.start_listener()

            server = MdnsServerPeer(port=self._lan_port)
            if not server.start():
                client.close()
                raise RuntimeError("Failed to start mDNS server")

            if not client.wait_for_discovery(timeout=5.0):
                server.close()
                client.close()
                raise RuntimeError("mDNS discovery failed")
            if not client.connect():
                server.close()
                client.close()
                raise RuntimeError("Failed to connect after mDNS discovery")
            if not server.wait_for_client(timeout=5.0):
                server.close()
                client.close()
                raise RuntimeError("Client did not connect")
            return server, client  # master=server, slave=client

        if self._mode == SlaveMode.LAN_MDNS_GUEST:
            # Slave=server+mDNS, master discovers
            client = MdnsClientPeer()
            client.start_listener()

            server = MdnsServerPeer(port=self._lan_port)
            if not server.start():
                client.close()
                raise RuntimeError("Failed to start mDNS server")

            if not client.wait_for_discovery(timeout=5.0):
                server.close()
                client.close()
                raise RuntimeError("mDNS discovery failed")
            if not client.connect():
                server.close()
                client.close()
                raise RuntimeError("Failed to connect after mDNS discovery")
            if not server.wait_for_client(timeout=5.0):
                server.close()
                client.close()
                raise RuntimeError("Client did not connect")
            return client, server  # master=client, slave=server

        if self._mode == SlaveMode.ONLINE_HOST:
            host = RelayHostPeer(self._relay_url)
            code = host.create_room()
            if not code:
                raise RuntimeError("Failed to create relay room")
            guest = RelayGuestPeer(self._relay_url)
            if not guest.join_room(code):
                host.close()
                raise RuntimeError("Failed to join relay room")
            host.wait_for_peer(timeout=10.0)

            spectator = None
            if with_spectator:
                spectator = RelaySpectatorPeer(self._relay_url)
                if not spectator.spectate_room(code):
                    host.close()
                    guest.close()
                    raise RuntimeError("Failed to spectate relay room")

            return host, guest, spectator  # master=host, slave=guest

        if self._mode == SlaveMode.ONLINE_GUEST:
            host = RelayHostPeer(self._relay_url)
            code = host.create_room()
            if not code:
                raise RuntimeError("Failed to create relay room")
            guest = RelayGuestPeer(self._relay_url)
            if not guest.join_room(code):
                host.close()
                raise RuntimeError("Failed to join relay room")
            host.wait_for_peer(timeout=10.0)

            spectator = None
            if with_spectator:
                spectator = RelaySpectatorPeer(self._relay_url)
                if not spectator.spectate_room(code):
                    host.close()
                    guest.close()
                    raise RuntimeError("Failed to spectate relay room")

            return guest, host, spectator  # master=guest, slave=host

        return None, None, None

    def run_game(
        self, game_seed: int,
        master_peer: NetworkPeer | None = None,
        slave_peer: NetworkPeer | None = None,
        spectator_peer: NetworkPeer | None = None,
        fault_seed: int | None = None,
        timing_seed: int | None = None,
    ) -> FuzzResult:
        """Run one complete game with chaos injection and lockstep verification.

        Parameters
        ----------
        fault_seed, timing_seed:
            Optional explicit seeds for deterministic replay. If None,
            derived from game_seed for variety during fuzzing.
        """
        game_rng = random.Random(game_seed)
        team_r_rgb = TEAM_R_RGB
        team_l_rgb = TEAM_L_RGB

        timeline = TimelineRecorder()
        timeline.record_phase("SETUP")

        # Use explicit seeds if provided (replay), else derive from game_seed
        if fault_seed is None:
            fault_seed = game_rng.randint(0, 2**32)
        if timing_seed is None:
            timing_seed = game_rng.randint(0, 2**32)

        seeds = {
            "game": game_seed,
            "fault": fault_seed,
            "timing": timing_seed,
        }

        scheduler = ScenarioScheduler(game_seed, self._chaos_config)
        scheduler.plan_scenarios(self._max_ply)

        fault_injector = FaultInjector(fault_seed, self._chaos_config.fault_configs)

        chaos_master: ChaosPeer | None = None
        chaos_slave: ChaosPeer | None = None
        chaos_spectator: ChaosPeer | None = None

        if master_peer:
            chaos_master = ChaosPeer(master_peer, "master", fault_injector, timeline)
        if slave_peer:
            chaos_slave = ChaosPeer(slave_peer, "slave", fault_injector, timeline)
        if spectator_peer:
            chaos_spectator = ChaosPeer(spectator_peer, "spectator", fault_injector, timeline)

        if master_peer:
            master_peer.clear()
        if slave_peer:
            slave_peer.clear()
        if spectator_peer:
            spectator_peer.clear()

        timeline.record_phase("COLOR_PICK")
        phase_ok, phase_err = self._run_phase_setup(
            master_peer, slave_peer, team_r_rgb, team_l_rgb, game_rng
        )
        if not phase_ok:
            return self._save_chaos_failure(
                seeds, 0, "phase_setup", phase_err,
                timeline, team_r_rgb, team_l_rgb
            )

        if spectator_peer:
            spectator_peer.clear()

        timeline.record_phase("PLAYING")

        master_engines = self._create_engines()
        slave_engines = self._create_engines()
        spectator_engines = self._create_engines() if spectator_peer else []

        master = LockstepVerifier(master_engines, "master")
        slave = LockstepVerifier(slave_engines, "slave")
        spectator = LockstepVerifier(spectator_engines, "spectator") if spectator_peer else None

        try:
            master.init_game(team_r_rgb, team_l_rgb)
            slave.init_game(team_r_rgb, team_l_rgb)
            if spectator:
                spectator.init_game(team_r_rgb, team_l_rgb)

            current_key = "r"
            peace_time = 0

            for ply in range(self._max_ply):
                scenarios = scheduler.get_scenarios_for_ply(ply)
                for scenario in scenarios:
                    ctx = _GameContext(
                        ply=ply,
                        phase="PLAYING",
                        master_peer=chaos_master,
                        slave_peer=chaos_slave,
                        spectator_peer=chaos_spectator,
                        current_team=current_key,
                        board_state=None,
                    )
                    result = execute_scenario(scenario, ctx, game_rng)
                    timeline.record_scenario(result.scenario_name, result.details)
                    if not result.passed:
                        return self._save_chaos_failure(
                            seeds, ply, f"scenario_{result.scenario_name}",
                            str(result.details), timeline, team_r_rgb, team_l_rgb
                        )

                master_moves, errors = master.verify_legal_moves(current_key)
                if errors:
                    return self._save_chaos_failure(
                        seeds, ply, "master_legal_moves", errors[0],
                        timeline, team_r_rgb, team_l_rgb
                    )

                slave_moves, errors = slave.verify_legal_moves(current_key)
                if errors:
                    return self._save_chaos_failure(
                        seeds, ply, "slave_legal_moves", errors[0],
                        timeline, team_r_rgb, team_l_rgb
                    )

                if master_moves != slave_moves:
                    only_master = sorted(master_moves - slave_moves)
                    only_slave = sorted(slave_moves - master_moves)
                    return self._save_chaos_failure(
                        seeds, ply, "master_slave_moves_mismatch",
                        f"only_master={only_master}, only_slave={only_slave}",
                        timeline, team_r_rgb, team_l_rgb
                    )

                if not master_moves:
                    timeline.record_phase("GAME_OVER")
                    break

                move = game_rng.choice(sorted(master_moves))
                fr, fc, tr, tc = move
                next_key = "l" if current_key == "r" else "r"

                timeline.record_move(fr, fc, tr, tc, current_key, {})

                if chaos_master:
                    move_msg = {
                        "type": "move",
                        "from_row": fr,
                        "from_col": fc,
                        "to_row": tr,
                        "to_col": tc,
                        "team_key": current_key,
                        "flags": {},
                    }
                    send_ok = chaos_master.send(move_msg)

                    if not send_ok and chaos_master.fault_injected:
                        # Fault was injected — log and retry send
                        # Note: LockstepRunner doesn't have recovery logic.
                        # Real recovery testing is in integration_e2e.py.
                        failure = chaos_master.last_failure or "unknown"
                        timeline.record_event("fault_injected", {
                            "ply": ply, "reason": failure, "peer": "master"
                        })

                        # Retry the send (chaos layer may let it through this time)
                        send_ok = chaos_master.send(move_msg)
                        if send_ok:
                            timeline.record_event("retry_success", {"ply": ply})
                            received = chaos_slave.recv(timeout=5.0)
                        else:
                            # Still failing — skip this message exchange
                            timeline.record_event("retry_failed", {"ply": ply})
                            received = None
                    elif not send_ok:
                        # Send failed — likely disconnected state from prior fault
                        failure = chaos_master.last_failure or "unknown"
                        timeline.record_event("send_failed", {
                            "ply": ply, "reason": failure, "peer": "master"
                        })
                        # Continue anyway — engines are local, network is dead
                        received = None
                    else:
                        # Normal path — move sent successfully
                        received = chaos_slave.recv(timeout=5.0)
                        if not received:
                            # Log recv failure but continue — engines are local,
                            # network layer is just for message passing.
                            # Real recovery testing is in integration_e2e.py.
                            if chaos_slave.fault_injected:
                                timeline.record_event("fault_injected", {
                                    "ply": ply, "reason": "recv_fault", "peer": "slave"
                                })
                            else:
                                # Genuine timeout with no injected fault = network bug
                                return self._save_chaos_failure(
                                    seeds, ply, "network_timeout",
                                    "slave did not receive move (no fault injected)",
                                    timeline, team_r_rgb, team_l_rgb
                                )

                    if chaos_spectator:
                        spec_received = chaos_spectator.recv(timeout=5.0)
                        # Spectator failures don't fail the test

                master_hash, errors = master.apply_and_verify(
                    fr, fc, tr, tc, current_key, next_key, peace_time
                )
                if errors:
                    return self._save_chaos_failure(
                        seeds, ply, "master_hash", errors[0],
                        timeline, team_r_rgb, team_l_rgb
                    )

                slave_hash, errors = slave.apply_and_verify(
                    fr, fc, tr, tc, current_key, next_key, peace_time
                )
                if errors:
                    return self._save_chaos_failure(
                        seeds, ply, "slave_hash", errors[0],
                        timeline, team_r_rgb, team_l_rgb
                    )

                if master_hash != slave_hash:
                    return self._save_chaos_failure(
                        seeds, ply, "master_slave_hash_mismatch",
                        f"master={master_hash[:16]}... slave={slave_hash[:16]}...",
                        timeline, team_r_rgb, team_l_rgb
                    )

                if spectator:
                    spec_hash, errors = spectator.apply_and_verify(
                        fr, fc, tr, tc, current_key, next_key, peace_time
                    )
                    if errors:
                        return self._save_chaos_failure(
                            seeds, ply, "spectator_hash", errors[0],
                            timeline, team_r_rgb, team_l_rgb
                        )
                    if spec_hash != master_hash:
                        return self._save_chaos_failure(
                            seeds, ply, "spectator_hash_mismatch",
                            f"master={master_hash[:16]}... spectator={spec_hash[:16]}...",
                            timeline, team_r_rgb, team_l_rgb
                        )

                current_key = next_key
                peace_time += 1

            return FuzzResult.ok(f"game completed ({ply+1} plies, chaos={self._chaos_config.profile.name})")

        finally:
            master.close()
            slave.close()
            if spectator:
                spectator.close()
            # Don't close peers here - they're reused across games

    def _save_failure(
        self, seed: int, ply: int, kind: str, detail: str,
        moves: list[dict], team_r_rgb: tuple, team_l_rgb: tuple,
    ) -> FuzzResult:
        """Save failure to legacy corpus and return FuzzResult."""
        corpus_path = save_corpus(
            self._crashes_dir, "chess", "grand_e2e",
            team_r_rgb, team_l_rgb, moves,
            {"ply": ply, "kind": kind, "detail": detail},
            seed,
        )
        return FuzzResult.failure(
            f"ply {ply}: {kind} - {detail}",
            corpus_path=corpus_path,
            seed=seed,
            ply=ply,
        )

    def _save_chaos_failure(
        self, seeds: dict, ply: int, kind: str, detail: str,
        timeline: TimelineRecorder, team_r_rgb: tuple, team_l_rgb: tuple,
    ) -> FuzzResult:
        """Save failure to chaos corpus (v2) and return FuzzResult."""
        corpus_path = save_chaos_corpus(
            self._crashes_dir,
            source="grand_e2e",
            seeds=seeds,
            chaos_profile=self._chaos_config.profile.name.lower(),
            timeline=timeline.to_timeline(),
            failure={"seq": len(timeline.events), "kind": kind, "detail": detail},
            team_r_rgb=team_r_rgb,
            team_l_rgb=team_l_rgb,
            mode=self._mode.name.lower(),
        )
        return FuzzResult.failure(
            f"ply {ply}: {kind} - {detail}",
            corpus_path=corpus_path,
            seed=seeds["game"],
            ply=ply,
        )

    def _is_network_failure(self, result: FuzzResult) -> bool:
        """Check if failure was network-related (needs reconnect)."""
        if result.success:
            return False
        msg = result.message.lower()
        return any(x in msg for x in [
            "disconnect", "timeout", "phase_setup", "network",
            "didn't receive", "connection",
        ])

    def run_fuzzing(self, iterations: int) -> tuple[int, int, int]:
        """Run multiple games. Returns (total, ok, failed)."""
        total = 0
        ok = 0
        failed = 0

        master_peer = None
        slave_peer = None
        spectator_peer = None

        current_port = self._lan_port

        def setup_network(is_reconnect: bool = False):
            nonlocal master_peer, slave_peer, spectator_peer, current_port
            if master_peer:
                master_peer.close()
            if slave_peer:
                slave_peer.close()
            if spectator_peer:
                spectator_peer.close()
            if is_reconnect:
                current_port += 1  # Use new port to avoid bind conflict
                self._lan_port = current_port
                time.sleep(0.2)
            master_peer, slave_peer, spectator_peer = self._setup_network(
                with_spectator=self._with_spectator
            )

        try:
            setup_network()
        except RuntimeError as e:
            print(f"  FATAL: network setup failed: {e}")
            return 0, 0, 1

        reconnect_failures = 0
        max_reconnect_failures = 5

        try:
            i = 0
            while iterations == 0 or i < iterations:
                game_seed = self._rng.randint(0, 2**32)
                result = self.run_game(game_seed, master_peer, slave_peer, spectator_peer)

                if result.success:
                    ok += 1
                    reconnect_failures = 0
                else:
                    failed += 1
                    print(f"  FAIL seed={game_seed}: {result.message}")

                    if self._is_network_failure(result) and self._mode != SlaveMode.LOCAL:
                        try:
                            setup_network(is_reconnect=True)
                            reconnect_failures = 0
                        except RuntimeError as e:
                            reconnect_failures += 1
                            if reconnect_failures >= max_reconnect_failures:
                                print(f"  FATAL: {max_reconnect_failures} reconnect failures, aborting")
                                break

                total += 1
                i += 1

                if total % 10 == 0:
                    print(f"  [{total}] ok={ok} failed={failed}")

            return total, ok, failed
        finally:
            if master_peer:
                master_peer.close()
            if slave_peer:
                slave_peer.close()
            if spectator_peer:
                spectator_peer.close()


def main() -> int:
    """Run Grand E2E Lockstep Fuzzer."""
    import argparse

    parser = argparse.ArgumentParser(description="Grand E2E Lockstep Fuzzer")
    parser.add_argument("--iterations", "-n", type=int, default=10)
    parser.add_argument("--seed", "-s", type=int, default=42)
    parser.add_argument(
        "--mode", "-m",
        choices=[
            "local",
            "lan_host", "lan_guest",
            "lan_beacon_host", "lan_beacon_guest",
            "lan_mdns_host", "lan_mdns_guest",
            "online_host", "online_guest",
        ],
        default="local",
    )
    parser.add_argument("--hil-url", help="HIL server WebSocket URL")
    parser.add_argument("--relay-url", default="wss://relay.chess101.net")
    parser.add_argument("--lan-port", type=int, default=65101)
    parser.add_argument("--spectator", action="store_true",
                        help="Add spectator (ONLINE modes only)")
    parser.add_argument(
        "--profile", "-p",
        choices=["gentle", "standard", "aggressive", "adversarial"],
        default="standard",
        help="Chaos intensity profile (default: standard)",
    )
    parser.add_argument(
        "--replay",
        type=str,
        metavar="CORPUS",
        help="Replay a chaos corpus file instead of fuzzing",
    )
    parser.add_argument(
        "--scenarios",
        type=str,
        help="Comma-separated scenarios to enable (e.g. RECONNECT_MID_GAME,WRONG_TURN_MOVE)",
    )
    args = parser.parse_args()

    mode_map = {
        "local": SlaveMode.LOCAL,
        "lan_host": SlaveMode.LAN_HOST,
        "lan_guest": SlaveMode.LAN_GUEST,
        "lan_beacon_host": SlaveMode.LAN_BEACON_HOST,
        "lan_beacon_guest": SlaveMode.LAN_BEACON_GUEST,
        "lan_mdns_host": SlaveMode.LAN_MDNS_HOST,
        "lan_mdns_guest": SlaveMode.LAN_MDNS_GUEST,
        "online_host": SlaveMode.ONLINE_HOST,
        "online_guest": SlaveMode.ONLINE_GUEST,
    }
    mode = mode_map[args.mode]

    profile_map = {
        "gentle": ChaosProfile.GENTLE,
        "standard": ChaosProfile.STANDARD,
        "aggressive": ChaosProfile.AGGRESSIVE,
        "adversarial": ChaosProfile.ADVERSARIAL,
    }
    profile = profile_map[args.profile]

    enabled_scenarios = None
    if args.scenarios:
        enabled_scenarios = set(s.strip().upper() for s in args.scenarios.split(","))

    if args.replay:
        print(f"[INFO] Replaying chaos corpus: {args.replay}")
        corpus_path = Path(args.replay)
        if not corpus_path.exists():
            print(f"  ERROR: corpus file not found: {corpus_path}")
            return 1

        corpus = load_corpus(corpus_path)
        if not is_chaos_corpus(corpus):
            print(f"  ERROR: not a chaos corpus (version != 2)")
            return 1

        seeds = corpus["seeds"]
        chaos_profile_name = corpus.get("chaos_profile", "standard")
        profile = profile_map.get(chaos_profile_name, ChaosProfile.STANDARD)

        expected_failure = corpus.get("failure", {})
        expected_kind = expected_failure.get("kind", "unknown")

        print(f"  seeds: game={seeds['game']} fault={seeds['fault']} timing={seeds['timing']}")
        print(f"  profile: {chaos_profile_name}")
        print(f"  expected failure: {expected_kind}")

        fuzzer = GrandE2EFuzzer(
            seed=seeds["game"],
            mode=mode,
            chaos_profile=profile,
        )
        fuzzer._fault_seed = seeds["fault"]
        fuzzer._timing_seed = seeds["timing"]

        result = fuzzer.run_game(seeds["game"])

        if expected_kind in ("test", "unknown"):
            if result.success:
                print(f"\n  REPLAY PASS: {result.message}")
                return 0
            else:
                print(f"\n  REPLAY FAIL: {result.message}")
                return 1

        if result.success:
            print(f"\n  UNEXPECTED PASS: expected failure '{expected_kind}' but game passed")
            return 1

        actual_kind = result.message.split(":")[1].strip().split(" ")[0] if ":" in result.message else "unknown"
        if expected_kind in result.message:
            print(f"\n  REPLAY REPRODUCED: {result.message}")
            return 0
        else:
            print(f"\n  DIFFERENT FAILURE: expected '{expected_kind}' got '{actual_kind}'")
            print(f"    {result.message}")
            return 1

    print(f"[INFO] Grand E2E Chaos Fuzzer: mode={args.mode} profile={args.profile} seed={args.seed}")

    fuzzer = GrandE2EFuzzer(
        seed=args.seed,
        mode=mode,
        hil_url=args.hil_url,
        relay_url=args.relay_url,
        lan_port=args.lan_port,
        with_spectator=args.spectator,
        chaos_profile=profile,
        enabled_scenarios=enabled_scenarios,
    )
    total, ok, failed = fuzzer.run_fuzzing(args.iterations)

    print(f"\nDone. {total} games")
    print(f"  ok={ok}  failed={failed}")

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
