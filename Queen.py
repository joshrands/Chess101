from __future__ import annotations

from Piece import Piece, BoardGrid
from Cell import Cell
from constants import PieceValue


class Queen(Piece):
    def calc_targets(self, board: BoardGrid) -> None:
        self.targets = []
        self._slide(board, 1, 1, self.row, self.col)
        self._slide(board, -1, 1, self.row, self.col)
        self._slide(board, 1, -1, self.row, self.col)
        self._slide(board, -1, -1, self.row, self.col)
        self._slide(board, 1, 0, self.row, self.col)
        self._slide(board, -1, 0, self.row, self.col)
        self._slide(board, 0, 1, self.row, self.col)
        self._slide(board, 0, -1, self.row, self.col)
        if self.critical:
            super().filter_to_pin_ray()

    def get_value(self, board: BoardGrid) -> int:
        total = PieceValue.QUEEN
        self.calc_targets(board)
        for cell in self.targets:
            total += 1
            if (cell.row == 3 or cell.row == 4) and (cell.col == 3 or cell.col == 4):
                total += 1
        return total

    def print_piece(self) -> None:
        print("Queen at", self.row, ",", self.col)
