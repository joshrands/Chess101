from Piece import Piece
from Cell import Cell
from constants import PieceValue


class Bishop(Piece):
    def calc_targets(self, board):
        self.targets = []
        self._slide(board, 1, 1, self.row, self.col)
        self._slide(board, -1, 1, self.row, self.col)
        self._slide(board, 1, -1, self.row, self.col)
        self._slide(board, -1, -1, self.row, self.col)
        if self.critical:
            super().filter_to_pin_ray()

    def get_value(self, board):
        total = PieceValue.BISHOP
        self.calc_targets(board)
        for cell in self.targets:
            total += 1
            if (cell.row == 3 or cell.row == 4) and (cell.col == 3 or cell.col == 4):
                total += 1
        return total

    def print_piece(self):
        print("Bishop at", self.row, ",", self.col)
