"""
test_pieces.py — tests for Pawn, Bishop, Rook, Knight, and Queen.

Each test builds a minimal board position and verifies calc_targets(),
get_value(), move(), and filter_to_king_escape() produce exactly the behavior
that currently exists (including known quirks and bugs).
"""
import pytest
from Team import Team
from Cell import Cell
from Pawn import Pawn
from Bishop import Bishop
from Rook import Rook
from Knight import Knight
from Queen import Queen
from King import King


def empty_board():
    return [[None] * 8 for _ in range(8)]


# ─────────────────────────────────────────────────────────────────────────────
# Pawn
# ─────────────────────────────────────────────────────────────────────────────

class TestPawn:
    def _teams(self):
        return Team(64, 180, 232), Team(255, 140, 0)

    # ── Init / direction ──

    def test_row6_direction_neg1(self):
        tr, tl = self._teams()
        p = Pawn(6, 3, tl)
        assert p.direction == -1

    def test_row1_direction_pos1(self):
        tr, tl = self._teams()
        p = Pawn(1, 3, tr)
        assert p.direction == 1

    def test_non_row6_direction_pos1(self):
        tr, tl = self._teams()
        for row in [0, 1, 2, 3, 4, 5]:
            p = Pawn(row, 0, tr)
            assert p.direction == 1, f"row {row} should give direction=1"

    def test_stores_starting_row(self):
        tr, _ = self._teams()
        p = Pawn(1, 4, tr)
        assert p.starting_row == 1

    def test_starting_col_stored_but_unused(self):
        # BUG #3 LOCK-IN: starting_col is assigned in __init__ but is never
        # referenced inside calc_targets() or get_value().  It IS used in move()
        # as part of the en-passant condition, but that condition also checks
        # starting_row, so the col check is effectively redundant for standard
        # starting positions.  Assert the attribute exists and matches col.
        tr, _ = self._teams()
        p = Pawn(1, 5, tr)
        assert hasattr(p, "starting_col")
        assert p.starting_col == 5

    def test_en_passantable_false_on_init(self):
        tr, _ = self._teams()
        p = Pawn(1, 0, tr)
        assert p.en_passantable is False

    def test_en_passant_loc_none_on_init(self):
        tr, _ = self._teams()
        p = Pawn(1, 0, tr)
        assert p.en_passant_loc is None

    # ── calc_targets ──

    def test_forward_one_step(self):
        tr, _ = self._teams()
        pawn = Pawn(3, 4, tr)
        board = empty_board()
        board[3][4] = pawn
        pawn.calc_targets(board)
        targets = [(c.row, c.col) for c in pawn.targets]
        assert (4, 4) in targets

    def test_forward_two_steps_from_starting_row(self):
        tr, _ = self._teams()
        pawn = Pawn(1, 4, tr)
        board = empty_board()
        board[1][4] = pawn
        pawn.calc_targets(board)
        targets = [(c.row, c.col) for c in pawn.targets]
        assert (2, 4) in targets
        assert (3, 4) in targets

    def test_two_step_blocked_at_first_square(self):
        tr, tl = self._teams()
        pawn = Pawn(1, 4, tr)
        blocker = Rook(2, 4, tl)
        board = empty_board()
        board[1][4] = pawn
        board[2][4] = blocker
        pawn.calc_targets(board)
        targets = [(c.row, c.col) for c in pawn.targets]
        assert (2, 4) not in targets
        assert (3, 4) not in targets

    def test_two_step_blocked_at_second_square(self):
        tr, tl = self._teams()
        pawn = Pawn(1, 4, tr)
        blocker = Rook(3, 4, tl)
        board = empty_board()
        board[1][4] = pawn
        board[3][4] = blocker
        pawn.calc_targets(board)
        targets = [(c.row, c.col) for c in pawn.targets]
        assert (2, 4) in targets   # first square is clear
        assert (3, 4) not in targets  # second square is blocked

    def test_diagonal_capture_left(self):
        tr, tl = self._teams()
        pawn = Pawn(3, 4, tr)
        enemy = Rook(4, 3, tl)
        board = empty_board()
        board[3][4] = pawn
        board[4][3] = enemy
        pawn.calc_targets(board)
        targets = [(c.row, c.col) for c in pawn.targets]
        assert (4, 3) in targets

    def test_diagonal_capture_right(self):
        tr, tl = self._teams()
        pawn = Pawn(3, 4, tr)
        enemy = Rook(4, 5, tl)
        board = empty_board()
        board[3][4] = pawn
        board[4][5] = enemy
        pawn.calc_targets(board)
        targets = [(c.row, c.col) for c in pawn.targets]
        assert (4, 5) in targets

    def test_no_diagonal_capture_empty_square(self):
        tr, _ = self._teams()
        pawn = Pawn(3, 4, tr)
        board = empty_board()
        board[3][4] = pawn
        pawn.calc_targets(board)
        targets = [(c.row, c.col) for c in pawn.targets]
        assert (4, 3) not in targets
        assert (4, 5) not in targets

    def test_no_diagonal_capture_own_piece(self):
        tr, _ = self._teams()
        pawn = Pawn(3, 4, tr)
        ally = Rook(4, 3, tr)
        board = empty_board()
        board[3][4] = pawn
        board[4][3] = ally
        pawn.calc_targets(board)
        targets = [(c.row, c.col) for c in pawn.targets]
        assert (4, 3) not in targets

    def test_en_passant_left(self):
        tr, tl = self._teams()
        pawn = Pawn(1, 4, tr)
        pawn.row = 4   # manually advance to row 4 (not starting row)
        enemy_pawn = Pawn(6, 3, tl)
        enemy_pawn.row = 4
        enemy_pawn.en_passantable = True
        board = empty_board()
        board[4][4] = pawn
        board[4][3] = enemy_pawn
        pawn.calc_targets(board)
        targets = [(c.row, c.col) for c in pawn.targets]
        assert (5, 3) in targets

    def test_en_passant_right(self):
        tr, tl = self._teams()
        pawn = Pawn(1, 4, tr)
        pawn.row = 4
        enemy_pawn = Pawn(6, 5, tl)
        enemy_pawn.row = 4
        enemy_pawn.en_passantable = True
        board = empty_board()
        board[4][4] = pawn
        board[4][5] = enemy_pawn
        pawn.calc_targets(board)
        targets = [(c.row, c.col) for c in pawn.targets]
        assert (5, 5) in targets

    def test_en_passant_loc_set_after_calc(self):
        tr, tl = self._teams()
        pawn = Pawn(1, 4, tr)
        pawn.row = 4
        enemy_pawn = Pawn(6, 3, tl)
        enemy_pawn.row = 4
        enemy_pawn.en_passantable = True
        board = empty_board()
        board[4][4] = pawn
        board[4][3] = enemy_pawn
        pawn.calc_targets(board)
        assert pawn.en_passant_loc is not None
        assert pawn.en_passant_loc.row == 5
        assert pawn.en_passant_loc.col == 3

    def test_en_passant_same_team_not_capturable(self):
        tr, _ = self._teams()
        pawn = Pawn(1, 4, tr)
        pawn.row = 4
        ally_pawn = Pawn(1, 3, tr)
        ally_pawn.row = 4
        ally_pawn.en_passantable = True
        board = empty_board()
        board[4][4] = pawn
        board[4][3] = ally_pawn
        pawn.calc_targets(board)
        targets = [(c.row, c.col) for c in pawn.targets]
        assert (5, 3) not in targets

    def test_no_targets_at_row0(self):
        tr, _ = self._teams()
        pawn = Pawn(1, 4, tr)
        pawn.row = 0
        board = empty_board()
        board[0][4] = pawn
        pawn.calc_targets(board)
        assert pawn.targets == []

    def test_no_targets_at_row7(self):
        tr, _ = self._teams()
        pawn = Pawn(1, 4, tr)
        pawn.row = 7
        board = empty_board()
        board[7][4] = pawn
        pawn.calc_targets(board)
        assert pawn.targets == []

    def test_critical_applies_critical_man(self):
        tr, _ = self._teams()
        pawn = Pawn(3, 4, tr)
        board = empty_board()
        board[3][4] = pawn
        pawn.calc_targets(board)
        # Mark critical and set critical_targets to only one allowed cell
        pawn.critical = True
        pawn.critical_targets = [Cell(4, 4)]
        # Re-run so filter_to_pin_ray fires
        pawn.targets = []
        pawn.calc_targets(board)
        assert all(c.row == 4 and c.col == 4 for c in pawn.targets)

    # ── move() ──

    def test_move_returns_none_normally(self):
        tr, _ = self._teams()
        pawn = Pawn(1, 4, tr)
        board = empty_board()
        board[1][4] = pawn
        result = pawn.move(2, 4, board)
        assert result is None

    def test_move_sets_en_passant_on_double_advance(self):
        tr, _ = self._teams()
        pawn = Pawn(1, 4, tr)  # starting_row=1, starting_col=4
        board = empty_board()
        board[1][4] = pawn
        pawn.move(3, 4, board)
        assert pawn.en_passantable is True

    def test_move_no_en_passant_from_non_starting_row(self):
        # BUG LOCK-IN: double advance from a row other than starting_row does
        # NOT set en_passantable, because the en passant condition also checks
        # old_row == self.starting_row.
        tr, _ = self._teams()
        pawn = Pawn(1, 4, tr)
        pawn.row = 3   # manually set to row 3 (not starting_row)
        board = empty_board()
        board[3][4] = pawn
        pawn.move(5, 4, board)  # advance 2 squares (but from wrong row)
        assert pawn.en_passantable is False

    def test_move_returns_captured_cell_on_en_passant(self):
        tr, tl = self._teams()
        pawn = Pawn(1, 4, tr)
        pawn.row = 4
        enemy_pawn = Pawn(6, 3, tl)
        enemy_pawn.row = 4
        enemy_pawn.en_passantable = True
        board = empty_board()
        board[4][4] = pawn
        board[4][3] = enemy_pawn
        pawn.calc_targets(board)
        # Move to en passant target
        result = pawn.move(5, 3, board)
        assert result is not None
        assert result.row == 4   # captured pawn's row
        assert result.col == 3   # captured pawn's col

    def test_promotion_dir1_at_row7(self):
        # BUG #5 LOCK-IN: (starting_row + 6) % 12 == row formula.
        # For starting_row=1: (1+6)%12 = 7 → promotes at row 7.
        tr, _ = self._teams()
        pawn = Pawn(1, 4, tr)
        pawn.row = 6   # pawn has advanced to row 6
        board = empty_board()
        board[6][4] = pawn
        pawn.move(7, 4, board)
        assert isinstance(board[7][4], Queen)

    def test_promotion_dir_neg1_at_row0(self):
        # For starting_row=6: (6+6)%12 = 0 → promotes at row 0.
        _, tl = self._teams()
        pawn = Pawn(6, 4, tl)
        pawn.row = 1
        board = empty_board()
        board[1][4] = pawn
        pawn.move(0, 4, board)
        assert isinstance(board[0][4], Queen)

    def test_promotion_modifies_board_array_directly(self):
        # LOCK-IN: Pawn.move() mutates board in place when promoting.
        tr, _ = self._teams()
        pawn = Pawn(1, 4, tr)
        pawn.row = 6
        board = empty_board()
        board[6][4] = pawn
        pawn.move(7, 4, board)
        # The piece at the promotion square is a new Queen, not the pawn
        assert board[7][4] is not pawn

    # ── filter_to_king_escape() override ──

    def test_skyfall_preserves_en_passant_loc(self):
        # BUG #9 LOCK-IN: Pawn.filter_to_king_escape() unconditionally
        # re-appends en_passant_loc even when it isn't in king_escape_cells.
        tr, tl = self._teams()
        pawn = Pawn(1, 4, tr)
        pawn.row = 4
        enemy_pawn = Pawn(6, 3, tl)
        enemy_pawn.row = 4
        enemy_pawn.en_passantable = True
        board = empty_board()
        board[4][4] = pawn
        board[4][3] = enemy_pawn
        pawn.calc_targets(board)

        king = King(0, 4, tr)
        # king_escape_cells does NOT include the en passant target (5,3)
        king.king_escape_cells = [Cell(3, 3)]

        pawn.filter_to_king_escape(king)
        targets = [(c.row, c.col) for c in pawn.targets]
        # En passant loc is still in targets despite not being a saving move
        assert (5, 3) in targets

    def test_skyfall_none_en_passant_loc_not_added(self):
        tr, _ = self._teams()
        pawn = Pawn(3, 4, tr)
        board = empty_board()
        board[3][4] = pawn
        pawn.calc_targets(board)
        assert pawn.en_passant_loc is None

        king = King(0, 4, tr)
        king.king_escape_cells = [Cell(4, 4)]
        pawn.filter_to_king_escape(king)
        # Only targets that are in king_escape_cells remain; no extra cells added
        targets = [(c.row, c.col) for c in pawn.targets]
        assert (4, 4) in targets
        assert len(pawn.targets) == 1

    # ── get_value() ──

    def test_pawn_value_minimum_5(self):
        tr, _ = self._teams()
        pawn = Pawn(3, 4, tr)
        board = empty_board()
        board[3][4] = pawn
        assert pawn.get_value(board) >= 5

    def test_pawn_value_center_bonus(self):
        # Targets at rows 3-4, cols 3-4 each add +1 extra (central bonus).
        tr, _ = self._teams()
        pawn = Pawn(3, 3, tr)  # pawn at center
        board = empty_board()
        board[3][3] = pawn
        value = pawn.get_value(board)
        assert value > 5


# ─────────────────────────────────────────────────────────────────────────────
# Bishop
# ─────────────────────────────────────────────────────────────────────────────

class TestBishop:
    def _team(self):
        return Team(64, 180, 232), Team(255, 140, 0)

    def test_open_board_13_diagonal_targets(self):
        tr, _ = self._team()
        bishop = Bishop(3, 3, tr)
        board = empty_board()
        board[3][3] = bishop
        bishop.calc_targets(board)
        assert len(bishop.targets) == 13

    def test_blocked_by_own_piece(self):
        tr, _ = self._team()
        bishop = Bishop(3, 3, tr)
        ally = Rook(5, 5, tr)
        board = empty_board()
        board[3][3] = bishop
        board[5][5] = ally
        bishop.calc_targets(board)
        targets = [(c.row, c.col) for c in bishop.targets]
        assert (5, 5) not in targets  # ally is NOT a target
        assert (4, 4) in targets      # square before ally IS a target

    def test_captures_enemy(self):
        tr, tl = self._team()
        bishop = Bishop(3, 3, tr)
        enemy = Rook(5, 5, tl)
        board = empty_board()
        board[3][3] = bishop
        board[5][5] = enemy
        bishop.calc_targets(board)
        targets = [(c.row, c.col) for c in bishop.targets]
        assert (5, 5) in targets    # enemy IS a target
        assert (6, 6) not in targets  # ray stops at enemy

    def test_corner_position(self):
        tr, _ = self._team()
        bishop = Bishop(0, 0, tr)
        board = empty_board()
        board[0][0] = bishop
        bishop.calc_targets(board)
        assert len(bishop.targets) == 7  # only (1,1)...(7,7)

    def test_critical_constrains_targets(self):
        tr, _ = self._team()
        bishop = Bishop(3, 3, tr)
        board = empty_board()
        board[3][3] = bishop
        bishop.critical = True
        bishop.critical_targets = [Cell(4, 4), Cell(5, 5)]
        bishop.calc_targets(board)
        assert all((c.row, c.col) in [(4, 4), (5, 5)] for c in bishop.targets)

    def test_value_base_15(self):
        tr, _ = self._team()
        bishop = Bishop(3, 3, tr)
        board = empty_board()
        board[3][3] = bishop
        assert bishop.get_value(board) >= 15

    def test_value_center_bonus(self):
        tr, _ = self._team()
        bishop = Bishop(2, 2, tr)
        board = empty_board()
        board[2][2] = bishop
        val = bishop.get_value(board)
        assert val > 15


# ─────────────────────────────────────────────────────────────────────────────
# Rook
# ─────────────────────────────────────────────────────────────────────────────

class TestRook:
    def _teams(self):
        return Team(64, 180, 232), Team(255, 140, 0)

    def test_open_board_14_targets(self):
        tr, _ = self._teams()
        rook = Rook(3, 3, tr)
        board = empty_board()
        board[3][3] = rook
        rook.calc_targets(board)
        assert len(rook.targets) == 14

    def test_blocked_by_own_piece_on_rank(self):
        tr, _ = self._teams()
        rook = Rook(3, 0, tr)
        ally = Rook(3, 4, tr)
        board = empty_board()
        board[3][0] = rook
        board[3][4] = ally
        rook.calc_targets(board)
        targets = [(c.row, c.col) for c in rook.targets]
        assert (3, 4) not in targets
        assert (3, 5) not in targets

    def test_blocked_by_own_piece_on_file(self):
        tr, _ = self._teams()
        rook = Rook(0, 3, tr)
        ally = Rook(4, 3, tr)
        board = empty_board()
        board[0][3] = rook
        board[4][3] = ally
        rook.calc_targets(board)
        targets = [(c.row, c.col) for c in rook.targets]
        assert (4, 3) not in targets
        assert (5, 3) not in targets

    def test_captures_enemy_on_rank(self):
        tr, tl = self._teams()
        rook = Rook(3, 0, tr)
        enemy = Rook(3, 5, tl)
        board = empty_board()
        board[3][0] = rook
        board[3][5] = enemy
        rook.calc_targets(board)
        targets = [(c.row, c.col) for c in rook.targets]
        assert (3, 5) in targets
        assert (3, 6) not in targets

    def test_captures_enemy_on_file(self):
        tr, tl = self._teams()
        rook = Rook(0, 3, tr)
        enemy = Rook(5, 3, tl)
        board = empty_board()
        board[0][3] = rook
        board[5][3] = enemy
        rook.calc_targets(board)
        targets = [(c.row, c.col) for c in rook.targets]
        assert (5, 3) in targets
        assert (6, 3) not in targets

    def test_critical_constrains_targets(self):
        tr, _ = self._teams()
        rook = Rook(0, 0, tr)
        board = empty_board()
        board[0][0] = rook
        rook.critical = True
        rook.critical_targets = [Cell(0, 1), Cell(0, 2)]
        rook.calc_targets(board)
        cols = {c.col for c in rook.targets}
        assert cols.issubset({1, 2})

    def test_value_base_27(self):
        tr, _ = self._teams()
        rook = Rook(3, 3, tr)
        board = empty_board()
        board[3][3] = rook
        assert rook.get_value(board) >= 27

    def test_value_center_bonus(self):
        tr, _ = self._teams()
        rook = Rook(3, 0, tr)
        board = empty_board()
        board[3][0] = rook
        val = rook.get_value(board)
        assert val > 27


# ─────────────────────────────────────────────────────────────────────────────
# Knight
# ─────────────────────────────────────────────────────────────────────────────

class TestKnight:
    def _teams(self):
        return Team(64, 180, 232), Team(255, 140, 0)

    def test_center_8_targets(self):
        tr, _ = self._teams()
        knight = Knight(3, 3, tr)
        board = empty_board()
        board[3][3] = knight
        knight.calc_targets(board)
        assert len(knight.targets) == 8

    def test_corner_2_targets(self):
        tr, _ = self._teams()
        knight = Knight(0, 0, tr)
        board = empty_board()
        board[0][0] = knight
        knight.calc_targets(board)
        assert len(knight.targets) == 2

    def test_edge_reduced_targets(self):
        tr, _ = self._teams()
        knight = Knight(0, 3, tr)
        board = empty_board()
        board[0][3] = knight
        knight.calc_targets(board)
        assert len(knight.targets) == 4

    def test_captures_enemy(self):
        tr, tl = self._teams()
        knight = Knight(3, 3, tr)
        enemy = Rook(5, 4, tl)
        board = empty_board()
        board[3][3] = knight
        board[5][4] = enemy
        knight.calc_targets(board)
        targets = [(c.row, c.col) for c in knight.targets]
        assert (5, 4) in targets

    def test_blocked_by_own_piece(self):
        tr, _ = self._teams()
        knight = Knight(3, 3, tr)
        ally = Rook(5, 4, tr)
        board = empty_board()
        board[3][3] = knight
        board[5][4] = ally
        knight.calc_targets(board)
        targets = [(c.row, c.col) for c in knight.targets]
        assert (5, 4) not in targets

    def test_jumps_over_intervening_pieces(self):
        tr, tl = self._teams()
        knight = Knight(3, 3, tr)
        board = empty_board()
        board[3][3] = knight
        board[3][4] = Rook(3, 4, tr)
        board[4][3] = Rook(4, 3, tr)
        board[4][4] = Rook(4, 4, tr)
        knight.calc_targets(board)
        targets = [(c.row, c.col) for c in knight.targets]
        assert (5, 4) in targets

    def test_critical_constrains_targets(self):
        tr, _ = self._teams()
        knight = Knight(3, 3, tr)
        board = empty_board()
        board[3][3] = knight
        knight.critical = True
        knight.critical_targets = [Cell(5, 4)]
        knight.calc_targets(board)
        targets = [(c.row, c.col) for c in knight.targets]
        assert targets == [(5, 4)]

    def test_value_base_13(self):
        tr, _ = self._teams()
        knight = Knight(3, 3, tr)
        board = empty_board()
        board[3][3] = knight
        assert knight.get_value(board) >= 13


# ─────────────────────────────────────────────────────────────────────────────
# Queen
# ─────────────────────────────────────────────────────────────────────────────

class TestQueen:
    def _teams(self):
        return Team(64, 180, 232), Team(255, 140, 0)

    def test_open_board_combines_rook_and_bishop(self):
        tr, _ = self._teams()
        queen = Queen(3, 3, tr)
        board = empty_board()
        board[3][3] = queen
        queen.calc_targets(board)
        assert len(queen.targets) == 27

    def test_blocked_by_own_pieces_all_directions(self):
        tr, _ = self._teams()
        queen = Queen(4, 4, tr)
        board = empty_board()
        board[4][4] = queen
        for dr, dc in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            board[4 + dr][4 + dc] = Rook(4 + dr, 4 + dc, tr)
        queen.calc_targets(board)
        assert queen.targets == []

    def test_captures_enemies_all_directions(self):
        tr, tl = self._teams()
        queen = Queen(4, 4, tr)
        board = empty_board()
        board[4][4] = queen
        for dr, dc in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
            board[4 + dr][4 + dc] = Rook(4 + dr, 4 + dc, tl)
        queen.calc_targets(board)
        assert len(queen.targets) == 8

    def test_critical_constrains_targets(self):
        tr, _ = self._teams()
        queen = Queen(3, 3, tr)
        board = empty_board()
        board[3][3] = queen
        queen.critical = True
        queen.critical_targets = [Cell(3, 4), Cell(3, 5)]
        queen.calc_targets(board)
        targets = [(c.row, c.col) for c in queen.targets]
        assert set(targets).issubset({(3, 4), (3, 5)})

    def test_value_base_49(self):
        tr, _ = self._teams()
        queen = Queen(3, 3, tr)
        board = empty_board()
        board[3][3] = queen
        assert queen.get_value(board) >= 49
