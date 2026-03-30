"""NetworkedGameRunner — multiplayer extension of GameRunner.

Adds WebSocket transport, LAN discovery, and the full message-negotiation
protocol on top of the existing GameRunner phase state machine.

Phase flow (networked):
    LOBBY → (HOST/JOIN selected) → COLOR_PICK → WAR_GAMES → PLAYING → GAME_OVER

Message flow:
    connect          → hello (both sides)
    hello exchanged  → HOST sends game_setup
    COLOR_PICK       → color_chosen (each side sends their choice)
    WAR_GAMES        → war_games_choice (each side sends their choice)
                       HOST sends game_start after both received
    PLAYING          → move / move_ack each turn
                       board_sync_request / board_sync on desync
    ping/pong        → every 10 s for keepalive
"""
from __future__ import annotations

import collections
import logging
import threading
import time
from enum import Enum, auto
from typing import Optional

import pygame

try:
    import cv2 as _cv2  # type: ignore[import]
    _CV2_AVAILABLE = True
except ImportError:
    _cv2 = None  # type: ignore[assignment]
    _CV2_AVAILABLE = False

try:
    import numpy as _np  # type: ignore[import]
    _NP_AVAILABLE = True
except ImportError:
    _np = None  # type: ignore[assignment]
    _NP_AVAILABLE = False

from core.team import Team
from network import chessmatrix as _chessmatrix
from network.client import GameClient
from network.discovery import BeaconBroadcaster, BeaconListener
from network.protocol import MoveFlags, board_hash, build_move_msg, decode_grid, encode_grid
from network.relay_client import RelayClient, _DEFAULT_RELAY_URL
from network.server import GameServer
from pieces.king import King
from pieces.pawn import Pawn
from simulator.app import GameRunner, Phase, _COLOR_NAMES, _BOARD_W, _SCALE, _CELL_PX

logger = logging.getLogger(__name__)

_PROTOCOL_VERSION = "1"
_PING_INTERVAL_S = 10.0
_PING_TIMEOUT_S  = 30.0
_RECONNECT_TIMEOUT_S = 60.0


class NetworkRole(Enum):
    """Which side of the connection this instance occupies."""
    LOCAL           = auto()   # local two-player play (no network)
    HOST            = auto()   # LAN host (GameServer)
    GUEST           = auto()   # LAN guest (GameClient)
    SPECTATOR       = auto()   # LAN spectator (receive-only)
    ONLINE_HOST     = auto()   # internet host via relay
    ONLINE_GUEST    = auto()   # internet guest via relay
    ONLINE_SPECTATOR = auto()  # internet spectator via relay


class NetworkedGameRunner(GameRunner):
    """GameRunner subclass that connects two instances over a WebSocket.

    Args:
        role: HOST, GUEST, or SPECTATOR.
        host_ip: Server IP to connect to (GUEST / SPECTATOR only).
        port: WebSocket port (default 65101).
        player_name: Display name for this player.
    """

    def __init__(
        self,
        role: NetworkRole,
        host_ip: Optional[str] = None,
        port: int = 65101,
        player_name: str = "Player",
        relay_url: str = _DEFAULT_RELAY_URL,
        room_code: Optional[str] = None,
    ) -> None:
        self._role = role
        self._host_ip = host_ip
        self._port = port
        self._player_name = player_name
        self._relay_url = relay_url
        self._room_code: Optional[str] = room_code.upper() if room_code else None

        # Network objects (created in run())
        self._server: Optional[GameServer] = None
        self._client: Optional[GameClient] = None
        self._relay_client: Optional[RelayClient] = None
        self._broadcaster: Optional[BeaconBroadcaster] = None
        self._listener: Optional[BeaconListener] = None

        # Thread-safe incoming message queue
        self._incoming: collections.deque = collections.deque()
        self._net_lock = threading.Lock()

        # Network state (mutated on main thread only, after draining _incoming)
        self._peer_name: Optional[str] = None
        self._peer_connected = False
        self._peer_disconnected = False
        self._disconnect_time_ms: Optional[int] = None
        self._reconnect_attempted = False   # True once a relay reconnect thread is running
        self._session_lost = False          # True when relay restarted and room is gone
        self._connecting = False            # True while background relay connect is in progress

        # Negotiation state
        self._local_color_sent = False
        self._remote_color_received = False
        self._local_war_sent = False
        self._remote_war_received = False
        self._waiting_for_game_start = False   # GUEST waits for HOST's game_start

        # Move protocol state
        self._net_seq = 0
        self._pending_send_move: Optional[dict] = None   # set after local move, before next_turn
        self._waiting_for_ack = False
        self._pending_remote_move: Optional[dict] = None

        # Keepalive
        self._last_ping_s: float = 0.0
        self._last_pong_s: float = time.time()

        # LOCAL: "both" — always the player's turn.
        # HOST / ONLINE_HOST: team_r ("r").
        # GUEST / ONLINE_GUEST: team_l ("l").
        # SPECTATOR / ONLINE_SPECTATOR: receive-only ("spectator").
        self._local_team_key = (
            "both"      if role == NetworkRole.LOCAL else
            "r"         if role in (NetworkRole.HOST, NetworkRole.ONLINE_HOST) else
            "spectator" if role in (NetworkRole.SPECTATOR, NetworkRole.ONLINE_SPECTATOR) else
            "l"
        )

        # Physical-host mode: Pi is HOST and Sim drives setup for both teams.
        self._is_physical_host_mode = False
        # Pi physical setup progress (populated by setup_status messages).
        self._physical_setup_r_complete = False
        self._physical_setup_l_complete = False

        # Room-code entry sub-state (Join Online from Lobby — text fallback)
        self._entering_room_code = False
        self._room_code_input    = ""

        # ChessMatrix display (host waiting for peer)
        self._chessmatrix_grid: Optional[list] = None   # 8×8 RGB grid, set after room created

        # Camera scanner (guest joining online via CODE_SCAN phase)
        self._cv_capture: Optional[object] = None        # cv2.VideoCapture or None
        self._cv_last_frame: Optional[object] = None     # most recent BGR numpy frame

        # Board-entry ChessMatrix state (CODE_SCAN_BOARD phase)
        self._cs: _chessmatrix.CodeScanState = _chessmatrix.CodeScanState()

        # Call parent AFTER setting our attrs so _reset() can reference them.
        # LOCAL role shows the Lobby so the player can choose a mode;
        # network roles skip the Lobby and go straight to NAME_ENTRY.
        if role == NetworkRole.LOCAL:
            super().__init__(skip_lobby=False)
            self._player_name = player_name
            # phase is already LOBBY from super().__init__
        else:
            super().__init__(skip_lobby=True)
            self._player_name = player_name
            self.phase = Phase.NAME_ENTRY

    # ── Lobby overrides ────────────────────────────────────────────────────────

    def _handle_lobby(self, event: pygame.event.Event) -> None:
        """Handle room-code entry sub-state; otherwise delegate to parent."""
        if self._entering_room_code:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_BACKSPACE:
                    self._room_code_input = self._room_code_input[:-1]
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    code = self._room_code_input.upper().strip()
                    if len(code) == 6:
                        self._room_code = code
                        self._entering_room_code = False
                        self._role = NetworkRole.ONLINE_GUEST
                        self._local_team_key = "l"
                        self.phase = Phase.NAME_ENTRY
                elif event.unicode and event.unicode.isalpha() and len(self._room_code_input) < 6:
                    self._room_code_input += event.unicode.upper()
            return
        super()._handle_lobby(event)

    def _lobby_select(self, opt_idx: int) -> None:
        """Handle all 6 lobby options including online modes."""
        if opt_idx == 0:
            # Play Locally — no networking needed
            self._role = NetworkRole.LOCAL
            self._local_team_key = "both"
            self.phase = Phase.COLOR_PICK
            logger.info("Lobby: Play Locally selected")

        elif opt_idx == 1:
            # Host LAN — set role then collect name
            self._role = NetworkRole.HOST
            self._local_team_key = "r"
            self.phase = Phase.NAME_ENTRY
            logger.info("Lobby: Host LAN selected")

        elif opt_idx == 2:
            # Join LAN — auto-discover; if no host_ip set, scan beacon
            self._role = NetworkRole.GUEST
            self._local_team_key = "l"
            self.phase = Phase.NAME_ENTRY
            logger.info("Lobby: Join LAN selected (will auto-discover)")

        elif opt_idx == 3:
            # Watch LAN
            self._role = NetworkRole.SPECTATOR
            self._local_team_key = "spectator"
            self.phase = Phase.NAME_ENTRY
            logger.info("Lobby: Watch LAN selected (will auto-discover)")

        elif opt_idx == 4:
            # Host Online — set role then collect name; relay room created after name
            self._role = NetworkRole.ONLINE_HOST
            self._local_team_key = "r"
            self.phase = Phase.NAME_ENTRY
            logger.info("Lobby: Host Online selected (relay: %s)", self._relay_url)

        elif opt_idx == 5:
            # Join Online — primary path is board-entry raster-beam UX
            self._room_code_input = ""
            self._cs.reset()
            self.phase = Phase.CODE_SCAN_BOARD
            logger.info("Lobby: Join Online — board-entry mode")

    # ── Name entry ─────────────────────────────────────────────────────────────

    def _handle_name_entry(self, event: "pygame.event.Event") -> None:
        """On Enter, start networking then advance to COLOR_PICK."""
        prev_phase = self.phase
        super()._handle_name_entry(event)
        if prev_phase == Phase.NAME_ENTRY and self.phase == Phase.COLOR_PICK:
            self._start_network()

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _reset(self) -> None:
        """Reset networked state alongside base game state."""
        self._local_color_sent = False
        self._remote_color_received = False
        self._local_war_sent = False
        self._remote_war_received = False
        self._waiting_for_game_start = False
        self._net_seq = 0
        self._pending_send_move = None
        self._waiting_for_ack = False
        self._pending_remote_move = None
        self._remote_last_move: Optional[tuple[int, int, int, int]] = None
        self._entering_room_code = False
        self._room_code_input    = ""
        self._chessmatrix_grid   = None
        self._cs.reset()
        self._close_camera()
        super()._reset()

    def _net_send(self, msg: dict) -> None:
        """Send a message over the active connection (thread-safe)."""
        if self._server:
            self._server.send(msg)
        elif self._client:
            self._client.send(msg)
        elif self._relay_client:
            self._relay_client.send(msg)

    def _on_network_message(self, msg: dict) -> None:
        """Called from the network daemon thread for every inbound message.

        Appends to ``_incoming`` so the main thread can process it safely.
        """
        with self._net_lock:
            self._incoming.append(msg)

    def _drain_incoming(self) -> None:
        """Process all queued inbound messages on the main thread."""
        with self._net_lock:
            batch = list(self._incoming)
            self._incoming.clear()
        for msg in batch:
            self._dispatch(msg)

    def _dispatch(self, msg: dict) -> None:
        """Route a message to the appropriate handler."""
        t = msg.get("type", "")
        handlers = {
            "hello":             self._on_hello,
            "game_setup":        self._on_game_setup,
            "color_chosen":      self._on_color_chosen,
            "war_games_choice":  self._on_war_games_choice,
            "game_start":        self._on_game_start,
            "move":              self._on_remote_move,
            "move_ack":          self._on_move_ack,
            "board_sync_request": self._on_board_sync_request,
            "board_sync":        self._on_board_sync,
            "rejoin_sync":       self._on_rejoin_sync,
            "game_event":        self._on_game_event,
            "setup_status":      self._on_setup_status,
            "ping":              self._on_ping,
            "pong":              self._on_pong,
            "error":             self._on_error,
            "relay_error":       self._on_relay_error,
            "_peer_lost":        self._on_peer_lost,
            "_reconnect_result": self._on_reconnect_result,
            "_network_ready":    self._on_network_ready,
            "_network_failed":   self._on_network_failed,
            "new_game":          self._on_new_game,
        }
        handler = handlers.get(t)
        if handler:
            handler(msg)
        else:
            logger.debug("Unknown message type: %r", t)

    def _local_team(self) -> Team:
        if self._local_team_key in ("both", "spectator"):
            return self._b.team_r   # arbitrary reference for non-networked / spectator
        return self._b.team_r if self._local_team_key == "r" else self._b.team_l

    def _remote_team(self) -> Team:
        return self._b.team_l if self._local_team_key == "r" else self._b.team_r

    def _is_my_turn(self) -> bool:
        if self._local_team_key == "both":
            return True   # LOCAL: always the player's turn
        if self._current_team is None:
            return False
        return self._current_team.r == self._local_team().r

    # ── Connection callbacks (called from network thread) ─────────────────────

    def _on_connected(self) -> None:
        """Peer connected — send hello."""
        self._last_pong_s = time.time()   # reset keepalive clock — peer just connected
        self._peer_connected = True
        self._chessmatrix_grid = None   # peer joined, stop displaying ChessMatrix
        # Translate online roles to their wire-protocol equivalents
        wire_role = {
            NetworkRole.ONLINE_HOST:      "host",
            NetworkRole.ONLINE_GUEST:     "guest",
            NetworkRole.ONLINE_SPECTATOR: "spectator",
        }.get(self._role, self._role.name.lower())
        self._net_send({
            "type": "hello",
            "version": _PROTOCOL_VERSION,
            "player_name": self._player_name,
            "role": wire_role,
        })
        logger.info("Connected to peer — sent hello (role=%s)", self._role.name)

    def _on_disconnected(self) -> None:
        """Peer disconnected — queue disconnect event."""
        with self._net_lock:
            self._incoming.append({"type": "_peer_lost"})

    # ── Message handlers (called on main thread) ───────────────────────────────

    def _on_peer_lost(self, msg: dict) -> None:  # noqa: ARG002
        """Internal: peer disconnected, show overlay."""
        self._peer_disconnected = True

    def _on_network_ready(self, msg: dict) -> None:
        """Background relay connect succeeded — wire up the client."""
        self._relay_client = msg["relay"]
        self._room_code    = msg.get("room_code") or self._room_code
        self._connecting   = False
        logger.info("Relay connected — room %s", self._room_code)
        # Encode ChessMatrix for HOST so it can be displayed while waiting for peer
        if self._role == NetworkRole.ONLINE_HOST and self._room_code:
            try:
                self._chessmatrix_grid = _chessmatrix.encode(self._room_code)
            except Exception as exc:
                logger.warning("ChessMatrix encode failed: %s", exc)

    def _on_network_failed(self, msg: dict) -> None:  # noqa: ARG002
        """Background relay connect failed."""
        self._connecting = False
        logger.error("Failed to connect to relay at %s", self._relay_url)

    def _on_reconnect_result(self, msg: dict) -> None:
        """Internal: result of a background relay reconnect attempt."""
        if msg.get("ok"):
            logger.info("Relay reconnect succeeded")
            self._peer_disconnected = False
            self._reconnect_attempted = False
            self._disconnect_time_ms = None
            self._session_lost = False
        else:
            logger.warning("Relay reconnect failed — relay likely restarted, session is gone")
            self._session_lost = True

    def _on_new_game(self, msg: dict) -> None:  # noqa: ARG002
        """Peer pressed N — reset without re-broadcasting."""
        self._reset()
        self._init_board()
        if self._local_team_key in ("r", "l") and (self._relay_client or self._server or self._client):
            self.phase = Phase.COLOR_PICK
            self._peer_disconnected = False
            self._disconnect_time_ms = None
            self._last_pong_s = time.time()
        logger.info("New game triggered by peer")

    def _new_game_local(self) -> None:
        """Local player pressed N — broadcast then reset."""
        self._net_send({"type": "new_game"})
        self._reset()
        self._init_board()
        if self._local_team_key in ("r", "l") and (self._relay_client or self._server or self._client):
            self.phase = Phase.COLOR_PICK
            self._peer_disconnected = False
            self._disconnect_time_ms = None
            self._last_pong_s = time.time()

    def _on_hello(self, msg: dict) -> None:
        remote_ver = msg.get("version", "")
        if remote_ver != _PROTOCOL_VERSION:
            logger.error("Version mismatch: remote=%r local=%r", remote_ver, _PROTOCOL_VERSION)
            self._net_send({"type": "error", "code": "version_mismatch"})
            return
        self._peer_name = msg.get("player_name", "Opponent")
        self._peer_disconnected = False   # clear any stale flag from handshake hiccup
        self._disconnect_time_ms = None
        self._reconnect_attempted = False
        self._session_lost = False
        self._last_pong_s = time.time()   # reset keepalive clock so NAME_ENTRY wait doesn't trigger timeout
        peer_role = msg.get("role", "guest")
        logger.info("Hello from %r (role=%s)", self._peer_name, peer_role)

        if self._role in (NetworkRole.HOST, NetworkRole.ONLINE_HOST):
            if peer_role == "spectator":
                # Send spectator a view of the current board state
                self._net_send({
                    "type": "game_setup",
                    "version": _PROTOCOL_VERSION,
                    "host_name": self._player_name,
                    "guest_name": self._peer_name,
                    "mode": "spectator_view",
                })
                if self.phase == Phase.PLAYING:
                    self._send_board_sync()
                logger.info("Sent game_setup (spectator_view)")
            elif self.phase == Phase.PLAYING:
                # Guest is rejoining an in-progress game — skip setup, sync state.
                self._waiting_for_ack = False
                self._net_seq = 0
                self._net_send(self._build_rejoin_sync())
                logger.info("Sent rejoin_sync to reconnecting guest")
            else:
                self._net_send({
                    "type": "game_setup",
                    "version": _PROTOCOL_VERSION,
                    "host_name": self._player_name,
                    "guest_name": self._peer_name,
                })
                self.phase = Phase.COLOR_PICK
                logger.info("Sent game_setup — advancing to COLOR_PICK")
        elif self.phase in (Phase.COLOR_PICK, Phase.WAR_GAMES, Phase.PLAYING):
            # Send hello back so HOST processes it.
            # - Initial connection (COLOR_PICK/WAR_GAMES): HOST receives hello → sets _peer_name → sends game_setup
            # - Mid-game reconnect (PLAYING): HOST receives hello → sends rejoin_sync
            self._on_connected()
            logger.info("Sending hello response (phase=%s) — HOST will send game_setup or rejoin_sync", self.phase.name)

    def _on_game_setup(self, msg: dict) -> None:
        """GUEST or SPECTATOR receives game_setup."""
        if self.phase == Phase.PLAYING:
            return   # replayed from relay history during reconnect — ignore
        mode = msg.get("mode", "")
        logger.info("Received game_setup (mode=%r)", mode)

        if mode == "spectator_view":
            # Spectator: skip setup phases, go straight to PLAYING.
            # Board sync will arrive separately and populate the grid.
            self._b.initialize_game_board()
            self._current_team = self._b.team_r
            self.phase = Phase.PLAYING
            logger.info("Spectator: waiting for board_sync to sync position")
        elif mode == "physical_host":
            # Pi is the physical host; Sim drives setup for BOTH teams.
            self._is_physical_host_mode = True
            self.phase = Phase.COLOR_PICK
            logger.info("Physical-host mode: Sim will choose colors for both teams")
        else:
            self.phase = Phase.COLOR_PICK

    def _on_color_chosen(self, msg: dict) -> None:
        """Remote side picked a team color."""
        team_key = msg.get("team_key")
        color_idx = msg.get("color_idx")
        if color_idx is None or team_key is None:
            return
        b = self._b
        t = b.team_array[color_idx]
        if team_key == "r":
            b.team_r.r, b.team_r.g, b.team_r.b = t.r, t.g, t.b
            b.team_r.name = _COLOR_NAMES[color_idx]
            self._selected_r_idx = color_idx
        else:
            b.team_l.r, b.team_l.g, b.team_l.b = t.r, t.g, t.b
            b.team_l.name = _COLOR_NAMES[color_idx]
            self._selected_l_idx = color_idx
        self._remote_color_received = True
        logger.info("Remote color_chosen: team=%s idx=%d", team_key, color_idx)
        self._check_color_complete()

    def _check_color_complete(self) -> None:
        """Advance to WAR_GAMES once both sides have picked colors."""
        if self._selected_r_idx is not None and self._selected_l_idx is not None:
            self._b.team_r.r += 1   # BUG LOCK-IN: mirrors local play
            self.phase = Phase.WAR_GAMES
            logger.info("Both colors chosen — advancing to WAR_GAMES")

    def _on_war_games_choice(self, msg: dict) -> None:
        """Remote side picked Human or AI."""
        team_key = msg.get("team_key")
        is_ai = msg.get("is_ai", False)
        b = self._b
        if team_key == "r":
            b.computer_player_r = is_ai
        else:
            b.computer_player_l = is_ai
        self._remote_war_received = True
        logger.info("Remote war_games_choice: team=%s ai=%s", team_key, is_ai)
        self._check_war_complete()

    def _check_war_complete(self) -> None:
        """HOST sends game_start when both sides have chosen; GUEST waits."""
        b = self._b
        if b.computer_player_r is None or b.computer_player_l is None:
            return
        if self._role in (NetworkRole.HOST, NetworkRole.ONLINE_HOST):
            logger.info("Both war_games choices received — sending game_start")
            self._net_send({
                "type": "game_start",
                "team_r": {"r": b.team_r.r, "g": b.team_r.g, "b": b.team_r.b},
                "team_l": {"r": b.team_l.r, "g": b.team_l.g, "b": b.team_l.b},
            })
            self._start_game()
        # GUEST waits for game_start message

    def _on_game_start(self, msg: dict) -> None:
        """GUEST receives game_start → begin the game."""
        if self.phase == Phase.PLAYING:
            return   # replayed from relay history during reconnect — ignore
        logger.info("Received game_start")
        self._start_game()
        # In physical_host mode the Pi still needs to do interactive_setup;
        # send our own setup_complete immediately (Sim board is auto-placed).
        if self._is_physical_host_mode:
            self._net_send({"type": "setup_complete"})
            logger.info("Physical-host: sent setup_complete (Sim board auto-placed)")

    def _on_setup_status(self, msg: dict) -> None:
        """Pi sends setup_status messages as physical pieces are placed."""
        team_key = msg.get("team_key", "")
        status   = msg.get("status", "")
        if team_key == "r" and status == "complete":
            self._physical_setup_r_complete = True
            logger.info("Physical setup: Pi team_r placement complete")
        elif team_key == "l" and status == "complete":
            self._physical_setup_l_complete = True
            logger.info("Physical setup: Pi team_l placement complete")

    def _on_remote_move(self, msg: dict) -> None:
        """Inbound move from opponent — queue for main thread application."""
        # Store for processing in _update() during opponent's turn
        self._pending_remote_move = msg

    def _on_move_ack(self, msg: dict) -> None:
        status = msg.get("status", "ok")
        if status == "ok":
            self._waiting_for_ack = False
        elif status == "desync":
            logger.warning("Desync reported by peer at seq=%d — sending board_sync", msg.get("seq", -1))
            self._send_board_sync()
            self._waiting_for_ack = False

    def _on_board_sync_request(self, msg: dict) -> None:
        logger.warning("Board sync requested by peer")
        self._send_board_sync()

    def _on_board_sync(self, msg: dict) -> None:
        """Apply a full board state received from peer."""
        logger.warning("Applying board_sync from peer")
        b = self._b
        decoded = decode_grid(msg["grid"], b.team_r, b.team_l)
        for r in range(8):
            for c in range(8):
                b.grid[r][c] = decoded[r][c]
        self.peace_time = msg.get("peace_time", self.peace_time)
        # Recalculate legal moves
        assert self._current_team is not None
        self._begin_turn(self._current_team)

    def _on_game_event(self, msg: dict) -> None:
        event_type = msg.get("event")
        logger.info("Remote game_event: %s", event_type)
        if event_type == "checkmate":
            losing_key = msg.get("losing_team_key", "")
            b = self._b
            losing_team = b.team_r if losing_key == "r" else b.team_l
            self._declare_victory(losing_team)
        elif event_type == "stalemate":
            self.stale_mate()

    def _on_ping(self, msg: dict) -> None:
        self._net_send({"type": "pong", "seq": msg.get("seq", 0)})

    def _on_pong(self, msg: dict) -> None:
        self._last_pong_s = time.time()

    def _on_error(self, msg: dict) -> None:
        logger.error("Network error from peer: %r", msg.get("code"))

    def _on_relay_error(self, msg: dict) -> None:
        code = msg.get("code", "unknown")
        if code == "illegal_move":
            logger.error(
                "Relay rejected our move as illegal: %s→%s",
                (msg.get("from_row"), msg.get("from_col")),
                (msg.get("to_row"),   msg.get("to_col")),
            )
            self._waiting_for_ack = False
            self._net_send({"type": "board_sync_request"})  # resync with peer's board state
        else:
            logger.error("Relay error: %s", code)

    # ── Board sync helper ──────────────────────────────────────────────────────

    def _build_rejoin_sync(self) -> dict:
        """Build a rejoin_sync message encoding the full current game state."""
        b = self._b
        assert self._current_team is not None
        team_key = "r" if self._current_team.r == b.team_r.r else "l"
        return {
            "type": "rejoin_sync",
            "grid": encode_grid(b.grid, b.team_r),
            "peace_time": self.peace_time,
            "current_team_key": team_key,
            "move_count": self._move_count,
            "team_r": {"r": b.team_r.r, "g": b.team_r.g, "b": b.team_r.b,
                        "name": b.team_r.name},
            "team_l": {"r": b.team_l.r, "g": b.team_l.g, "b": b.team_l.b,
                        "name": b.team_l.name},
            "computer_player_r": bool(b.computer_player_r),
            "computer_player_l": bool(b.computer_player_l),
        }

    def _on_rejoin_sync(self, msg: dict) -> None:
        """GUEST receives rejoin_sync — restore full game state and resume."""
        b = self._b

        tr = msg.get("team_r", {})
        tl = msg.get("team_l", {})
        b.team_r.r, b.team_r.g, b.team_r.b = tr["r"], tr["g"], tr["b"]
        b.team_r.name = tr.get("name", "Right")
        b.team_l.r, b.team_l.g, b.team_l.b = tl["r"], tl["g"], tl["b"]
        b.team_l.name = tl.get("name", "Left")

        decoded = decode_grid(msg["grid"], b.team_r, b.team_l)
        for r in range(8):
            for c in range(8):
                b.grid[r][c] = decoded[r][c]

        self.peace_time = msg.get("peace_time", 0)
        self._move_count = msg.get("move_count", 0)
        b.computer_player_r = msg.get("computer_player_r", False)
        b.computer_player_l = msg.get("computer_player_l", False)

        current_key = msg.get("current_team_key", "r")
        self._current_team = b.team_r if current_key == "r" else b.team_l

        # Reset sequence so move numbering starts fresh for both sides.
        self._net_seq = 0
        self._waiting_for_ack = False
        self._pending_remote_move = None

        self.phase = Phase.PLAYING
        self._begin_turn(self._current_team)
        logger.info("Rejoined in-progress game — %s's turn", self._current_team.name)

    def _send_board_sync(self) -> None:
        b = self._b
        assert self._current_team is not None
        team_key = "r" if self._current_team.r == b.team_r.r else "l"
        self._net_send({
            "type": "board_sync",
            "grid": encode_grid(b.grid, b.team_r),
            "peace_time": self.peace_time,
            "current_team_key": team_key,
        })

    # ── MoveFlags builder ─────────────────────────────────────────────────────

    def _build_move_flags(
        self,
        piece,
        fr: int,
        fc: int,
        tr: int,
        tc: int,
        pre_capture,
    ) -> MoveFlags:
        """Build MoveFlags by inspecting the move BEFORE _apply_move is called.

        Args:
            piece: The piece being moved (still at grid[fr][fc] position).
            fr, fc: From-row, from-col.
            tr, tc: To-row, to-col.
            pre_capture: Whatever was at grid[tr][tc] before the move started.
        """
        is_capture = pre_capture is not None
        is_en_passant = False
        captured_at = None
        is_castling = False
        rook_from = None
        rook_to = None
        is_promotion = False

        if isinstance(piece, Pawn):
            # En passant: pawn moved diagonally to an empty square
            if abs(tc - fc) == 1 and pre_capture is None:
                is_en_passant = True
                captured_at = (tr - piece.direction, tc)
            # Promotion: pawn reaches opposite back rank
            if (piece.starting_row + 6) % 12 == tr:
                is_promotion = True

        elif isinstance(piece, King):
            # Castling: king moves two squares horizontally
            if fr == tr and abs(tc - fc) == 2:
                is_castling = True
                if tc == fc - 2:   # queen-side
                    rook_from = (fr, fc - 4)
                    rook_to   = (fr, fc - 1)
                else:               # king-side
                    rook_from = (fr, fc + 3)
                    rook_to   = (fr, fc + 1)

        return MoveFlags(
            is_capture=is_capture,
            is_en_passant=is_en_passant,
            is_castling=is_castling,
            is_promotion=is_promotion,
            captured_at=captured_at,
            rook_from=rook_from,
            rook_to=rook_to,
        )

    # ── Overrides — COLOR_PICK ────────────────────────────────────────────────

    def _handle_color_pick(self, event: pygame.event.Event) -> None:
        """Networked COLOR_PICK: each side controls only their own row."""
        if self._local_team_key == "both":
            # LOCAL mode — use base GameRunner's unrestricted handler
            super()._handle_color_pick(event)
            return
        if event.type != pygame.MOUSEBUTTONDOWN:
            return
        if self._peer_name is None:     # peer hasn't joined yet — ignore clicks
            return
        if self._local_color_sent:      # already picked — ignore re-picks
            return
        cell = self._px_to_cell(*event.pos)
        if cell is None:
            return
        row, col = cell
        b = self._b

        # HOST controls row 2 (team_r); GUEST controls row 5 (team_l).
        # In physical_host mode the GUEST (Sim) picks BOTH rows on behalf of Pi.
        if self._local_team_key == "r" and row == 2:
            self._selected_r_idx = col
            t = b.team_array[col]
            b.team_r.r, b.team_r.g, b.team_r.b = t.r, t.g, t.b
            b.team_r.name = _COLOR_NAMES[col]
            self._local_color_sent = True
            self._net_send({"type": "color_chosen", "team_key": "r", "color_idx": col})
            logger.info("Sent color_chosen r idx=%d", col)
            self._check_color_complete()

        elif self._local_team_key == "l" and row == 5:
            self._selected_l_idx = col
            t = b.team_array[col]
            b.team_l.r, b.team_l.g, b.team_l.b = t.r, t.g, t.b
            b.team_l.name = _COLOR_NAMES[col]
            self._local_color_sent = True
            self._net_send({"type": "color_chosen", "team_key": "l", "color_idx": col})
            logger.info("Sent color_chosen l idx=%d", col)
            self._check_color_complete()

        elif self._is_physical_host_mode and self._local_team_key == "l" and row == 2:
            # Physical-host mode: Sim GUEST picks row 2 on Pi's behalf
            self._selected_r_idx = col
            t = b.team_array[col]
            b.team_r.r, b.team_r.g, b.team_r.b = t.r, t.g, t.b
            b.team_r.name = _COLOR_NAMES[col]
            self._net_send({"type": "color_chosen", "team_key": "r", "color_idx": col})
            logger.info("Physical-host: sent color_chosen r idx=%d for Pi", col)
            self._check_color_complete()

    # ── Overrides — WAR_GAMES ─────────────────────────────────────────────────

    def _handle_war_games(self, event: pygame.event.Event) -> None:
        """Networked WAR_GAMES: each side controls only their own row."""
        if self._local_team_key == "both":
            # LOCAL mode — use base GameRunner's unrestricted handler
            super()._handle_war_games(event)
            return
        if event.type != pygame.MOUSEBUTTONDOWN:
            return
        if self._local_war_sent:        # already chose — ignore re-picks
            return
        cell = self._px_to_cell(*event.pos)
        if cell is None:
            return
        row, col = cell
        b = self._b

        # HOST controls row 3 (team_r); GUEST controls row 4 (team_l).
        # In physical_host mode the GUEST (Sim) picks BOTH rows on behalf of Pi.
        if self._local_team_key == "r" and row == 3:
            b.computer_player_r = col >= 4
            self._local_war_sent = True
            self._net_send({
                "type": "war_games_choice",
                "team_key": "r",
                "is_ai": bool(b.computer_player_r),
            })
            logger.info("Sent war_games_choice r ai=%s", b.computer_player_r)
            self._check_war_complete()

        elif self._local_team_key == "l" and row == 4:
            b.computer_player_l = col < 4
            self._local_war_sent = True
            self._net_send({
                "type": "war_games_choice",
                "team_key": "l",
                "is_ai": bool(b.computer_player_l),
            })
            logger.info("Sent war_games_choice l ai=%s", b.computer_player_l)
            self._check_war_complete()

        elif self._is_physical_host_mode and self._local_team_key == "l" and row == 3:
            # Physical-host mode: Sim GUEST picks row 3 on Pi's behalf
            b.computer_player_r = col >= 4
            self._net_send({
                "type": "war_games_choice",
                "team_key": "r",
                "is_ai": bool(b.computer_player_r),
            })
            logger.info("Physical-host: sent war_games_choice r ai=%s for Pi", b.computer_player_r)
            self._check_war_complete()

    # ── Overrides — PLAYING ───────────────────────────────────────────────────

    def _render_playing(self) -> None:
        """Extend base rendering with two networked-only visuals.

        1. Waiting animation: while it's the opponent's turn, pulse the checker
           pattern (same animation the base class uses during AI thinking) so the
           local player has a clear visual cue that they're waiting.

        2. Last-move blink: once the opponent's move lands, blink the destination
           square until the local player makes their own move, so it's easy to see
           what changed.
        """
        b = self._b

        if not self._is_my_turn() and not self._peer_disconnected:
            # Pulse checker while waiting for opponent — mirrors AI-thinking code
            b.canvas.Clear()
            b.checker_brightness += b.checker_brightness_dir
            if b.checker_brightness <= 0:
                b.checker_brightness_dir *= -1
                b.checker_brightness = 0
            elif b.checker_brightness >= 255:
                b.checker_brightness_dir *= -1
                b.checker_brightness = 255
            b.choose_light_checker_town()
            b.matrix.blit_to_screen()
            self._draw_piece_overlay()
            return

        # Normal rendering (my turn, or peer disconnected)
        super()._render_playing()

        # Clear blink as soon as the local player picks up a piece
        if self._selected_piece is not None:
            self._remote_last_move = None

        # Blink the opponent's last move on the pygame surface (on top of piece overlay)
        if self._remote_last_move is not None:
            fr, fc, tr, tc = self._remote_last_move
            screen = b.matrix._screen
            if screen is not None:
                remote = self._remote_team()
                color = (remote.r, remote.g, remote.b)
                # From square: always-on dim tint
                from_surf = pygame.Surface((_CELL_PX, _CELL_PX), pygame.SRCALPHA)
                from_surf.fill((*color, 55))
                screen.blit(from_surf, (fc * _CELL_PX, fr * _CELL_PX))
                # To square: pulsing border
                if (pygame.time.get_ticks() // 400) % 2:
                    pygame.draw.rect(screen, color,
                                     (tc * _CELL_PX, tr * _CELL_PX, _CELL_PX, _CELL_PX), 4)

    def _handle_game_over(self, event: pygame.event.Event) -> None:
        """N key broadcasts new_game to both sides then resets."""
        if event.type == pygame.KEYDOWN and event.key == pygame.K_n:
            self._new_game_local()
            return
        super()._handle_game_over(event)

    def _handle_playing(self, event: pygame.event.Event) -> None:
        """Block input during opponent's turn or while waiting for move_ack."""
        if event.type == pygame.KEYDOWN and event.key == pygame.K_n:
            self._new_game_local()
            return
        if not self._is_my_turn() or self._waiting_for_ack:
            return
        # Capture move info before applying
        if event.type == pygame.MOUSEBUTTONDOWN:
            cell = self._px_to_cell(*event.pos)
            if cell is not None and self._selected_piece is not None:
                tr, tc = cell
                b = self._b
                for target in self._selected_piece.targets:
                    if target.row == tr and target.col == tc:
                        fr = self._selected_piece.row
                        fc = self._selected_piece.col
                        pre_capture = b.grid[tr][tc]
                        flags = self._build_move_flags(
                            self._selected_piece, fr, fc, tr, tc, pre_capture)
                        self._pending_send_move = {
                            "fr": fr, "fc": fc, "tr": tr, "tc": tc,
                            "piece": type(self._selected_piece).__name__,
                            "captured": type(pre_capture).__name__ if pre_capture else None,
                            "flags": flags,
                        }
                        break
        # Let parent handle the actual move application + _next_turn call
        super()._handle_playing(event)

    def _next_turn(self) -> None:
        """After a local move, send it to the peer then call parent._next_turn."""
        if self._pending_send_move is not None:
            self._remote_last_move = None  # clear blink when local player moves
            pm = self._pending_send_move
            self._pending_send_move = None
            b = self._b
            assert self._current_team is not None
            # current_team is still the team that JUST moved (before parent swaps it)
            team_key = "r" if self._current_team.r == b.team_r.r else "l"
            # If a promotion just finished, the chosen piece is already on the board —
            # stamp its class name so the remote side can apply the same promotion.
            if pm["flags"].is_promotion:
                pm["flags"].promoted_to = type(b.grid[pm["tr"]][pm["tc"]]).__name__
            # In LOCAL mode there is no peer — skip network send and ack wait
            if self._local_team_key != "both":
                h = board_hash(b.grid, self.peace_time, team_key, b.team_r)
                self._net_seq += 1
                msg = build_move_msg(
                    self._net_seq,
                    pm["fr"], pm["fc"], pm["tr"], pm["tc"],
                    pm["piece"], pm["flags"], h,
                )
                self._net_send(msg)
                self._waiting_for_ack = True
            self._log_move(
                "You", pm["piece"],
                pm["fr"], pm["fc"], pm["tr"], pm["tc"],
                pm.get("captured"),
                promoted_to=pm["flags"].promoted_to,
            )
        super()._next_turn()

    def _begin_turn(self, team) -> None:
        """Only run AI for our own team; suppress it for the remote team."""
        super()._begin_turn(team)
        # In a real networked game (not LOCAL / spectator), each side only controls
        # its own team.  super()._begin_turn() may have set _ai_thinking=True because
        # the *remote* team happens to be AI-controlled, but we must not run that AI
        # locally — the remote instance will run it and send the resulting move.
        if self._local_team_key not in ("both", "spectator") and not self._is_my_turn():
            self._ai_thinking = False

    # ── Update ────────────────────────────────────────────────────────────────

    # ── Move logging ──────────────────────────────────────────────────────────

    _COLS = "abcdefgh"

    def _cell_str(self, row: int, col: int) -> str:
        return f"{self._COLS[col]}{8 - row}"

    def _log_move(
        self,
        who: str,
        piece_name: str,
        fr: int, fc: int,
        tr: int, tc: int,
        captured: Optional[str],
        promoted_to: Optional[str] = None,
    ) -> None:
        line = f"[{who}] {piece_name} {self._cell_str(fr, fc)}→{self._cell_str(tr, tc)}"
        if captured:
            line += f"  ×{captured}"
        if promoted_to:
            line += f"  ={promoted_to}"
        logger.info(line)

    # ── Update ────────────────────────────────────────────────────────────────

    def _update(self) -> None:
        """Drain incoming messages and apply remote moves when it's their turn."""
        self._drain_incoming()
        self._check_keepalive()

        # Update window title to reflect whose turn it is
        if self.phase == Phase.PLAYING and self._peer_name:
            if self._peer_disconnected:
                caption = f"Chess101 — {self._peer_name} disconnected"
            elif self._is_my_turn():
                caption = "Chess101 — Your turn"
            else:
                caption = f"Chess101 — {self._peer_name}'s turn"
            pygame.display.set_caption(caption)

        # Apply a pending remote move when it's the opponent's turn
        if (self.phase == Phase.PLAYING
                and not self._is_my_turn()
                and self._pending_remote_move is not None):
            self._apply_remote_move(self._pending_remote_move)
            self._pending_remote_move = None

        # Show disconnect overlay
        if self._peer_disconnected and self._disconnect_time_ms is None:
            self._disconnect_time_ms = pygame.time.get_ticks()
            logger.warning("Peer disconnected — showing overlay")

        # Once the reconnect countdown expires, attempt a relay reconnect in the background.
        if (self._peer_disconnected
                and not self._reconnect_attempted
                and not self._session_lost
                and self._relay_client is not None
                and self._disconnect_time_ms is not None):
            elapsed = (pygame.time.get_ticks() - self._disconnect_time_ms) // 1000
            if elapsed >= _RECONNECT_TIMEOUT_S:
                self._reconnect_attempted = True
                rc = self._relay_client
                def _attempt(rc=rc) -> None:
                    ok = rc.reconnect(timeout=15.0)
                    self._incoming.append({"type": "_reconnect_result", "ok": ok})
                threading.Thread(target=_attempt, daemon=True, name="RelayReconnect").start()

        # Intercept AI moves before the parent applies them so _next_turn() sends
        # the move to the peer.  _pending_send_move must be set before _next_turn()
        # is called inside super()._update().  The piece is still at old_r/old_c
        # at this point (super hasn't moved it yet), so _build_move_flags is valid.
        if (self.phase == Phase.PLAYING
                and self._is_my_turn()
                and self._ai_thinking
                and self._ai_thread is not None
                and not self._ai_thread.is_alive()):
            best = self._ai_result
            if best is not None and best.old_cell is not None and best.new_cell is not None:
                b = self._b
                old_r, old_c = best.old_cell.row, best.old_cell.col
                tgt_r, tgt_c = best.new_cell.row, best.new_cell.col
                piece = b.grid[old_r][old_c]
                if piece is not None:
                    pre_capture = b.grid[tgt_r][tgt_c]
                    flags = self._build_move_flags(
                        piece, old_r, old_c, tgt_r, tgt_c, pre_capture)
                    self._pending_send_move = {
                        "fr": old_r, "fc": old_c, "tr": tgt_r, "tc": tgt_c,
                        "piece": type(piece).__name__,
                        "captured": type(pre_capture).__name__ if pre_capture else None,
                        "flags": flags,
                    }

        super()._update()

    def _apply_remote_move(self, msg: dict) -> None:
        """Apply a remote move message to the local board.

        Validates it's the opponent's turn, applies the move via _apply_move,
        computes board_hash and sends move_ack, then advances to the next turn.
        """
        b = self._b
        fr = msg["from_row"]
        fc = msg["from_col"]
        tr = msg["to_row"]
        tc = msg["to_col"]

        # Validate turn
        if self._is_my_turn():
            logger.warning("Remote move received but it's my turn — ignoring")
            return
        if b.grid[fr][fc] is None:
            logger.warning("Remote move from empty square %d%d", fr, fc)
            return

        moving_name = type(b.grid[fr][fc]).__name__
        captured_name = type(b.grid[tr][tc]).__name__ if b.grid[tr][tc] else None

        # Update peace_time before moving (capture detection)
        flags = MoveFlags.from_dict(msg.get("flags", {}))
        if flags.is_capture or isinstance(b.grid[fr][fc], Pawn):
            self.peace_time = 0
        else:
            self.peace_time += 1

        b.grid[tr][tc] = b.grid[fr][fc]
        self._apply_move(fr, fc, tr, tc)
        self._move_count += 1

        # If the remote player promoted a pawn, apply their chosen piece directly
        # and suppress the local promotion picker (_promoting_pawn set by _apply_move).
        if flags.is_promotion and self._promoting_pawn is not None:
            from pieces.queen import Queen as _Queen
            from pieces.knight import Knight as _Knight
            from pieces.bishop import Bishop as _Bishop
            from pieces.rook import Rook as _Rook
            _promo_map: dict[str, type] = {
                "Queen": _Queen, "Knight": _Knight,
                "Bishop": _Bishop, "Rook": _Rook,
            }
            piece_name = flags.promoted_to or "Queen"
            cls = _promo_map.get(piece_name, _Queen)
            pawn = b.grid[tr][tc]
            if pawn is not None:
                b.grid[tr][tc] = cls(tr, tc, pawn.team)
            self._promoting_pawn = None

        # Compute local hash and compare
        assert self._current_team is not None
        team_key = "r" if self._current_team.r == b.team_r.r else "l"
        local_hash = board_hash(b.grid, self.peace_time, team_key, b.team_r)
        remote_hash = msg.get("board_hash", "")

        if local_hash == remote_hash:
            status = "ok"
        else:
            status = "desync"
            logger.warning("Hash mismatch after remote move seq=%d — requesting board_sync",
                           msg.get("seq", -1))

        self._net_send({
            "type": "move_ack",
            "seq": msg.get("seq", 0),
            "status": status,
        })

        if status == "desync":
            self._net_send({"type": "board_sync_request"})

        self._log_move(
            self._peer_name or "Them", moving_name,
            fr, fc, tr, tc,
            captured_name,
            promoted_to=flags.promoted_to if flags.is_promotion else None,
        )

        # Remember last remote move so _render_playing can blink the destination
        self._remote_last_move = (fr, fc, tr, tc)

        # Advance turn (this side becomes the next player)
        self._next_turn()

    def _check_keepalive(self) -> None:
        """Send ping every 10s; treat no pong in 30s as disconnect."""
        if not self._peer_connected:
            return
        now = time.time()
        if now - self._last_ping_s >= _PING_INTERVAL_S:
            self._last_ping_s = now
            self._net_send({"type": "ping", "seq": self._net_seq})
        if now - self._last_pong_s >= _PING_TIMEOUT_S:
            logger.warning("No pong in %.0fs — treating as disconnect", _PING_TIMEOUT_S)
            self._peer_disconnected = True
            self._last_pong_s = now + 1000  # prevent repeated triggers

    # ── Panel ─────────────────────────────────────────────────────────────────

    def _render_panel_extra(self, text, sep, pfont_sm, pfont_md) -> None:
        """Inject network status rows into the side panel."""
        from simulator.app import _P_DIM, _P_GOOD, _P_BAD, _P_WARN, _P_TEXT

        sep()

        _ROLE_LABELS = {
            NetworkRole.LOCAL:            "Local",
            NetworkRole.HOST:             "LAN Host",
            NetworkRole.GUEST:            "LAN Guest",
            NetworkRole.SPECTATOR:        "Spectating (LAN)",
            NetworkRole.ONLINE_HOST:      "Online Host",
            NetworkRole.ONLINE_GUEST:     "Online Guest",
            NetworkRole.ONLINE_SPECTATOR: "Spectating (Online)",
        }
        if self._is_physical_host_mode:
            role_label = "Network (Physical-host)"
        else:
            role_label = _ROLE_LABELS.get(self._role, self._role.name)
        text(f"Mode    {role_label}", pfont_md, _P_DIM)

        # Room code display for online host (share with opponent)
        if self._role == NetworkRole.ONLINE_HOST:
            sep()
            if self._connecting:
                text("Connecting to relay...", pfont_sm, _P_WARN)
            elif self._room_code:
                text("Share this code:", pfont_md, _P_TEXT)
                text(f"  {self._room_code}", pfont_md, _P_GOOD)
            sep()

        # Board-entry ChessMatrix hints
        if self.phase == Phase.CODE_SCAN_BOARD:
            sep()
            if self._cs.typing:
                text("Type room code:", pfont_md, _P_TEXT)
                display = self._room_code_input + "_" * (6 - len(self._room_code_input))
                text(f"  {display}", pfont_md, _P_GOOD)
                text("ESC: back to board", pfont_sm, _P_DIM)
            else:
                text("Board: click corners + cells", pfont_sm, _P_DIM)
                text("T: type code  C: camera", pfont_sm, _P_DIM)
                text("ESC: back to lobby", pfont_sm, _P_DIM)
            sep()

        # Room code entry hint (join online from lobby)
        if self._entering_room_code:
            sep()
            text("Enter room code:", pfont_md, _P_TEXT)
            display = self._room_code_input + "_" * (6 - len(self._room_code_input))
            text(f"  {display}", pfont_md, _P_GOOD)
            sep()

        if self._role == NetworkRole.LOCAL:
            return   # no peer info for local play

        if self.phase == Phase.PLAYING and self._role not in (
            NetworkRole.SPECTATOR, NetworkRole.ONLINE_SPECTATOR
        ):
            if self._peer_disconnected:
                pass   # shown below
            elif self._is_my_turn():
                text(">>> YOUR TURN <<<", pfont_md, _P_GOOD)
            else:
                text(f"Waiting for {self._peer_name or 'opponent'}...", pfont_sm, _P_DIM)

        if self._peer_name:
            bars = "●" * 4
            text(f"Peer    {self._peer_name}  {bars}", pfont_sm, _P_GOOD)
        elif self._peer_disconnected:
            text("Peer    DISCONNECTED", pfont_sm, _P_BAD)
            if self._session_lost:
                text("Session lost — relay restarted", pfont_sm, _P_BAD)
            elif self._reconnect_attempted:
                text("Reconnecting...", pfont_sm, _P_WARN)
            elif self._disconnect_time_ms is not None:
                elapsed = (pygame.time.get_ticks() - self._disconnect_time_ms) // 1000
                remaining = max(0, int(_RECONNECT_TIMEOUT_S) - elapsed)
                text(f"Waiting {remaining}s to reconnect...", pfont_sm, _P_WARN)
        else:
            text("Waiting for opponent...", pfont_sm, _P_DIM)

        if self._is_physical_host_mode:
            r_done = "✓" if self._physical_setup_r_complete else "…"
            l_done = "✓" if self._physical_setup_l_complete else "…"
            text(f"Pi setup  R:{r_done}  L:{l_done}", pfont_sm, _P_DIM)

    def _pre_flip(self) -> None:
        """Apply disconnect overlay before the display flip."""
        if self.phase != Phase.PLAYING or not self._peer_disconnected:
            return
        b = self._b
        screen = b.matrix._screen
        if screen is None:
            return
        overlay = pygame.Surface((_BOARD_W, 32 * _SCALE), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        screen.blit(overlay, (0, 0))

    # ── run() ─────────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Show name entry, then (on Enter) start networking and run the Pygame loop."""
        super().run()
        self._stop_network()

    def _start_network(self) -> None:
        """Create and start the server or client based on role."""
        if self._role == NetworkRole.LOCAL:
            return   # no networking for local play

        elif self._role == NetworkRole.HOST:
            self._server = GameServer(
                port=self._port,
                on_connected=self._on_connected,
                on_disconnected=self._on_disconnected,
            )
            self._server.set_message_handler(self._on_network_message)
            if not self._server.start():
                logger.error("Server failed to bind — check that port %d is free", self._port)
                return
            self._broadcaster = BeaconBroadcaster(
                host_name=self._player_name,
                port=self._port,
                state="lobby",
            )
            self._broadcaster.start()
            logger.info("Hosting on port %d — waiting for opponent", self._port)

        elif self._role in (NetworkRole.GUEST, NetworkRole.SPECTATOR):
            # Auto-discover host on LAN if no IP was provided
            if self._host_ip is None:
                logger.info("LAN: scanning for host...")
                from network.discovery import BeaconListener as _BL
                _listener = _BL()
                _listener.start()
                import time as _time
                deadline = _time.time() + 8.0
                while _time.time() < deadline and not _listener.games:
                    _time.sleep(0.25)
                for game in _listener.games.values():
                    self._host_ip = game.ip
                    break
                _listener.stop()
                if self._host_ip is None:
                    logger.error("No LAN host found — use --join IP to specify one")
                    return
            self._client = GameClient(
                host_ip=self._host_ip,
                port=self._port,
                on_connected=self._on_connected,
                on_disconnected=self._on_disconnected,
            )
            self._client.set_message_handler(self._on_network_message)
            connected = self._client.connect(timeout=10.0)
            if not connected:
                logger.error("Could not connect to %s:%d", self._host_ip, self._port)

        elif self._role == NetworkRole.ONLINE_HOST:
            self._connecting = True
            def _connect_host() -> None:
                relay = RelayClient(
                    relay_url=self._relay_url,
                    role="host",
                    player_name=self._player_name,
                    on_peer_connected=self._on_connected,
                    on_peer_disconnected=self._on_disconnected,
                )
                relay.set_message_handler(self._on_network_message)
                code = relay.create_room(timeout=60.0)
                if code:
                    logger.info("Online room created: %s — waiting for opponent", code)
                    self._incoming.append({"type": "_network_ready", "relay": relay, "room_code": code})
                else:
                    self._incoming.append({"type": "_network_failed"})
            threading.Thread(target=_connect_host, daemon=True, name="RelayConnect").start()

        elif self._role in (NetworkRole.ONLINE_GUEST, NetworkRole.ONLINE_SPECTATOR):
            self._connecting = True
            ws_role = "spectator" if self._role == NetworkRole.ONLINE_SPECTATOR else "guest"
            room = self._room_code or ""
            def _connect_guest(ws_role: str = ws_role, room: str = room) -> None:
                relay = RelayClient(
                    relay_url=self._relay_url,
                    role=ws_role,
                    player_name=self._player_name,
                    on_peer_connected=self._on_connected,
                    on_peer_disconnected=self._on_disconnected,
                )
                relay.set_message_handler(self._on_network_message)
                # Wire up _relay_client before join_room blocks so that any
                # inbound game messages (e.g. HOST's hello) that arrive
                # during the handshake can be responded to immediately.
                self._relay_client = relay
                ok = relay.join_room(room, timeout=60.0) if ws_role == "guest" else relay.spectate_room(room, timeout=60.0)
                if ok:
                    logger.info("Joined online room %s as %s", room, ws_role)
                    self._incoming.append({"type": "_network_ready", "relay": relay})
                else:
                    self._relay_client = None
                    self._incoming.append({"type": "_network_failed"})
            threading.Thread(target=_connect_guest, daemon=True, name="RelayConnect").start()

    def _stop_network(self) -> None:
        if self._server:
            self._server.stop()
        if self._client:
            self._client.stop()
        if self._relay_client:
            self._relay_client.stop()
        if self._broadcaster:
            self._broadcaster.stop()
        if self._listener:
            self._listener.stop()

    # ── ChessMatrix host display ───────────────────────────────────────────

    def _render_chessmatrix_waiting(self) -> None:
        """Paint the encoded ChessMatrix onto the LED canvas."""
        b = self._b
        b.canvas.Clear()
        if self._chessmatrix_grid is not None:
            try:
                _chessmatrix.render_to_led(self._chessmatrix_grid, b.canvas)
            except Exception as exc:
                logger.warning("ChessMatrix render failed: %s", exc)
        b.matrix.blit_to_screen()

    # ── Camera scanner (CODE_SCAN phase) ──────────────────────────────────

    def _close_camera(self) -> None:
        """Release the camera capture if it is open."""
        cap = self._cv_capture
        if cap is not None:
            try:
                cap.release()  # type: ignore[attr-defined]
            except Exception:
                pass
            self._cv_capture = None
        self._cv_last_frame = None

    def _handle_code_scan(self, event: pygame.event.Event) -> None:
        """Handle input during CODE_SCAN: ESC returns to lobby; manual fallback typing."""
        if event.type != pygame.KEYDOWN:
            return
        if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
            self._close_camera()
            self.phase = Phase.LOBBY
            return
        # Manual text fallback alongside camera (accepts alpha chars only)
        if event.unicode and event.unicode.isalpha() and len(self._room_code_input) < 6:
            self._room_code_input += event.unicode.upper()
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            code = self._room_code_input.upper().strip()
            if len(code) == 6 and code.isalpha():
                self._room_code = code
                self._close_camera()
                self._role = NetworkRole.ONLINE_GUEST
                self._local_team_key = "l"
                self.phase = Phase.NAME_ENTRY
                logger.info("Room code entered manually: %s", code)

    def _render_code_scan(self) -> None:
        """Render the camera feed; attempt ChessMatrix decode each frame."""
        from simulator.app import _BOARD_W

        screen = self._b.matrix._screen
        if screen is None:
            return

        cap = self._cv_capture
        if cap is not None and _CV2_AVAILABLE and _NP_AVAILABLE:
            ret, frame = cap.read()  # type: ignore[attr-defined]
            if ret and frame is not None:
                self._cv_last_frame = frame
                # Attempt decode
                try:
                    code = _chessmatrix.decode_frame(frame)
                    if code is not None:
                        self._room_code = code
                        self._close_camera()
                        self._role = NetworkRole.ONLINE_GUEST
                        self._local_team_key = "l"
                        self.phase = Phase.NAME_ENTRY
                        logger.info("ChessMatrix scanned: room code %s", code)
                        return
                except Exception as exc:
                    logger.debug("ChessMatrix decode attempt: %s", exc)

        # Render last captured frame (or black if no frame yet)
        board_px = 32 * _SCALE
        last = self._cv_last_frame
        if last is not None and _CV2_AVAILABLE and _NP_AVAILABLE:
            try:
                frame_rgb = _cv2.cvtColor(last, _cv2.COLOR_BGR2RGB)  # type: ignore[attr-defined]
                # pygame wants (width, height, 3) but numpy shape is (h, w, 3)
                surf = pygame.surfarray.make_surface(
                    _np.transpose(frame_rgb, (1, 0, 2)))  # type: ignore[attr-defined]
                surf_scaled = pygame.transform.scale(surf, (board_px, board_px))
                screen.blit(surf_scaled, (0, 0))
            except Exception:
                screen.fill((0, 0, 0), (0, 0, board_px, board_px))
        else:
            screen.fill((0, 0, 0), (0, 0, board_px, board_px))

    # ── CODE_SCAN_BOARD — board-entry ChessMatrix UX ──────────────────────
    # State is held in self._cs (CodeScanState). Phase logic is driven by
    # ScanPhase enum properties; timing constants live in chessmatrix module.

    def _handle_code_scan_board(self, event: "pygame.event.Event") -> None:
        """Handle input during CODE_SCAN_BOARD phase."""
        if event.type == pygame.KEYDOWN:
            if self._cs.typing:
                # ── Text-entry sub-mode: all keys go to the room code buffer ──
                if event.key == pygame.K_ESCAPE:
                    self._cs.typing = False
                    self._room_code_input = ""
                    return
                if event.key in (pygame.K_BACKSPACE, pygame.K_DELETE):
                    self._room_code_input = self._room_code_input[:-1]
                    return
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    code = self._room_code_input.upper().strip()
                    if len(code) == 6 and code.isalpha():
                        self._room_code = code
                        self._role = NetworkRole.ONLINE_GUEST
                        self._local_team_key = "l"
                        self._cs.typing = False
                        self.phase = Phase.NAME_ENTRY
                        logger.info("CODE_SCAN_BOARD: room code typed manually: %s", code)
                    return
                # Any alpha char (including C) goes into the buffer
                if event.unicode and event.unicode.isalpha() and len(self._room_code_input) < 6:
                    self._room_code_input += event.unicode.upper()
                return

            # ── Board-scan mode ──────────────────────────────────────────────
            if event.key == pygame.K_ESCAPE:
                self.phase = Phase.LOBBY
                return
            if event.key == pygame.K_t:
                self._cs.typing = True
                self._room_code_input = ""
                logger.info("CODE_SCAN_BOARD: entering keyboard text mode")
                return
            if event.key == pygame.K_c:
                # 'C' → camera fallback
                self._room_code_input = ""
                if _CV2_AVAILABLE:
                    self._close_camera()
                    cap = _cv2.VideoCapture(0)  # type: ignore[attr-defined]
                    if cap.isOpened():
                        self._cv_capture = cap
                        self.phase = Phase.CODE_SCAN
                        logger.info("CODE_SCAN_BOARD: switching to camera scanner")
                        return
                    cap.release()
                logger.info("CODE_SCAN_BOARD: camera unavailable")
                return

        if event.type != pygame.MOUSEBUTTONDOWN:
            return

        cell = self._px_to_cell(*event.pos)
        if cell is None:
            return
        row, col = cell

        phase  = _chessmatrix.ScanPhase(self._cs.phase)
        corner = phase.corner
        now_t  = time.monotonic()

        if phase.is_wait:
            if (row, col) == corner:
                self._cs.phase         = phase.value.replace("_wait", "_active")
                self._cs.pending       = set()
                self._cs.last_activity = now_t
                logger.info("CODE_SCAN_BOARD: %s corner clicked — entry active",
                            phase.color.name.lower())

        elif phase.is_active:
            if (row, col) == corner:
                self._cs.phase      = phase.value.replace("_active", "_fading")
                self._cs.fade_start = now_t
                logger.info("CODE_SCAN_BOARD: %s corner removed — 3 s fade started",
                            phase.color.name.lower())
            elif (row, col) in _chessmatrix.DATA_CELLS:
                if (row, col) in self._cs.pending:
                    self._cs.pending.discard((row, col))
                    self._cs.excite_times.pop((row, col), None)
                else:
                    self._cs.pending.add((row, col))
                    self._cs.excite_times[(row, col)] = now_t
                self._cs.last_activity = now_t

        elif phase.is_fading:
            if (row, col) == corner:
                self._cs.phase         = phase.value.replace("_fading", "_active")
                self._cs.fade_start    = None
                self._cs.last_activity = now_t
                logger.info("CODE_SCAN_BOARD: %s fade cancelled — back to active",
                            phase.color.name.lower())

    def _cs_commit_and_advance(self) -> None:
        """Commit the current pending cells and advance to the next phase."""
        phase = _chessmatrix.ScanPhase(self._cs.phase)
        committed_color = int(phase.color)
        for cell in self._cs.pending:
            self._cs.locked[cell] = committed_color
        logger.info(
            "CODE_SCAN_BOARD: %s locked in (%d cells) → %s",
            phase.color.name.lower(),
            sum(1 for v in self._cs.locked.values() if v == committed_color),
            phase.next_phase.value,
        )
        self._cs.phase      = phase.next_phase
        self._cs.pending    = set()
        self._cs.fade_start = None

    def _render_code_scan_board(self) -> None:
        """Render the board-entry ChessMatrix screen with raster beam animation."""
        now = time.monotonic()

        # Advance fading phase when the corner fade completes
        if _chessmatrix.ScanPhase(self._cs.phase).is_fading:
            elapsed = now - (self._cs.fade_start or 0.0)
            if elapsed >= _chessmatrix._CORNER_FADE_S:
                self._cs_commit_and_advance()
                if self._cs.phase == _chessmatrix.ScanPhase.DECODING:
                    self._cs_do_decode()
                    return

        b = self._b
        b.canvas.Clear()
        params = _chessmatrix.BeamRenderParams.from_scan_state(self._cs, now)
        _chessmatrix.render_beam_frame_from_params(b.canvas, params)
        b.matrix.blit_to_screen()

    def _cs_do_decode(self) -> None:
        """Decode the entered cell state; on success connect to relay, on failure flash error."""
        try:
            import chessmatrix as _cm  # type: ignore[import]
            grid = _chessmatrix.grid_from_cell_state(self._cs.locked)
            data = _cm.decode(grid)
            room_code = _chessmatrix.bytes_to_room_code(data)
        except Exception as exc:
            logger.warning("CODE_SCAN_BOARD: decode failed — %s", exc)
            self._cs_run_error_flash()
            return

        logger.info("CODE_SCAN_BOARD: decoded room code %s", room_code)
        self._room_code = room_code
        self._role = NetworkRole.ONLINE_GUEST
        self._local_team_key = "l"
        self.phase = Phase.NAME_ENTRY

    def _cs_run_error_flash(self) -> None:
        """Flash all 32 data cells red/white 3× then restart from red_wait."""
        import time as _time
        b = self._b
        screen = b.matrix._screen

        _FLASH_COLORS = [(255, 0, 0), (200, 200, 200)]
        for _ in range(3):
            for rgb in _FLASH_COLORS:
                b.canvas.Clear()
                _chessmatrix.render_border_only(b.canvas)
                for row, col in _chessmatrix.DATA_CELLS:
                    _chessmatrix._set_cell(b.canvas, row, col, *rgb)
                b.matrix.blit_to_screen()
                if screen is not None:
                    pygame.display.flip()
                _time.sleep(0.12)

        # Reset to red_wait
        self._cs.reset()
        logger.info("CODE_SCAN_BOARD: restarting entry after decode error")

    # ── _render override ───────────────────────────────────────────────────

    def _render(self) -> None:
        """Extend base render to handle ChessMatrix host display and CODE_SCAN."""
        from simulator.app import _P_DIM, _P_TEXT, _P_WARN, _BOARD_W

        # HOST waiting for peer: show ChessMatrix instead of game board
        if (self._role == NetworkRole.ONLINE_HOST
                and self._chessmatrix_grid is not None
                and not self._peer_connected):
            self._render_chessmatrix_waiting()
            self._render_panel()
            self._pre_flip()
            pygame.display.flip()
            return

        super()._render()
