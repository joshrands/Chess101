from __future__ import annotations

from pieces.piece import Piece, BoardGrid
from core.cell import Cell
from core.constants import PieceValue


class Bishop(Piece):
    def calc_targets(self, board: BoardGrid) -> None:
        self.targets = []
        self._slide(board, 1, 1, self.row, self.col)
        self._slide(board, -1, 1, self.row, self.col)
        self._slide(board, 1, -1, self.row, self.col)
        self._slide(board, -1, -1, self.row, self.col)
        if self.critical:
            super().filter_to_pin_ray()

    def get_value(self, board: BoardGrid) -> int:
        total = PieceValue.BISHOP
        self.calc_targets(board)
        for cell in self.targets:
            total += 1
            if (cell.row == 3 or cell.row == 4) and (cell.col == 3 or cell.col == 4):
                total += 1
        return total

    def print_piece(self) -> None:
        print("Bishop at", self.row, ",", self.col)
