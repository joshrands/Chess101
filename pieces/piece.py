from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from core.team import Team
from core.cell import Cell

if TYPE_CHECKING:
    from pieces.king import King


class Piece(ABC):
    def __init__(self, row: int, col: int, team: Team) -> None:
        self.row = row
        self.col = col
        self.targets: list[Cell] = []
        self.team = team
        self.touched: bool = False
        self.critical: bool = False
        self.critical_targets: list[Cell] = []

    @abstractmethod
    def calc_targets(self, board: BoardGrid) -> None:
        raise NotImplementedError()

    @abstractmethod
    def get_value(self, board: BoardGrid) -> int:
        raise NotImplementedError()

    def move(self, new_row: int, new_col: int, board: BoardGrid) -> None:
        self.row = new_row
        self.col = new_col
        self.touched = True

    def _ray_cast(
        self,
        board: BoardGrid,
        current_row: int,
        current_col: int,
        dr: int,
        dc: int,
    ) -> tuple[int, int]:
        if 0 <= current_row < 8 and 0 <= current_col < 8:
            next_loc = (
                0 <= current_row + dr < 8 and 0 <= current_col + dc < 8
            )
            if board[current_row][current_col] is not None:
                if board[current_row][current_col].team != self.team:
                    return current_row, current_col
                else:
                    return -1, -1
            elif next_loc:
                return self._ray_cast(board, current_row + dr, current_col + dc, dr, dc)
        return -1, -1

    def _slide(self, board: BoardGrid, dr: int, dc: int, row: int, col: int) -> None:
        if 0 <= row + dr <= 7 and 0 <= col + dc <= 7:
            if board[row + dr][col + dc] is None:
                self.targets.append(Cell(row + dr, col + dc))
                self._slide(board, dr, dc, row + dr, col + dc)
            elif board[row + dr][col + dc].team != self.team:
                self.targets.append(Cell(row + dr, col + dc))

    def filter_to_pin_ray(self) -> None:
        new_targets = []
        for critical_cell in self.critical_targets:
            for cell in self.targets:
                if critical_cell.row == cell.row and critical_cell.col == cell.col:
                    new_targets.append(cell)
        self.targets = new_targets

    def filter_to_king_escape(self, king: King) -> None:
        new_targets = []
        for target in self.targets:
            for saving_target in king.king_escape_cells:
                if target.row == saving_target.row and target.col == saving_target.col:
                    new_targets.append(target)
        self.targets = new_targets

    def print_piece(self, board: BoardGrid) -> None:
        print("Piece at", self.row, ",", self.col)

    def get_targets(self) -> list[Cell]:
        return self.targets


# Defined after class so Piece is in scope at evaluation time.
# Uses Optional rather than X | Y to stay compatible with Python 3.9.
BoardGrid = list[list[Optional[Piece]]]
