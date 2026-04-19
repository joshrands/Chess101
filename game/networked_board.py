"""NetworkedBoard — Board subclass for Pi-hosted networked games.

Wraps the existing physical-board game loop with WebSocket transport so a
Raspberry Pi can play against a Mac simulator (or another Pi) over LAN.

Role assignments
~~~~~~~~~~~~~~~~
- HOST  → controls ``team_r`` (rows 0–1, back rank at the top of the board).
- GUEST → controls ``team_l`` (rows 6–7).

Setup flow (Sim-as-UI, Option B from the design doc)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. Pi starts its WebSocket server and waits.
2. The connecting simulator sends ``hello``.
3. Pi responds with ``game_setup`` (``mode: "physical_host"``).
4. Sim drives COLOR_PICK and WAR_GAMES for *both* teams, sending
   ``color_chosen`` and ``war_games_choice`` messages for each.
5. Pi (HOST) collects all four messages and sends ``game_start``.
6. Pi runs ``interactive_setup`` for both teams (physical reed-switch
   detection).  Progress is reported via ``setup_status`` messages.
7. Sim signals ``setup_complete`` when its side is ready.
8. Pi waits for ``setup_complete`` from the Sim, then starts the game loop.

Turn loop
~~~~~~~~~
- Local team's turn  → ``do_turn()`` (existing physical logic) plus the
  ``_on_local_move`` hook, which sends the move and waits for ``move_ack``.
- Remote team's turn → ``_wait_for_remote_move()`` blocks until a ``move``
  message arrives, applies it, and sends ``move_ack`` back.
"""
from __future__ import annotations

import collections
import copy
import logging
import threading
import time
from typing import TYPE_CHECKING, Optional

from game.board import Board
from network.protocol import (
    MoveFlags,
    board_hash,
    build_move_msg,
    encode_grid,
)
from pieces.king import King
from pieces.pawn import Pawn

if TYPE_CHECKING:
    from network.client import GameClient
    from network.relay_client import RelayClient
    from network.server import GameServer

logger = logging.getLogger(__name__)

_ACK_TIMEOUT_S    = 30.0   # seconds to wait for move_ack before declaring disconnect
_REMOTE_TIMEOUT_S = 300.0  # 5 minutes for the opponent to move before timeout
_SETUP_TIMEOUT_S  = 300.0  # 5 minutes for physical setup before timeout


class NetworkedBoard(Board):
    """Board subclass that transmits moves over a WebSocket connection.

    Args:
        net: An active ``GameServer`` or ``GameClient`` instance.
        local_team_key: ``"r"`` if this Pi is HOST (team_r), ``"l"`` if GUEST
            (team_l).
    """

    def __init__(
        self,
        net: "GameServer | GameClient | RelayClient",
        local_team_key: str = "r",
        relay: "RelayClient | None" = None,
        *args,
        **kwargs,
    ) -> None:
        # Store network attrs before super().__init__ so Board.__init__ can
        # access them if needed.
        self._net = net
        self._local_team_key = local_team_key
        # Relay client for online play (HOST: already has room code;
        # GUEST: will call join_room inside _chessmatrix_input_ux)
        self._relay: "RelayClient | None" = relay

        self._net_lock = threading.Lock()
        self._incoming: collections.deque = collections.deque()

        # Events used to synchronise the blocking run() flow.
        self._config_received  = threading.Event()
        self._game_start_evt   = threading.Event()
        self._remote_setup_evt = threading.Event()
        self._move_ack_evt     = threading.Event()

        # Config received from Sim-as-UI
        self._remote_team_r_color_idx: Optional[int] = None
        self._remote_team_l_color_idx: Optional[int] = None
        self._remote_team_r_is_ai: Optional[bool]    = None
        self._remote_team_l_is_ai: Optional[bool]    = None

        # Move protocol
        self._net_seq = 0
        self._pending_remote_move: Optional[dict] = None
        self._last_move_ack_status: str = "ok"

        # Peer info
        self._peer_name: Optional[str] = None

        # Pending end-game animation from remote game_event
        self._pending_game_event: Optional[tuple] = None

        # Keepalive
        self._keepalive_stop = threading.Event()
        self._ping_seq = 0

        super().__init__(*args, **kwargs)
        self._net.set_message_handler(self._on_network_message)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _net_send(self, msg: dict) -> None:
        """Send over the active connection (thread-safe)."""
        self._net.send(msg)

    def _local_team(self):
        return self.team_r if self._local_team_key == "r" else self.team_l

    def _remote_team(self):
        return self.team_l if self._local_team_key == "r" else self.team_r

    # ── Network message handling ───────────────────────────────────────────────

    def _on_network_message(self, msg: dict) -> None:
        """Called from network daemon thread — queue for main-thread processing.

        Pings are answered immediately (from the network thread) so the sim's
        keepalive never times out even when the main thread is blocked waiting
        for physical piece movement.
        """
        if msg.get("type") == "ping":
            self._net_send({"type": "pong", "seq": msg.get("seq", 0)})
            return
        with self._net_lock:
            self._incoming.append(msg)

    def _drain_incoming(self) -> None:
        """Process all queued messages on the calling (main) thread."""
        with self._net_lock:
            batch = list(self._incoming)
            self._incoming.clear()
        for msg in batch:
            self._dispatch(msg)

    def _dispatch(self, msg: dict) -> None:
        handlers = {
            "hello":            self._on_hello,
            "color_chosen":     self._on_color_chosen,
            "war_games_choice": self._on_war_games_choice,
            "game_start":       self._on_game_start,
            "move":             self._on_remote_move,
            "move_ack":         self._on_move_ack,
            "setup_complete":   self._on_remote_setup_complete,
            "board_sync_request": self._on_board_sync_request,
            "board_sync":       self._on_board_sync,
            "game_event":       self._on_game_event,
            "ping":             self._on_ping,
        }
        handler = handlers.get(msg.get("type", ""))
        if handler:
            handler(msg)
        else:
            logger.debug("Unknown message type: %r", msg.get("type"))

    # ── Connection callbacks (called from network thread) ─────────────────────

    def on_connected(self) -> None:
        """Peer connected — send hello and (if HOST) send game_setup."""
        self._peer_name = None
        self._net_send({
            "type": "hello",
            "version": "1",
            "player_name": "Pi",
        })
        logger.info("Peer connected — sent hello")

    def on_disconnected(self) -> None:
        """Peer disconnected."""
        logger.warning("Peer disconnected")
        with self._net_lock:
            self._incoming.append({"type": "_peer_lost"})

    # ── Message handlers ───────────────────────────────────────────────────────

    def _on_hello(self, msg: dict) -> None:
        self._peer_name = msg.get("player_name", "Opponent")
        logger.info("Hello from %r", self._peer_name)
        if self._local_team_key == "r":
            # Pi is HOST — send game_setup with physical_host mode
            self._net_send({
                "type": "game_setup",
                "version": "1",
                "host_name": "Pi",
                "guest_name": self._peer_name,
                "mode": "physical_host",
            })
            logger.info("Sent game_setup (physical_host mode)")

    def _on_color_chosen(self, msg: dict) -> None:
        team_key   = msg.get("team_key")
        color_idx  = msg.get("color_idx")
        if color_idx is None or team_key is None:
            return
        t = self.team_array[color_idx]
        if team_key == "r":
            self.team_r.r, self.team_r.g, self.team_r.b = t.r, t.g, t.b
            self.team_r.name = t.name
            self._remote_team_r_color_idx = color_idx
        else:
            self.team_l.r, self.team_l.g, self.team_l.b = t.r, t.g, t.b
            self.team_l.name = t.name
            self._remote_team_l_color_idx = color_idx
        logger.info("Color chosen: team=%s idx=%d", team_key, color_idx)
        self._check_config_complete()

    def _on_war_games_choice(self, msg: dict) -> None:
        team_key = msg.get("team_key")
        is_ai    = msg.get("is_ai", False)
        if team_key == "r":
            self.computer_player_r = is_ai
            self._remote_team_r_is_ai = is_ai
        else:
            self.computer_player_l = is_ai
            self._remote_team_l_is_ai = is_ai
        logger.info("War games choice: team=%s ai=%s", team_key, is_ai)
        self._check_config_complete()

    def _check_config_complete(self) -> None:
        """Signal _config_received once all four setup messages have arrived."""
        if self._config_received.is_set():
            return
        if (
            self._remote_team_r_color_idx is not None
            and self._remote_team_l_color_idx is not None
            and self._remote_team_r_is_ai    is not None
            and self._remote_team_l_is_ai    is not None
        ):
            # Apply BUG-02 lock-in: mirrors local-play behaviour
            self.team_r.r += 1
            self._config_received.set()
            logger.info("Configuration complete — ready for interactive_setup")

    def _on_game_start(self, msg: dict) -> None:
        """GUEST receives game_start from HOST (unusual in physical_host mode,
        but Pi as GUEST would receive this from a Sim HOST)."""
        logger.info("Received game_start")
        self._game_start_evt.set()

    def _on_remote_move(self, msg: dict) -> None:
        self._pending_remote_move = msg

    def _on_move_ack(self, msg: dict) -> None:
        self._last_move_ack_status = msg.get("status", "ok")
        self._move_ack_evt.set()
        if self._last_move_ack_status == "desync":
            logger.warning("Desync at seq=%d — sending board_sync", msg.get("seq", -1))
            self._send_board_sync()

    def _on_remote_setup_complete(self, msg: dict) -> None:
        logger.info("Remote setup complete")
        self._remote_setup_evt.set()

    def _on_board_sync(self, msg: dict) -> None:
        from network.protocol import decode_grid
        logger.warning("Applying board_sync from peer")
        decoded = decode_grid(msg["grid"], self.team_r, self.team_l)
        for r in range(8):
            for c in range(8):
                self.grid[r][c] = decoded[r][c]
        self.peace_time = msg.get("peace_time", self.peace_time)

    def _on_game_event(self, msg: dict) -> None:
        event = msg.get("event")
        losing_key = msg.get("losing_team_key", "")
        logger.info("Remote game_event: %s (losing=%s)", event, losing_key)
        if event == "checkmate":
            self.game_over = True
            losing_team = self.team_r if losing_key == "r" else self.team_l
            self._pending_game_event = ("checkmate", losing_team)
        elif event == "stalemate":
            self.game_over = True
            self._pending_game_event = ("stalemate", None)

    def _on_ping(self, msg: dict) -> None:
        self._net_send({"type": "pong", "seq": msg.get("seq", 0)})

    def _start_keepalive(self) -> None:
        """Start a daemon thread that sends ping every 10s."""
        def _keepalive_loop():
            while not self._keepalive_stop.is_set():
                self._ping_seq += 1
                self._net_send({"type": "ping", "seq": self._ping_seq})
                self._keepalive_stop.wait(10.0)
        t = threading.Thread(target=_keepalive_loop, daemon=True, name="Keepalive")
        t.start()

    def _stop_keepalive(self) -> None:
        self._keepalive_stop.set()

    def _on_board_sync_request(self, msg: dict) -> None:
        logger.warning("Board sync requested by peer")
        self._send_board_sync()

    def _send_board_sync(self) -> None:
        team_key = "r" if self._local_team_key == "r" else "l"
        self._net_send({
            "type": "board_sync",
            "grid": encode_grid(self.grid, self.team_r),
            "peace_time": self.peace_time,
            "current_team_key": team_key,
        })

    # ── Waiting animation ──────────────────────────────────────────────────────

    def _run_waiting_animation(self) -> None:
        """Chase a light around the board edges until a peer connects.

        Three phases:
        1. CHASE  — single cyan beam circles the perimeter until connection.
        2. CONVERGE — orange counter-beam spawns; both ease-in accelerate to
           collision on the opposite side.
        3. FLASH + EXPLODE — full-board white flash, then an energetic
           shockwave expands from the collision revealing the checkerboard.
        """
        import math

        # Build the edge path: top row L→R, right col T→B, bottom row R→L, left col B→T
        edge_cells: list[tuple[int, int]] = []
        for c in range(8):
            edge_cells.append((0, c))       # top edge
        for r in range(1, 8):
            edge_cells.append((r, 7))       # right edge
        for c in range(6, -1, -1):
            edge_cells.append((7, c))       # bottom edge
        for r in range(6, 0, -1):
            edge_cells.append((r, 0))       # left edge

        n = len(edge_cells)
        TAIL_LEN = 6

        def _draw_dim_checker() -> None:
            for r in range(8):
                for c in range(8):
                    shade = 12 if (r + c) % 2 == 0 else 6
                    self.light_cell(self.canvas, r, c, shade, shade, shade)

        def _draw_beam_colored(pos: int, direction: int,
                               color: tuple[int, int, int]) -> None:
            """Draw a beam head + fading tail with the given *color*."""
            cr, cg, cb = color
            for i in range(TAIL_LEN):
                idx = (pos - i * direction) % n
                r, c = edge_cells[idx]
                frac = ((TAIL_LEN - i) / TAIL_LEN) ** 2
                self.light_cell(self.canvas, r, c,
                                int(cr * frac), int(cg * frac), int(cb * frac))

        CYAN = (64, 255, 255)
        ORANGE = (255, 160, 0)

        # ── Phase 1: CHASE ────────────────────────────────────────────────
        step = 0
        while self._peer_name is None:
            self._drain_incoming()
            self.canvas.Clear()
            _draw_dim_checker()
            _draw_beam_colored(step, 1, CYAN)
            self.canvas = self.matrix.SwapOnVSync(self.canvas)
            step = (step + 1) % n
            time.sleep(0.06)

        # ── Phase 2: CONVERGE ─────────────────────────────────────────────
        # Both beams carry the chase beam's initial speed and accelerate
        # into the collision point.
        spawn_pos = step
        collision_pos = (spawn_pos + n // 2) % n
        half_n = n // 2  # distance each beam must travel

        # The chase beam moves 1 cell / 0.06s.  Express initial velocity as
        # a fraction of half_n per second so the motion is continuous:
        #   v0 = (1 / 0.06) / half_n  ≈  16.7 / 14  ≈  1.19  (in normalised units/s)
        # We want progress(T) = v0*T + a*T² = 1.0, solving for T with a chosen
        # acceleration.  Using T = 0.9 s:
        #   a = (1 - v0*T) / T²
        CONVERGE_DURATION = 0.9
        chase_speed = 1.0 / 0.06            # cells per second
        v0 = chase_speed / half_n            # normalised velocity (fraction of half_n per s)
        accel = (1.0 - v0 * CONVERGE_DURATION) / (CONVERGE_DURATION ** 2)

        FRAME_DT = 0.02
        start_time = time.monotonic()

        while True:
            self._drain_incoming()
            elapsed = time.monotonic() - start_time
            t = min(elapsed, CONVERGE_DURATION)

            # progress = v0*t + a*t²  (carries initial speed, then accelerates)
            progress = min(v0 * t + accel * t * t, 1.0)
            fwd_cells = int(progress * half_n)
            rev_cells = int(progress * half_n)

            self.canvas.Clear()
            _draw_dim_checker()
            fwd_pos = (spawn_pos + fwd_cells) % n
            rev_pos = (spawn_pos - rev_cells) % n
            _draw_beam_colored(fwd_pos, 1, CYAN)
            _draw_beam_colored(rev_pos, -1, ORANGE)
            self.canvas = self.matrix.SwapOnVSync(self.canvas)

            if progress >= 1.0:
                break
            time.sleep(FRAME_DT)

        # ── Phase 3: FLASH + EXPLODE ──────────────────────────────────────
        collision_r, collision_c = edge_cells[collision_pos]

        # --- single-frame white flash across the entire board ---
        self.canvas.Clear()
        for r in range(8):
            for c in range(8):
                self.light_cell(self.canvas, r, c, 255, 255, 255)
        self.canvas = self.matrix.SwapOnVSync(self.canvas)
        time.sleep(0.06)

        # --- shockwave explosion ---
        # Precompute Euclidean distance from collision for every cell
        # (Euclidean gives a rounder, more energetic-looking wavefront)
        distances: list[list[float]] = []
        max_dist = 0.0
        for r in range(8):
            row_dists: list[float] = []
            for c in range(8):
                d = math.sqrt((r - collision_r) ** 2 + (c - collision_c) ** 2)
                row_dists.append(d)
                if d > max_dist:
                    max_dist = d
            distances.append(row_dists)

        # Precompute which cells are lit in the standard checkerboard
        checker_lit: list[list[bool]] = [[False] * 8 for _ in range(8)]
        for x in range(4):
            for y in range(4):
                checker_lit[1 + 2 * x][2 * y] = True
        for x in range(4):
            for y in range(4):
                checker_lit[2 * x][1 + 2 * y] = True

        checker_color = getattr(self, "theme_checker_color", (255, 255, 255))

        EXPAND_SPEED = 14.0    # cells per second
        WAVEFRONT_WIDTH = 2.5  # cells wide — fat, energetic ring
        AFTERGLOW_WIDTH = 1.5  # secondary trailing glow behind the front
        GAP_WIDTH = 1.0        # dark gap between afterglow and checkerboard
        start_time = time.monotonic()

        while True:
            elapsed = time.monotonic() - start_time
            radius = elapsed * EXPAND_SPEED

            total_trail = WAVEFRONT_WIDTH + AFTERGLOW_WIDTH + GAP_WIDTH
            if radius > max_dist + total_trail:
                break  # fully revealed

            self.canvas.Clear()
            for r in range(8):
                for c in range(8):
                    d = distances[r][c]
                    front_edge = radius + WAVEFRONT_WIDTH / 2
                    back_edge = radius - WAVEFRONT_WIDTH / 2
                    afterglow_edge = back_edge - AFTERGLOW_WIDTH
                    gap_edge = afterglow_edge - GAP_WIDTH

                    if d > front_edge:
                        # Ahead of wavefront: dim checker background
                        shade = 12 if (r + c) % 2 == 0 else 6
                        self.light_cell(self.canvas, r, c, shade, shade, shade)
                    elif d > back_edge:
                        # Primary wavefront: hot white core
                        t = 1.0 - (d - back_edge) / WAVEFRONT_WIDTH
                        # Bell-curve intensity — brightest at center of band
                        intensity = math.sin(t * math.pi)
                        gr = int(255 * intensity)
                        gg = int(255 * intensity)
                        gb = int(240 * intensity)
                        if checker_lit[r][c]:
                            cr_, cg_, cb_ = checker_color
                            self.light_cell(self.canvas, r, c,
                                            max(gr, cr_), max(gg, cg_), max(gb, cb_))
                        else:
                            self.light_cell(self.canvas, r, c, gr, gg, gb)
                    elif d > afterglow_edge:
                        # Afterglow: warm orange fade trailing the front
                        t = (d - afterglow_edge) / AFTERGLOW_WIDTH
                        glow_r = int(180 * t)
                        glow_g = int(100 * t)
                        glow_b = int(50 * t)
                        if checker_lit[r][c]:
                            cr_, cg_, cb_ = checker_color
                            self.light_cell(self.canvas, r, c,
                                            max(glow_r, cr_), max(glow_g, cg_),
                                            max(glow_b, cb_))
                        else:
                            self.light_cell(self.canvas, r, c,
                                            glow_r, glow_g, glow_b)
                    elif d > gap_edge:
                        # Dark gap: black space between shockwave and board
                        pass  # canvas already cleared to black
                    else:
                        # Behind everything: revealed checkerboard
                        if checker_lit[r][c]:
                            self.light_cell(self.canvas, r, c, *checker_color)
                        # else: black (LED off) — canvas already cleared

            self.canvas = self.matrix.SwapOnVSync(self.canvas)
            time.sleep(0.025)

        # Final frame: clean checkerboard
        self.canvas.Clear()
        self.light_checker_town(self.canvas, checker_color)
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

    # ── _on_local_move hook (called by Board.do_turn after each physical move) ─

    def _on_local_move(self, fr: int, fc: int, tr: int, tc: int, pre_capture) -> None:
        """Build MoveFlags, send move message, wait for move_ack."""
        piece = self.grid[tr][tc]  # grid[tr][tc] = moving piece after do_turn assignment
        if piece is None:
            return
        flags = self._build_move_flags(piece, fr, fc, tr, tc, pre_capture)

        self._net_seq += 1
        team_key = "r" if piece.team.r == self.team_r.r else "l"
        h = board_hash(self.grid, self.peace_time, team_key, self.team_r)
        msg = build_move_msg(self._net_seq, fr, fc, tr, tc,
                             type(piece).__name__, flags, h)
        self._net_send(msg)
        logger.info("Sent move seq=%d %d%d→%d%d", self._net_seq, fr, fc, tr, tc)

        # Wait for ack
        self._move_ack_evt.clear()
        deadline = time.time() + _ACK_TIMEOUT_S
        while not self._move_ack_evt.is_set() and time.time() < deadline:
            self._drain_incoming()
            time.sleep(0.05)
        if not self._move_ack_evt.is_set():
            logger.error("move_ack timeout — treating as disconnect")
            self.game_over = True

    def _on_game_over(self, event: str, losing_team) -> None:
        """Notify peer of checkmate or stalemate."""
        losing_key = "r" if losing_team.r == self.team_r.r else "l"
        self._net_send({
            "type": "game_event",
            "event": event,
            "losing_team_key": losing_key,
        })
        logger.info("Sent game_event: %s (losing=%s)", event, losing_key)

    # ── MoveFlags builder ──────────────────────────────────────────────────────

    def _build_move_flags(self, piece, fr, fc, tr, tc, pre_capture) -> MoveFlags:
        is_capture    = pre_capture is not None
        is_en_passant = False
        captured_at   = None
        is_castling   = False
        rook_from     = None
        rook_to       = None
        is_promotion  = False

        if isinstance(piece, Pawn):
            if abs(tc - fc) == 1 and pre_capture is None:
                is_en_passant = True
                captured_at   = (tr - piece.direction, tc)
            if (piece.starting_row + 6) % 12 == tr:
                is_promotion = True
        elif isinstance(piece, King):
            if fr == tr and abs(tc - fc) == 2:
                is_castling = True
                if tc == fc - 2:
                    rook_from = (fr, fc - 4)
                    rook_to   = (fr, fc - 1)
                else:
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

    # ── Remote move application ────────────────────────────────────────────────

    def _wait_for_remote_move(self, timeout: float = _REMOTE_TIMEOUT_S) -> None:
        """Block until a remote move arrives or the timeout expires.

        Sets ``self.game_over = True`` on timeout.
        """
        deadline = time.time() + timeout
        while not self.game_over and time.time() < deadline:
            self._drain_incoming()
            if self._pending_remote_move is not None:
                msg = self._pending_remote_move
                self._pending_remote_move = None
                self._apply_remote_move(msg)
                return
            time.sleep(0.05)

        if not self.game_over:
            logger.error("Timeout waiting for remote move — game over")
            self.game_over = True

    def _apply_remote_move(self, msg: dict) -> None:
        """Apply an incoming move message by guiding the human to physically
        move the piece on the board — same UX as computer_move."""
        from core.constants import CellOccupancy

        fr = msg["from_row"]
        fc = msg["from_col"]
        tr = msg["to_row"]
        tc = msg["to_col"]

        if self.grid[fr][fc] is None:
            logger.warning("Remote move from empty square %d,%d", fr, fc)
            return

        flags = MoveFlags.from_dict(msg.get("flags", {}))
        piece = self.grid[fr][fc]

        # Clear en_passantable for the remote team's pawns (mirrors do_turn)
        for row in self.grid:
            for p in row:
                if isinstance(p, Pawn) and p.team.r == piece.team.r:
                    p.en_passantable = False
        if flags.is_capture or isinstance(piece, Pawn):
            self.peace_time = 0
        else:
            self.peace_time += 1

        is_capture = self.grid[tr][tc] is not None

        # Guide the human through the physical move on the board
        self._guide_physical_move(fr, fc, tr, tc, piece, is_capture)

        self.grid[tr][tc] = self.grid[fr][fc]
        self._apply_move(fr, fc, tr, tc)

        # Verify hash
        team_key   = "r" if piece.team.r == self.team_r.r else "l"
        h          = board_hash(self.grid, self.peace_time, team_key, self.team_r)
        remote_h   = msg.get("board_hash", "")
        status     = "ok" if h == remote_h else "desync"
        self._net_send({"type": "move_ack", "seq": msg.get("seq", 0), "status": status})
        if status == "desync":
            self._net_send({"type": "board_sync_request"})
            # Log moved pieces and en_passant state for debugging
            ep_pieces = []
            touched_pieces = []
            for row in self.grid:
                for p in row:
                    if p is not None and isinstance(p, Pawn) and p.en_passantable:
                        ep_pieces.append(f"{p.row},{p.col}")
                    if p is not None and getattr(p, 'touched', False):
                        touched_pieces.append(f"{type(p).__name__}@{p.row},{p.col}")
            logger.warning("Hash mismatch seq=%d local=%s remote=%s peace=%d turn=%s ep=[%s] touched=[%s]",
                           msg.get("seq", -1), h[:12], remote_h[:12],
                           self.peace_time, team_key,
                           ",".join(ep_pieces), ",".join(touched_pieces))

    def _guide_physical_move(self, fr, fc, tr, tc, piece, is_capture) -> None:
        """Guide the human to physically execute a remote move on the board.

        Lights up the source square until the piece is lifted, then lights up
        the destination square until the piece is placed there. For captures,
        first waits for the captured piece to be removed.
        """
        from core.constants import CellOccupancy

        if not hasattr(self, "canvas"):
            return

        team = piece.team

        if is_capture:
            # Step 1: highlight source piece — wait for it to be lifted
            logger.info("Remote move: lift %s at %d,%d (capture)", type(piece).__name__, fr, fc)
            state = CellOccupancy.OCCUPIED
            while state == CellOccupancy.OCCUPIED:
                self.master.read_data()
                self.canvas.Clear()
                self.light_checker_town(self.canvas)
                self.light_cell(self.canvas, fr, fc, team.r, team.g, team.b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                state = self.master.get_cell_state(fr, fc)

            # Step 2: highlight captured piece — wait for it to be removed
            logger.info("Remote move: remove captured piece at %d,%d", tr, tc)
            state = CellOccupancy.OCCUPIED
            while state == CellOccupancy.OCCUPIED:
                self.master.read_data()
                self.canvas.Clear()
                self.light_checker_town(self.canvas)
                self.light_cell(self.canvas, tr, tc, team.r, team.g, team.b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                state = self.master.get_cell_state(tr, tc)
            time.sleep(0.1)

            # Step 3: blink destination — wait for piece to be placed
            logger.info("Remote move: place piece at %d,%d", tr, tc)
            state = CellOccupancy.EMPTY
            while state == CellOccupancy.EMPTY:
                self.master.read_data()
                self.canvas.Clear()
                self.light_checker_town(self.canvas)
                self.light_cell(self.canvas, tr, tc, team.r, team.g, team.b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                time.sleep(0.1)
                self.canvas.Clear()
                self.light_checker_town(self.canvas)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                state = self.master.get_cell_state(tr, tc)
        else:
            # Non-capture: highlight source — wait for lift
            logger.info("Remote move: lift %s at %d,%d", type(piece).__name__, fr, fc)
            state = CellOccupancy.OCCUPIED
            while state == CellOccupancy.OCCUPIED:
                self.master.read_data()
                self.canvas.Clear()
                self.light_checker_town(self.canvas)
                self.light_cell(self.canvas, fr, fc, team.r, team.g, team.b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                state = self.master.get_cell_state(fr, fc)

            # Blink destination — wait for piece to be placed
            logger.info("Remote move: place piece at %d,%d", tr, tc)
            state = CellOccupancy.EMPTY
            while state == CellOccupancy.EMPTY:
                self.master.read_data()
                self.canvas.Clear()
                self.light_checker_town(self.canvas)
                self.light_cell(self.canvas, tr, tc, team.r, team.g, team.b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                time.sleep(0.1)
                self.canvas.Clear()
                self.light_checker_town(self.canvas)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                state = self.master.get_cell_state(tr, tc)

        logger.info("Remote move: physical move complete %d,%d→%d,%d", fr, fc, tr, tc)

    # ── Online play helpers ────────────────────────────────────────────────────

    def _show_chessmatrix_waiting(self, room_code: str) -> None:
        """Display the ChessMatrix barcode on the LED matrix and block until
        the relay peer connects.

        Re-blits the barcode every 5 s so the display stays fresh.  Returns
        as soon as ``_relay._peer_joined`` is set.
        """
        from network import chessmatrix as _cm_mod

        grid = _cm_mod.encode(room_code)
        relay = self._relay

        def _blit() -> None:
            self.canvas.Clear()
            _cm_mod.render_to_led(grid, self.canvas)
            self.canvas = self.matrix.SwapOnVSync(self.canvas)

        _blit()
        logger.info("Displaying ChessMatrix for room %s — waiting for peer...", room_code)

        last_blit = time.time()
        while relay is not None and not relay._peer_joined.is_set():  # type: ignore[attr-defined]
            self._drain_incoming()
            if time.time() - last_blit >= 5.0:
                _blit()
                last_blit = time.time()
            time.sleep(0.1)

        logger.info("Relay peer connected — proceeding")

    def _chessmatrix_input_ux(self) -> "str | None":
        """Reed-switch–driven ChessMatrix code entry for the Pi GUEST.

        Mirrors the simulator's CODE_SCAN_BOARD flow using ``self.master``
        for piece detection instead of mouse clicks.

        Returns the decoded 6-character room code, or ``None`` on repeated
        failure (user gave up / too many reed-switch errors).
        """
        from core.constants import CellOccupancy
        from network import chessmatrix as _cm_mod
        import chessmatrix as _cm_lib  # type: ignore[import]

        _FADE_S      = 3.0
        _INACT_S     = 5.0
        _FRAME_S     = 1.0 / 30.0   # ~30 fps render loop
        _MAX_RETRIES = 3

        _CORNERS = {
            "red":   (1, 6),
            "green": (6, 1),
            "blue":  (6, 6),
        }
        _COLOR_IDX = {"red": 1, "green": 2, "blue": 3}
        _PHASE_ORDER = ["red", "green", "blue"]

        def _cell_occupied(row: int, col: int) -> bool:
            self.master.read_data()
            return self.master.get_cell_state(row, col) == CellOccupancy.OCCUPIED

        def _render(locked: dict, current_color: int, beam_phase: float,
                    blink_on: bool, active_corner: "tuple|None",
                    fade_frac: float, corner_pulsing: bool, pulse_t: float) -> None:
            self.canvas.Clear()
            _cm_mod.render_beam_frame(
                self.canvas, locked, current_color, beam_phase,
                blink_on, active_corner=active_corner, fade_frac=fade_frac,
                corner_color=_COLOR_IDX.get(
                    active_corner and next(
                        (k for k, v in _CORNERS.items() if v == active_corner), None
                    ) or "", 0
                ) if active_corner else 0,
                corner_pulsing=corner_pulsing,
                pulse_t=pulse_t,
            )
            self.canvas = self.matrix.SwapOnVSync(self.canvas)

        for _attempt in range(_MAX_RETRIES):
            locked: dict = {}
            pending: set = set()
            last_activity: "float | None" = None
            fade_start: "float | None" = None

            # Step 0: clear the board of any pieces
            logger.info("ChessMatrix input: clear all pieces from board")
            while True:
                self.master.read_data()
                any_piece = any(
                    self.master.get_cell_state(r, c) == CellOccupancy.OCCUPIED
                    for r in range(8) for c in range(8)
                )
                if not any_piece:
                    break
                self.canvas.Clear()
                _cm_mod.render_border_only(self.canvas)
                for r in range(8):
                    for c in range(8):
                        if self.master.get_cell_state(r, c) == CellOccupancy.OCCUPIED:
                            _cm_mod._set_cell(self.canvas, r, c, 255, 80, 0)  # orange warning
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                time.sleep(0.1)

            # Steps 1–3: red → green → blue entry
            for color_name in _PHASE_ORDER:
                corner = _CORNERS[color_name]
                color_idx = _COLOR_IDX[color_name]
                cs = f"{color_name}_wait"
                last_activity = None
                fade_start = None
                pending = set()

                # Track previous reed-switch state to detect edges
                prev_corner = False
                prev_data: dict = {}

                while True:
                    now = time.time()
                    beam_phase = (now % 0.8) / 0.8
                    blink_on = (now % 0.5) < 0.25

                    is_active = cs == f"{color_name}_active"
                    is_fading = cs == f"{color_name}_fading"
                    is_waiting = cs == f"{color_name}_wait"

                    # Compute fade_frac
                    fade_frac = 0.0
                    if is_fading and fade_start is not None:
                        fade_frac = min((now - fade_start) / _FADE_S, 1.0)
                        if fade_frac >= 1.0:
                            # Lock in pending cells
                            for cell in pending:
                                locked[cell] = color_idx
                            logger.info("ChessMatrix: %s locked (%d cells)", color_name, len(pending))
                            break  # advance to next color

                    corner_pulsing = (
                        is_active
                        and last_activity is not None
                        and (now - last_activity) >= _INACT_S
                    )

                    # Poll reed switches (edges only)
                    self.master.read_data()
                    cur_corner = self.master.get_cell_state(*corner) == CellOccupancy.OCCUPIED

                    if is_waiting and cur_corner and not prev_corner:
                        cs = f"{color_name}_active"
                        last_activity = now
                        pending = set()
                        logger.info("ChessMatrix: %s corner placed — active", color_name)

                    elif is_active:
                        if not cur_corner and prev_corner:
                            # Corner removed → start fade
                            cs = f"{color_name}_fading"
                            fade_start = now
                            logger.info("ChessMatrix: %s corner removed — fading", color_name)
                        else:
                            # Check data cells for edge changes
                            for cell in _cm_mod.DATA_CELLS:
                                cur = self.master.get_cell_state(*cell) == CellOccupancy.OCCUPIED
                                was = prev_data.get(cell, False)
                                if cur and not was:
                                    pending.add(cell)
                                    last_activity = now
                                elif not cur and was:
                                    pending.discard(cell)
                                    last_activity = now

                    elif is_fading:
                        if cur_corner and not prev_corner:
                            # Corner replaced → cancel fade
                            cs = f"{color_name}_active"
                            fade_start = None
                            last_activity = now
                            logger.info("ChessMatrix: %s fade cancelled", color_name)

                    prev_corner = cur_corner
                    prev_data = {
                        cell: (self.master.get_cell_state(*cell) == CellOccupancy.OCCUPIED)
                        for cell in _cm_mod.DATA_CELLS
                    }

                    # Build display locked dict
                    display_locked = dict(locked)
                    if is_active or is_fading:
                        for cell in pending:
                            display_locked[cell] = color_idx

                    active_beam_color = color_idx if (is_active or is_fading) else 0
                    active_corner_pos = corner if not is_waiting else corner  # always show corner

                    _render(
                        display_locked,
                        active_beam_color,
                        beam_phase,
                        blink_on,
                        active_corner_pos,
                        fade_frac,
                        corner_pulsing,
                        now,
                    )
                    time.sleep(_FRAME_S)

            # Decode
            try:
                grid = _cm_mod.grid_from_cell_state(locked)
                data = _cm_lib.decode(grid)
                room_code = _cm_mod.bytes_to_room_code(data)
                logger.info("ChessMatrix: decoded room code %s", room_code)
                return room_code
            except Exception as exc:
                logger.warning("ChessMatrix: decode failed (%s) — retry %d/%d",
                               exc, _attempt + 1, _MAX_RETRIES)
                # Error flash
                for _ in range(3):
                    for rgb in ((255, 0, 0), (200, 200, 200)):
                        self.canvas.Clear()
                        _cm_mod.render_border_only(self.canvas)
                        for r, c in _cm_mod.DATA_CELLS:
                            _cm_mod._set_cell(self.canvas, r, c, *rgb)
                        self.canvas = self.matrix.SwapOnVSync(self.canvas)
                        time.sleep(0.12)

        logger.error("ChessMatrix: max retries exceeded — aborting")
        return None

    # ── run() override ─────────────────────────────────────────────────────────

    def run(self, skip_setup: bool = False, init_num: str = "") -> None:  # noqa: ARG002
        """Override Board.run() with the networked game lifecycle.

        Skips ``color_picker`` and ``war_games`` (handled by Sim-as-UI).
        Waits for configuration from the Sim, runs ``interactive_setup``,
        then enters the alternating turn loop.
        """
        self._start_keepalive()
        self.canvas = self.matrix.CreateFrameCanvas()

        # ── Relay online play preamble ─────────────────────────────
        if self._relay is not None:
            if self._local_team_key == "r":
                # HOST: create room, show ChessMatrix, wait for peer
                room_code = self._relay.create_room(timeout=60.0)
                if room_code is None:
                    logger.error("Failed to create relay room — aborting")
                    return
                logger.info("Relay room created: %s", room_code)
                self._show_chessmatrix_waiting(room_code)
            else:
                # GUEST: enter room code via reed-switch ChessMatrix input
                room_code = self._chessmatrix_input_ux()
                if room_code is None:
                    logger.error("ChessMatrix input aborted — aborting")
                    return
                connected = self._relay.join_room(room_code, timeout=30.0)
                if not connected:
                    logger.error("Failed to join relay room %s — aborting", room_code)
                    return
                logger.info("Joined relay room: %s", room_code)
            # Wire up message handler now that peer is connected
            self._relay.set_message_handler(self._on_network_message)

        # ── Waiting animation — light chases board edges until peer connects ──
        if self._peer_name is None:
            self._run_waiting_animation()

        logger.info("NetworkedBoard: waiting for configuration from Sim...")

        # ── Wait for Sim-as-UI to send color + war_games choices ──
        if self._local_team_key == "r":
            # Pi is HOST: wait for Sim to send all 4 config messages
            deadline = time.time() + _SETUP_TIMEOUT_S
            while not self._config_received.is_set() and time.time() < deadline:
                self._drain_incoming()
                time.sleep(0.05)
            if not self._config_received.is_set():
                logger.error("Timed out waiting for config from Sim")
                return
        else:
            # Pi is GUEST: wait for game_start from HOST Sim
            deadline = time.time() + _SETUP_TIMEOUT_S
            while not self._game_start_evt.is_set() and time.time() < deadline:
                self._drain_incoming()
                time.sleep(0.05)
            if not self._game_start_evt.is_set():
                logger.error("Timed out waiting for game_start")
                return

        # When Pi is HOST, send game_start after config is ready
        if self._local_team_key == "r":
            self._net_send({"type": "game_start"})
            logger.info("Sent game_start — starting physical setup")

        # ── Physical piece placement ───────────────────────────────
        # Clear both buffers so interactive_setup starts clean.
        self.canvas.Clear()
        self.canvas = self.matrix.SwapOnVSync(self.canvas)
        self.canvas.Clear()

        self.interactive_setup(self.team_r)
        self._net_send({"type": "setup_status", "team_key": "r", "status": "complete"})

        self.interactive_setup(self.team_l)
        self._net_send({"type": "setup_status", "team_key": "l", "status": "complete"})

        logger.info("Physical setup complete — waiting for Sim side...")

        # ── Wait for Sim side to finish setup ─────────────────────
        deadline = time.time() + _SETUP_TIMEOUT_S
        while not self._remote_setup_evt.is_set() and time.time() < deadline:
            self._drain_incoming()
            time.sleep(0.1)
        if not self._remote_setup_evt.is_set():
            logger.error("Timed out waiting for remote setup_complete")
            return

        # ── Start game ────────────────────────────────────────────
        # Transition from direct-draw (interactive_setup) back to
        # double-buffered rendering.  Match the pattern from Board.run().
        self.canvas.Clear()
        temp = self.matrix.SwapOnVSync(self.canvas)
        temp.Clear()
        self.light_checker_town(temp)
        self.canvas = self.matrix.SwapOnVSync(temp)

        self.initialize_game_board()

        local_team  = self._local_team()
        remote_team = self._remote_team()

        logger.info("team_r.r=%d team_l.r=%d local=%s remote=%s",
                     self.team_r.r, self.team_l.r,
                     local_team.name, remote_team.name)

        logger.info(
            "Game started — local=%s (%s)  remote=%s",
            local_team.name, self._local_team_key, remote_team.name,
        )

        while not self.game_over:
            self.canvas.Clear()
            self.light_checker_town(self.canvas)
            self.canvas = self.matrix.SwapOnVSync(self.canvas)
            self.canvas.Clear()

            # team_r turn
            self._do_turn_networked(self.team_r)
            if self.game_over:
                break

            # team_l turn
            self._do_turn_networked(self.team_l)
            self.canvas = self.matrix.SwapOnVSync(self.canvas)

        # ── End-game animation ────────────────────────────────────
        # Drain any remaining messages (e.g. game_event from sim)
        deadline = time.time() + 5.0
        while self._pending_game_event is None and time.time() < deadline:
            self._drain_incoming()
            time.sleep(0.05)

        if self._pending_game_event is not None:
            event, losing_team = self._pending_game_event
            self._pending_game_event = None
            logger.info("Playing end-game animation: %s", event)
            if event == "checkmate" and losing_team is not None:
                self.seth_victory(losing_team)
            elif event == "stalemate":
                self.stale_mate()
        else:
            logger.warning("Game over but no pending game_event received")

    def _do_turn_networked(self, team) -> None:
        """Route to local physical turn or remote wait based on team ownership."""
        local_team = self._local_team()
        if team.r == local_team.r:
            self.do_turn(team)   # triggers _on_local_move hook when move made
        else:
            self._wait_for_remote_move()
