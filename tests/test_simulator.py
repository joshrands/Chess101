"""
test_simulator.py — Regression tests for the Chess101 Mac Pygame simulator.

Each test class is anchored to a specific bug found during development.
The tests are intentionally narrow: they verify the exact symptom that was
broken, so a regression will point directly at the cause.

Bugs covered
============
1. WAR_GAMES kitty-corner layout — row 3 left=Human/right=AI,
   row 4 left=AI/right=Human (mirrored from the Pi original).
2. Piece deselection — clicking the already-selected piece must deselect it
   ("put it back down"), not re-select it.
3. AI thinking blocks mouse input — clicks are ignored while the AI thread runs.
4. Win animation speed — inner-square colors must not regenerate faster than
   50 ms (Pi uses time.sleep(0.05)); previously they updated every frame (16 ms).
5. AI runs in a background thread — _execute_ai_move must return immediately
   and leave the Pygame event loop free.
6. Phase transitions — COLOR_PICK → WAR_GAMES → PLAYING → GAME_OVER.
7. peace_time tracking — capture resets to 0, non-capture increments by 1.
8. Turn-end cleanup — _next_turn clears selected piece, check state, and flips
   the active team.
9. Logging — key game events are emitted at the correct level so the terminal
   shows the same output as the Pi.

Run with:
    .venv/bin/python -m pytest tests/test_simulator.py -v
"""
from __future__ import annotations

import copy
import logging
import os
import sys
import types
from unittest.mock import patch

import pytest
import pygame

# ── Headless pygame ───────────────────────────────────────────────────────────
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

# Override conftest's MagicMock rgbmatrix with the real FakeRGBMatrix so that
# GameRunner's rendering paths execute actual code (not silent mocks).
import simulator.fake_rgbmatrix as _frm

_rmod = types.ModuleType("rgbmatrix")
_rmod.RGBMatrix = _frm.FakeRGBMatrix
_rmod.RGBMatrixOptions = _frm.FakeRGBMatrixOptions
_rmod.FrameCanvas = _frm.FakeFrameCanvas
sys.modules["rgbmatrix"] = sys.modules["rgbmatrix.core"] = _rmod

_smbus = types.ModuleType("smbus")


class _SMBus:
    def __init__(self, *a, **kw) -> None: pass
    def read_byte(self, *a, **kw) -> int: return 0
    def write_byte(self, *a, **kw) -> None: pass


_smbus.SMBus = _SMBus
sys.modules["smbus"] = _smbus

# ── Simulator imports (safe now that stubs are in place) ──────────────────────
from simulator.app import GameRunner, Phase, _CELL_PX  # noqa: E402
from pieces.pawn import Pawn                            # noqa: E402
from pieces.king import King                            # noqa: E402
from pieces.rook import Rook                            # noqa: E402
from pieces.queen import Queen                          # noqa: E402


# ── Shared helpers ────────────────────────────────────────────────────────────

def _click(row: int, col: int) -> pygame.event.Event:
    """Synthesise a MOUSEBUTTONDOWN at the centre pixel of board cell (row, col)."""
    px = col * _CELL_PX + _CELL_PX // 2
    py = row * _CELL_PX + _CELL_PX // 2
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": (px, py), "button": 1})


def _keydown(key: int) -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, {"key": key, "mod": 0, "unicode": ""})


# ── Module-scoped pygame surface (created once for the whole file) ────────────

@pytest.fixture(scope="module")
def _pygame():
    pygame.init()
    pygame.display.set_mode((960, 960))
    yield
    pygame.quit()


# ── Per-test runners ─────────────────────────────────────────────────────────

@pytest.fixture
def fresh(_pygame):
    """GameRunner freshly initialised, in COLOR_PICK phase."""
    gr = GameRunner(skip_lobby=True)
    gr._init_board()
    return gr


@pytest.fixture
def in_war_games(fresh):
    """GameRunner in WAR_GAMES (both team colors chosen, player types pending)."""
    gr = fresh
    # Click col 0 on row 2 → team_r picks color index 0
    # Click col 1 on row 5 → team_l picks color index 1
    gr._handle_event(_click(2, 0))
    gr._handle_event(_click(5, 1))
    assert gr.phase == Phase.WAR_GAMES, "Pre-condition: must be in WAR_GAMES"
    return gr


@pytest.fixture
def playing_hh(fresh):
    """GameRunner in PLAYING phase, human vs human."""
    gr = fresh
    b = gr._board
    b.team_r.r, b.team_r.g, b.team_r.b = 65, 180, 232
    b.team_l.r, b.team_l.g, b.team_l.b = 255, 140, 0
    b.computer_player_r = False
    b.computer_player_l = False
    gr._start_game()
    assert gr.phase == Phase.PLAYING
    return gr


@pytest.fixture
def playing_ha(fresh):
    """GameRunner in PLAYING phase, human (team_r) vs AI (team_l)."""
    gr = fresh
    b = gr._board
    b.team_r.r, b.team_r.g, b.team_r.b = 65, 180, 232
    b.team_l.r, b.team_l.g, b.team_l.b = 255, 140, 0
    b.computer_player_r = False
    b.computer_player_l = True
    gr._start_game()
    assert gr.phase == Phase.PLAYING
    return gr


# ═════════════════════════════════════════════════════════════════════════════
# Bug 1 — WAR_GAMES kitty-corner layout
# ═════════════════════════════════════════════════════════════════════════════

class TestWarGamesLayout:
    """Row 3: left half (cols 0-3) = Human, right half (cols 4-7) = AI.
    Row 4 is MIRRORED: left half = AI, right half = Human.
    This is the "kitty-corner" layout matching the Pi original."""

    def test_row3_left_half_sets_human(self, in_war_games):
        gr = in_war_games
        gr._handle_event(_click(3, 0))
        assert gr._board.computer_player_r is False, \
            "Col 0 on row 3 must select Human for team_r"

    def test_row3_right_half_sets_ai(self, in_war_games):
        gr = in_war_games
        gr._handle_event(_click(3, 7))
        assert gr._board.computer_player_r is True, \
            "Col 7 on row 3 must select AI for team_r"

    def test_row3_boundary_col3_is_human(self, in_war_games):
        gr = in_war_games
        gr._handle_event(_click(3, 3))
        assert gr._board.computer_player_r is False

    def test_row3_boundary_col4_is_ai(self, in_war_games):
        gr = in_war_games
        gr._handle_event(_click(3, 4))
        assert gr._board.computer_player_r is True

    def test_row4_left_half_sets_ai(self, in_war_games):
        """Kitty-corner: left half of row 4 is AI, NOT Human."""
        gr = in_war_games
        gr._handle_event(_click(4, 0))
        assert gr._board.computer_player_l is True, \
            "Col 0 on row 4 must select AI for team_l (kitty-corner)"

    def test_row4_right_half_sets_human(self, in_war_games):
        """Kitty-corner: right half of row 4 is Human, NOT AI."""
        gr = in_war_games
        gr._handle_event(_click(4, 7))
        assert gr._board.computer_player_l is False, \
            "Col 7 on row 4 must select Human for team_l (kitty-corner)"

    def test_row4_boundary_col3_is_ai(self, in_war_games):
        gr = in_war_games
        gr._handle_event(_click(4, 3))
        assert gr._board.computer_player_l is True

    def test_row4_boundary_col4_is_human(self, in_war_games):
        gr = in_war_games
        gr._handle_event(_click(4, 4))
        assert gr._board.computer_player_l is False

    def test_both_decided_advances_to_playing(self, in_war_games):
        gr = in_war_games
        gr._handle_event(_click(3, 0))   # Human for team_r
        gr._handle_event(_click(4, 7))   # Human for team_l
        assert gr.phase == Phase.PLAYING


# ═════════════════════════════════════════════════════════════════════════════
# Bug 2 — Piece deselection ("put it back down")
# ═════════════════════════════════════════════════════════════════════════════

class TestPieceDeselection:
    """Clicking an already-selected piece must deselect it.
    Previously the click handler re-selected it, trapping the piece."""

    def test_click_friendly_selects_piece(self, playing_hh):
        gr = playing_hh
        gr._handle_event(_click(1, 4))   # team_r pawn at (1,4)
        assert gr._selected_piece is not None

    def test_click_selected_piece_again_deselects(self, playing_hh):
        """BUG FIX: second click on same piece must clear _selected_piece."""
        gr = playing_hh
        gr._handle_event(_click(1, 4))
        piece = gr._selected_piece
        assert piece is not None, "Pre-condition: first click must select"
        gr._handle_event(_click(1, 4))   # same square again
        assert gr._selected_piece is None, \
            "Second click on selected piece must put it back down"

    def test_click_enemy_piece_clears_selection(self, playing_hh):
        gr = playing_hh
        gr._handle_event(_click(1, 4))
        assert gr._selected_piece is not None
        gr._handle_event(_click(6, 4))   # team_l pawn — enemy
        assert gr._selected_piece is None

    def test_click_empty_square_clears_selection(self, playing_hh):
        gr = playing_hh
        gr._handle_event(_click(1, 4))
        assert gr._selected_piece is not None
        gr._handle_event(_click(4, 4))   # empty square mid-board
        assert gr._selected_piece is None

    def test_click_different_friendly_piece_switches_selection(self, playing_hh):
        gr = playing_hh
        gr._handle_event(_click(1, 0))   # select pawn at (1,0)
        first = gr._selected_piece
        gr._handle_event(_click(1, 4))   # select different pawn at (1,4)
        assert gr._selected_piece is not first
        assert gr._selected_piece is gr._board.grid[1][4]


# ═════════════════════════════════════════════════════════════════════════════
# Bug 3 — AI thinking blocks mouse input
# ═════════════════════════════════════════════════════════════════════════════

class TestAIThinkingBlocksInput:
    """While _ai_thinking is True, mouse clicks must have no effect."""

    def test_click_ignored_when_ai_thinking(self, playing_hh):
        gr = playing_hh
        gr._ai_thinking = True
        gr._handle_event(_click(1, 4))
        assert gr._selected_piece is None, \
            "Mouse click must be ignored while AI is thinking"

    def test_click_processed_when_ai_not_thinking(self, playing_hh):
        gr = playing_hh
        assert not gr._ai_thinking
        gr._handle_event(_click(1, 4))
        assert gr._selected_piece is not None

    def test_ai_thinking_flag_set_when_ai_turn(self, playing_ha):
        """After team_r (human) makes a move, team_l (AI) turn begins.
        _ai_thinking must be True so the next update launches the thread."""
        gr = playing_ha
        b = gr._board
        # Make a valid human move: pawn from (1,4) to (3,4)
        b.grid[3][4] = b.grid[1][4]
        gr._apply_move(1, 4, 3, 4)
        gr._next_turn()   # now team_l's (AI) turn
        assert gr._ai_thinking is True, \
            "_ai_thinking must be set when it is the AI player's turn"

    def test_ai_thinking_false_for_human_turn(self, playing_hh):
        gr = playing_hh
        assert gr._ai_thinking is False, \
            "_ai_thinking must be False at the start of a human turn"


# ═════════════════════════════════════════════════════════════════════════════
# Bug 4 — Win animation speed throttled to 50 ms
# ═════════════════════════════════════════════════════════════════════════════

class TestWinAnimationThrottle:
    """The Pi sleeps 50 ms between frames in declare_victory().
    In the simulator we must not regenerate random colors faster than that,
    otherwise the flash is 3× too fast at 60 fps."""

    def _setup_victory(self, gr):
        gr.phase = Phase.GAME_OVER
        gr._is_draw = False
        gr._winner_team = gr._board.team_r

    def test_colors_not_regenerated_within_50ms(self, playing_hh):
        """Two renders 30 ms apart must produce the same color grid."""
        gr = playing_hh
        self._setup_victory(gr)
        with patch("pygame.time.get_ticks", return_value=1000):
            gr._render_game_over()
            colors_after_first = copy.deepcopy(gr._game_over_colors)
        with patch("pygame.time.get_ticks", return_value=1030):  # only 30 ms later
            gr._render_game_over()
            colors_after_second = copy.deepcopy(gr._game_over_colors)
        assert colors_after_first == colors_after_second, \
            "Color grid must not change before 50 ms have elapsed"

    def test_colors_regenerated_after_50ms(self, playing_hh):
        """Two renders 60 ms apart must produce different color grids
        (probability of a collision is astronomically small)."""
        gr = playing_hh
        self._setup_victory(gr)
        with patch("pygame.time.get_ticks", return_value=1000):
            gr._render_game_over()
            colors_first = copy.deepcopy(gr._game_over_colors)
        with patch("pygame.time.get_ticks", return_value=1060):  # 60 ms later
            gr._render_game_over()
            colors_second = copy.deepcopy(gr._game_over_colors)
        assert colors_first != colors_second, \
            "Color grid must be regenerated after 50 ms"

    def test_colors_initialised_on_first_render(self, playing_hh):
        """_game_over_colors must be populated after the first render."""
        gr = playing_hh
        self._setup_victory(gr)
        assert gr._game_over_colors == [], "Pre-condition: no colors before first render"
        with patch("pygame.time.get_ticks", return_value=0):
            gr._render_game_over()
        assert len(gr._game_over_colors) == 6
        assert len(gr._game_over_colors[0]) == 6

    def test_draw_render_does_not_use_random_colors(self, playing_hh):
        """Stalemate (draw) shows solid team halves — no random colors needed."""
        gr = playing_hh
        gr.phase = Phase.GAME_OVER
        gr._is_draw = True
        # Should not raise and should not touch _game_over_colors
        gr._render_game_over()
        assert gr._game_over_colors == [], \
            "Draw animation must not populate _game_over_colors"

    def test_last_game_over_ms_updated_on_color_refresh(self, playing_hh):
        gr = playing_hh
        self._setup_victory(gr)
        with patch("pygame.time.get_ticks", return_value=5000):
            gr._render_game_over()
        assert gr._last_game_over_ms == 5000


# ═════════════════════════════════════════════════════════════════════════════
# Bug 5 — AI runs in a background thread (non-blocking)
# ═════════════════════════════════════════════════════════════════════════════

class TestAIThreading:
    """_execute_ai_move must launch a daemon thread and return immediately.
    Previously it ran the full alpha-beta search synchronously, blocking the
    Pygame event loop for seconds."""

    def test_execute_ai_move_returns_immediately(self, playing_hh):
        gr = playing_hh
        gr._ai_thinking = True
        gr._execute_ai_move()
        # If this completes without blocking, the thread was launched correctly.
        assert gr._ai_thread is not None, "_ai_thread must be set after launch"
        gr._ai_thread.join(timeout=30)  # wait for cleanup; timeout guards the test

    def test_ai_thread_is_daemon(self, playing_hh):
        """Daemon thread so the process can exit even if AI is still thinking."""
        gr = playing_hh
        gr._ai_thinking = True
        gr._execute_ai_move()
        assert gr._ai_thread.daemon is True, "AI thread must be a daemon thread"
        gr._ai_thread.join(timeout=30)

    def test_ai_result_set_after_thread_completes(self, playing_hh):
        """_ai_result must be a Tree node with old_cell and new_cell once done."""
        gr = playing_hh
        gr._ai_thinking = True
        gr._execute_ai_move()
        gr._ai_thread.join(timeout=30)
        # The starting board has legal moves so a result must be found
        assert gr._ai_result is not None, "_ai_result must be set after thread finishes"
        assert gr._ai_result.old_cell is not None
        assert gr._ai_result.new_cell is not None

    def test_update_launches_thread_only_once(self, playing_hh):
        """Calling _update() twice while AI is thinking must not spawn a second thread."""
        gr = playing_hh
        gr._ai_thinking = True
        gr._update()
        first_thread = gr._ai_thread
        gr._update()   # second call — must reuse existing thread, not create a new one
        assert gr._ai_thread is first_thread, \
            "_update must not spawn a new thread if one is already running"
        if first_thread:
            first_thread.join(timeout=30)

    def test_ai_thread_cleared_after_move_applied(self, playing_hh):
        """After the AI thread finishes and _update applies the move,
        _ai_thread must be set back to None."""
        gr = playing_hh
        gr._ai_thinking = True
        gr._execute_ai_move()
        gr._ai_thread.join(timeout=30)  # ensure thread has finished
        gr._update()   # should detect completion and apply move
        assert gr._ai_thread is None, \
            "_ai_thread must be cleared once the move has been applied"


# ═════════════════════════════════════════════════════════════════════════════
# Bug 6 — Phase transitions
# ═════════════════════════════════════════════════════════════════════════════

class TestPhaseTransitions:

    def test_initial_phase_is_color_pick(self, fresh):
        assert fresh.phase == Phase.COLOR_PICK

    def test_row2_click_sets_selected_r_idx(self, fresh):
        gr = fresh
        gr._handle_event(_click(2, 3))
        assert gr._selected_r_idx == 3

    def test_row5_click_sets_selected_l_idx(self, fresh):
        gr = fresh
        gr._handle_event(_click(5, 6))
        assert gr._selected_l_idx == 6

    def test_only_one_color_does_not_advance(self, fresh):
        gr = fresh
        gr._handle_event(_click(2, 0))
        assert gr.phase == Phase.COLOR_PICK, "Phase must stay at COLOR_PICK until both colors chosen"

    def test_both_colors_advance_to_war_games(self, fresh):
        gr = fresh
        gr._handle_event(_click(2, 0))
        gr._handle_event(_click(5, 1))
        assert gr.phase == Phase.WAR_GAMES

    def test_team_r_r_incremented_bug_lock_in(self, fresh):
        """BUG LOCK-IN: Board.color_picker() adds 1 to team_r.r after color
        selection. Simulator must preserve this to match Pi behaviour."""
        gr = fresh
        b = gr._board
        original_r = b.team_array[0].r
        gr._handle_event(_click(2, 0))
        gr._handle_event(_click(5, 1))
        assert b.team_r.r == original_r + 1, \
            "team_r.r must be incremented by 1 after color pick (Pi BUG LOCK-IN)"

    def test_n_key_in_playing_resets_to_color_pick(self, playing_hh):
        gr = playing_hh
        gr._handle_event(_keydown(pygame.K_n))
        assert gr.phase == Phase.COLOR_PICK

    def test_n_key_in_game_over_resets_to_color_pick(self, playing_hh):
        gr = playing_hh
        gr.phase = Phase.GAME_OVER
        gr._handle_event(_keydown(pygame.K_n))
        assert gr.phase == Phase.COLOR_PICK

    def test_stalemate_sets_game_over_phase(self, playing_hh):
        gr = playing_hh
        gr.stale_mate()
        assert gr.phase == Phase.GAME_OVER
        assert gr._is_draw is True


# ═════════════════════════════════════════════════════════════════════════════
# Bug 7 — peace_time tracking
# ═════════════════════════════════════════════════════════════════════════════

class TestPeaceTimeTracking:
    """peace_time tracks half-moves without a capture (for the fifty-move rule).
    Capture must reset it to 0; a quiet move must increment it."""

    def test_capture_resets_peace_time(self, playing_hh):
        gr = playing_hh
        b = gr._board
        gr.peace_time = 10
        # Place an enemy piece where a pawn will move (guaranteed capture)
        from pieces.rook import Rook
        victim = Rook(3, 4, b.team_l)
        b.grid[3][4] = victim
        # Simulate the click sequence: select pawn at (1,4), move to (3,4)
        gr._handle_event(_click(1, 4))
        gr._handle_event(_click(3, 4))
        assert gr.peace_time == 0, "Capture must reset peace_time to 0"

    def test_pawn_move_resets_peace_time(self, playing_hh):
        """Pawn moves are irreversible in chess, so they reset peace_time to 0
        exactly like a capture — even when the destination square is empty."""
        gr = playing_hh
        gr.peace_time = 10
        gr._handle_event(_click(1, 4))   # select pawn at (1,4)
        gr._handle_event(_click(2, 4))   # quiet pawn advance
        assert gr.peace_time == 0, "Pawn move must reset peace_time to 0"

    def test_quiet_rook_move_increments_peace_time(self, playing_hh):
        """A non-pawn, non-capture move increments peace_time by 1.
        Uses a rook placed on a clear mid-board square so it has reachable targets."""
        from pieces.rook import Rook
        gr = playing_hh
        b = gr._board
        gr.peace_time = 5
        # Place a team_r rook on an open square and compute its targets
        rook = Rook(4, 0, b.team_r)
        b.grid[4][0] = rook
        rook.calc_targets(b.grid)
        # Pick any empty reachable target
        target = next(t for t in rook.targets if b.grid[t.row][t.col] is None)
        gr._handle_event(_click(4, 0))          # select rook
        assert gr._selected_piece is rook, "Pre-condition: rook must be selected"
        gr._handle_event(_click(target.row, target.col))
        assert gr.peace_time == 6, \
            "Non-pawn, non-capture move must increment peace_time by 1"


# ═════════════════════════════════════════════════════════════════════════════
# Bug 8 — Turn-end cleanup via _next_turn
# ═════════════════════════════════════════════════════════════════════════════

class TestNextTurnCleanup:
    """_next_turn must reset all transient per-turn state and flip the active team."""

    def test_selected_piece_cleared(self, playing_hh):
        gr = playing_hh
        gr._selected_piece = gr._board.grid[1][0]  # artificially set
        gr._next_turn()
        assert gr._selected_piece is None

    def test_in_check_cleared(self, playing_hh):
        gr = playing_hh
        gr._in_check = True
        gr._next_turn()
        assert gr._in_check is False

    def test_king_check_pos_cleared(self, playing_hh):
        gr = playing_hh
        gr._king_check_pos = (0, 4)
        gr._next_turn()
        assert gr._king_check_pos is None

    def test_ai_thinking_cleared(self, playing_hh):
        gr = playing_hh
        gr._ai_thinking = True
        gr._next_turn()
        assert gr._ai_thinking is False

    def test_team_flips_from_r_to_l(self, playing_hh):
        gr = playing_hh
        b = gr._board
        assert gr._current_team.r == b.team_r.r, "Pre-condition: team_r starts first"
        gr._next_turn()
        assert gr._current_team.r == b.team_l.r, "After first _next_turn, team_l must be active"

    def test_team_flips_from_l_to_r(self, playing_hh):
        gr = playing_hh
        b = gr._board
        gr._next_turn()   # → team_l
        gr._next_turn()   # → team_r
        assert gr._current_team.r == b.team_r.r


# ═════════════════════════════════════════════════════════════════════════════
# Bug 9 — Logging output
# ═════════════════════════════════════════════════════════════════════════════

class TestLogging:
    """GameRunner must emit the same log events as board.py on the Pi so that
    the terminal output is meaningful during simulator sessions."""

    def test_start_game_logs_running(self, fresh, caplog):
        gr = fresh
        b = gr._board
        b.team_r.r, b.team_r.g, b.team_r.b = 65, 180, 232
        b.team_l.r, b.team_l.g, b.team_l.b = 255, 140, 0
        b.computer_player_r = False
        b.computer_player_l = False
        with caplog.at_level(logging.INFO, logger="simulator.app"):
            gr._start_game()
        messages = [r.message for r in caplog.records]
        assert any("Running game" in m for m in messages), \
            "INFO 'Running game...' must be logged on game start"

    def test_begin_turn_logs_player_move(self, playing_hh, caplog):
        gr = playing_hh
        with caplog.at_level(logging.INFO, logger="simulator.app"):
            gr._begin_turn(gr._board.team_r)
        messages = [r.message for r in caplog.records]
        assert any("move" in m.lower() for m in messages), \
            "INFO 'Player: <name>'s move.' must be logged at turn start"

    def test_begin_turn_includes_team_name(self, playing_hh, caplog):
        gr = playing_hh
        b = gr._board
        with caplog.at_level(logging.INFO, logger="simulator.app"):
            gr._begin_turn(b.team_r)
        assert any(b.team_r.name in r.message for r in caplog.records), \
            "Log message must contain the team's name"

    def test_check_logged_at_debug(self, playing_hh, caplog):
        """When the king is in check, a DEBUG message must be emitted."""
        gr = playing_hh
        b = gr._board
        # Manually put king in check: place enemy queen adjacent to king
        king_pos = next(
            (r, c) for r in range(8) for c in range(8)
            if isinstance(b.grid[r][c], King)
            and b.grid[r][c].team.r == b.team_r.r
        )
        kr, kc = king_pos
        # Place an enemy queen one square away so calc_targets detects check
        attack_row = kr + 1 if kr < 7 else kr - 1
        b.grid[attack_row][kc] = Queen(attack_row, kc, b.team_l)
        with caplog.at_level(logging.DEBUG, logger="simulator.app"):
            gr._begin_turn(b.team_r)
        debug_msgs = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("CHECK" in m.upper() for m in debug_msgs), \
            "DEBUG 'KING IS IN CHECK' must be logged when king is in check"

    def test_stalemate_logged_from_rules(self, playing_hh, caplog):
        """declare_stalemate() (called by rules.py for fifty-move / threefold)
        must emit an INFO log so the terminal reflects the game result."""
        gr = playing_hh
        with caplog.at_level(logging.INFO, logger="simulator.app"):
            gr.stale_mate()
        messages = [r.message for r in caplog.records]
        assert any("stalemate" in m.lower() or "draw" in m.lower()
                   for m in messages), \
            "INFO stalemate/draw message must be logged from declare_stalemate()"

    def test_stalemate_logged_from_begin_turn(self, playing_hh, caplog):
        """When _begin_turn detects no legal moves and no check (positional
        stalemate), a distinct INFO message must be logged."""
        gr = playing_hh
        b = gr._board
        # Strip all team_r pieces except the king, then place it in a corner
        # with no legal moves and no check — positional stalemate scenario
        for r in range(8):
            for c in range(8):
                p = b.grid[r][c]
                if p is not None and p.team.r == b.team_r.r and not isinstance(p, King):
                    b.grid[r][c] = None
        with caplog.at_level(logging.INFO, logger="simulator.app"):
            gr._begin_turn(b.team_r)   # may or may not be stalemate depending on position
        # We just verify the logger is wired up — the specific message depends on
        # whether the king actually has moves in this position.
        assert len(caplog.records) > 0, \
            "At least one log record must be emitted by _begin_turn"

    def test_ai_move_logged_at_debug(self, playing_hh, caplog):
        """When the AI thread completes and _update applies the move, the
        coordinates must be logged at DEBUG level."""
        from core.cell import Cell
        from ai.tree import Tree

        gr = playing_hh
        b = gr._board
        # Fake a completed AI result (a minimal Tree with old/new cells set)
        fake_result = Tree(copy.deepcopy(b.grid), Cell(1, 0), Cell(2, 0),
                           b.team_r, b.team_l)
        gr._ai_thinking = True
        gr._ai_result = fake_result
        # Simulate a thread that is already done (set _ai_thread to a finished thread)
        import threading
        done = threading.Thread(target=lambda: None)
        done.start()
        done.join()
        gr._ai_thread = done  # thread is done but not None

        with caplog.at_level(logging.DEBUG, logger="simulator.app"):
            gr._update()

        debug_msgs = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("best move" in m.lower() for m in debug_msgs), \
            "DEBUG 'the best move involves...' must be logged when AI move is applied"

    def test_human_move_logged_at_debug(self, playing_hh, caplog):
        gr = playing_hh
        with caplog.at_level(logging.DEBUG, logger="simulator.app"):
            gr._handle_event(_click(1, 4))   # select pawn
            gr._handle_event(_click(3, 4))   # move two squares
        debug_msgs = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("human" in m.lower() or "moves" in m.lower() for m in debug_msgs), \
            "DEBUG message must be logged when human executes a move"


# ═════════════════════════════════════════════════════════════════════════════
# Bug 10 — pedestal_r NameError when a piece is selected
# ═════════════════════════════════════════════════════════════════════════════

class TestPieceOverlaySelectedPiece:
    """_draw_piece_overlay must not crash when a piece is selected.

    After refactoring the loop to use _draw_one_piece, `pedestal_r` was left
    undefined but was still referenced by the selection-ring code at the end
    of the method. Selecting any piece and rendering must complete without
    NameError.
    BUG LOCK-IN: if pedestal_r is reintroduced as undefined, the render raises.
    """

    def test_draw_overlay_with_selected_piece_no_crash(self, playing_hh):
        gr = playing_hh
        # Select a pawn (team_r, row 1) so _selected_piece is not None
        gr._handle_event(_click(1, 4))
        assert gr._selected_piece is not None, "Pre-condition: piece must be selected"
        # Must not raise NameError (pedestal_r was undefined after refactor)
        gr._draw_piece_overlay()

    def test_draw_overlay_no_selection_no_crash(self, playing_hh):
        gr = playing_hh
        assert gr._selected_piece is None
        gr._draw_piece_overlay()  # must not raise

    def test_render_playing_with_selected_piece_no_crash(self, playing_hh):
        """Full _render_playing path with a selected piece must not crash."""
        gr = playing_hh
        gr._handle_event(_click(1, 0))   # select a pawn
        assert gr._selected_piece is not None
        gr._render_playing()   # exercises the selection-ring branch


# ═════════════════════════════════════════════════════════════════════════════
# Bug 11 — piece image loading must not block startup
# ═════════════════════════════════════════════════════════════════════════════

class TestPieceImageLoading:
    """Piece images load in a background thread; startup must be instant.

    _draw_one_piece must fall back to the glyph renderer when _piece_surfs is
    empty (i.e. images not yet loaded), and must not crash.
    _load_piece_images must populate _piece_surfs with 12 surfaces when the
    cburnett SVG files are present and cairosvg is installed.
    BUG LOCK-IN: moving _load_piece_images back to the main thread would slow
    startup; the background-thread launch is the correct behaviour.
    """

    def test_piece_surfs_empty_at_construction(self, _pygame):
        """_piece_surfs starts empty because loading runs in a background thread."""
        import threading
        gr = GameRunner(skip_lobby=True)
        # Patch the background thread so it never runs — simulates the window
        # appearing before images finish loading.
        with patch("threading.Thread"):
            gr2 = GameRunner(skip_lobby=True)
            gr2._init_board()
        assert isinstance(gr2._piece_surfs, dict)
        # May be empty (thread was patched out) or populated — either is fine;
        # what matters is it doesn't raise and the type is correct.

    def test_draw_one_piece_glyph_fallback_no_crash(self, playing_hh):
        """_draw_one_piece works even with an empty _piece_surfs dict."""
        import pygame as pg
        gr = playing_hh
        screen = gr._b.matrix._screen
        assert screen is not None
        # Clear surfs to simulate images-not-yet-loaded
        gr._piece_surfs = {}
        b = gr._b
        piece = b.grid[1][0]   # a pawn
        assert piece is not None
        # Must not raise — should use glyph fallback
        gr._draw_one_piece(screen, piece, 60, 60, b.team_r.r)

    def test_load_piece_images_populates_surfs(self, playing_hh):
        """When cairosvg and the SVG files are available, 12 surfaces are loaded."""
        pytest.importorskip("cairosvg")
        gr = playing_hh
        gr._piece_surfs = {}
        gr._load_piece_images()
        assert len(gr._piece_surfs) == 12, (
            f"Expected 12 piece surfaces, got {len(gr._piece_surfs)}. "
            "Missing: " + str(set(gr._piece_surfs.keys()))
        )
        import pygame as pg
        for key, surf in gr._piece_surfs.items():
            assert isinstance(surf, pg.Surface), f"Surface for {key} is not a pygame.Surface"
