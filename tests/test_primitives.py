"""
test_primitives.py — tests for Cell, Team, and the Piece abstract base class.

Piece is tested via Rook as a concrete subclass (it's the simplest sliding
piece and has no special-case logic of its own).
"""
import pytest
from Cell import Cell
from Team import Team
from Rook import Rook
from Piece import Piece


# ── Cell ─────────────────────────────────────────────────────────────────────

class TestCell:
    def test_default_init(self):
        c = Cell()
        assert c.row == 0
        assert c.col == 0

    def test_custom_init(self):
        c = Cell(3, 5)
        assert c.row == 3
        assert c.col == 5

    def test_attribute_names_are_row_and_col(self):
        c = Cell(2, 7)
        assert hasattr(c, "row")
        assert hasattr(c, "col")
        assert not hasattr(c, "x")
        assert not hasattr(c, "y")


# ── Team ─────────────────────────────────────────────────────────────────────

class TestTeam:
    def test_stores_rgb(self):
        t = Team(10, 20, 30)
        assert t.r == 10
        assert t.g == 20
        assert t.b == 30

    def test_default_name_is_wendy(self):
        # BUG LOCK-IN: hardcoded default name — must not change during refactor.
        t = Team(0, 0, 0)
        assert t.name == "Wendy"

    def test_set_name(self):
        t = Team(0, 0, 0)
        t.set_name("Alice")
        assert t.name == "Alice"

    def test_two_teams_are_independent(self):
        a = Team(100, 50, 0)
        b = Team(100, 200, 0)
        # Same r, different g/b — they are separate objects
        assert a.g != b.g
        assert a is not b


# ── Piece base class (via Rook) ───────────────────────────────────────────────

class TestPieceBase:
    def _rook(self, row=0, col=0, team=None):
        if team is None:
            team = Team(64, 180, 232)
        return Rook(row, col, team)

    def _board(self):
        return [[None] * 8 for _ in range(8)]

    # ── Default attribute values ──

    def test_piece_touched_false_on_init(self):
        r = self._rook()
        assert r.touched is False

    def test_piece_critical_false_on_init(self):
        r = self._rook()
        assert r.critical is False

    def test_piece_targets_empty_on_init(self):
        r = self._rook()
        assert r.targets == []

    def test_piece_critical_targets_empty_on_init(self):
        r = self._rook()
        assert r.critical_targets == []

    # ── move() ──

    def test_move_updates_position(self):
        r = self._rook(0, 0)
        board = self._board()
        board[0][0] = r
        r.move(3, 4, board)
        assert r.row == 3
        assert r.col == 4

    def test_move_sets_touched_true(self):
        r = self._rook(0, 0)
        board = self._board()
        board[0][0] = r
        r.move(3, 4, board)
        assert r.touched is True

    # ── get_targets() ──

    def test_get_targets_returns_targets_list(self):
        r = self._rook()
        assert r.get_targets() is r.targets

    # ── filter_to_king_escape() ──

    def test_skyfall_keeps_targets_in_king_escape_cells(self):
        team = Team(64, 180, 232)
        rook = self._rook(4, 0, team)
        rook.targets = [Cell(4, 1), Cell(4, 2), Cell(4, 3)]

        from King import King
        king = King(4, 7, team)
        king.god_save_the_king = [Cell(4, 2), Cell(4, 3)]

        rook.sky_fall(king)
        assert len(rook.targets) == 2
        cols = {c.col for c in rook.targets}
        assert cols == {2, 3}

    def test_skyfall_clears_all_when_no_overlap(self):
        team = Team(64, 180, 232)
        rook = self._rook(0, 0, team)
        rook.targets = [Cell(0, 1), Cell(0, 2)]

        from King import King
        king = King(0, 7, team)
        king.god_save_the_king = [Cell(3, 3)]

        rook.sky_fall(king)
        assert rook.targets == []

    # ── filter_to_pin_ray() ──

    def test_critical_man_intersects_targets_with_critical_targets(self):
        rook = self._rook()
        rook.targets = [Cell(0, 1), Cell(0, 2), Cell(0, 3)]
        rook.critical_targets = [Cell(0, 2), Cell(0, 5)]
        rook.critical_man()
        assert len(rook.targets) == 1
        assert rook.targets[0].col == 2

    def test_critical_man_empty_when_no_overlap(self):
        rook = self._rook()
        rook.targets = [Cell(0, 1), Cell(0, 2)]
        rook.critical_targets = [Cell(5, 5)]
        rook.critical_man()
        assert rook.targets == []

    # ── _ray_cast() ──

    def test_kingsman_finds_enemy_piece(self):
        team_r = Team(64, 180, 232)
        team_l = Team(255, 140, 0)
        rook = Rook(3, 3, team_r)
        enemy = Rook(3, 6, team_l)
        board = [[None] * 8 for _ in range(8)]
        board[3][3] = rook
        board[3][6] = enemy
        # _ray_cast looks in dir (0,1) starting from (3,4)
        row, col = rook._kingsman(board, 3, 4, 0, 1)
        assert row == 3
        assert col == 6

    def test_kingsman_returns_minus1_when_blocked_by_own_piece(self):
        team_r = Team(64, 180, 232)
        rook = Rook(3, 3, team_r)
        ally = Rook(3, 5, team_r)
        board = [[None] * 8 for _ in range(8)]
        board[3][3] = rook
        board[3][5] = ally
        row, col = rook._kingsman(board, 3, 4, 0, 1)
        assert row == -1
        assert col == -1

    def test_kingsman_returns_minus1_when_empty_ray(self):
        team_r = Team(64, 180, 232)
        rook = Rook(3, 3, team_r)
        board = [[None] * 8 for _ in range(8)]
        board[3][3] = rook
        row, col = rook._kingsman(board, 3, 4, 0, 1)
        assert row == -1
        assert col == -1
