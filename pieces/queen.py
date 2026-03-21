from __future__ import annotations

from pieces.piece import Piece, BoardGrid
from core.cell import Cell
from core.constants import PieceValue


class Queen(Piece):
    """A queen chess piece that slides in all eight directions.

    The queen combines the movement of a rook and a bishop. It is also the
    promotion target when a pawn reaches the opposite back rank.
    """

    def calc_targets(self, board: BoardGrid) -> None:
        """Populates self.targets with all squares reachable by this queen.

        Slides along all four diagonal rays and all four orthogonal rays.
        Applies pin filtering if the queen is pinned (self.critical is True).

        Args:
            board: The current 8x8 board state.
        """
        self.targets = []
        self._blade_runner(board, 1, 1, self.row, self.col)
        self._blade_runner(board, -1, 1, self.row, self.col)
        self._blade_runner(board, 1, -1, self.row, self.col)
        self._blade_runner(board, -1, -1, self.row, self.col)
        self._blade_runner(board, 1, 0, self.row, self.col)
        self._blade_runner(board, -1, 0, self.row, self.col)
        self._blade_runner(board, 0, 1, self.row, self.col)
        self._blade_runner(board, 0, -1, self.row, self.col)
        if self.critical:
            super().critical_man()

    def get_value(self, board: BoardGrid) -> int:
        """Returns the heuristic value of this queen.

        Base value from PieceValue.QUEEN, plus one point per reachable square,
        and an extra point for each target in the four central squares
        (rows 3–4, cols 3–4).

        Args:
            board: The current 8x8 board state.

        Returns:
            Integer heuristic score for this queen.
        """
        total: int = PieceValue.QUEEN
        self.calc_targets(board)
        for cell in self.targets:
            total += 1
            if (cell.row == 3 or cell.row == 4) and (cell.col == 3 or cell.col == 4):
                total += 1
        return total

    def print_piece(self) -> None:
        """Prints the piece type and current position to stdout."""
        print("Queen at", self.row, ",", self.col)
