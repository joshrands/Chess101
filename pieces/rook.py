from __future__ import annotations

from pieces.piece import Piece, BoardGrid
from core.cell import Cell
from core.constants import PieceValue


class Rook(Piece):
    """A rook chess piece that slides orthogonally in all four directions.

    The touched attribute is also used by King.calc_targets() to determine
    castling eligibility: a rook that has never moved (touched == False) is
    a valid castling partner.
    """

    def calc_targets(self, board: BoardGrid) -> None:
        """Populates self.targets with all orthogonal squares reachable by this rook.

        Slides along all four orthogonal rays (N, S, E, W). Applies pin
        filtering if the rook is pinned (self.critical is True).

        Args:
            board: The current 8x8 board state.
        """
        self.targets = []
        self._blade_runner(board, 1, 0, self.row, self.col)
        self._blade_runner(board, 0, 1, self.row, self.col)
        self._blade_runner(board, -1, 0, self.row, self.col)
        self._blade_runner(board, 0, -1, self.row, self.col)
        if self.critical:
            super().critical_man()

    def get_value(self, board: BoardGrid) -> int:
        """Returns the heuristic value of this rook.

        Base value from PieceValue.ROOK, plus one point per reachable square,
        and an extra point for each target in the four central squares
        (rows 3–4, cols 3–4).

        Args:
            board: The current 8x8 board state.

        Returns:
            Integer heuristic score for this rook.
        """
        total: int = PieceValue.ROOK
        self.calc_targets(board)
        for cell in self.targets:
            total += 1
            if (cell.row == 3 or cell.row == 4) and (cell.col == 3 or cell.col == 4):
                total += 1
        return total

    def print_piece(self) -> None:
        """Prints the piece type and current position to stdout."""
        print("Rook at", self.row, ",", self.col)
