from __future__ import annotations

from pieces.piece import Piece, BoardGrid
from core.cell import Cell
from core.constants import PieceValue

_KNIGHT_DELTAS = [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]
"""All eight (dr, dc) offsets for a knight's L-shaped jump."""


class Knight(Piece):
    """A knight chess piece that jumps in an L-shape.

    Unlike sliding pieces, the knight leaps over any intervening pieces.
    A pinned knight (self.critical == True) will have all its moves filtered
    away by filter_to_pin_ray(), since it cannot move along a pin ray.
    """

    def calc_targets(self, board: BoardGrid) -> None:
        """Populates self.targets with all squares reachable by this knight.

        Checks all eight L-shaped jump destinations. A square is reachable if
        it is on the board and not occupied by a friendly piece. Applies pin
        filtering if the knight is pinned (self.critical is True), which in
        practice removes all targets since a knight cannot move along a ray.

        Args:
            board: The current 8x8 board state.
        """
        self.targets = []
        for dr, dc in _KNIGHT_DELTAS:
            r, c = self.row + dr, self.col + dc
            if 0 <= r <= 7 and 0 <= c <= 7:
                occupant = board[r][c]
                if occupant is None or occupant.team != self.team:
                    self.targets.append(Cell(r, c))
        if self.critical:
            super().critical_man()

    def get_value(self, board: BoardGrid) -> int:
        """Returns the heuristic value of this knight.

        Base value from PieceValue.KNIGHT, plus one point per reachable square,
        and an extra point for each target in the four central squares
        (rows 3–4, cols 3–4).

        Args:
            board: The current 8x8 board state.

        Returns:
            Integer heuristic score for this knight.
        """
        total = PieceValue.KNIGHT
        self.calc_targets(board)
        for cell in self.targets:
            total += 1
            if (cell.row == 3 or cell.row == 4) and (cell.col == 3 or cell.col == 4):
                total += 1
        return total

    def print_piece(self) -> None:
        """Prints the piece type and current position to stdout."""
        print("Knight at", self.row, ",", self.col)
