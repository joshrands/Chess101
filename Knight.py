from __future__ import annotations

from Piece import Piece, BoardGrid
from Cell import Cell
from constants import PieceValue

_KNIGHT_DELTAS = [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]


class Knight(Piece):
    def calc_targets(self, board: BoardGrid) -> None:
        self.targets = []
        for dr, dc in _KNIGHT_DELTAS:
            r, c = self.row + dr, self.col + dc
            if 0 <= r <= 7 and 0 <= c <= 7:
                occupant = board[r][c]
                if occupant is None or occupant.team != self.team:
                    self.targets.append(Cell(r, c))
        if self.critical:
            super().filter_to_pin_ray()

    def get_value(self, board: BoardGrid) -> int:
        total = PieceValue.KNIGHT
        self.calc_targets(board)
        for cell in self.targets:
            total += 1
            if (cell.row == 3 or cell.row == 4) and (cell.col == 3 or cell.col == 4):
                total += 1
        return total

    def print_piece(self) -> None:
        print("Knight at", self.row, ",", self.col)
