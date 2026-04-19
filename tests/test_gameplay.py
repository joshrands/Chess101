"""
test_gameplay.py — Integration tests for Chess101 gameplay logic.

Two layers of coverage:
  1. Pure chess logic (no display) — piece calc_targets, move(), post-capture
     board state.  Uses the same imports as the rest of the test suite.
  2. GameRunner integration (headless pygame) — full move execution through the
     simulator's event handlers, verifying grid state after moves.

Run with:
    .venv/bin/python -m pytest tests/test_gameplay.py -v
"""
from __future__ import annotations

import copy
import os
import sys
import types

import pytest

# ── Headless pygame for GameRunner tests ──────────────────────────────────────
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

# Override any existing rgbmatrix stub from conftest so GameRunner gets our fake
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

# ── Chess module imports (safe now that stubs are in place) ───────────────────
from Pawn import Pawn          # noqa: E402  (shim → pieces/pawn.py)
from Rook import Rook          # noqa: E402
from Bishop import Bishop      # noqa: E402
from Knight import Knight      # noqa: E402
from Queen import Queen        # noqa: E402
from King import King          # noqa: E402
from Team import Team          # noqa: E402
from Cell import Cell          # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _board():
    return [[None] * 8 for _ in range(8)]


def _teams():
    """Return (team_r, team_l) with distinct colours matching Board defaults."""
    return Team(64, 180, 232), Team(255, 140, 0)


def _targets(piece):
    return {(c.row, c.col) for c in piece.targets}


# ─────────────────────────────────────────────────────────────────────────────
# Pawn — calc_targets
# ─────────────────────────────────────────────────────────────────────────────

class TestPawnCapture:

    def test_diagonal_left_capture_included(self):
        """Pawn must list the diagonal-left enemy square as a target."""
        tr, tl = _teams()
        pawn = Pawn(3, 4, tr)   # direction=1, so captures at row 4
        enemy = Rook(4, 3, tl)
        board = _board()
        board[3][4] = pawn
        board[4][3] = enemy
        pawn.calc_targets(board)
        assert (4, 3) in _targets(pawn), \
            "Pawn should be able to capture diagonally to the left"

    def test_diagonal_right_capture_included(self):
        """Pawn must list the diagonal-right enemy square as a target."""
        tr, tl = _teams()
        pawn = Pawn(3, 4, tr)
        enemy = Bishop(4, 5, tl)
        board = _board()
        board[3][4] = pawn
        board[4][5] = enemy
        pawn.calc_targets(board)
        assert (4, 5) in _targets(pawn), \
            "Pawn should be able to capture diagonally to the right"

    def test_cannot_capture_forward(self):
        """A pawn must NOT list a forward square occupied by an enemy as a target."""
        tr, tl = _teams()
        pawn = Pawn(3, 4, tr)
        blocker = Rook(4, 4, tl)
        board = _board()
        board[3][4] = pawn
        board[4][4] = blocker
        pawn.calc_targets(board)
        assert (4, 4) not in _targets(pawn), \
            "Pawn cannot capture straight ahead"

    def test_cannot_capture_own_piece_diagonally(self):
        """Pawn must not list a friendly-occupied diagonal as a target."""
        tr, _ = _teams()
        pawn = Pawn(3, 4, tr)
        friendly = Knight(4, 3, tr)
        board = _board()
        board[3][4] = pawn
        board[4][3] = friendly
        pawn.calc_targets(board)
        assert (4, 3) not in _targets(pawn), \
            "Pawn cannot capture a friendly piece"

    def test_team_l_pawn_captures_toward_lower_rows(self):
        """team_l pawns move in direction=-1 when initialised at row 6.

        BUG LOCK-IN: Pawn.direction is determined solely by the row passed to
        __init__ (row==6 → -1, else → 1).  It is NOT set from the team.
        A team_l pawn must be created at row 6 to get direction=-1; if
        initialised at any other row it will move the wrong way.
        To test a mid-board team_l pawn we must init at 6 then update .row.
        """
        tr, tl = _teams()
        pawn = Pawn(6, 4, tl)     # init at starting row → direction=-1
        pawn.row = 4              # simulate having advanced two squares
        enemy = Knight(3, 5, tr)
        board = _board()
        board[4][4] = pawn
        board[3][5] = enemy
        pawn.calc_targets(board)
        assert (3, 5) in _targets(pawn), \
            "team_l pawn (direction=-1) should capture diagonally toward row 3"

    def test_direction_set_by_row_not_team(self):
        """BUG LOCK-IN: direction is row-based, not team-based.
        A team_l pawn initialised at a non-6 row gets direction=1 (upward),
        which is wrong for team_l.  Tests confirm the known behaviour so
        regressions are caught.
        """
        _, tl = _teams()
        wrong = Pawn(4, 4, tl)    # team_l but NOT at row 6
        assert wrong.direction == 1, \
            "Pawn initialised at row!=6 always gets direction=1 regardless of team"

    def test_pawn_at_column_edge_no_index_error(self):
        """Pawn at col=0 or col=7 with adjacent enemy must not raise IndexError."""
        tr, tl = _teams()
        pawn_left = Pawn(3, 0, tr)
        board = _board()
        board[3][0] = pawn_left
        board[4][1] = Rook(4, 1, tl)
        pawn_left.calc_targets(board)   # col-1 would be -1 — must be guarded
        assert (4, 1) in _targets(pawn_left)

        pawn_right = Pawn(3, 7, tr)
        board[3][7] = pawn_right
        board[4][6] = Rook(4, 6, tl)
        pawn_right.calc_targets(board)   # col+1 would be 8 — must be guarded
        assert (4, 6) in _targets(pawn_right)


# ─────────────────────────────────────────────────────────────────────────────
# Pawn — move() and post-capture grid state
# ─────────────────────────────────────────────────────────────────────────────

class TestPawnMoveState:

    def test_normal_capture_grid_state(self):
        """After executing a capture the old square is None, new square has the pawn."""
        tr, tl = _teams()
        pawn = Pawn(3, 4, tr)
        enemy = Rook(4, 3, tl)
        board = _board()
        board[3][4] = pawn
        board[4][3] = enemy

        # Mimic GameRunner._handle_playing execute-move sequence
        board[4][3] = board[3][4]          # move piece to target
        pawn.move(4, 3, board)             # update internal state
        board[3][4] = None                 # clear old square

        assert board[3][4] is None, "Old square must be empty after capture"
        assert board[4][3] is pawn, "New square must hold the capturing pawn"
        assert pawn.row == 4, "pawn.row must reflect new position"
        assert pawn.col == 3, "pawn.col must reflect new position"

    def test_grid_index_matches_piece_coords_after_move(self):
        """piece.row/col must match where the piece sits in the grid after a move."""
        tr, tl = _teams()
        pawn = Pawn(1, 3, tr)
        board = _board()
        board[1][3] = pawn

        board[2][3] = board[1][3]
        pawn.move(2, 3, board)
        board[1][3] = None

        for r in range(8):
            for c in range(8):
                p = board[r][c]
                if p is pawn:
                    assert (p.row, p.col) == (r, c), \
                        f"Piece at grid ({r},{c}) has stale coords ({p.row},{p.col})"

    def test_en_passant_removes_captured_pawn(self):
        """En passant move must remove the captured pawn from the board."""
        tr, tl = _teams()
        attacker = Pawn(4, 4, tr)   # team_r, direction=1
        victim = Pawn(4, 5, tl)     # team_l, just moved two squares → en_passantable
        victim.en_passantable = True
        board = _board()
        board[4][4] = attacker
        board[4][5] = victim
        attacker.calc_targets(board)
        assert (5, 5) in _targets(attacker), "En passant target should be listed"

        # Execute en passant
        board[5][5] = board[4][4]
        captured_cell = attacker.move(5, 5, board)
        board[4][4] = None
        if captured_cell is not None:
            board[captured_cell.row][captured_cell.col] = None

        assert board[4][5] is None, "En passant victim must be removed from board"
        assert board[5][5] is attacker


# ─────────────────────────────────────────────────────────────────────────────
# GameRunner integration (headless pygame)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def runner():
    """A fully initialised GameRunner in PLAYING phase (Human vs Human)."""
    import pygame
    pygame.init()
    pygame.display.set_mode((640, 640))

    from simulator.app import GameRunner, Phase
    gr = GameRunner()
    gr._init_board()

    b = gr._board
    # Apply colours (skip full color_picker flow)
    b.team_r.r, b.team_r.g, b.team_r.b = 65, 180, 232   # blue +1
    b.team_l.r, b.team_l.g, b.team_l.b = 255, 140, 0    # orange

    b.computer_player_r = False
    b.computer_player_l = False
    gr._start_game()

    yield gr

    pygame.quit()


class TestGameRunnerMoves:

    def test_opening_grid_has_pieces(self, runner):
        b = runner._board
        # After transpose fix: King at col 3, Queen at col 4
        assert b.grid[0][3] is not None, "King should be at (0,3)"
        assert isinstance(b.grid[0][3], King)
        assert b.grid[1][0] is not None, "team_r pawn should be at (1,0)"
        assert isinstance(b.grid[1][0], Pawn)

    def test_pawn_targets_calculated_at_start(self, runner):
        """After _begin_turn, team_r pawns should have forward targets."""
        pawn = runner._board.grid[1][4]
        assert pawn is not None and isinstance(pawn, Pawn)
        assert len(pawn.targets) > 0, "Pawns should have targets at game start"

    def test_human_pawn_move_updates_grid(self, runner):
        """Executing a pawn move via _apply_move must update the grid correctly."""
        b = runner._board
        # Move pawn from (1,4) to (3,4) (two-square opening)
        old_r, old_c = 1, 4
        new_r, new_c = 3, 4
        assert b.grid[old_r][old_c] is not None
        piece = b.grid[old_r][old_c]

        b.grid[new_r][new_c] = b.grid[old_r][old_c]
        runner._apply_move(old_r, old_c, new_r, new_c)

        assert b.grid[old_r][old_c] is None, "Old square must be empty after move"
        assert b.grid[new_r][new_c] is piece, "New square must have the moved piece"
        assert piece.row == new_r and piece.col == new_c, \
            "Piece internal coords must match new grid position"

    def test_grid_index_always_matches_piece_coords(self, runner):
        """Every piece on the board must have piece.row/col matching its grid slot."""
        b = runner._board
        for r in range(8):
            for c in range(8):
                p = b.grid[r][c]
                if p is not None:
                    assert (p.row, p.col) == (r, c), \
                        f"{type(p).__name__} at grid({r},{c}) has stale coords ({p.row},{p.col})"

    def test_pawn_diagonal_capture_via_apply_move(self, runner):
        """A pawn placed adjacent to an enemy can capture diagonally."""
        b = runner._board
        tr, tl = b.team_r, b.team_l

        # Place a fresh scenario on an empty corner of the board
        attacker = Pawn(3, 3, tr)
        victim = Rook(4, 4, tl)
        b.grid[3][3] = attacker
        b.grid[4][4] = victim

        attacker.calc_targets(b.grid)
        assert (4, 4) in {(c.row, c.col) for c in attacker.targets}, \
            "Pawn must be able to target the diagonal enemy square"

        # Execute the capture
        b.grid[4][4] = b.grid[3][3]
        runner._apply_move(3, 3, 4, 4)

        assert b.grid[3][3] is None
        assert b.grid[4][4] is attacker
        assert attacker.row == 4 and attacker.col == 4

        # Clean up
        b.grid[4][4] = None

    def test_render_playing_does_not_raise(self, runner):
        """_render_playing must complete without exceptions."""
        runner._render_playing()   # uses blit_to_screen + overlay + display.flip
