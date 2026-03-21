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

from core.team import Team
from network.client import GameClient
from network.discovery import BeaconBroadcaster, BeaconListener
from network.protocol import MoveFlags, board_hash, build_move_msg, decode_grid, encode_grid
from network.server import GameServer
from pieces.king import King
from pieces.pawn import Pawn
from simulator.app import GameRunner, Phase, _COLOR_NAMES, _BOARD_W, _SCALE

logger = logging.getLogger(__name__)

_PROTOCOL_VERSION = "1"
_PING_INTERVAL_S = 10.0
_PING_TIMEOUT_S  = 30.0
_RECONNECT_TIMEOUT_S = 60.0


class NetworkRole(Enum):
    """Which side of the connection this instance occupies."""
    HOST      = auto()
    GUEST     = auto()
    SPECTATOR = auto()


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
    ) -> None:
        self._role = role
        self._host_ip = host_ip
        self._port = port
        self._player_name = player_name

        # Network objects (created in run())
        self._server: Optional[GameServer] = None
        self._client: Optional[GameClient] = None
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

        # HOST controls team_r (key "r"), GUEST controls team_l (key "l"),
        # SPECTATOR has no team so _is_my_turn() always returns False.
        self._local_team_key = (
            "r" if role == NetworkRole.HOST else
            "spectator" if role == NetworkRole.SPECTATOR else
            "l"
        )

        # Physical-host mode: Pi is HOST and Sim drives setup for both teams.
        self._is_physical_host_mode = False
        # Pi physical setup progress (populated by setup_status messages).
        self._physical_setup_r_complete = False
        self._physical_setup_l_complete = False

        # Call parent AFTER setting our attrs so _reset() can reference them
        super().__init__(skip_lobby=True)

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
        super()._reset()

    def _net_send(self, msg: dict) -> None:
        """Send a message over the active connection (thread-safe)."""
        if self._server:
            self._server.send(msg)
        elif self._client:
            self._client.send(msg)

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
            "game_event":        self._on_game_event,
            "setup_status":      self._on_setup_status,
            "ping":              self._on_ping,
            "pong":              self._on_pong,
            "error":             self._on_error,
            "_peer_lost":        self._on_peer_lost,
            "new_game":          self._on_new_game,
        }
        handler = handlers.get(t)
        if handler:
            handler(msg)
        else:
            logger.debug("Unknown message type: %r", t)

    def _local_team(self) -> Team:
        return self._b.team_r if self._local_team_key == "r" else self._b.team_l

    def _remote_team(self) -> Team:
        return self._b.team_l if self._local_team_key == "r" else self._b.team_r

    def _is_my_turn(self) -> bool:
        if self._current_team is None:
            return False
        return self._current_team.r == self._local_team().r

    # ── Connection callbacks (called from network thread) ─────────────────────

    def _on_connected(self) -> None:
        """Peer connected — send hello."""
        self._peer_connected = True
        self._net_send({
            "type": "hello",
            "version": _PROTOCOL_VERSION,
            "player_name": self._player_name,
            "role": self._role.name.lower(),
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

    def _on_new_game(self, msg: dict) -> None:  # noqa: ARG002
        """Peer pressed N — reset without re-broadcasting."""
        self._reset()
        self._init_board()
        logger.info("New game triggered by peer")

    def _new_game_local(self) -> None:
        """Local player pressed N — broadcast then reset."""
        self._net_send({"type": "new_game"})
        self._reset()
        self._init_board()

    def _on_hello(self, msg: dict) -> None:
        remote_ver = msg.get("version", "")
        if remote_ver != _PROTOCOL_VERSION:
            logger.error("Version mismatch: remote=%r local=%r", remote_ver, _PROTOCOL_VERSION)
            self._net_send({"type": "error", "code": "version_mismatch"})
            return
        self._peer_name = msg.get("player_name", "Opponent")
        self._peer_disconnected = False   # clear any stale flag from handshake hiccup
        self._disconnect_time_ms = None
        peer_role = msg.get("role", "guest")
        logger.info("Hello from %r (role=%s)", self._peer_name, peer_role)

        if self._role == NetworkRole.HOST:
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
            else:
                self._net_send({
                    "type": "game_setup",
                    "version": _PROTOCOL_VERSION,
                    "host_name": self._player_name,
                    "guest_name": self._peer_name,
                })
                self.phase = Phase.COLOR_PICK
                logger.info("Sent game_setup — advancing to COLOR_PICK")

    def _on_game_setup(self, msg: dict) -> None:
        """GUEST or SPECTATOR receives game_setup."""
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
        if self._role == NetworkRole.HOST:
            logger.info("Both war_games choices received — sending game_start")
            self._net_send({"type": "game_start"})
            self._start_game()
        # GUEST waits for game_start message

    def _on_game_start(self, msg: dict) -> None:
        """GUEST receives game_start → begin the game."""
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
            logger.debug("move_ack ok seq=%d", msg.get("seq", -1))
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

    # ── Board sync helper ──────────────────────────────────────────────────────

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
        if event.type != pygame.MOUSEBUTTONDOWN:
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
        if event.type != pygame.MOUSEBUTTONDOWN:
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
                            "flags": flags,
                        }
                        break
        # Let parent handle the actual move application + _next_turn call
        super()._handle_playing(event)

    def _next_turn(self) -> None:
        """After a local move, send it to the peer then call parent._next_turn."""
        if self._pending_send_move is not None:
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
            h = board_hash(b.grid, self.peace_time, team_key, b.team_r)
            self._net_seq += 1
            msg = build_move_msg(
                self._net_seq,
                pm["fr"], pm["fc"], pm["tr"], pm["tc"],
                pm["piece"], pm["flags"], h,
            )
            self._net_send(msg)
            self._waiting_for_ack = True
            logger.debug("Sent move seq=%d %d%d→%d%d", self._net_seq, pm["fr"], pm["fc"], pm["tr"], pm["tc"])
        super()._next_turn()

    # ── Update ────────────────────────────────────────────────────────────────

    def _update(self) -> None:
        """Drain incoming messages and apply remote moves when it's their turn."""
        self._drain_incoming()
        self._check_keepalive()

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
        if self._role == NetworkRole.SPECTATOR:
            role_label = "Spectating"
        elif self._is_physical_host_mode:
            role_label = "Network (Physical-host)"
        else:
            role_label = f"Network ({self._role.name.capitalize()})"
        text(f"Mode    {role_label}", pfont_md, _P_DIM)

        if self.phase == Phase.PLAYING and self._role != NetworkRole.SPECTATOR:
            if self._peer_disconnected:
                pass   # shown below
            elif self._is_my_turn():
                text(">>> YOUR TURN <<<", pfont_md, _P_GOOD)
            else:
                text(f"Waiting for {self._peer_name or 'opponent'}...", pfont_sm, _P_DIM)

        if self._peer_name:
            bars = "●" * 4   # static for now; could use ping RTT in future
            text(f"Peer    {self._peer_name}  {bars}", pfont_sm, _P_GOOD)
        elif self._peer_disconnected:
            text("Peer    DISCONNECTED", pfont_sm, _P_BAD)
            if self._disconnect_time_ms is not None:
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
        """Apply board overlay before the single display flip each frame.

        Bright board  = it is your turn.
        Light dim     = waiting for the opponent's move.
        Heavy dim     = opponent disconnected.
        """
        if self.phase != Phase.PLAYING:
            return
        b = self._b
        screen = b.matrix._screen
        if screen is None:
            return

        if self._peer_disconnected:
            alpha = 140   # heavy: disconnected
        elif self._role != NetworkRole.SPECTATOR and not self._is_my_turn():
            alpha = 70    # light: waiting for opponent
        else:
            return        # board stays bright — it is your turn

        overlay = pygame.Surface((_BOARD_W, 32 * _SCALE), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, alpha))
        screen.blit(overlay, (0, 0))

    # ── run() ─────────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Start the network connection, then hand off to the parent Pygame loop."""
        self._start_network()
        super().run()
        self._stop_network()

    def _start_network(self) -> None:
        """Create and start the server or client based on role."""
        if self._role == NetworkRole.HOST:
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
            assert self._host_ip is not None, "host_ip required for GUEST/SPECTATOR"
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
            # Listener for Lobby panel
            self._listener = BeaconListener()
            self._listener.start()

    def _stop_network(self) -> None:
        if self._server:
            self._server.stop()
        if self._client:
            self._client.stop()
        if self._broadcaster:
            self._broadcaster.stop()
        if self._listener:
            self._listener.stop()
