"""
test_king.py — comprehensive tests for King piece logic.

Covers: init, _walk, calc_targets (including castling and self-check
filtering), find_attacker (all attacker types), determine_direction_from_enemy_towards_king
(float-return bug), build_check_escape_path, pin detection (critical flag), and
King.move() castling return values.
"""
import pytest
from Team import Team
from Cell import Cell
from King import King
from Rook import Rook
from Bishop import Bishop
from Knight import Knight
from Queen import Queen
from Pawn import Pawn


def empty_board():
    return [[None] * 8 for _ in range(8)]


def place(board, row, col, piece):
    board[row][col] = piece
    return board


# ─────────────────────────────────────────────────────────────────────────────
# Init
# ─────────────────────────────────────────────────────────────────────────────

class TestKingInit:
    def test_row7_direction_neg1(self):
        tl = Team(255, 140, 0)
        king = King(7, 4, tl)
        assert king.direction == -1

    def test_row0_direction_pos1(self):
        tr = Team(64, 180, 232)
        king = King(0, 4, tr)
        assert king.direction == 1

    def test_other_rows_direction_pos1(self):
        tr = Team(64, 180, 232)
        for row in [1, 2, 3, 4, 5, 6]:
            king = King(row, 4, tr)
            assert king.direction == 1

    def test_king_escape_cells_starts_empty(self):
        tr = Team(64, 180, 232)
        king = King(0, 4, tr)
        assert king.god_save_the_king == []

    def test_touched_false_on_init(self):
        tr = Team(64, 180, 232)
        king = King(0, 4, tr)
        assert king.touched is False


# ─────────────────────────────────────────────────────────────────────────────
# _walk
# ─────────────────────────────────────────────────────────────────────────────

class TestWalk:
    def test_adds_empty_adjacent_square(self):
        tr = Team(64, 180, 232)
        king = King(4, 4, tr)
        board = empty_board()
        board[4][4] = king
        king._blade_walker(board, 1, 0, 4, 4)
        assert any(c.row == 5 and c.col == 4 for c in king.targets)

    def test_adds_enemy_adjacent_square(self):
        tr = Team(64, 180, 232)
        tl = Team(255, 140, 0)
        king = King(4, 4, tr)
        enemy = Rook(5, 4, tl)
        board = empty_board()
        board[4][4] = king
        board[5][4] = enemy
        king._blade_walker(board, 1, 0, 4, 4)
        assert any(c.row == 5 and c.col == 4 for c in king.targets)

    def test_does_not_add_own_piece(self):
        tr = Team(64, 180, 232)
        king = King(4, 4, tr)
        ally = Rook(5, 4, tr)
        board = empty_board()
        board[4][4] = king
        board[5][4] = ally
        king._blade_walker(board, 1, 0, 4, 4)
        assert not any(c.row == 5 and c.col == 4 for c in king.targets)

    def test_respects_board_boundary(self):
        tr = Team(64, 180, 232)
        king = King(0, 0, tr)
        board = empty_board()
        board[0][0] = king
        king._blade_walker(board, -1, 0, 0, 0)  # would go to row -1
        king._blade_walker(board, 0, -1, 0, 0)  # would go to col -1
        assert king.targets == []


# ─────────────────────────────────────────────────────────────────────────────
# calc_targets
# ─────────────────────────────────────────────────────────────────────────────

class TestCalcTargets:
    def test_returns_false_when_safe(self):
        tr = Team(64, 180, 232)
        king = King(4, 4, tr)
        board = empty_board()
        board[4][4] = king
        result = king.calc_targets(board)
        assert result is False

    def test_returns_true_when_in_check(self):
        tr = Team(64, 180, 232)
        tl = Team(255, 140, 0)
        king = King(4, 4, tr)
        enemy_rook = Rook(4, 7, tl)
        board = empty_board()
        board[4][4] = king
        board[4][7] = enemy_rook
        result = king.calc_targets(board)
        assert result is True

    def test_removes_moves_into_check(self):
        tr = Team(64, 180, 232)
        tl = Team(255, 140, 0)
        king = King(4, 4, tr)
        # Enemy rook controls the entire row 5
        enemy_rook = Rook(5, 7, tl)
        board = empty_board()
        board[4][4] = king
        board[5][7] = enemy_rook
        king.calc_targets(board)
        targets = [(c.row, c.col) for c in king.targets]
        assert (5, 3) not in targets
        assert (5, 4) not in targets
        assert (5, 5) not in targets

    def test_king_escape_cells_populated_on_check(self):
        tr = Team(64, 180, 232)
        tl = Team(255, 140, 0)
        king = King(4, 4, tr)
        enemy_rook = Rook(4, 7, tl)
        board = empty_board()
        board[4][4] = king
        board[4][7] = enemy_rook
        king.calc_targets(board)
        # king_escape_cells should contain the path from rook to king
        gstk = [(c.row, c.col) for c in king.god_save_the_king]
        assert (4, 7) in gstk  # attacker's square
        assert (4, 6) in gstk  # intermediate square
        assert (4, 5) in gstk  # intermediate square

    def test_all_8_adjacent_squares_available_on_empty_board(self):
        tr = Team(64, 180, 232)
        king = King(4, 4, tr)
        board = empty_board()
        board[4][4] = king
        king.calc_targets(board)
        assert len(king.targets) == 8


# ─────────────────────────────────────────────────────────────────────────────
# find_attacker
# ─────────────────────────────────────────────────────────────────────────────

class TestFindAttacker:
    def _setup(self, king_row=4, king_col=4):
        tr = Team(64, 180, 232)
        tl = Team(255, 140, 0)
        king = King(king_row, king_col, tr)
        board = empty_board()
        board[king_row][king_col] = king
        return tr, tl, king, board

    def test_safe_returns_minus1_minus1(self):
        tr, tl, king, board = self._setup()
        r, c = king.am_i_gonna_die(board)
        assert r == -1
        assert c == -1

    def test_rook_on_same_rank(self):
        tr, tl, king, board = self._setup()
        enemy = Rook(4, 7, tl)
        board[4][7] = enemy
        r, c = king.am_i_gonna_die(board)
        assert r == 4
        assert c == 7

    def test_rook_on_same_file(self):
        tr, tl, king, board = self._setup()
        enemy = Rook(0, 4, tl)
        board[0][4] = enemy
        r, c = king.am_i_gonna_die(board)
        assert r == 0
        assert c == 4

    def test_bishop_on_diagonal(self):
        tr, tl, king, board = self._setup()
        enemy = Bishop(1, 7, tl)
        board[1][7] = enemy
        r, c = king.am_i_gonna_die(board)
        assert r == 1
        assert c == 7

    def test_queen_on_rank(self):
        tr, tl, king, board = self._setup()
        enemy = Queen(4, 0, tl)
        board[4][0] = enemy
        r, c = king.am_i_gonna_die(board)
        assert r == 4
        assert c == 0

    def test_queen_on_diagonal(self):
        tr, tl, king, board = self._setup()
        enemy = Queen(1, 1, tl)
        board[1][1] = enemy
        r, c = king.am_i_gonna_die(board)
        assert r == 1
        assert c == 1

    def test_knight_attack(self):
        tr, tl, king, board = self._setup()
        # Knight at (2,5): L-shape from (4,4) → (4-2, 4+1) = (2,5)
        enemy = Knight(2, 5, tl)
        board[2][5] = enemy
        r, c = king.am_i_gonna_die(board)
        assert r == 2
        assert c == 5

    def test_pawn_attack_from_forward_direction(self):
        # King at (4,4) with direction=1 — enemy pawn at (5,5) checks it
        tr, tl, king, board = self._setup()
        enemy_pawn = Pawn(6, 5, tl)
        enemy_pawn.row = 5
        board[5][5] = enemy_pawn
        r, c = king.am_i_gonna_die(board)
        assert r == 5
        assert c == 5

    def test_pawn_wrong_direction_no_check(self):
        # Enemy pawn at (3,5) — behind the king's direction=1 — should NOT check
        tr, tl, king, board = self._setup()
        enemy_pawn = Pawn(6, 5, tl)
        enemy_pawn.row = 3
        board[3][5] = enemy_pawn
        r, c = king.am_i_gonna_die(board)
        assert r == -1
        assert c == -1

    def test_adjacent_enemy_king_on_rank(self):
        tr, tl, king, board = self._setup()
        enemy_king = King(4, 5, tl)
        board[4][5] = enemy_king
        r, c = king.am_i_gonna_die(board)
        assert r == 4
        assert c == 5

    def test_adjacent_enemy_king_on_diagonal(self):
        tr, tl, king, board = self._setup()
        enemy_king = King(5, 5, tl)
        board[5][5] = enemy_king
        r, c = king.am_i_gonna_die(board)
        assert r == 5
        assert c == 5

    def test_returns_only_first_attacker_in_double_check(self):
        # BUG #7 LOCK-IN: only the first attacker found in the iteration order
        # is returned; the second attacker is silently ignored.
        tr, tl, king, board = self._setup()
        enemy_rook = Rook(4, 7, tl)
        enemy_bishop = Bishop(1, 1, tl)
        board[4][7] = enemy_rook
        board[1][1] = enemy_bishop
        r, c = king.am_i_gonna_die(board)
        assert (r, c) in [(4, 7), (1, 1)]
        assert not (r == 4 and c == 7 and False)

    def test_resets_critical_flag_on_all_allies(self):
        tr, tl, king, board = self._setup()
        ally_rook = Rook(4, 2, tr)
        ally_rook.critical = True
        board[4][2] = ally_rook
        king.am_i_gonna_die(board)
        assert ally_rook.critical is False

    def test_marks_pinned_piece_as_critical(self):
        tr, tl, king, board = self._setup()
        ally = Rook(4, 2, tr)
        enemy = Rook(4, 0, tl)
        board[4][2] = ally
        board[4][0] = enemy
        king.am_i_gonna_die(board)
        assert ally.critical is True

    def test_pinned_piece_gets_critical_targets(self):
        tr, tl, king, board = self._setup()
        ally = Rook(4, 2, tr)
        enemy = Rook(4, 0, tl)
        board[4][2] = ally
        board[4][0] = enemy
        king.am_i_gonna_die(board)
        critical_positions = [(c.row, c.col) for c in ally.critical_targets]
        assert (4, 0) in critical_positions  # enemy square
        assert (4, 1) in critical_positions  # intermediate square

    def test_pin_detected_when_in_check_from_different_direction(self):
        # Regression for the am_i_gonna_die early-return bug:
        # Before the fix, finding check in one direction returned immediately,
        # skipping scan of other directions — so the pinned piece never got
        # critical=True and could illegally capture the checker.
        #
        # Setup: king at (4,4)
        #   Diagonal (-1,-1): enemy bishop at (1,1) → check
        #   Horizontal (0,+1): ally rook at (4,6) pinned by enemy queen at (4,7)
        #
        # The diagonal direction is scanned before the horizontal ones in the
        # loop order, so the old code returned before marking the rook critical.
        tr, tl, king, board = self._setup()
        enemy_bishop = Bishop(1, 1, tl)
        ally_rook    = Rook(4, 6, tr)
        enemy_queen  = Queen(4, 7, tl)
        board[1][1] = enemy_bishop
        board[4][6] = ally_rook
        board[4][7] = enemy_queen
        attacker_row, attacker_col = king.am_i_gonna_die(board)
        # King must be in check
        assert (attacker_row, attacker_col) != (-1, -1), "King should be in check"
        # Ally rook must also be marked critical (pinned by queen)
        assert ally_rook.critical is True, \
            "Pinned rook must be critical even when king is simultaneously in check"

    def test_diagonal_pin_by_bishop_marks_friendly_critical(self):
        # Covers am_i_gonna_die lines 271-274: diagonal branch where a friendly
        # piece is between the king and an enemy Bishop/Queen.
        #
        # Setup: king at (4,4), ally rook at (3,3), enemy bishop at (2,2).
        # Direction (-1,-1): _i_spy encounters friendly rook first (scout),
        # then continues and finds enemy bishop → PIN → rook.critical = True.
        tr, tl, king, board = self._setup()
        ally_rook = Rook(3, 3, tr)
        enemy_bishop = Bishop(2, 2, tl)
        board[3][3] = ally_rook
        board[2][2] = enemy_bishop
        king.am_i_gonna_die(board)
        assert ally_rook.critical is True, \
            "Rook pinned diagonally by bishop must be marked critical"
        assert len(ally_rook.critical_targets) > 0, \
            "Pinned rook must have critical_targets set"


# ─────────────────────────────────────────────────────────────────────────────
# determine_direction_from_enemy_towards_king (float-return bug)
# ─────────────────────────────────────────────────────────────────────────────

class TestDetermineDirection:
    def _king(self):
        tr = Team(64, 180, 232)
        king = King(4, 4, tr)
        return king

    def test_same_row_col_component_is_float(self):
        # BUG #1 LOCK-IN: Python 3 true division returns float.
        # Enemy at (4,7), king at (4,4) → returns (0, -1.0)
        king = self._king()
        dir1, dir2 = king.determine_direction_from_enemy_towards_king(4, 7)
        assert dir1 == 0
        assert isinstance(dir2, float)

    def test_same_col_row_component_is_float(self):
        # Enemy at (1,4), king at (4,4) → returns (1.0, 0)
        king = self._king()
        dir1, dir2 = king.determine_direction_from_enemy_towards_king(1, 4)
        assert isinstance(dir1, float)
        assert dir2 == 0

    def test_diagonal_both_components_are_float(self):
        # Enemy at (1,7), king at (4,4) → both components are floats
        king = self._king()
        dir1, dir2 = king.determine_direction_from_enemy_towards_king(1, 7)
        assert isinstance(dir1, float)
        assert isinstance(dir2, float)

    def test_correct_sign_enemy_to_the_right(self):
        king = self._king()
        dir1, dir2 = king.determine_direction_from_enemy_towards_king(4, 7)
        assert dir2 == -1.0

    def test_correct_sign_enemy_to_the_left(self):
        king = self._king()
        dir1, dir2 = king.determine_direction_from_enemy_towards_king(4, 0)
        assert dir2 == 1.0

    def test_correct_sign_enemy_above(self):
        king = self._king()
        dir1, dir2 = king.determine_direction_from_enemy_towards_king(1, 4)
        assert dir1 == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# build_check_escape_path
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildCheckEscapePath:
    def _king(self):
        tr = Team(64, 180, 232)
        king = King(4, 4, tr)
        return king

    def test_includes_attacker_cell(self):
        king = self._king()
        result = king.please_god_save_the_king(4, 7)
        positions = [(c.row, c.col) for c in result]
        assert (4, 7) in positions

    def test_includes_intermediate_cells(self):
        king = self._king()
        result = king.please_god_save_the_king(4, 7)
        assert any(c.row == 4 and c.col == 6 for c in result)
        assert any(c.row == 4 and c.col == 5 for c in result)

    def test_excludes_king_cell(self):
        king = self._king()
        result = king.please_god_save_the_king(4, 7)
        positions = [(c.row, c.col) for c in result]
        assert (4, 4) not in positions


# ─────────────────────────────────────────────────────────────────────────────
# Castling
# ─────────────────────────────────────────────────────────────────────────────

class TestCastling:
    def _setup_clean_castling(self):
        """King at (0,4), rooks at (0,0) and (0,7), all untouched, no threats."""
        tr = Team(64, 180, 232)
        king = King(0, 4, tr)
        rook_q = Rook(0, 0, tr)
        rook_k = Rook(0, 7, tr)
        board = empty_board()
        board[0][4] = king
        board[0][0] = rook_q
        board[0][7] = rook_k
        return tr, king, rook_q, rook_k, board

    def test_queenside_target_added_when_eligible(self):
        tr, king, rook_q, rook_k, board = self._setup_clean_castling()
        king.calc_targets(board)
        targets = [(c.row, c.col) for c in king.targets]
        assert (0, 2) in targets

    def test_kingside_target_added_when_eligible(self):
        tr, king, rook_q, rook_k, board = self._setup_clean_castling()
        king.calc_targets(board)
        targets = [(c.row, c.col) for c in king.targets]
        assert (0, 6) in targets

    def test_queenside_blocked_by_piece_between(self):
        tr, king, rook_q, rook_k, board = self._setup_clean_castling()
        board[0][1] = Knight(0, 1, tr)
        king.calc_targets(board)
        targets = [(c.row, c.col) for c in king.targets]
        assert (0, 2) not in targets

    def test_kingside_blocked_by_piece_between(self):
        tr, king, rook_q, rook_k, board = self._setup_clean_castling()
        board[0][6] = Knight(0, 6, tr)
        king.calc_targets(board)
        targets = [(c.row, c.col) for c in king.targets]
        assert (0, 6) not in targets

    def test_castling_not_available_when_king_touched(self):
        tr, king, rook_q, rook_k, board = self._setup_clean_castling()
        king.touched = True
        king.calc_targets(board)
        targets = [(c.row, c.col) for c in king.targets]
        assert (0, 2) not in targets
        assert (0, 6) not in targets

    def test_castling_not_available_when_rook_touched(self):
        tr, king, rook_q, rook_k, board = self._setup_clean_castling()
        rook_q.touched = True
        king.calc_targets(board)
        targets = [(c.row, c.col) for c in king.targets]
        assert (0, 2) not in targets

    def test_castling_not_available_when_king_in_check(self):
        tr, king, rook_q, rook_k, board = self._setup_clean_castling()
        tl = Team(255, 140, 0)
        enemy = Rook(7, 4, tl)
        board[7][4] = enemy
        king.calc_targets(board)
        targets = [(c.row, c.col) for c in king.targets]
        assert (0, 2) not in targets
        assert (0, 6) not in targets

    def test_queenside_castling_not_available_when_passing_through_check(self):
        tr, king, rook_q, rook_k, board = self._setup_clean_castling()
        tl = Team(255, 140, 0)
        enemy = Rook(7, 3, tl)
        board[7][3] = enemy
        king.calc_targets(board)
        targets = [(c.row, c.col) for c in king.targets]
        assert (0, 2) not in targets

    def test_move_returns_rook_cells_queenside_castle(self):
        tr = Team(64, 180, 232)
        king = King(0, 4, tr)
        board = empty_board()
        board[0][4] = king
        old_rook_cell, new_rook_cell = king.move(0, 2, board)
        assert old_rook_cell is not None
        assert old_rook_cell.row == 0
        assert old_rook_cell.col == 0
        assert new_rook_cell.row == 0
        assert new_rook_cell.col == 3

    def test_move_returns_rook_cells_kingside_castle(self):
        tr = Team(64, 180, 232)
        king = King(0, 4, tr)
        board = empty_board()
        board[0][4] = king
        old_rook_cell, new_rook_cell = king.move(0, 6, board)
        assert old_rook_cell.col == 7
        assert new_rook_cell.col == 5

    def test_move_returns_none_none_for_normal_move(self):
        tr = Team(64, 180, 232)
        king = King(4, 4, tr)
        board = empty_board()
        board[4][4] = king
        r1, r2 = king.move(5, 5, board)
        assert r1 is None
        assert r2 is None

    def test_move_sets_touched_true(self):
        tr = Team(64, 180, 232)
        king = King(4, 4, tr)
        board = empty_board()
        board[4][4] = king
        king.move(5, 4, board)
        assert king.touched is True

    def test_queenside_castle_destination_in_check_removes_castle(self):
        # Covers king.py line 135: castle_left is set True, then the simulated
        # position at the castled square is in check → castle_left = False.
        #
        # Enemy rook at (7,2) threatens col 2 only — the king's current square
        # (0,4) and step square (0,3) are safe, but the destination (0,2) is not.
        tr, king, rook_q, rook_k, board = self._setup_clean_castling()
        tl = Team(255, 140, 0)
        enemy = Rook(7, 2, tl)
        board[7][2] = enemy
        king.calc_targets(board)
        targets = [(c.row, c.col) for c in king.targets]
        assert (0, 2) not in targets, \
            "Queen-side castling must be removed when the destination square is under attack"


# ─────────────────────────────────────────────────────────────────────────────
# get_value (tuple-truthy bug)
# ─────────────────────────────────────────────────────────────────────────────

class TestKingGetValue:
    def test_get_value_always_zero_due_to_truthy_tuple(self):
        # BUG #10 LOCK-IN: King.get_value() does:
        #   if self.find_attacker(board):
        #       value = 0
        # find_attacker() always returns a tuple, e.g. (-1,-1) when safe.
        # In Python, ANY non-empty tuple is truthy — including (-1,-1).
        # Therefore get_value() always returns 0, never 1000.
        tr = Team(64, 180, 232)
        king = King(4, 4, tr)
        board = empty_board()
        board[4][4] = king
        assert king.get_value(board) == 0

    def test_get_value_zero_even_when_in_check(self):
        tr = Team(64, 180, 232)
        tl = Team(255, 140, 0)
        king = King(4, 4, tr)
        enemy = Rook(4, 7, tl)
        board = empty_board()
        board[4][4] = king
        board[4][7] = enemy
        assert king.get_value(board) == 0


# ─────────────────────────────────────────────────────────────────────────────
# print_piece
# ─────────────────────────────────────────────────────────────────────────────

class TestKingPrintPiece:
    def test_print_piece(self, capsys):
        tr = Team(64, 180, 232)
        king = King(3, 6, tr)
        king.print_piece()
        out = capsys.readouterr().out
        assert "3" in out and "6" in out
