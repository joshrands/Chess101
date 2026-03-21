from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from core.team import Team
from core.cell import Cell

if TYPE_CHECKING:
    from pieces.king import King


class Piece(ABC):
    """Abstract base class for all chess pieces.

    Attributes:
        row: Current board row (0 = team_r back rank, 7 = team_l back rank).
        col: Current board column (0–7).
        targets: Legal destination squares for the current position.
        team: The team this piece belongs to.
        touched: True once the piece has been moved from its starting square.
        critical: True when the piece is pinned (moving would expose the king).
        critical_targets: Cells along the pin ray; only moves to these squares
            are legal while the piece is pinned.
    """

    def __init__(self, row: int, col: int, team: Team) -> None:
        """Initializes a Piece at the given board position.

        Args:
            row: Starting row on the board.
            col: Starting column on the board.
            team: The team this piece belongs to.
        """
        self.row = row
        self.col = col
        self.targets: list[Cell] = []
        self.team = team
        self.touched: bool = False
        self.critical: bool = False
        self.critical_targets: list[Cell] = []

    @abstractmethod
    def calc_targets(self, board: BoardGrid) -> None:
        """Populates self.targets with all legal destination squares.

        Implementations must also apply pin filtering via filter_to_pin_ray()
        when self.critical is True.

        Args:
            board: The current 8x8 board state.
        """
        raise NotImplementedError()

    @abstractmethod
    def get_value(self, board: BoardGrid) -> int:
        """Returns the heuristic material + mobility value of this piece.

        Used by the AI's minimax evaluation function.

        Args:
            board: The current 8x8 board state.

        Returns:
            Integer score representing the piece's value.
        """
        raise NotImplementedError()

    def move(self, new_row: int, new_col: int, board: BoardGrid) -> None:
        """Moves the piece to the target square and marks it as touched.

        Args:
            new_row: Destination row.
            new_col: Destination column.
            board: The current 8x8 board state (unused in the base
                implementation but available to subclass overrides).
        """
        self.row = new_row
        self.col = new_col
        self.touched = True

    def _kingsman(
        self,
        board: BoardGrid,
        current_row: int,
        current_col: int,
        dr: int,
        dc: int,
    ) -> tuple[int, int]:
        """Recursively searches along a ray for the first occupied enemy square.

        Skips empty squares; stops and returns the square if the first piece
        found belongs to the opposing team, or returns (-1, -1) if the ray is
        blocked by a friendly piece or exits the board.

        Args:
            board: The current 8x8 board state.
            current_row: Row of the square currently being examined.
            current_col: Column of the square currently being examined.
            dr: Row step direction (-1, 0, or 1).
            dc: Column step direction (-1, 0, or 1).

        Returns:
            (row, col) of the first enemy piece on the ray, or (-1, -1) if
            none is found before the ray is blocked or leaves the board.
        """
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
                return self._kingsman(board, current_row + dr, current_col + dc, dr, dc)
        return -1, -1

    def _blade_runner(self, board: BoardGrid, dr: int, dc: int, row: int, col: int) -> None:
        """Recursively appends reachable squares along a single ray to self.targets.

        Continues through empty squares and stops after adding a capturable
        enemy square. Friendly-occupied squares end the ray without adding.

        Args:
            board: The current 8x8 board state.
            dr: Row step direction (-1, 0, or 1).
            dc: Column step direction (-1, 0, or 1).
            row: Row of the square last added (or the piece's own square on
                the initial call).
            col: Column of the square last added (or the piece's own square
                on the initial call).
        """
        if 0 <= row + dr <= 7 and 0 <= col + dc <= 7:
            if board[row + dr][col + dc] is None:
                self.targets.append(Cell(row + dr, col + dc))
                self._blade_runner(board, dr, dc, row + dr, col + dc)
            elif board[row + dr][col + dc].team != self.team:
                self.targets.append(Cell(row + dr, col + dc))

    def critical_man(self) -> None:
        """Restricts self.targets to squares that lie on the current pin ray.

        Called after calc_targets() when self.critical is True. Retains only
        squares present in both self.targets and self.critical_targets.
        """
        new_targets = []
        for critical_cell in self.critical_targets:
            for cell in self.targets:
                if critical_cell.row == cell.row and critical_cell.col == cell.col:
                    new_targets.append(cell)
        self.targets = new_targets

    def sky_fall(self, king: King) -> None:
        """Restricts self.targets to squares that resolve a check on the king.

        Called when the friendly king is in check. Only moves that block or
        capture the attacker (i.e., squares in king.god_save_the_king) remain.

        Args:
            king: The friendly King whose king_escape_cells define the
                squares that resolve the check.
        """
        new_targets = []
        for target in self.targets:
            for saving_target in king.god_save_the_king:
                if target.row == saving_target.row and target.col == saving_target.col:
                    new_targets.append(target)
        self.targets = new_targets

    def print_piece(self, board: BoardGrid) -> None:
        """Prints the piece type and current position to stdout."""
        print("Piece at", self.row, ",", self.col)

    def get_targets(self) -> list[Cell]:
        """Returns the list of legal target squares computed by calc_targets()."""
        return self.targets


# Defined after class so Piece is in scope at evaluation time.
# Uses Optional rather than X | Y to stay compatible with Python 3.9.
BoardGrid = list[list[Optional[Piece]]]
