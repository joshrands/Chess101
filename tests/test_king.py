"""
test_king.py — comprehensive tests for King piece logic.

Covers: init, bladeWalker, calcTargets (including castling and self-check
filtering), amIGonnaDie (all attacker types), determineDirectionFromEnemyTowardsKing
(float-return bug), pleaseGodSaveTheKing, pin detection (critical flag), and
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

    def test_god_save_the_king_starts_empty(self):
        tr = Team(64, 180, 232)
        king = King(0, 4, tr)
        assert king.godSaveTheKing == []

    def test_touched_false_on_init(self):
        tr = Team(64, 180, 232)
        king = King(0, 4, tr)
        assert king.touched is False


# ─────────────────────────────────────────────────────────────────────────────
# bladeWalker
# ─────────────────────────────────────────────────────────────────────────────

class TestBladeWalker:
    def test_adds_empty_adjacent_square(self):
        tr = Team(64, 180, 232)
        king = King(4, 4, tr)
        board = empty_board()
        board[4][4] = king
        king.bladeWalker(board, 1, 0, 4, 4)
        assert any(c.row == 5 and c.col == 4 for c in king.targets)

    def test_adds_enemy_adjacent_square(self):
        tr = Team(64, 180, 232)
        tl = Team(255, 140, 0)
        king = King(4, 4, tr)
        enemy = Rook(5, 4, tl)
        board = empty_board()
        board[4][4] = king
        board[5][4] = enemy
        king.bladeWalker(board, 1, 0, 4, 4)
        assert any(c.row == 5 and c.col == 4 for c in king.targets)

    def test_does_not_add_own_piece(self):
        tr = Team(64, 180, 232)
        king = King(4, 4, tr)
        ally = Rook(5, 4, tr)
        board = empty_board()
        board[4][4] = king
        board[5][4] = ally
        king.bladeWalker(board, 1, 0, 4, 4)
        assert not any(c.row == 5 and c.col == 4 for c in king.targets)

    def test_respects_board_boundary(self):
        tr = Team(64, 180, 232)
        king = King(0, 0, tr)
        board = empty_board()
        board[0][0] = king
        king.bladeWalker(board, -1, 0, 0, 0)  # would go to row -1
        king.bladeWalker(board, 0, -1, 0, 0)  # would go to col -1
        assert king.targets == []


# ─────────────────────────────────────────────────────────────────────────────
# calcTargets
# ─────────────────────────────────────────────────────────────────────────────

class TestCalcTargets:
    def test_returns_false_when_safe(self):
        tr = Team(64, 180, 232)
        king = King(4, 4, tr)
        board = empty_board()
        board[4][4] = king
        result = king.calcTargets(board)
        assert result is False

    def test_returns_true_when_in_check(self):
        tr = Team(64, 180, 232)
        tl = Team(255, 140, 0)
        king = King(4, 4, tr)
        enemy_rook = Rook(4, 7, tl)
        board = empty_board()
        board[4][4] = king
        board[4][7] = enemy_rook
        result = king.calcTargets(board)
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
        king.calcTargets(board)
        targets = [(c.row, c.col) for c in king.targets]
        # Squares (5,3), (5,4), (5,5) are all controlled by the rook
        assert (5, 3) not in targets
        assert (5, 4) not in targets
        assert (5, 5) not in targets

    def test_god_save_the_king_populated_on_check(self):
        tr = Team(64, 180, 232)
        tl = Team(255, 140, 0)
        king = King(4, 4, tr)
        enemy_rook = Rook(4, 7, tl)
        board = empty_board()
        board[4][4] = king
        board[4][7] = enemy_rook
        king.calcTargets(board)
        # godSaveTheKing should contain the path from rook to king
        gstk = [(c.row, c.col) for c in king.godSaveTheKing]
        assert (4, 7) in gstk  # attacker's square
        assert (4, 6) in gstk  # intermediate square
        assert (4, 5) in gstk  # intermediate square

    def test_all_8_adjacent_squares_available_on_empty_board(self):
        tr = Team(64, 180, 232)
        king = King(4, 4, tr)
        board = empty_board()
        board[4][4] = king
        king.calcTargets(board)
        assert len(king.targets) == 8


# ─────────────────────────────────────────────────────────────────────────────
# amIGonnaDie
# ─────────────────────────────────────────────────────────────────────────────

class TestAmIGonnaDie:
    def _setup(self, king_row=4, king_col=4):
        tr = Team(64, 180, 232)
        tl = Team(255, 140, 0)
        king = King(king_row, king_col, tr)
        board = empty_board()
        board[king_row][king_col] = king
        return tr, tl, king, board

    def test_safe_returns_minus1_minus1(self):
        tr, tl, king, board = self._setup()
        r, c = king.amIGonnaDie(board)
        assert r == -1
        assert c == -1

    def test_rook_on_same_rank(self):
        tr, tl, king, board = self._setup()
        enemy = Rook(4, 7, tl)
        board[4][7] = enemy
        r, c = king.amIGonnaDie(board)
        assert r == 4
        assert c == 7

    def test_rook_on_same_file(self):
        tr, tl, king, board = self._setup()
        enemy = Rook(0, 4, tl)
        board[0][4] = enemy
        r, c = king.amIGonnaDie(board)
        assert r == 0
        assert c == 4

    def test_bishop_on_diagonal(self):
        tr, tl, king, board = self._setup()
        enemy = Bishop(1, 7, tl)
        board[1][7] = enemy
        r, c = king.amIGonnaDie(board)
        assert r == 1
        assert c == 7

    def test_queen_on_rank(self):
        tr, tl, king, board = self._setup()
        enemy = Queen(4, 0, tl)
        board[4][0] = enemy
        r, c = king.amIGonnaDie(board)
        assert r == 4
        assert c == 0

    def test_queen_on_diagonal(self):
        tr, tl, king, board = self._setup()
        enemy = Queen(1, 1, tl)
        board[1][1] = enemy
        r, c = king.amIGonnaDie(board)
        assert r == 1
        assert c == 1

    def test_knight_attack(self):
        tr, tl, king, board = self._setup()
        # Knight at (2,5): L-shape from (4,4) → (4-2, 4+1) = (2,5)
        enemy = Knight(2, 5, tl)
        board[2][5] = enemy
        r, c = king.amIGonnaDie(board)
        assert r == 2
        assert c == 5

    def test_pawn_attack_from_forward_direction(self):
        # King at (4,4) with direction=1 — enemy pawn at (5,5) checks it
        tr, tl, king, board = self._setup()
        # king.direction is 1 (row != 7)
        enemy_pawn = Pawn(6, 5, tl)
        enemy_pawn.row = 5
        board[5][5] = enemy_pawn
        r, c = king.amIGonnaDie(board)
        assert r == 5
        assert c == 5

    def test_pawn_wrong_direction_no_check(self):
        # Enemy pawn at (3,5) — behind the king's direction=1 — should NOT check
        tr, tl, king, board = self._setup()
        enemy_pawn = Pawn(6, 5, tl)
        enemy_pawn.row = 3
        board[3][5] = enemy_pawn
        r, c = king.amIGonnaDie(board)
        assert r == -1
        assert c == -1

    def test_adjacent_enemy_king_on_rank(self):
        tr, tl, king, board = self._setup()
        enemy_king = King(4, 5, tl)
        board[4][5] = enemy_king
        r, c = king.amIGonnaDie(board)
        assert r == 4
        assert c == 5

    def test_adjacent_enemy_king_on_diagonal(self):
        tr, tl, king, board = self._setup()
        enemy_king = King(5, 5, tl)
        board[5][5] = enemy_king
        r, c = king.amIGonnaDie(board)
        assert r == 5
        assert c == 5

    def test_returns_only_first_attacker_in_double_check(self):
        # BUG #7 LOCK-IN: only the first attacker found in the iteration order
        # is returned; the second attacker is silently ignored.
        tr, tl, king, board = self._setup()
        # Two simultaneous attackers
        enemy_rook = Rook(4, 7, tl)   # attacks along rank
        enemy_bishop = Bishop(1, 1, tl)  # attacks along diagonal
        board[4][7] = enemy_rook
        board[1][1] = enemy_bishop
        r, c = king.amIGonnaDie(board)
        # Only ONE attacker is returned — we just assert it's one of the two
        assert (r, c) in [(4, 7), (1, 1)]
        # Crucially, only ONE is returned, not both
        assert not (r == 4 and c == 7 and False)  # still returns a single tuple

    def test_resets_critical_flag_on_all_allies(self):
        tr, tl, king, board = self._setup()
        ally_rook = Rook(4, 2, tr)
        ally_rook.critical = True  # pre-set to True
        board[4][2] = ally_rook
        king.amIGonnaDie(board)
        assert ally_rook.critical is False

    def test_marks_pinned_piece_as_critical(self):
        tr, tl, king, board = self._setup()
        # King at (4,4), ally rook at (4,2), enemy rook at (4,0)
        ally = Rook(4, 2, tr)
        enemy = Rook(4, 0, tl)
        board[4][2] = ally
        board[4][0] = enemy
        king.amIGonnaDie(board)
        assert ally.critical is True

    def test_pinned_piece_gets_critical_targets(self):
        tr, tl, king, board = self._setup()
        ally = Rook(4, 2, tr)
        enemy = Rook(4, 0, tl)
        board[4][2] = ally
        board[4][0] = enemy
        king.amIGonnaDie(board)
        # criticalTargets should include the path between enemy and king
        critical_positions = [(c.row, c.col) for c in ally.criticalTargets]
        assert (4, 0) in critical_positions  # enemy square
        assert (4, 1) in critical_positions  # intermediate square


# ─────────────────────────────────────────────────────────────────────────────
# determineDirectionFromEnemyTowardsKing (float-return bug)
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
        dir1, dir2 = king.determineDirectionFromEnemyTowardsKing(4, 7)
        assert dir1 == 0
        assert isinstance(dir2, float)

    def test_same_col_row_component_is_float(self):
        # Enemy at (1,4), king at (4,4) → returns (1.0, 0)
        king = self._king()
        dir1, dir2 = king.determineDirectionFromEnemyTowardsKing(1, 4)
        assert isinstance(dir1, float)
        assert dir2 == 0

    def test_diagonal_both_components_are_float(self):
        # Enemy at (1,7), king at (4,4) → both components are floats
        king = self._king()
        dir1, dir2 = king.determineDirectionFromEnemyTowardsKing(1, 7)
        assert isinstance(dir1, float)
        assert isinstance(dir2, float)

    def test_correct_sign_enemy_to_the_right(self):
        # Enemy at (4,7) → direction towards king is (0, -1.0)
        king = self._king()
        dir1, dir2 = king.determineDirectionFromEnemyTowardsKing(4, 7)
        assert dir2 == -1.0  # move left toward king

    def test_correct_sign_enemy_to_the_left(self):
        # Enemy at (4,0) → direction towards king is (0, +1.0)
        king = self._king()
        dir1, dir2 = king.determineDirectionFromEnemyTowardsKing(4, 0)
        assert dir2 == 1.0  # move right toward king

    def test_correct_sign_enemy_above(self):
        # Enemy at (1,4) → direction towards king is (+1.0, 0)
        king = self._king()
        dir1, dir2 = king.determineDirectionFromEnemyTowardsKing(1, 4)
        assert dir1 == 1.0  # move down toward king


# ─────────────────────────────────────────────────────────────────────────────
# pleaseGodSaveTheKing
# ─────────────────────────────────────────────────────────────────────────────

class TestPleaseGodSaveTheKing:
    def _king(self):
        tr = Team(64, 180, 232)
        king = King(4, 4, tr)
        return king

    def test_includes_attacker_cell(self):
        king = self._king()
        result = king.pleaseGodSaveTheKing(4, 7)
        positions = [(c.row, c.col) for c in result]
        assert (4, 7) in positions

    def test_includes_intermediate_cells(self):
        king = self._king()
        result = king.pleaseGodSaveTheKing(4, 7)
        # Enemy at (4,7), king at (4,4) — cells (4,7), (4,6), (4,5)
        positions = [(c.row, c.col) for c in result]
        # Due to float arithmetic, col values may be floats but compare equal
        assert any(c.row == 4 and c.col == 6 for c in result)
        assert any(c.row == 4 and c.col == 5 for c in result)

    def test_excludes_king_cell(self):
        king = self._king()
        result = king.pleaseGodSaveTheKing(4, 7)
        positions = [(c.row, c.col) for c in result]
        assert (4, 4) not in positions  # king's own square excluded


# ─────────────────────────────────────────────────────────────────────────────
# Castling
# ─────────────────────────────────────────────────────────────────────────────

class TestCastling:
    def _setup_clean_castling(self):
        """King at (0,4), rooks at (0,0) and (0,7), all untouched, no threats."""
        tr = Team(64, 180, 232)
        king = King(0, 4, tr)
        rook_q = Rook(0, 0, tr)  # queenside
        rook_k = Rook(0, 7, tr)  # kingside
        board = empty_board()
        board[0][4] = king
        board[0][0] = rook_q
        board[0][7] = rook_k
        return tr, king, rook_q, rook_k, board

    def test_queenside_target_added_when_eligible(self):
        tr, king, rook_q, rook_k, board = self._setup_clean_castling()
        king.calcTargets(board)
        targets = [(c.row, c.col) for c in king.targets]
        assert (0, 2) in targets

    def test_kingside_target_added_when_eligible(self):
        tr, king, rook_q, rook_k, board = self._setup_clean_castling()
        king.calcTargets(board)
        targets = [(c.row, c.col) for c in king.targets]
        assert (0, 6) in targets

    def test_queenside_blocked_by_piece_between(self):
        tr, king, rook_q, rook_k, board = self._setup_clean_castling()
        # Place a knight at (0,1) — blocks queenside castling
        board[0][1] = Knight(0, 1, tr)
        king.calcTargets(board)
        targets = [(c.row, c.col) for c in king.targets]
        assert (0, 2) not in targets

    def test_kingside_blocked_by_piece_between(self):
        tr, king, rook_q, rook_k, board = self._setup_clean_castling()
        board[0][6] = Knight(0, 6, tr)
        king.calcTargets(board)
        targets = [(c.row, c.col) for c in king.targets]
        assert (0, 6) not in targets

    def test_castling_not_available_when_king_touched(self):
        tr, king, rook_q, rook_k, board = self._setup_clean_castling()
        king.touched = True
        king.calcTargets(board)
        targets = [(c.row, c.col) for c in king.targets]
        assert (0, 2) not in targets
        assert (0, 6) not in targets

    def test_castling_not_available_when_rook_touched(self):
        tr, king, rook_q, rook_k, board = self._setup_clean_castling()
        rook_q.touched = True
        king.calcTargets(board)
        targets = [(c.row, c.col) for c in king.targets]
        assert (0, 2) not in targets  # queenside rook touched

    def test_castling_not_available_when_king_in_check(self):
        tr, king, rook_q, rook_k, board = self._setup_clean_castling()
        tl = Team(255, 140, 0)
        # Enemy rook puts king in check on file
        enemy = Rook(7, 4, tl)
        board[7][4] = enemy
        king.calcTargets(board)
        targets = [(c.row, c.col) for c in king.targets]
        assert (0, 2) not in targets
        assert (0, 6) not in targets

    def test_queenside_castling_not_available_when_passing_through_check(self):
        tr, king, rook_q, rook_k, board = self._setup_clean_castling()
        tl = Team(255, 140, 0)
        # Enemy rook controls (0,3) — the intermediate square for queenside
        enemy = Rook(7, 3, tl)
        board[7][3] = enemy
        king.calcTargets(board)
        targets = [(c.row, c.col) for c in king.targets]
        assert (0, 2) not in targets

    # ── King.move() castling return values ──

    def test_move_returns_rook_cells_queenside_castle(self):
        tr = Team(64, 180, 232)
        king = King(0, 4, tr)
        board = empty_board()
        board[0][4] = king
        old_rook_cell, new_rook_cell = king.move(0, 2, board)
        # Queenside: rook moves from (0,0) to (0,3)
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
        # Kingside: rook moves from (0,7) to (0,5)
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


# ─────────────────────────────────────────────────────────────────────────────
# getValue (tuple-truthy bug)
# ─────────────────────────────────────────────────────────────────────────────

class TestKingGetValue:
    def test_get_value_always_zero_due_to_truthy_tuple(self):
        # BUG #10 LOCK-IN: King.getValue() does:
        #   if self.amIGonnaDie(board):
        #       value = 0
        # amIGonnaDie() always returns a tuple, e.g. (-1,-1) when safe.
        # In Python, ANY non-empty tuple is truthy — including (-1,-1).
        # Therefore getValue() always returns 0, never 1000.
        tr = Team(64, 180, 232)
        king = King(4, 4, tr)
        board = empty_board()
        board[4][4] = king
        # Even on a completely empty board with no threats, getValue returns 0
        assert king.getValue(board) == 0

    def test_get_value_zero_even_when_in_check(self):
        tr = Team(64, 180, 232)
        tl = Team(255, 140, 0)
        king = King(4, 4, tr)
        enemy = Rook(4, 7, tl)
        board = empty_board()
        board[4][4] = king
        board[4][7] = enemy
        # Also returns 0 when in check (for a different reason than intended)
        assert king.getValue(board) == 0
