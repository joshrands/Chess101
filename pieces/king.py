from __future__ import annotations

from pieces.piece import Piece, BoardGrid
from core.cell import Cell
from core.team import Team
from core.constants import PieceValue


class King(Piece):

    def __init__(self, row: int, col: int, team: Team) -> None:
        self.row = row
        self.col = col
        self.targets: list[Cell] = []
        self.team = team
        if self.row == 7:
            self.direction = -1
        else:
            self.direction = 1
        self.touched: bool = False
        self.critical: bool = False
        self.king_escape_cells: list[Cell] = []

    def _walk(self, board: BoardGrid, dr: int, dc: int, row: int, col: int) -> None:
        if 0 <= row + dr <= 7 and 0 <= col + dc <= 7:
            if board[row + dr][col + dc] is None:
                self.targets.append(Cell(row + dr, col + dc))
            elif board[row + dr][col + dc].team != self.team:
                self.targets.append(Cell(row + dr, col + dc))

    def calc_targets(self, board: BoardGrid) -> bool:
        from pieces.rook import Rook
        self.targets = []
        self._walk(board, 1, 1, self.row, self.col)
        self._walk(board, -1, 1, self.row, self.col)
        self._walk(board, 1, -1, self.row, self.col)
        self._walk(board, -1, -1, self.row, self.col)
        self._walk(board, 1, 0, self.row, self.col)
        self._walk(board, -1, 0, self.row, self.col)
        self._walk(board, 0, 1, self.row, self.col)
        self._walk(board, 0, -1, self.row, self.col)

        old_row = self.row
        old_col = self.col

        if not self.touched:
            if (isinstance(board[self.row][self.col - 4], Rook)
                    and not board[self.row][self.col - 4].touched):
                if (board[self.row][self.col - 1] is None
                        and board[self.row][self.col - 2] is None
                        and board[self.row][self.col - 3] is None):
                    self.targets.append(Cell(self.row, self.col - 2))
            if (isinstance(board[self.row][self.col + 3], Rook)
                    and not board[self.row][self.col + 3].touched):
                if board[self.row][self.col + 1] is None and board[self.row][self.col + 2] is None:
                    self.targets.append(Cell(self.row, self.col + 2))

        targets_to_remove = []

        castle_left = False
        castle_left_step = True
        castle_right = False
        castle_right_step = True
        castle_left_cell = Cell(-1, -1)
        castle_right_cell = Cell(-1, -1)

        for cell in self.targets:
            if cell.row == old_row and cell.col == old_col - 2:
                castle_left = True
                castle_left_cell = cell
            if cell.row == old_row and cell.col == old_col + 2:
                castle_right = True
                castle_right_cell = cell
            original_piece = board[cell.row][cell.col]
            board[cell.row][cell.col] = self
            board[self.row][self.col] = None
            self.row = cell.row
            self.col = cell.col
            threat_row, threat_col = self.find_attacker(board)
            if threat_row != -1 and threat_col != -1:
                if cell.row == old_row and cell.col == old_col - 2:
                    castle_left = False
                if cell.row == old_row and cell.col == old_col + 2:
                    castle_right = False
                if cell.row == old_row and cell.col == old_col - 1:
                    castle_left_step = False
                if cell.row == old_row and cell.col == old_col + 1:
                    castle_right_step = False
                targets_to_remove.append(cell)

            board[old_row][old_col] = self
            board[cell.row][cell.col] = original_piece
            self.row = old_row
            self.col = old_col

        _attacker_row, _attacker_col = self.find_attacker(board)
        in_check = _attacker_row != -1 and _attacker_col != -1

        if castle_left and (not castle_left_step or in_check):
            self.targets.remove(castle_left_cell)
        if castle_right and (not castle_right_step or in_check):
            self.targets.remove(castle_right_cell)
        for to_remove in targets_to_remove:
            self.targets.remove(to_remove)

        return in_check

    def get_value(self, board: BoardGrid) -> int:
        value = PieceValue.KING
        if self.find_attacker(board):
            value = 0
        return value

    def move(self, new_row: int, new_col: int, board: BoardGrid) -> tuple[Cell | None, Cell | None]:
        old_row = self.row
        old_col = self.col
        self.row = new_row
        self.col = new_col
        self.touched = True
        if new_row == old_row and new_col == old_col - 2:
            return Cell(old_row, old_col - 4), Cell(old_row, old_col - 1)
        elif new_row == old_row and new_col == old_col + 2:
            return Cell(old_row, old_col + 3), Cell(old_row, old_col + 1)
        else:
            return None, None

    def find_attacker(self, board: BoardGrid) -> tuple[int, int]:
        from pieces.rook import Rook
        from pieces.bishop import Bishop
        from pieces.knight import Knight
        from pieces.pawn import Pawn
        from pieces.queen import Queen

        for row in board:
            for piece in row:
                if piece is not None and piece.team == self.team:
                    piece.critical = False

        for i in [-1, 0, 1]:
            for j in [-1, 0, 1]:
                if i == 0 and j == 0:
                    continue

                enemy_row, enemy_col, scout_row, scout_col = self._scan_ray(
                    board, self.row + i, self.col + j, i, j)

                if i == 0 or j == 0:
                    if scout_row != -1:
                        if enemy_row != -1:
                            if isinstance(board[enemy_row][enemy_col], (Rook, Queen)):
                                board[scout_row][scout_col].critical = True
                                board[scout_row][scout_col].critical_targets = (
                                    self.build_check_escape_path(enemy_row, enemy_col)
                                )
                    elif enemy_row != -1:
                        if isinstance(board[enemy_row][enemy_col], (Rook, Queen)):
                            self.king_escape_cells = self.build_check_escape_path(
                                enemy_row, enemy_col)
                            return enemy_row, enemy_col
                        elif isinstance(board[enemy_row][enemy_col], King):
                            if abs(enemy_row - self.row) + abs(enemy_col - self.col) == 1:
                                self.king_escape_cells = self.build_check_escape_path(
                                    enemy_row, enemy_col)
                                return enemy_row, enemy_col
                else:
                    if scout_row != -1:
                        if enemy_row != -1:
                            if isinstance(board[enemy_row][enemy_col], (Bishop, Queen)):
                                board[scout_row][scout_col].critical = True
                                board[scout_row][scout_col].critical_targets = (
                                    self.build_check_escape_path(enemy_row, enemy_col)
                                )
                    elif enemy_row != -1:
                        if isinstance(board[enemy_row][enemy_col], (Bishop, Queen)):
                            self.king_escape_cells = self.build_check_escape_path(
                                enemy_row, enemy_col)
                            return enemy_row, enemy_col
                        elif isinstance(board[enemy_row][enemy_col], King):
                            if abs(enemy_row - self.row) + abs(enemy_col - self.col) == 2:
                                self.king_escape_cells = self.build_check_escape_path(
                                    enemy_row, enemy_col)
                                return enemy_row, enemy_col
                        elif isinstance(board[enemy_row][enemy_col], Pawn):
                            if enemy_row - self.row == self.direction:
                                self.king_escape_cells = self.build_check_escape_path(
                                    enemy_row, enemy_col)
                                return enemy_row, enemy_col

        row_deltas = [2, 2, -2, -2, 1, 1, -1, -1]
        col_deltas = [1, -1, 1, -1, 2, -2, 2, -2]
        for i in range(8):
            knight_row, knight_col = self._check_knight(
                board, row_deltas[i], col_deltas[i], self.row, self.col)
            if knight_row != -1 and knight_col != -1:
                self.king_escape_cells = [Cell(knight_row, knight_col)]
                return knight_row, knight_col

        return -1, -1

    def _scan_ray(
        self,
        board: BoardGrid,
        current_row: int,
        current_col: int,
        dr: int,
        dc: int,
    ) -> tuple[int, int, int, int]:
        next_loc = (
            0 <= current_row + dr < 8 and 0 <= current_col + dc < 8
        )
        if 0 <= current_row < 8 and 0 <= current_col < 8:
            if board[current_row][current_col] is not None:
                if board[current_row][current_col].team != self.team:
                    return current_row, current_col, -1, -1
                elif next_loc:
                    scout_row, scout_col = board[current_row][current_col]._ray_cast(
                        board, current_row + dr, current_col + dc, dr, dc)
                    return scout_row, scout_col, current_row, current_col
            elif next_loc:
                e_row, e_col, s_row, s_col = self._scan_ray(
                    board, current_row + dr, current_col + dc, dr, dc)
                return e_row, e_col, s_row, s_col
        return -1, -1, -1, -1

    def _check_knight(
        self,
        board: BoardGrid,
        dr: int,
        dc: int,
        row: int,
        col: int,
    ) -> tuple[int, int]:
        from pieces.knight import Knight
        if 0 <= row + dr <= 7 and 0 <= col + dc <= 7:
            if (isinstance(board[row + dr][col + dc], Knight)
                    and board[row + dr][col + dc].team != self.team):
                return row + dr, col + dc
        return -1, -1

    def build_check_escape_path(self, enemy_row: int, enemy_col: int) -> list[Cell]:
        dr, dc = self.determine_direction_from_enemy_towards_king(enemy_row, enemy_col)
        save_the_king: list[Cell] = []
        while not (enemy_row == self.row and enemy_col == self.col):
            save_the_king.append(Cell(enemy_row, enemy_col))
            enemy_row = enemy_row + dr
            enemy_col = enemy_col + dc
        return save_the_king

    def determine_direction_from_enemy_towards_king(
        self, enemy_row: int, enemy_col: int
    ) -> tuple[float, float]:
        if enemy_row == self.row:
            return 0, -1 * (enemy_col - self.col) / abs(enemy_col - self.col)
        elif enemy_col == self.col:
            return -1 * (enemy_row - self.row) / abs(enemy_row - self.row), 0
        else:
            return (
                -1 * (enemy_row - self.row) / abs(enemy_row - self.row),
                -1 * (enemy_col - self.col) / abs(enemy_col - self.col),
            )

    def print_piece(self) -> None:
        print("King at", self.row, ",", self.col)
