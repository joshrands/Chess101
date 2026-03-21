from __future__ import annotations

from pieces.piece import Piece, BoardGrid
from core.cell import Cell
from core.constants import PieceValue


class Bishop(Piece):
    """A bishop chess piece that slides diagonally in all four directions."""

    def calc_targets(self, board: BoardGrid) -> None:
        """Populates self.targets with all diagonal squares reachable by this bishop.

        Slides along all four diagonal rays (NE, NW, SE, SW). Applies pin
        filtering if the bishop is pinned (self.critical is True).

        Args:
            board: The current 8x8 board state.
        """
        self.targets = []
        self._slide(board, 1, 1, self.row, self.col)
        self._slide(board, -1, 1, self.row, self.col)
        self._slide(board, 1, -1, self.row, self.col)
        self._slide(board, -1, -1, self.row, self.col)
        if self.critical:
            super().filter_to_pin_ray()

    def get_value(self, board: BoardGrid) -> int:
        """Returns the heuristic value of this bishop.

        Base value from PieceValue.BISHOP, plus one point per reachable square,
        and an extra point for each target in the four central squares
        (rows 3–4, cols 3–4).

        Args:
            board: The current 8x8 board state.

        Returns:
            Integer heuristic score for this bishop.
        """
        total = PieceValue.BISHOP
        self.calc_targets(board)
        for cell in self.targets:
            total += 1
            if (cell.row == 3 or cell.row == 4) and (cell.col == 3 or cell.col == 4):
                total += 1
        return total

    def print_piece(self) -> None:
        """Prints the piece type and current position to stdout."""
        print("Bishop at", self.row, ",", self.col)
