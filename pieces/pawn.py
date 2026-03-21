from __future__ import annotations

from pieces.piece import Piece, BoardGrid
from core.cell import Cell
from core.constants import PieceValue


class Pawn(Piece):
    """A pawn chess piece.

    Moves one square forward, captures diagonally, and supports en passant
    and promotion to Queen upon reaching the opposite back rank.

    Attributes:
        starting_row: The row the pawn occupied at the start of the game.
        starting_col: The column the pawn occupied at the start of the game.
        direction: +1 for pawns starting on row 1 (moving toward row 7),
            -1 for pawns starting on row 6 (moving toward row 0).
        en_passantable: True for exactly one turn after this pawn advances
            two squares, making it capturable via en passant.
        en_passant_loc: The square to move to when capturing en passant,
            or None if no en passant capture is currently available.
    """

    def __init__(self, row: int, col: int, team) -> None:
        """Initializes a Pawn at the given board position.

        Args:
            row: Starting row on the board.
            col: Starting column on the board.
            team: The team this pawn belongs to.
        """
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
        """Populates self.targets with all legal pawn moves on the given board.

        Computes diagonal captures, one-square advances, the optional two-square
        advance from the starting row, and en passant captures. Applies pin
        filtering if the pawn is pinned (self.critical is True).

        Sets self.en_passant_loc to the destination square if an en passant
        capture is available, otherwise leaves it as None.

        Args:
            board: The current 8x8 board state.
        """
        from pieces.pawn import Pawn  # local import to avoid circular ref at class level
        self.en_passant_loc = None
        self.targets = []
        if self.row != 0 and self.row != 7:
            diag_left = board[self.row + self.direction][self.col - 1] if self.col != 0 else None
            if diag_left is not None and isinstance(diag_left, Piece):
                if diag_left.team != self.team:
                    self.targets.append(Cell(self.row + self.direction, self.col - 1))

            diag_right = board[self.row + self.direction][self.col + 1] if self.col != 7 else None
            if diag_right is not None and isinstance(diag_right, Piece):
                if diag_right.team != self.team:
                    self.targets.append(Cell(self.row + self.direction, self.col + 1))

            if board[self.row + self.direction][self.col] is None:
                self.targets.append(Cell(self.row + self.direction, self.col))

            if self.row == self.starting_row:
                if (board[self.row + 2 * self.direction][self.col] is None
                        and board[self.row + self.direction][self.col] is None):
                    self.targets.append(Cell(self.row + 2 * self.direction, self.col))

            left_neighbor = board[self.row][self.col - 1] if self.col != 0 else None
            if isinstance(left_neighbor, Pawn) and left_neighbor.team != self.team:
                if left_neighbor.en_passantable:
                    self.targets.append(Cell(self.row + self.direction, self.col - 1))
                    self.en_passant_loc = Cell(self.row + self.direction, self.col - 1)

            right_neighbor = board[self.row][self.col + 1] if self.col != 7 else None
            if isinstance(right_neighbor, Pawn) and right_neighbor.team != self.team:
                if right_neighbor.en_passantable:
                    self.targets.append(Cell(self.row + self.direction, self.col + 1))
                    self.en_passant_loc = Cell(self.row + self.direction, self.col + 1)

        if self.critical:
            super().critical_man()

    def get_value(self, board: BoardGrid) -> int:
        """Returns the heuristic value of this pawn.

        Base value from PieceValue.PAWN, plus one point per reachable square,
        and an extra point for each target in the four central squares
        (rows 3–4, cols 3–4).

        Args:
            board: The current 8x8 board state.

        Returns:
            Integer heuristic score for this pawn.
        """
        self.calc_targets(board)
        total: int = PieceValue.PAWN
        total = total + len(self.targets)
        for cell in self.targets:
            total += 1
            if (cell.row == 3 or cell.row == 4) and (cell.col == 3 or cell.col == 4):
                total += 1
        return total

    def sky_fall(self, king) -> None:
        """Restricts targets to squares that resolve a check, preserving en passant.

        Overrides Piece.filter_to_king_escape() to also keep the en passant
        destination when one is available, since capturing the attacker via
        en passant can itself resolve the check.

        Args:
            king: The friendly King whose king_escape_cells define the squares
                that resolve the check.
        """
        new_targets = []
        for target in self.targets:
            for saving_target in king.god_save_the_king:
                if target.row == saving_target.row and target.col == saving_target.col:
                    new_targets.append(target)
        if self.en_passant_loc is not None:
            loc = self.en_passant_loc
            # Only allow en passant when in check if:
            # (1) it was not filtered away by critical_man() — pawn is not pinned off that ray
            # (2) it actually captures the checking piece — the captured pawn sits at
            #     (loc.row - direction, loc.col), NOT at loc itself
            in_pre_targets = any(
                t.row == loc.row and t.col == loc.col for t in self.targets
            )
            captured_row = loc.row - self.direction
            captures_checker = any(
                s.row == captured_row and s.col == loc.col
                for s in king.god_save_the_king
            )
            if in_pre_targets and captures_checker:
                new_targets.append(Cell(loc.row, loc.col))
        self.targets = new_targets

    def move(self, new_row: int, new_col: int, board: BoardGrid) -> Cell | None:
        """Moves the pawn, handling en passant flag and en passant capture.

        Promotion is intentionally NOT handled here; Board.upgrade_pawn() is
        called by do_turn() after this method returns when the pawn reaches the
        back rank.

        If the pawn advances two squares from its starting position,
        self.en_passantable is set to True so adjacent enemy pawns can capture
        it via en passant on the very next turn.

        If the destination matches self.en_passant_loc, this is an en passant
        capture and the method returns the Cell of the captured pawn so the
        caller can remove it from the board.

        Args:
            new_row: Destination row.
            new_col: Destination column.
            board: The current 8x8 board state (unused after promotion removed).

        Returns:
            The Cell of the enemy pawn captured via en passant, or None if this
            was a normal move or advance.
        """
        old_row = self.row
        old_col = self.col
        self.row = new_row
        self.col = new_col
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
        """Prints the piece type and current position to stdout."""
        print("Pawn at", self.row, ",", self.col)
