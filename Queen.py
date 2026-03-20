from Piece import Piece
from Cell import Cell


class Queen(Piece):
    def _slide(self, board, dr, dc, row, col):
        if 0 <= row + dr <= 7 and 0 <= col + dc <= 7:
            if board[row + dr][col + dc] is None:
                self.targets.append(Cell(row + dr, col + dc))
                self._slide(board, dr, dc, row + dr, col + dc)
            elif board[row + dr][col + dc].team != self.team:
                self.targets.append(Cell(row + dr, col + dc))

    def calc_targets(self, board):
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

    def get_value(self, board):
        total = 49
        self.calc_targets(board)
        for cell in self.targets:
            total += 1
            if (cell.row == 3 or cell.row == 4) and (cell.col == 3 or cell.col == 4):
                total += 1
        return total

    def print_piece(self):
        print("Queen at", self.row, ",", self.col)
