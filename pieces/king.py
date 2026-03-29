from __future__ import annotations

from pieces.piece import Piece, BoardGrid
from core.cell import Cell
from core.team import Team
from core.constants import PieceValue


class King(Piece):
    """The king chess piece.

    Moves one square in any direction. Responsible for detecting check,
    computing castling eligibility, identifying pinned friendly pieces, and
    building the set of squares that would resolve a check.

    Attributes:
        direction: +1 for the king starting on row 0, -1 for row 7. Used when
            checking pawn-attack direction during find_attacker().
        king_escape_cells: Squares that, if moved to by any friendly piece,
            would resolve a current check (i.e., the attacker's square and all
            squares between the attacker and the king on the attack ray).
    """

    def __init__(self, row: int, col: int, team: Team) -> None:
        """Initializes the King at the given board position.

        Args:
            row: Starting row on the board.
            col: Starting column on the board.
            team: The team this king belongs to.
        """
        self.row = row
        self.col = col
        self.targets: list[Cell] = []
        self.team = team
        if self.row == 7:
            self.direction = -1
        else:
            self.direction = 1
        self.touched: bool = False
        self.critical: bool = False
        self.god_save_the_king: list[Cell] = []

    def _blade_walker(self, board: BoardGrid, dr: int, dc: int, row: int, col: int) -> None:
        """Adds the single adjacent square in direction (dr, dc) to self.targets if reachable.

        The square is considered reachable if it is on the board and either
        empty or occupied by an enemy piece. Does not check whether the square
        is safe — that filtering happens in calc_targets().

        Args:
            board: The current 8x8 board state.
            dr: Row step (-1, 0, or 1).
            dc: Column step (-1, 0, or 1).
            row: The king's current row.
            col: The king's current column.
        """
        if 0 <= row + dr <= 7 and 0 <= col + dc <= 7:
            neighbor = board[row + dr][col + dc]
            if neighbor is None:
                self.targets.append(Cell(row + dr, col + dc))
            elif neighbor.team != self.team:
                self.targets.append(Cell(row + dr, col + dc))

    def calc_targets(self, board: BoardGrid) -> bool:
        """Populates self.targets with legal king moves and returns whether the king is in check.

        Steps performed:
        1. Generates all one-step candidate squares via _walk().
        2. Adds castling destinations (queen-side col-2, king-side col+2) if
           the king and the relevant rook are both untouched and the squares
           between them are empty.
        3. Simulates each candidate move on the board to detect self-check via
           find_attacker(); unsafe squares are removed.
        4. Castling is additionally disallowed if the king is currently in
           check or if the intermediate step square is attacked.

        Args:
            board: The current 8x8 board state.

        Returns:
            True if the king is currently in check after all filtering, False
            otherwise.
        """
        from pieces.rook import Rook
        self.targets = []
        self._blade_walker(board, 1, 1, self.row, self.col)
        self._blade_walker(board, -1, 1, self.row, self.col)
        self._blade_walker(board, 1, -1, self.row, self.col)
        self._blade_walker(board, -1, -1, self.row, self.col)
        self._blade_walker(board, 1, 0, self.row, self.col)
        self._blade_walker(board, -1, 0, self.row, self.col)
        self._blade_walker(board, 0, 1, self.row, self.col)
        self._blade_walker(board, 0, -1, self.row, self.col)

        old_row = self.row
        old_col = self.col

        if not self.touched:
            left_rook = board[self.row][self.col - 4]
            if isinstance(left_rook, Rook) and not left_rook.touched:
                if (board[self.row][self.col - 1] is None
                        and board[self.row][self.col - 2] is None
                        and board[self.row][self.col - 3] is None):
                    self.targets.append(Cell(self.row, self.col - 2))
            right_rook = board[self.row][self.col + 3]
            if isinstance(right_rook, Rook) and not right_rook.touched:
                if board[self.row][self.col + 1] is None and board[self.row][self.col + 2] is None:
                    self.targets.append(Cell(self.row, self.col + 2))

        targets_to_remove = []

        castle_left = False
        castle_left_step = True
        castle_right = False
        castle_right_step = True
        castle_left_cell = Cell(-1, -1)
        castle_right_cell = Cell(-1, -1)

        for cell in self.targets:
            if cell.row == old_row and cell.col == old_col - 2:
                castle_left = True
                castle_left_cell = cell
            if cell.row == old_row and cell.col == old_col + 2:
                castle_right = True
                castle_right_cell = cell
            original_piece = board[cell.row][cell.col]
            board[cell.row][cell.col] = self
            board[self.row][self.col] = None
            self.row = cell.row
            self.col = cell.col
            threat_row, threat_col = self.am_i_gonna_die(board)
            if threat_row != -1 and threat_col != -1:
                if cell.row == old_row and cell.col == old_col - 2:
                    castle_left = False
                if cell.row == old_row and cell.col == old_col + 2:
                    castle_right = False
                if cell.row == old_row and cell.col == old_col - 1:
                    castle_left_step = False
                if cell.row == old_row and cell.col == old_col + 1:
                    castle_right_step = False
                targets_to_remove.append(cell)

            board[old_row][old_col] = self
            board[cell.row][cell.col] = original_piece
            self.row = old_row
            self.col = old_col

        _attacker_row, _attacker_col = self.am_i_gonna_die(board)
        in_check = _attacker_row != -1 and _attacker_col != -1

        if castle_left and (not castle_left_step or in_check):
            self.targets.remove(castle_left_cell)
        if castle_right and (not castle_right_step or in_check):
            self.targets.remove(castle_right_cell)
        for to_remove in targets_to_remove:
            self.targets.remove(to_remove)

        return in_check

    def get_value(self, board: BoardGrid) -> int:
        """Returns the heuristic value of the king.

        Returns PieceValue.KING normally, or 0 if the king is currently in
        check (signaling a degraded position to the AI evaluator).

        Args:
            board: The current 8x8 board state.

        Returns:
            Integer heuristic score for this king.
        """
        value: int = PieceValue.KING
        if self.am_i_gonna_die(board):
            value = 0
        return value

    def move(self, new_row: int, new_col: int, board: BoardGrid) -> tuple[Cell | None, Cell | None]:
        """Moves the king and signals the rook positions involved in a castling move.

        Updates the king's position and marks it as touched. If the move is a
        two-square horizontal move, it is a castling move and the method returns
        the rook's current cell and its destination cell so the caller can
        reposition the rook on the board.

        Args:
            new_row: Destination row.
            new_col: Destination column.
            board: The current 8x8 board state (not mutated here; the caller
                is responsible for updating rook position on castling).

        Returns:
            A (rook_from_cell, rook_to_cell) tuple if castling, or
            (None, None) for a regular king move.
        """
        old_row = self.row
        old_col = self.col
        self.row = new_row
        self.col = new_col
        self.touched = True
        if new_row == old_row and new_col == old_col - 2:
            return Cell(old_row, old_col - 4), Cell(old_row, old_col - 1)
        elif new_row == old_row and new_col == old_col + 2:
            return Cell(old_row, old_col + 3), Cell(old_row, old_col + 1)
        else:
            return None, None

    def am_i_gonna_die(self, board: BoardGrid) -> tuple[int, int]:
        """Scans the board for any enemy piece currently giving check to this king.

        Also clears and resets the critical (pin) flags on all friendly pieces,
        then re-evaluates pins by examining every ray from the king outward. A
        friendly piece on a ray is marked critical (pinned) when an enemy
        sliding piece of the correct type lies further along the same ray.

        Sets self.god_save_the_king to the squares that would block or capture
        the checking piece if check is detected.

        Args:
            board: The current 8x8 board state.

        Returns:
            (row, col) of the attacking piece if the king is in check, or
            (-1, -1) if the king is safe.
        """
        from pieces.rook import Rook
        from pieces.bishop import Bishop
        from pieces.knight import Knight
        from pieces.pawn import Pawn
        from pieces.queen import Queen

        for row in board:
            for piece in row:
                if piece is not None and piece.team == self.team:
                    piece.critical = False

        attacker_row, attacker_col = -1, -1
        attacker_count = 0

        for i in [-1, 0, 1]:
            for j in [-1, 0, 1]:
                if i == 0 and j == 0:
                    continue

                enemy_row, enemy_col, scout_row, scout_col = self._i_spy(
                    board, self.row + i, self.col + j, i, j)

                if i == 0 or j == 0:
                    if scout_row != -1:
                        if enemy_row != -1:
                            if isinstance(board[enemy_row][enemy_col], (Rook, Queen)):
                                scout_piece = board[scout_row][scout_col]
                                if scout_piece is not None:
                                    scout_piece.critical = True
                                    scout_piece.critical_targets = (
                                        self.please_god_save_the_king(enemy_row, enemy_col)
                                    )
                    elif enemy_row != -1:
                        if isinstance(board[enemy_row][enemy_col], (Rook, Queen)):
                            self.god_save_the_king = self.please_god_save_the_king(
                                enemy_row, enemy_col)
                            attacker_row, attacker_col = enemy_row, enemy_col
                            attacker_count += 1
                        elif isinstance(board[enemy_row][enemy_col], King):
                            if abs(enemy_row - self.row) + abs(enemy_col - self.col) == 1:
                                self.god_save_the_king = self.please_god_save_the_king(
                                    enemy_row, enemy_col)
                                attacker_row, attacker_col = enemy_row, enemy_col
                                attacker_count += 1
                else:
                    if scout_row != -1:
                        if enemy_row != -1:
                            if isinstance(board[enemy_row][enemy_col], (Bishop, Queen)):
                                scout_piece = board[scout_row][scout_col]
                                if scout_piece is not None:
                                    scout_piece.critical = True
                                    scout_piece.critical_targets = (
                                        self.please_god_save_the_king(enemy_row, enemy_col)
                                    )
                    elif enemy_row != -1:
                        if isinstance(board[enemy_row][enemy_col], (Bishop, Queen)):
                            self.god_save_the_king = self.please_god_save_the_king(
                                enemy_row, enemy_col)
                            attacker_row, attacker_col = enemy_row, enemy_col
                            attacker_count += 1
                        elif isinstance(board[enemy_row][enemy_col], King):
                            if abs(enemy_row - self.row) + abs(enemy_col - self.col) == 2:
                                self.god_save_the_king = self.please_god_save_the_king(
                                    enemy_row, enemy_col)
                                attacker_row, attacker_col = enemy_row, enemy_col
                                attacker_count += 1
                        elif isinstance(board[enemy_row][enemy_col], Pawn):
                            if enemy_row - self.row == self.direction:
                                self.god_save_the_king = self.please_god_save_the_king(
                                    enemy_row, enemy_col)
                                attacker_row, attacker_col = enemy_row, enemy_col
                                attacker_count += 1

        row_deltas = [2, 2, -2, -2, 1, 1, -1, -1]
        col_deltas = [1, -1, 1, -1, 2, -2, 2, -2]
        for i in range(8):
            knight_row, knight_col = self._knight_in_shining_armor(
                board, row_deltas[i], col_deltas[i], self.row, self.col)
            if knight_row != -1 and knight_col != -1:
                self.god_save_the_king = [Cell(knight_row, knight_col)]
                attacker_row, attacker_col = knight_row, knight_col
                attacker_count += 1
                break

        # Double check: no single piece can resolve two checks at once,
        # so only king moves are legal.  Clear god_save_the_king so that
        # sky_fall filters out all non-king targets.
        if attacker_count > 1:
            self.god_save_the_king = []

        return attacker_row, attacker_col

    def _i_spy(
        self,
        board: BoardGrid,
        current_row: int,
        current_col: int,
        dr: int,
        dc: int,
    ) -> tuple[int, int, int, int]:
        """Scans a ray outward from the king to detect checks and pins.

        Walks the ray one square at a time:
        - Empty square: recurse further along the ray.
        - Enemy piece with no friendly piece between it and the king:
          returns (enemy_row, enemy_col, -1, -1) indicating a direct threat.
        - Friendly piece encountered first: uses _ray_cast() from that
          friendly piece's position to look for an enemy behind it. If found,
          returns (enemy_row, enemy_col, friendly_row, friendly_col) indicating
          a pin; the friendly piece is the scout.

        Args:
            board: The current 8x8 board state.
            current_row: Row of the square currently being examined.
            current_col: Column of the square currently being examined.
            dr: Row step direction (-1, 0, or 1).
            dc: Column step direction (-1, 0, or 1).

        Returns:
            A four-tuple (enemy_row, enemy_col, scout_row, scout_col).
            enemy_row/enemy_col: position of the threatening enemy piece, or
                -1/-1 if none found on this ray.
            scout_row/scout_col: position of the pinned friendly piece, or
                -1/-1 if the king is directly threatened (no friendly piece
                between the king and the attacker).
        """
        next_loc = (
            0 <= current_row + dr < 8 and 0 <= current_col + dc < 8
        )
        if 0 <= current_row < 8 and 0 <= current_col < 8:
            cur_piece = board[current_row][current_col]
            if cur_piece is not None:
                if cur_piece.team != self.team:
                    return current_row, current_col, -1, -1
                elif next_loc:
                    scout_row, scout_col = cur_piece._kingsman(
                        board, current_row + dr, current_col + dc, dr, dc)
                    return scout_row, scout_col, current_row, current_col
            elif next_loc:
                e_row, e_col, s_row, s_col = self._i_spy(
                    board, current_row + dr, current_col + dc, dr, dc)
                return e_row, e_col, s_row, s_col
        return -1, -1, -1, -1

    def _knight_in_shining_armor(
        self,
        board: BoardGrid,
        dr: int,
        dc: int,
        row: int,
        col: int,
    ) -> tuple[int, int]:
        """Checks whether an enemy knight occupies the given L-shaped offset from (row, col).

        Args:
            board: The current 8x8 board state.
            dr: Row offset for the knight jump.
            dc: Column offset for the knight jump.
            row: The king's current row.
            col: The king's current column.

        Returns:
            (row+dr, col+dc) if an enemy knight is at that square, else (-1, -1).
        """
        from pieces.knight import Knight
        if 0 <= row + dr <= 7 and 0 <= col + dc <= 7:
            candidate = board[row + dr][col + dc]
            if isinstance(candidate, Knight) and candidate.team != self.team:
                return row + dr, col + dc
        return -1, -1

    def please_god_save_the_king(self, enemy_row: int, enemy_col: int) -> list[Cell]:
        """Builds the list of squares a friendly piece can move to in order to resolve a check.

        Starts at the attacker's square and steps toward the king, collecting
        every intermediate square (inclusive of the attacker, exclusive of the
        king itself). A friendly piece can resolve the check by moving to any
        one of these squares (either capturing the attacker or interposing).

        Args:
            enemy_row: Row of the attacking piece.
            enemy_col: Column of the attacking piece.

        Returns:
            List of Cell objects from the attacker's square to the square
            immediately adjacent to the king along the attack ray.
        """
        dr, dc = self.determine_direction_from_enemy_towards_king(enemy_row, enemy_col)
        save_the_king: list[Cell] = []
        r: float = enemy_row
        c: float = enemy_col
        while not (r == self.row and c == self.col):
            save_the_king.append(Cell(int(r), int(c)))
            r = r + dr
            c = c + dc
        return save_the_king

    def determine_direction_from_enemy_towards_king(
        self, enemy_row: int, enemy_col: int
    ) -> tuple[float, float]:
        """Computes the unit step (dr, dc) pointing from the attacker toward the king.

        Handles three cases: same row (horizontal ray), same column (vertical
        ray), and diagonal rays. Each component is either 0, +1, or -1.

        Args:
            enemy_row: Row of the attacking piece.
            enemy_col: Column of the attacking piece.

        Returns:
            A (dr, dc) tuple of floats representing the normalized direction
            from the attacker toward the king.
        """
        if enemy_row == self.row:
            return 0, -1 * (enemy_col - self.col) / abs(enemy_col - self.col)
        elif enemy_col == self.col:
            return -1 * (enemy_row - self.row) / abs(enemy_row - self.row), 0
        else:
            return (
                -1 * (enemy_row - self.row) / abs(enemy_row - self.row),
                -1 * (enemy_col - self.col) / abs(enemy_col - self.col),
            )

    def print_piece(self) -> None:
        """Prints the piece type and current position to stdout."""
        print("King at", self.row, ",", self.col)
