from __future__ import annotations

import collections
import copy
import logging
import random
import sys
import textwrap
import threading
from enum import Enum, auto
from typing import Optional

logger = logging.getLogger(__name__)

import pygame

from ai.ai import AI
from ai.tree import Tree
from core.cell import Cell
from core.team import Team
from game import rules as _rules
from game.board import Board
from pieces.bishop import Bishop
from pieces.king import King
from pieces.knight import Knight
from pieces.pawn import Pawn
from pieces.piece import Piece
from pieces.queen import Queen
from pieces.rook import Rook
from simulator.sensor import SimSensor

_SCALE = 30           # each 4-pixel LED cell → 120 px on screen
_CELL_PX = 4 * _SCALE  # 120

# Color names matching Board.team_array order (indices 0-7)
_COLOR_NAMES = [
    "Blue", "Purple", "Yellow", "Pink",
    "Green", "Orange", "Dark Blue", "Cyan",
]

# Unicode chess symbols: (team_r symbol, team_l symbol)
# team_r uses hollow/white glyphs, team_l uses solid/black glyphs so shapes differ
_PIECE_UNICODE: dict[type, tuple[str, str]] = {
    Pawn:   ('♙', '♟'),
    Rook:   ('♖', '♜'),
    Knight: ('♘', '♞'),
    Bishop: ('♗', '♝'),
    Queen:  ('♕', '♛'),
    King:   ('♔', '♚'),
}


# ── Side-panel layout ─────────────────────────────────────────────────────────
_BOARD_W  = 32 * _SCALE   # 960 — width of the LED canvas area
_PANEL_W  = 340           # side panel width
_WIN_W    = _BOARD_W + _PANEL_W

# Panel colour palette
_P_BG    = (18,  22,  32)   # background
_P_SEP   = (45,  50,  68)   # divider lines
_P_TEXT  = (185, 192, 210)  # normal text
_P_DIM   = (95,  103, 125)  # labels / secondary text
_P_GOOD  = (85,  200, 115)  # green  (low peace-time)
_P_WARN  = (228, 172, 52)   # yellow (caution)
_P_BAD   = (232, 72,  62)   # red    (check / danger)

# Log-level colours in the panel
_P_LEVEL = {
    logging.DEBUG:    (108, 145, 198),
    logging.INFO:     (152, 206, 152),
    logging.WARNING:  (228, 168, 58),
    logging.ERROR:    (228, 72,  62),
    logging.CRITICAL: (255, 42,  42),
}

# Short module suffix shown before each log line
_LOG_SRC = {
    "simulator.app": "sim",
    "game.rules":    "rul",
    "game.board":    "brd",
}


class _PanelLogHandler(logging.Handler):
    """Captures log records into a deque for display in the side panel."""

    def __init__(self, maxlines: int = 120) -> None:
        """Initialize the handler with a fixed-capacity record deque.

        Args:
            maxlines: Maximum number of log records to retain before the
                oldest entries are discarded.
        """
        super().__init__()
        self.records: collections.deque = collections.deque(maxlen=maxlines)

    def emit(self, record: logging.LogRecord) -> None:
        """Append a log record to the internal deque for panel display.

        Args:
            record: The log record produced by the logging framework.
        """
        self.records.append(record)


class Phase(Enum):
    """Finite-state-machine phases that govern the simulator's game loop.

    Attributes:
        LOBBY: Pre-game menu — choose local/network play mode.
        COLOR_PICK: Players are choosing team colours on the LED grid.
        WAR_GAMES: Players are selecting Human vs. AI for each side.
        PLAYING: The chess game is in progress.
        GAME_OVER: The game has ended (checkmate, stalemate, or draw).
    """

    NAME_ENTRY = auto()
    LOBBY = auto()
    COLOR_PICK = auto()
    WAR_GAMES = auto()
    PLAYING = auto()
    GAME_OVER = auto()


# Lobby option constants
_LOBBY_OPTIONS = [
    "Play Locally",
    "Host a Game",
    "Join a Game",
    "Watch a Game",
]
# LED colors for each lobby option (one per pair of rows)
_LOBBY_COLORS = [
    (64,  180, 232),   # Blue  — Play Locally
    (25,  200, 35),    # Green — Host a Game
    (245, 125, 0),     # Orange — Join a Game
    (190, 25,  255),   # Purple — Watch a Game
]


class GameRunner:
    """Game state machine that drives Board's rendering methods via a Pygame loop."""

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def __init__(self, skip_lobby: bool = False) -> None:
        """Set up the persistent panel log handler and perform the first reset.

        The panel log handler is attached to the root logger here so it
        survives across game resets. All other mutable state is delegated
        to `_reset()`.

        Args:
            skip_lobby: If True, start directly at COLOR_PICK instead of
                showing the Lobby menu (equivalent to the ``--local`` flag).
        """
        self._skip_lobby = skip_lobby
        self._board: Optional[Board] = None
        # Panel log handler — created once so it persists across resets
        self._panel_handler = _PanelLogHandler(maxlines=120)
        self._panel_handler.setLevel(logging.DEBUG)
        _console = logging.StreamHandler(sys.stdout)
        _console.setLevel(logging.DEBUG)
        _console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(self._panel_handler)
        root_logger.addHandler(_console)
        # Suppress noisy third-party DEBUG logs
        for _noisy in ("websockets", "asyncio"):
            logging.getLogger(_noisy).setLevel(logging.WARNING)
        # Panel fonts — populated by _init_board after pygame.init()
        self._pfont_sm: Optional[pygame.font.Font] = None
        self._pfont_md: Optional[pygame.font.Font] = None
        self._pfont_lg: Optional[pygame.font.Font] = None
        self._pfont_xl: Optional[pygame.font.Font] = None
        self._pfont_entry: Optional[pygame.font.Font] = None
        # Player name — persists across resets (not in _reset)
        self._player_name: str = ""
        self._reset()

    def _reset(self) -> None:
        """Reset all transient game state back to initial values.

        Clears phase, team selections, piece selections, AI worker state,
        game-over flags, duck-typed board attributes consumed by
        ``game/rules.py``, move counters, and WAR_GAMES animation counters.
        Does NOT destroy the ``_board`` instance or the panel log handler.
        Clears the panel log so each new game starts with a fresh feed.
        """
        if hasattr(self, "_panel_handler"):
            self._panel_handler.records.clear()
        self.phase = Phase.COLOR_PICK if getattr(self, "_skip_lobby", False) else Phase.LOBBY

        # Lobby transient state
        self._lobby_selected: int = 0   # 0=Play Locally, 1=Host, 2=Join, 3=Watch

        # Color-pick transient state
        self._selected_r_idx: Optional[int] = None
        self._selected_l_idx: Optional[int] = None

        # Playing transient state
        self._selected_piece: Optional[Piece] = None
        self._in_check = False
        self._king_check_pos: Optional[tuple[int, int]] = None
        self._ai_thinking = False
        self._promoting_pawn: Optional[tuple[int, int]] = None  # (row, col) pending promotion
        self._promoting_lifted = False       # True once player clicks the pawn to "lift" it
        self._promoting_index = 0            # current candidate index: 0=Q,1=N,2=B,3=R
        self._promoting_last_cycle_ms = 0    # timestamp of last auto-cycle
        self._current_team: Optional[Team] = None
        self._ai_thread: Optional[threading.Thread] = None
        self._ai_result: Optional[Tree] = None
        self._ai_display_board: Optional[list] = None
        self._ai_display_lock = threading.Lock()

        # Game-over transient state
        self._winner_team: Optional[Team] = None
        self._is_draw = False
        self._game_over_colors: list[list[tuple]] = []  # cached random inner colors
        self._last_game_over_ms = 0

        # Duck-type attributes read/written by game/rules.py
        self.game_over = False
        self.peace_time = 0
        self.days_left_since_injury: list = []
        self.days_right_since_injury: list = []
        self.double_left_jeopardy: list = []
        self.double_right_jeopardy: list = []

        # Move counter
        self._move_count = 0

        # WAR_GAMES animation counters
        self._think = 0
        self._think_l = 0
        self._think_r = 0
        self._last_think_ms = 0

    def _init_board(self) -> None:
        """Create a fresh Board with fake hardware wired up (call after pygame.init())."""
        from simulator.fake_rgbmatrix import FakeRGBMatrix

        self._board = Board(sensor=SimSensor())
        matrix = FakeRGBMatrix()
        matrix._screen = pygame.display.get_surface()
        self._b.matrix = matrix
        self._b.canvas = matrix.CreateFrameCanvas()
        self._b.checker_brightness = 0
        self._b.checker_brightness_dir = 2
        # Not yet decided — need None so WAR_GAMES knows nothing is selected yet
        self._b.computer_player_r = None
        self._b.computer_player_l = None
        # Font for piece overlay and panel UI — try fonts with good Unicode coverage
        font_size = int(_CELL_PX * 0.52)
        _ui_font_name = None
        for _fname in ("applesymbols", "arial", "dejavusans", None):
            if _fname is None or pygame.font.match_font(_fname):
                self._font = pygame.font.SysFont(_fname, font_size)
                _ui_font_name = _fname
                break
        # Panel UI fonts — same font family so →, ●, ✓, … render correctly
        self._pfont_sm = pygame.font.SysFont(_ui_font_name, 13)
        self._pfont_md = pygame.font.SysFont(_ui_font_name, 15)
        self._pfont_lg = pygame.font.SysFont(_ui_font_name, 18, bold=True)
        # Name-entry screen fonts
        self._pfont_xl    = pygame.font.SysFont(_ui_font_name, 36, bold=True)
        self._pfont_entry = pygame.font.SysFont(_ui_font_name, 52, bold=True)

    # ── Internal narrowing helpers ─────────────────────────────────────────────

    @property
    def _b(self) -> "Board":
        """Return self._board, asserting it has been initialised."""
        assert self._board is not None, "_board accessed before _init_board()"
        return self._board

    # ── Properties that game/rules.py needs via the duck-type 'board' arg ─────

    @property
    def team_r(self) -> Team:
        """Return the right (first) player's Team object from the active Board.

        Returns:
            The Team instance for the right-hand player.
        """
        return self._b.team_r

    @property
    def team_l(self) -> Team:
        """Return the left (second) player's Team object from the active Board.

        Returns:
            The Team instance for the left-hand player.
        """
        return self._b.team_l

    # ── Coordinate helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _px_to_cell(px: int, py: int) -> Optional[tuple[int, int]]:
        """Convert a screen pixel coordinate to a board (row, col) index.

        Args:
            px: Pixel x-coordinate within the board canvas area.
            py: Pixel y-coordinate within the board canvas area.

        Returns:
            A ``(row, col)`` tuple if the pixel falls within the 8x8 grid,
            or ``None`` if it is outside the board area.
        """
        row = py // _CELL_PX
        col = px // _CELL_PX
        if 0 <= row < 8 and 0 <= col < 8:
            return row, col
        return None

    # ── Team-piece helpers ─────────────────────────────────────────────────────

    def _get_team_pieces(self, team: Team, grid=None) -> list:
        """Collect all pieces on the board that belong to the given team.

        Args:
            team: The team whose pieces should be returned.
            grid: An optional 8x8 board grid to search. Defaults to the
                live ``Board.grid`` when not provided.

        Returns:
            A flat list of ``Piece`` instances owned by ``team``.
        """
        b = self._b
        if grid is None:
            grid = b.grid
        return [p for row in grid for p in row
                if p is not None and p.team.r == team.r]

    # ── Chess logic ────────────────────────────────────────────────────────────

    def _apply_move(self, old_row: int, old_col: int,
                    target_row: int, target_col: int) -> None:
        """Finalize a piece move on the live board grid.

        Calls the appropriate piece-specific ``move()`` method to handle
        special rules (en passant for Pawns, castling for Kings), then
        clears the origin square. The destination square must already hold
        the moving piece before this method is called.

        Args:
            old_row: Row index the piece moved from.
            old_col: Column index the piece moved from.
            target_row: Row index the piece moved to.
            target_col: Column index the piece moved to.
        """
        b = self._b
        piece = b.grid[target_row][target_col]
        if isinstance(piece, Pawn):
            self.peace_time = 0
            enemy = piece.move(target_row, target_col, b.grid)
            if enemy is not None:
                b.grid[enemy.row][enemy.col] = None
            if (piece.starting_row + 6) % 12 == target_row:
                self._promoting_pawn = (target_row, target_col)
        elif isinstance(piece, King):
            rook_loc, rook_tgt = piece.move(target_row, target_col, b.grid)
            if rook_loc is not None and rook_tgt is not None:
                b.grid[rook_tgt.row][rook_tgt.col] = (
                    b.grid[rook_loc.row][rook_loc.col])
                b.grid[rook_loc.row][rook_loc.col] = None
                rook_piece = b.grid[rook_tgt.row][rook_tgt.col]
                if rook_piece is not None:
                    rook_piece.move(rook_tgt.row, rook_tgt.col, b.grid)
        else:
            if piece is not None:
                piece.move(target_row, target_col, b.grid)
        b.grid[old_row][old_col] = None

    def _add_nodes(self, node: Tree, team: Team, depth: int = 2) -> None:
        """Recursively expand a game-tree node with all legal moves for a team.

        For each piece belonging to ``team`` in ``node.board_state``, legal
        targets are computed (with check filtering applied), a deep-copied
        child board is created for every target, and the resulting ``Tree``
        nodes are attached as children. The opponent's moves are then
        expanded recursively until ``depth`` reaches zero.

        As boards are generated they are also written to
        ``_ai_display_board`` (under ``_ai_display_lock``) so the render
        loop can animate the AI's search in real time.

        Args:
            node: The parent game-tree node to expand.
            team: The team whose moves are generated at this ply.
            depth: Remaining half-moves (plies) to expand. Expansion stops
                when this reaches zero.
        """
        b = self._b
        if depth == 0:
            return
        team_king = None
        check = False
        for piece in self._get_team_pieces(team, node.board_state):
            if isinstance(piece, King):
                team_king = piece
                check = team_king.calc_targets(node.board_state)
        for piece in self._get_team_pieces(team, node.board_state):
            piece.calc_targets(node.board_state)
            if check and not isinstance(piece, King):
                piece.sky_fall(team_king)
            for target in piece.targets:
                new_board = copy.deepcopy(node.board_state)
                new_piece = new_board[piece.row][piece.col]
                new_board[target.row][target.col] = new_piece
                new_piece.move(target.row, target.col, new_board)
                new_board[piece.row][piece.col] = None
                with self._ai_display_lock:
                    self._ai_display_board = new_board
                node.add_child(Tree(
                    new_board,
                    Cell(piece.row, piece.col),
                    Cell(target.row, target.col),
                    b.team_r,
                    b.team_l,
                ))
        next_team = b.team_r if team.r == b.team_l.r else b.team_l
        for child in node.children:
            self._add_nodes(child, next_team, depth - 1)

    # ── ASCII board dump ───────────────────────────────────────────────────────

    _PIECE_CHAR: dict[type, str] = {
        Pawn: 'P', Rook: 'R', Knight: 'N',
        Bishop: 'B', Queen: 'Q', King: 'K',
    }

    def _log_board_ascii(self) -> None:
        """Print a compact ASCII board to the terminal.

        Uppercase letters = team_r pieces (rows 0–1 at game start).
        Lowercase letters = team_l pieces (rows 6–7 at game start).
        '·' = empty square.
        """
        b = self._b
        lines = ["", "    0 1 2 3 4 5 6 7", "  ┌─────────────────┐"]
        for r, row in enumerate(b.grid):
            cells = []
            for piece in row:
                if piece is None:
                    cells.append("·")
                else:
                    ch = self._PIECE_CHAR.get(type(piece), "?")
                    cells.append(ch if piece.team.r == b.team_r.r else ch.lower())
            lines.append(f"{r} │ {' '.join(cells)} │")
        lines.append("  └─────────────────┘")
        lines.append(f"    {b.team_r.name}=UPPER  {b.team_l.name}=lower")
        logger.info("\n".join(lines))

    def stale_mate(self) -> None:
        """Called by game/rules.py on fifty-move / threefold-repetition."""
        self._is_draw = True
        self.phase = Phase.GAME_OVER
        self._log_board_ascii()
        logger.info("Stalemate — draw declared.")

    def _declare_victory(self, losing_team: Team) -> None:
        """Record the winning team and transition to the GAME_OVER phase.

        Args:
            losing_team: The team that has been checkmated; the opponent is
                stored as the winner.
        """
        b = self._b
        self._winner_team = b.team_r if losing_team.r == b.team_l.r else b.team_l
        self.phase = Phase.GAME_OVER

    def _begin_turn(self, team: Team) -> None:
        """Set up the board state at the start of a team's turn.

        Checks the fifty-move rule, calculates legal moves for every piece
        belonging to ``team`` (applying king-escape filtering when the king
        is in check), and detects checkmate or stalemate when no moves
        remain. Updates ``_in_check`` and ``_king_check_pos`` for the
        renderer and kicks off the AI worker when the active team is
        computer-controlled.

        Args:
            team: The team whose turn is beginning.
        """
        b = self._b
        if _rules.bob_ross(self, team, b.grid):
            return

        check = False
        king_row, king_col = -1, -1
        pieces_with_moves = 0

        for row in b.grid:
            for piece in row:
                if (piece is not None
                        and isinstance(piece, King)
                        and piece.team.r == team.r):
                    check = piece.calc_targets(b.grid)
                    if len(piece.get_targets()) > 0:
                        pieces_with_moves += 1
                    king_row, king_col = piece.row, piece.col

        for row in b.grid:
            for piece in row:
                if isinstance(piece, Pawn) and piece.team.r == team.r:
                    piece.en_passantable = False
                if piece is not None and not isinstance(piece, King):
                    piece.calc_targets(b.grid)
                    if check:
                        king_piece = b.grid[king_row][king_col]
                        if isinstance(king_piece, King):
                            piece.sky_fall(king_piece)
                    if len(piece.get_targets()) > 0 and piece.team.r == team.r:
                        pieces_with_moves += 1

        if pieces_with_moves == 0:
            self.game_over = True
            self._log_board_ascii()
            if not check:
                self._is_draw = True
                self.phase = Phase.GAME_OVER
                logger.info("The only winning move is not to play")
            else:
                self._declare_victory(team)
                winner = self._winner_team
                logger.info("Checkmate! %s wins.", winner.name if winner is not None else "?")
            return

        self._in_check = check
        self._king_check_pos = (king_row, king_col) if check else None
        if check:
            logger.debug("KING IS IN CHECK")
        logger.info("Player: %s's move.", team.name)

        is_ai = (
            (team.r == b.team_r.r and b.computer_player_r) or
            (team.r == b.team_l.r and b.computer_player_l)
        )
        if is_ai:
            self._ai_thinking = True

    def _execute_ai_move(self) -> None:
        """Launch the AI computation in a background thread."""
        self._ai_result = None
        self._ai_display_board = None
        self._ai_thread = threading.Thread(target=self._run_ai, daemon=True)
        self._ai_thread.start()

    def _run_ai(self) -> None:
        """Runs in a background thread — builds tree and stores best move."""
        b = self._b
        assert self._current_team is not None, "_current_team not set before AI run"
        current_team = self._current_team
        root = Tree(copy.deepcopy(b.grid), None, None, b.team_r, b.team_l)
        self._add_nodes(root, current_team, depth=2)
        if root.children:
            self._ai_result = AI(root, current_team).alpha_beta_search()

    def _next_turn(self) -> None:
        """Clear per-turn state and hand control to the opposing team.

        Resets the selected piece, check indicators, and AI flag, then
        swaps the active team and calls ``_begin_turn`` for the new side.
        """
        b = self._b
        self._selected_piece = None
        self._in_check = False
        self._king_check_pos = None
        self._ai_thinking = False
        assert self._current_team is not None, "_current_team not set before _next_turn"
        self._current_team = (
            b.team_l if self._current_team.r == b.team_r.r else b.team_r)
        self._begin_turn(self._current_team)

    # ── Rendering ──────────────────────────────────────────────────────────────

    def _render_name_entry(self) -> None:
        """Render the name-entry screen onto the board canvas area."""
        b = self._b
        b.canvas.Clear()
        b.matrix.blit_to_screen()   # fills board area with black
        screen = b.matrix._screen
        if screen is None or self._pfont_xl is None or self._pfont_entry is None:
            return
        cx = _BOARD_W // 2
        h  = 32 * _SCALE

        title_surf = self._pfont_xl.render("Enter your name", True, (185, 192, 210))
        screen.blit(title_surf, title_surf.get_rect(center=(cx, h // 3)))

        cursor = "|" if (pygame.time.get_ticks() // 530) % 2 else " "
        name_surf = self._pfont_entry.render(self._player_name + cursor, True, (255, 255, 255))
        screen.blit(name_surf, name_surf.get_rect(center=(cx, h // 2)))

        if self._pfont_sm:
            hint_surf = self._pfont_sm.render("Press Enter to continue", True, (95, 103, 125))
            screen.blit(hint_surf, hint_surf.get_rect(center=(cx, h * 2 // 3)))

    def _handle_name_entry(self, event: pygame.event.Event) -> None:
        """Handle keyboard input in the NAME_ENTRY phase."""
        if event.type != pygame.KEYDOWN:
            return
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.phase = Phase.COLOR_PICK
        elif event.key == pygame.K_BACKSPACE:
            self._player_name = self._player_name[:-1]
        elif event.unicode and event.unicode.isprintable() and len(self._player_name) < 20:
            self._player_name += event.unicode

    def _render_lobby(self) -> None:
        """Render the lobby menu onto the LED canvas.

        Each of the 4 options occupies two rows of 8 cells.  The selected
        option is shown at full brightness; others are dimmed to one-third.
        """
        b = self._b
        b.canvas.Clear()
        for opt_idx, (r, g, bl) in enumerate(_LOBBY_COLORS):
            row_a = opt_idx * 2
            row_b = opt_idx * 2 + 1
            dim = opt_idx != self._lobby_selected
            fr, fg, fb = (r // 3, g // 3, bl // 3) if dim else (r, g, bl)
            for col in range(8):
                b.light_cell(b.canvas, row_a, col, fr, fg, fb)
                b.light_cell(b.canvas, row_b, col, fr, fg, fb)
        b.matrix.blit_to_screen()

    def _render_color_pick(self) -> None:
        """Render the colour-selection screen to the LED canvas.

        Lights row 2 with all eight team colours for the right player and
        row 5 for the left player. Once a side has made a selection, all
        other colour cells on that row are dimmed to a quarter brightness.
        """
        b = self._b
        b.canvas.Clear()
        r_sel = self._selected_r_idx
        l_sel = self._selected_l_idx
        for i in range(8):
            t = b.team_array[i]
            # Dim all cells except the selected one once a choice is made
            if r_sel is not None and i != r_sel:
                b.light_cell(b.canvas, 2, i, t.r // 4, t.g // 4, t.b // 4)
            else:
                b.light_cell(b.canvas, 2, i, t.r, t.g, t.b)
            if l_sel is not None and i != l_sel:
                b.light_cell(b.canvas, 5, i, t.r // 4, t.g // 4, t.b // 4)
            else:
                b.light_cell(b.canvas, 5, i, t.r, t.g, t.b)
        b.matrix.blit_to_screen()

    def _render_war_games(self) -> None:
        """Render the Human-vs-AI selection screen to the LED canvas.

        Row 3 represents the right team (cols 0-3 = Human, cols 4-7 = AI)
        and row 4 represents the left team (cols 0-3 = AI, cols 4-7 = Human),
        mirroring the layout of ``Board.war_games()``. Unselected halves
        show an animated single-dot sweep on a white background; confirmed
        AI choices show a sweeping dot, confirmed Human choices show a solid
        team-colour fill.
        """
        b = self._b
        b.canvas.Clear()
        think = self._think

        # Row 3: team R — cols 0-3 = Human, cols 4-7 = AI (mirrors war_games())
        if b.computer_player_r is not None:
            if b.computer_player_r:
                # AI selected: animated single dot on white row
                for i in range(8):
                    if i == 7 - self._think_r:
                        b.light_cell(b.canvas, 3, i,
                                     b.team_r.r, b.team_r.g, b.team_r.b)
                    else:
                        b.light_cell(b.canvas, 3, i, 255, 255, 255)
            else:
                # Human selected: solid team color
                for i in range(8):
                    b.light_cell(b.canvas, 3, i, b.team_r.r, b.team_r.g, b.team_r.b)
        else:
            # Undecided: left half solid, right half animated
            for i in range(8):
                if i < 4:
                    b.light_cell(b.canvas, 3, i, b.team_r.r, b.team_r.g, b.team_r.b)
                else:
                    if i == 7 - think:
                        b.light_cell(b.canvas, 3, i,
                                     b.team_r.r, b.team_r.g, b.team_r.b)
                    else:
                        b.light_cell(b.canvas, 3, i, 255, 255, 255)

        # Row 4: team L — kitty-corner from row 3: cols 0-3 = AI, cols 4-7 = Human
        if b.computer_player_l is not None:
            if b.computer_player_l:
                # AI selected: animated single dot on white row (left-to-right)
                for i in range(8):
                    if i == self._think_l:
                        b.light_cell(b.canvas, 4, i,
                                     b.team_l.r, b.team_l.g, b.team_l.b)
                    else:
                        b.light_cell(b.canvas, 4, i, 255, 255, 255)
            else:
                # Human selected: solid team color
                for i in range(8):
                    b.light_cell(b.canvas, 4, i, b.team_l.r, b.team_l.g, b.team_l.b)
        else:
            # Undecided: left half animated (AI), right half solid (Human)
            for i in range(8):
                if i < 4:
                    if i == think:
                        b.light_cell(b.canvas, 4, i,
                                     b.team_l.r, b.team_l.g, b.team_l.b)
                    else:
                        b.light_cell(b.canvas, 4, i, 255, 255, 255)
                else:
                    b.light_cell(b.canvas, 4, i, b.team_l.r, b.team_l.g, b.team_l.b)

        b.matrix.blit_to_screen()

    def _draw_piece_overlay(self, grid=None) -> None:
        """Draw chess pieces as Unicode-symbol circles on top of the scaled LED surface.

        Uses grid enumeration indices (not piece.row/col) so the overlay always
        matches the actual board state even if a piece's internal coords lag.
        Pass a custom grid (e.g. AI's considered board) to visualize that instead;
        selection highlights are suppressed when a custom grid is used.
        """
        screen = self._b.matrix._screen
        if screen is None:
            return
        show_selection = grid is None
        if grid is None:
            grid = self._b.grid

        b = self._b
        team_r_r = b.team_r.r  # used to pick which Unicode glyph variant

        r_circle = int(_CELL_PX * 0.38)    # piece circle radius
        shadow_off = max(3, r_circle // 8)  # drop-shadow offset

        for row_idx, row in enumerate(grid):
            for col_idx, piece in enumerate(row):
                if piece is None:
                    continue
                cx = col_idx * _CELL_PX + _CELL_PX // 2
                cy = row_idx * _CELL_PX + _CELL_PX // 2
                tc = (piece.team.r, piece.team.g, piece.team.b)

                # Drop shadow
                pygame.draw.circle(screen, (20, 20, 20),
                                   (cx + shadow_off, cy + shadow_off), r_circle)
                # Team-colour fill
                pygame.draw.circle(screen, tc, (cx, cy), r_circle)
                # Thin white ring
                pygame.draw.circle(screen, (255, 255, 255), (cx, cy), r_circle, 2)

                # Pick glyph: team_r → hollow/white variant, team_l → solid/black variant
                glyphs = _PIECE_UNICODE.get(type(piece), ('?', '?'))
                symbol = glyphs[0] if piece.team.r == team_r_r else glyphs[1]

                # Text colour: white on dark teams, near-black on light teams
                brightness = 0.299 * tc[0] + 0.587 * tc[1] + 0.114 * tc[2]
                text_color = (20, 20, 20) if brightness > 140 else (245, 245, 245)

                # Render with a 1-px outline for legibility (draw shadow then draw symbol)
                surf = self._font.render(symbol, True, text_color)
                rect = surf.get_rect(center=(cx, cy))
                outline_surf = self._font.render(
                    symbol, True,
                    (20, 20, 20) if brightness <= 140 else (230, 230, 230))
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    screen.blit(outline_surf, rect.move(dx, dy))
                screen.blit(surf, rect)

        if not show_selection:
            return

        # Highlight selected piece with a pulsing bright ring
        if self._selected_piece is not None:
            p = self._selected_piece
            for row_idx, row in enumerate(self._b.grid):
                for col_idx, gp in enumerate(row):
                    if gp is p:
                        cx = col_idx * _CELL_PX + _CELL_PX // 2
                        cy = row_idx * _CELL_PX + _CELL_PX // 2
                        if (pygame.time.get_ticks() // 500) % 2:
                            pygame.draw.circle(screen, (255, 255, 255),
                                               (cx, cy), r_circle + 4, 3)

    def _render_playing(self) -> None:
        """Render one frame of the active chess game to the LED canvas.

        While the AI is thinking, pulses the checker pattern and draws the
        AI's currently-considered board state as a piece overlay. During a
        human turn, draws a static white checker pattern, highlights legal
        target squares for the selected piece, blinks the selected piece's
        cell, and overlays all pieces as Unicode-symbol circles.
        """
        b = self._b
        b.canvas.Clear()

        if self._ai_thinking:
            # Pulse checker while AI thinks — matches board's choose_light_checker_town
            b.checker_brightness += b.checker_brightness_dir
            if b.checker_brightness <= 0:
                b.checker_brightness_dir *= -1
                b.checker_brightness = 0
            elif b.checker_brightness >= 255:
                b.checker_brightness_dir *= -1
                b.checker_brightness = 255
            b.choose_light_checker_town()
            b.matrix.blit_to_screen()
            with self._ai_display_lock:
                ai_grid = self._ai_display_board
            self._draw_piece_overlay(grid=ai_grid)
        else:
            # Static white checker during human turn — matches do_turn rendering
            b.light_checker_town(b.canvas)

            if self._selected_piece:
                # Light all legal target squares in team colour (board's actual method)
                b.light_targets(self._selected_piece)
                # Blink selected piece square: team colour for 0.5 s, off for 0.5 s
                # (mirrors do_turn: if time.time() - int(time.time()) > 0.5)
                if (pygame.time.get_ticks() // 500) % 2:
                    p = self._selected_piece
                    b.light_cell(b.canvas, p.row, p.col,
                                 p.team.r, p.team.g, p.team.b)

            b.matrix.blit_to_screen()
            self._draw_piece_overlay()

            if self._promoting_pawn is not None:
                self._render_promotion_overlay()

    def _render_promotion_overlay(self) -> None:
        """Draw the promotion picker overlay.

        Before the pawn is lifted: blinks the promotion square to prompt the
        player to click it.  After lifting: cycles through Queen/Knight/Bishop/
        Rook every 0.8 s (matching the Pi's interaction feel), lighting the
        current candidate's targets and the promotion square in team colour.
        Click anywhere to confirm the currently-displayed piece.
        """
        b = self._b
        assert self._promoting_pawn is not None
        assert self._current_team is not None
        p_row, p_col = self._promoting_pawn
        team = self._current_team
        _CANDIDATES: list[type[Queen] | type[Knight] | type[Bishop] | type[Rook]] = [
            Queen, Knight, Bishop, Rook
        ]
        _LABELS = ["Queen", "Knight", "Bishop", "Rook"]

        if not self._promoting_lifted:
            # Blink the promotion square to tell the player to click it
            if (pygame.time.get_ticks() // 500) % 2:
                b.light_cell(b.canvas, p_row, p_col, team.r, team.g, team.b)
            b.matrix.blit_to_screen()
            self._draw_piece_overlay()
            pygame.display.set_caption("PROMOTION — click the pawn to begin")
        else:
            # Advance the cycle every 800 ms
            now = pygame.time.get_ticks()
            if now - self._promoting_last_cycle_ms >= 800:
                self._promoting_index = (self._promoting_index + 1) % len(_CANDIDATES)
                self._promoting_last_cycle_ms = now

            # Show the current candidate's targets and light the promotion square
            pick = _CANDIDATES[self._promoting_index](p_row, p_col, team)
            pick.calc_targets(b.grid)
            b.light_targets(pick)
            b.light_cell(b.canvas, p_row, p_col, team.r, team.g, team.b)
            b.matrix.blit_to_screen()
            self._draw_piece_overlay()
            label = _LABELS[self._promoting_index]
            pygame.display.set_caption(f"PROMOTION — {label} (click to confirm)")

    def _render_game_over(self) -> None:
        """Render the game-over screen to the LED canvas.

        On a draw, the top four rows are lit in the right team's colour and
        the bottom four in the left team's colour. On a win, the border
        cells pulse the winner's colour while the 6x6 inner grid cycles
        through random colours at roughly 20 fps, matching the Pi's
        ``time.sleep(0.05)`` animation.
        """
        b = self._b
        b.canvas.Clear()
        if self._is_draw:
            for i in range(4):
                for j in range(8):
                    b.light_cell(b.canvas, i, j,
                                 b.team_r.r, b.team_r.g, b.team_r.b)
            for i in range(4, 8):
                for j in range(8):
                    b.light_cell(b.canvas, i, j,
                                 b.team_l.r, b.team_l.g, b.team_l.b)
        else:
            w = self._winner_team
            assert w is not None, "_winner_team accessed before being set"
            # Regenerate random inner-square colors at 20 fps — matches Pi's time.sleep(0.05)
            now = pygame.time.get_ticks()
            if not self._game_over_colors or now - self._last_game_over_ms >= 50:
                self._game_over_colors = [
                    [(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                     for _ in range(6)]
                    for _ in range(6)
                ]
                self._last_game_over_ms = now
            for m in range(8):
                b.light_cell(b.canvas, m, 0, w.r, w.g, w.b)
                b.light_cell(b.canvas, 0, m, w.r, w.g, w.b)
                b.light_cell(b.canvas, m, 7, w.r, w.g, w.b)
                b.light_cell(b.canvas, 7, m, w.r, w.g, w.b)
            for j in range(6):
                for k in range(6):
                    r, g, bv = self._game_over_colors[j][k]
                    b.light_cell(b.canvas, j + 1, k + 1, r, g, bv)
        b.matrix.blit_to_screen()

    # ── Event handlers ─────────────────────────────────────────────────────────

    def _handle_lobby(self, event: pygame.event.Event) -> None:
        """Handle input events in the LOBBY phase.

        Arrow keys or W/S navigate the option list.  Enter or mouse click
        on a row selects the highlighted option.

        Args:
            event: The Pygame event to process.
        """
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_UP, pygame.K_w):
                self._lobby_selected = (self._lobby_selected - 1) % len(_LOBBY_OPTIONS)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self._lobby_selected = (self._lobby_selected + 1) % len(_LOBBY_OPTIONS)
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._lobby_select(self._lobby_selected)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            px, py = event.pos
            if px < _BOARD_W:
                cell = self._px_to_cell(px, py)
                if cell is not None:
                    opt_idx = cell[0] // 2   # two rows per option
                    self._lobby_selected = opt_idx
                    self._lobby_select(opt_idx)

    def _lobby_select(self, opt_idx: int) -> None:
        """Execute the lobby option at *opt_idx*.

        Option 0 (Play Locally) advances directly to COLOR_PICK.
        Options 1-3 (Host / Join / Watch) will be wired to
        NetworkedGameRunner in a future task; for now they fall back to
        local play with a log message.

        Args:
            opt_idx: Index into ``_LOBBY_OPTIONS`` (0–3).
        """
        label = _LOBBY_OPTIONS[opt_idx]
        if opt_idx == 0:
            logger.info("Lobby: Play Locally selected")
            self.phase = Phase.COLOR_PICK
        else:
            logger.info("Lobby: '%s' selected — network play not yet implemented", label)

    def _handle_color_pick(self, event: pygame.event.Event) -> None:
        """Handle mouse clicks during the COLOR_PICK phase.

        A click on row 2 assigns a colour to the right team; a click on
        row 5 assigns a colour to the left team. Once both teams have
        chosen, applies the Board's colour-picker bug lock-in and advances
        the phase to WAR_GAMES.

        Args:
            event: The Pygame event to process.
        """
        if event.type != pygame.MOUSEBUTTONDOWN:
            return
        cell = self._px_to_cell(*event.pos)
        if cell is None:
            return
        row, col = cell
        b = self._b
        if row == 2:
            self._selected_r_idx = col
            t = b.team_array[col]
            b.team_r.r, b.team_r.g, b.team_r.b = t.r, t.g, t.b
            b.team_r.name = _COLOR_NAMES[col]
        elif row == 5:
            self._selected_l_idx = col
            t = b.team_array[col]
            b.team_l.r, b.team_l.g, b.team_l.b = t.r, t.g, t.b
            b.team_l.name = _COLOR_NAMES[col]
        if self._selected_r_idx is not None and self._selected_l_idx is not None:
            b.team_r.r += 1  # BUG LOCK-IN: mirrors Board.color_picker() line 902
            self.phase = Phase.WAR_GAMES

    def _handle_war_games(self, event: pygame.event.Event) -> None:
        """Handle mouse clicks during the WAR_GAMES phase.

        A click on row 3 sets whether the right team is Human or AI
        (cols 0-3 = Human, cols 4-7 = AI). A click on row 4 does the same
        for the left team (cols 0-3 = AI, cols 4-7 = Human). Once both
        sides are decided, ``_start_game()`` is called.

        Args:
            event: The Pygame event to process.
        """
        if event.type != pygame.MOUSEBUTTONDOWN:
            return
        cell = self._px_to_cell(*event.pos)
        if cell is None:
            return
        row, col = cell
        b = self._b
        if row == 3:
            b.computer_player_r = col >= 4   # cols 4-7 = AI, 0-3 = Human
        elif row == 4:
            b.computer_player_l = col < 4    # cols 0-3 = AI, 4-7 = Human (kitty-corner)
        if b.computer_player_r is not None and b.computer_player_l is not None:
            self._start_game()

    def _start_game(self) -> None:
        """Initialize the board for play and begin the right team's first turn.

        Calls ``Board.initialize_game_board()`` to place all pieces, sets
        the active team to ``team_r``, transitions to the PLAYING phase, and
        delegates to ``_begin_turn``.
        """
        b = self._b
        b.initialize_game_board()
        self._current_team = b.team_r
        self.phase = Phase.PLAYING
        logger.info(
            "Running game... Right=%s (%d,%d,%d)  Left=%s (%d,%d,%d)",
            b.team_r.name, b.team_r.r, b.team_r.g, b.team_r.b,
            b.team_l.name, b.team_l.r, b.team_l.g, b.team_l.b,
        )
        self._begin_turn(self._current_team)

    def _handle_playing(self, event: pygame.event.Event) -> None:
        """Handle input during the PLAYING phase.

        Pressing N resets the game. Mouse clicks outside the board deselect
        the current piece. Clicks on the board either select a friendly
        piece, execute a legal move for the already-selected piece, or
        deselect if the same piece is clicked again. Input is ignored while
        the AI is thinking.

        Args:
            event: The Pygame event to process.
        """
        if event.type == pygame.KEYDOWN and event.key == pygame.K_n:
            self._reset()
            self._init_board()
            return
        if self._promoting_pawn is not None:
            if event.type == pygame.MOUSEBUTTONDOWN:
                cell = self._px_to_cell(*event.pos)
                p_row, p_col = self._promoting_pawn
                if not self._promoting_lifted:
                    # Click the pawn to "lift" it and begin cycling
                    if cell == (p_row, p_col):
                        self._promoting_lifted = True
                        self._promoting_index = 0
                        self._promoting_last_cycle_ms = pygame.time.get_ticks()
                else:
                    # Any click "sets the piece down" and confirms the current choice
                    _CANDIDATES: list[type[Queen] | type[Knight] | type[Bishop] | type[Rook]] = [
                        Queen, Knight, Bishop, Rook
                    ]
                    chosen_cls = _CANDIDATES[self._promoting_index]
                    pawn = self._b.grid[p_row][p_col]
                    assert isinstance(pawn, Pawn)
                    self._b.grid[p_row][p_col] = chosen_cls(p_row, p_col, pawn.team)
                    logger.info("Promoted pawn to %s at (%d,%d)",
                                chosen_cls.__name__, p_row, p_col)
                    self._promoting_pawn = None
                    self._promoting_lifted = False
                    self._next_turn()
            return
        if event.type != pygame.MOUSEBUTTONDOWN:
            return
        if self._ai_thinking:
            return
        cell = self._px_to_cell(*event.pos)
        if cell is None:
            self._selected_piece = None
            return
        row, col = cell
        b = self._b
        assert self._current_team is not None, "_current_team not set in _handle_playing"
        current_team = self._current_team

        if self._selected_piece is not None:
            for target in self._selected_piece.targets:
                if target.row == row and target.col == col:
                    old_r = self._selected_piece.row
                    old_c = self._selected_piece.col
                    logger.debug(
                        "Human moves piece at %s%s to %s%s",
                        old_r, old_c, row, col)
                    if b.grid[row][col] is not None:
                        self.peace_time = 0
                    else:
                        self.peace_time += 1
                    b.grid[row][col] = b.grid[old_r][old_c]
                    self._apply_move(old_r, old_c, row, col)
                    self._move_count += 1
                    self._selected_piece = None
                    if self._promoting_pawn is None:
                        self._next_turn()
                    return
            piece = b.grid[row][col]
            if piece is self._selected_piece:
                # Clicking the already-selected piece puts it back down
                self._selected_piece = None
            elif piece is not None and piece.team.r == current_team.r:
                self._selected_piece = piece
            else:
                self._selected_piece = None
        else:
            piece = b.grid[row][col]
            if piece is not None and piece.team.r == current_team.r:
                self._selected_piece = piece

    def _handle_game_over(self, event: pygame.event.Event) -> None:
        """Handle input during the GAME_OVER phase.

        Pressing N resets all game state and re-initialises the board so a
        new game can be started.

        Args:
            event: The Pygame event to process.
        """
        if event.type == pygame.KEYDOWN and event.key == pygame.K_n:
            self._reset()
            self._init_board()

    def _handle_event(self, event: pygame.event.Event) -> None:
        """Route a Pygame event to the handler for the current phase.

        Args:
            event: The Pygame event to dispatch.
        """
        if self.phase == Phase.NAME_ENTRY:
            self._handle_name_entry(event)
        elif self.phase == Phase.LOBBY:
            self._handle_lobby(event)
        elif self.phase == Phase.COLOR_PICK:
            self._handle_color_pick(event)
        elif self.phase == Phase.WAR_GAMES:
            self._handle_war_games(event)
        elif self.phase == Phase.PLAYING:
            self._handle_playing(event)
        elif self.phase == Phase.GAME_OVER:
            self._handle_game_over(event)

    # ── Update ─────────────────────────────────────────────────────────────────

    def _update(self) -> None:
        """Advance time-driven state for the current frame.

        During WAR_GAMES, advances the animation dot counters every 200 ms.
        During PLAYING with an active AI, launches the AI worker thread on
        the first call, and on subsequent calls checks whether the thread
        has finished; when it has, applies the best move found and hands
        off to the next turn.
        """
        now = pygame.time.get_ticks()
        if self.phase == Phase.WAR_GAMES and now - self._last_think_ms >= 200:
            self._last_think_ms = now
            self._think = (self._think + 1) % 4
            self._think_l = (self._think_l + 1) % 8
            self._think_r = (self._think_r + 1) % 8
        if self.phase == Phase.PLAYING and self._ai_thinking:
            if self._ai_thread is None:
                self._execute_ai_move()
            elif not self._ai_thread.is_alive():
                self._ai_thread = None
                best = self._ai_result
                if best is not None and best.old_cell is not None and best.new_cell is not None:
                    b = self._b
                    old_r, old_c = best.old_cell.row, best.old_cell.col
                    tgt_r, tgt_c = best.new_cell.row, best.new_cell.col
                    logger.debug(
                        "the best move involves moving the piece at square %s%s to %s%s",
                        old_r, old_c, tgt_r, tgt_c)
                    if b.grid[tgt_r][tgt_c] is not None:
                        self.peace_time = 0
                    else:
                        self.peace_time += 1
                    b.grid[tgt_r][tgt_c] = b.grid[old_r][old_c]
                    self._apply_move(old_r, old_c, tgt_r, tgt_c)
                    self._move_count += 1
                self._ai_thinking = False
                self._next_turn()

    def _render_panel_extra(self, text, sep, pfont_sm, pfont_md) -> None:
        """Hook for subclasses to inject extra panel rows before the log.

        Called at the end of ``_render_panel`` just before the log separator.
        The default implementation is a no-op.
        """

    def _render_panel(self) -> None:
        """Draw the telemetry / log side panel to the right of the board."""
        if self._pfont_sm is None or self._pfont_md is None or self._pfont_lg is None:
            return  # fonts not ready (before _init_board)
        pfont_sm = self._pfont_sm
        pfont_md = self._pfont_md
        pfont_lg = self._pfont_lg
        screen = self._b.matrix._screen
        if screen is None:
            return

        pad = 14
        x0  = _BOARD_W          # left edge of panel
        w   = _PANEL_W
        h   = 32 * _SCALE

        pygame.draw.rect(screen, _P_BG, (x0, 0, w, h))

        y = 10

        def text(msg: str, font, color, indent: int = 0) -> None:
            nonlocal y
            surf = font.render(msg, True, color)
            screen.blit(surf, (x0 + pad + indent, y))
            y += surf.get_height() + 3

        def sep() -> None:
            nonlocal y
            y += 5
            pygame.draw.line(screen, _P_SEP,
                             (x0 + pad, y), (x0 + w - pad, y))
            y += 8

        def color_swatch(rgb: tuple, cx: int, cy: int, r: int = 7) -> None:
            pygame.draw.circle(screen, rgb, (cx, cy), r)
            pygame.draw.circle(screen, _P_SEP, (cx, cy), r, 1)

        # ── Title ────────────────────────────────────────────────────────────
        text("Chess 101", pfont_lg, _P_TEXT)
        sep()

        # ── Phase ────────────────────────────────────────────────────────────
        text(f"Phase   {self.phase.name}", pfont_md, _P_DIM)

        b = self._b

        # ── Phase-specific status ─────────────────────────────────────────────
        if self.phase == Phase.NAME_ENTRY:
            text("Type your name, then", pfont_sm, _P_DIM)
            text("press Enter to connect.", pfont_sm, _P_DIM)
            if self._player_name:
                text(f"Name: {self._player_name}", pfont_md, _P_TEXT)

        elif self.phase == Phase.LOBBY:
            for i, opt in enumerate(_LOBBY_OPTIONS):
                prefix = "> " if i == self._lobby_selected else "  "
                col = _LOBBY_COLORS[i]
                text(f"{prefix}{opt}", pfont_md,
                     col if i == self._lobby_selected else _P_DIM)

        elif self.phase == Phase.COLOR_PICK:
            text("Row 2 → Right team colour", pfont_sm, _P_DIM)
            text("Row 5 → Left  team colour", pfont_sm, _P_DIM)
            if self._selected_r_idx is not None:
                tc = b.team_r
                text(f"Right  {tc.name}", pfont_sm,
                     (tc.r, tc.g, tc.b))
            if self._selected_l_idx is not None:
                tc = b.team_l
                text(f"Left   {tc.name}", pfont_sm,
                     (tc.r, tc.g, tc.b))

        elif self.phase == Phase.WAR_GAMES:
            text("Row 3 left=Human right=AI", pfont_sm, _P_DIM)
            text("Row 4 left=AI    right=Human", pfont_sm, _P_DIM)

        elif self.phase in (Phase.PLAYING, Phase.GAME_OVER):
            # ── Current team ──────────────────────────────────────────────
            if self._current_team is not None:
                tc = self._current_team
                surf_t = pfont_md.render(
                    f"Turn    {tc.name}", True, (tc.r, tc.g, tc.b))
                screen.blit(surf_t, (x0 + pad, y))
                swatch_x = x0 + pad + surf_t.get_width() + 10
                swatch_y = y + surf_t.get_height() // 2
                color_swatch((tc.r, tc.g, tc.b), swatch_x, swatch_y)
                y += surf_t.get_height() + 3

            text(f"Move    #{self._move_count}", pfont_md, _P_TEXT)

            # ── Peace-time progress bar ───────────────────────────────────
            peace = self.peace_time
            text(f"Peace   {peace} / 50", pfont_sm, _P_DIM)
            bar_w  = w - pad * 2
            bar_h  = 9
            pygame.draw.rect(screen, _P_SEP,
                             (x0 + pad, y, bar_w, bar_h), border_radius=4)
            filled = int(bar_w * min(peace, 50) / 50)
            if filled > 0:
                ratio = peace / 50
                bar_c = (
                    int(_P_GOOD[0] + (_P_BAD[0] - _P_GOOD[0]) * ratio),
                    int(_P_GOOD[1] + (_P_BAD[1] - _P_GOOD[1]) * ratio),
                    int(_P_GOOD[2] + (_P_BAD[2] - _P_GOOD[2]) * ratio),
                )
                pygame.draw.rect(screen, bar_c,
                                 (x0 + pad, y, filled, bar_h), border_radius=4)
            y += bar_h + 8

            # ── Alerts ────────────────────────────────────────────────────
            if self._in_check:
                blink = (pygame.time.get_ticks() // 380) % 2
                text("!! KING IN CHECK",
                     pfont_md, _P_BAD if blink else _P_WARN)

            if self._ai_thinking:
                dots = "." * ((pygame.time.get_ticks() // 320) % 4 + 1)
                text(f"AI thinking{dots}", pfont_md, _P_WARN)

            # ── Game-over result ──────────────────────────────────────────
            if self.phase == Phase.GAME_OVER:
                sep()
                if self._is_draw:
                    text("  DRAW", pfont_lg, _P_WARN)
                elif self._winner_team:
                    wt = self._winner_team
                    text(f"  {wt.name} wins!",
                         pfont_lg, (wt.r, wt.g, wt.b))
                text("Press N to play again", pfont_sm, _P_DIM)

        self._render_panel_extra(text, sep, pfont_sm, pfont_md)

        sep()

        # ── Log feed ─────────────────────────────────────────────────────────
        text("LOG", pfont_md, _P_DIM)

        line_h   = pfont_sm.get_height() + 2
        avail_h  = h - y - pad
        max_lines = max(1, avail_h // line_h)
        char_w   = pfont_sm.size("X")[0]
        max_chars = max(1, (w - pad * 2) // char_w)

        records = list(self._panel_handler.records)
        # Collect all wrapped lines, then show the most recent ones that fit
        all_lines: list[tuple[str, tuple[int, int, int]]] = []
        for rec in records:
            src    = _LOG_SRC.get(rec.name, rec.name.split(".")[-1][:3])
            prefix = f"{rec.levelname[0]}[{src}] "
            msg    = rec.getMessage()
            color  = _P_LEVEL.get(rec.levelno, _P_TEXT)
            indent = " " * len(prefix)
            for wrapped_line in textwrap.wrap(
                msg, width=max_chars,
                initial_indent=prefix,
                subsequent_indent=indent,
            ) or [prefix]:
                all_lines.append((wrapped_line, color))
        for line, color in all_lines[-max_lines:]:
            surf = pfont_sm.render(line, True, color)
            screen.blit(surf, (x0 + pad, y))
            y += line_h
            if y >= h - pad:
                break

    def _render(self) -> None:
        """Render the current frame by delegating to the phase-specific renderer.

        Calls the appropriate ``_render_*`` method for the active phase,
        then draws the side panel and flips the Pygame display buffer.
        """
        if self.phase == Phase.NAME_ENTRY:
            self._render_name_entry()
        elif self.phase == Phase.LOBBY:
            self._render_lobby()
        elif self.phase == Phase.COLOR_PICK:
            self._render_color_pick()
        elif self.phase == Phase.WAR_GAMES:
            self._render_war_games()
        elif self.phase == Phase.PLAYING:
            self._render_playing()
        elif self.phase == Phase.GAME_OVER:
            self._render_game_over()
        self._render_panel()
        self._pre_flip()
        pygame.display.flip()

    def _pre_flip(self) -> None:
        """Hook called just before ``pygame.display.flip()`` each frame.

        Subclasses can override to blit overlays onto the screen without
        causing a double-flip artefact.
        """

    # ── Game loop ──────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Start the simulator: initialise Pygame, create the board, and run the game loop.

        Configures the root logger, opens the Pygame window sized to fit the
        LED board canvas plus the side panel, initialises the Board with
        fake hardware, then enters the main 60 fps event/update/render loop
        until the window is closed.
        """
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(levelname)s %(name)s: %(message)s",
        )
        pygame.init()
        pygame.display.set_mode((_WIN_W, 32 * _SCALE))
        pygame.display.set_caption("Chess101 Simulator")
        clock = pygame.time.Clock()
        self._init_board()

        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                else:
                    self._handle_event(event)
            self._update()
            self._render()
            clock.tick(60)

        pygame.quit()
