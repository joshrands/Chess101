from __future__ import annotations

from Piece import Piece, BoardGrid
from Cell import Cell
from Queen import Queen
from constants import PieceValue


class Pawn(Piece):
    def __init__(self, row: int, col: int, team) -> None:
        self.row = row
        self.col = col
        self.targets: list[Cell] = []
        self.team = team
        self.starting_row = row
        self.starting_col = col
        if self.row == 6:
            self.direction = -1
        else:
            self.direction = 1
        self.en_passantable: bool = False
        self.en_passant_loc: Cell | None = None
        self.critical: bool = False
        self.critical_targets: list[Cell] = []

    def calc_targets(self, board: BoardGrid) -> None:
        self.en_passant_loc = None
        self.targets = []
        if self.row != 0 and self.row != 7:
            if self.col != 0 and isinstance(board[self.row + self.direction][self.col - 1], Piece):
                if board[self.row + self.direction][self.col - 1].team != self.team:
                    self.targets.append(Cell(self.row + self.direction, self.col - 1))

            if self.col != 7 and isinstance(board[self.row + self.direction][self.col + 1], Piece):
                if board[self.row + self.direction][self.col + 1].team != self.team:
                    self.targets.append(Cell(self.row + self.direction, self.col + 1))

            if board[self.row + self.direction][self.col] is None:
                self.targets.append(Cell(self.row + self.direction, self.col))

            if self.row == self.starting_row:
                if (board[self.row + 2 * self.direction][self.col] is None
                        and board[self.row + self.direction][self.col] is None):
                    self.targets.append(Cell(self.row + 2 * self.direction, self.col))

            if (self.col != 0
                    and isinstance(board[self.row][self.col - 1], Pawn)
                    and board[self.row][self.col - 1].team != self.team):
                if board[self.row][self.col - 1].en_passantable:
                    self.targets.append(Cell(self.row + self.direction, self.col - 1))
                    self.en_passant_loc = Cell(self.row + self.direction, self.col - 1)

            if (self.col != 7
                    and isinstance(board[self.row][self.col + 1], Pawn)
                    and board[self.row][self.col + 1].team != self.team):
                if board[self.row][self.col + 1].en_passantable:
                    self.targets.append(Cell(self.row + self.direction, self.col + 1))
                    self.en_passant_loc = Cell(self.row + self.direction, self.col + 1)

        if self.critical:
            super().filter_to_pin_ray()

    def get_value(self, board: BoardGrid) -> int:
        self.calc_targets(board)
        total = PieceValue.PAWN
        total = total + len(self.targets)
        for cell in self.targets:
            total += 1
            if (cell.row == 3 or cell.row == 4) and (cell.col == 3 or cell.col == 4):
                total += 1
        return total

    def filter_to_king_escape(self, king) -> None:
        new_targets = []
        for target in self.targets:
            for saving_target in king.king_escape_cells:
                if target.row == saving_target.row and target.col == saving_target.col:
                    new_targets.append(target)
        if self.en_passant_loc is not None:
            new_targets.append(Cell(self.en_passant_loc.row, self.en_passant_loc.col))
        self.targets = new_targets

    def move(self, new_row: int, new_col: int, board: BoardGrid) -> Cell | None:
        old_row = self.row
        old_col = self.col
        self.row = new_row
        self.col = new_col
        if (self.starting_row + 6) % 12 == self.row:
            board[self.row][self.col] = Queen(self.row, self.col, self.team)
        if (old_row == self.starting_row
                and old_col == self.starting_col
                and (new_row - old_row) == 2 * self.direction):
            self.en_passantable = True
        if (self.en_passant_loc is not None
                and new_row == self.en_passant_loc.row
                and new_col == self.en_passant_loc.col):
            return Cell(self.en_passant_loc.row - self.direction, self.en_passant_loc.col)
        else:
            return None

    def print_piece(self) -> None:
        print("Pawn at", self.row, ",", self.col)
