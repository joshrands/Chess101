from __future__ import annotations

from typing import TYPE_CHECKING

from core.team import Team
from pieces.piece import Piece, BoardGrid

if TYPE_CHECKING:
    from core.cell import Cell


class Tree:
    """Game-tree node that stores a board snapshot and the move that produced it.

    Each node holds a full 8x8 board state and a list of child nodes
    representing all legal successor positions.  The root node has
    ``old_cell`` and ``new_cell`` set to ``None``.

    Attributes:
        children: Ordered list of child ``Tree`` nodes (successor positions).
        board_state: 8x8 grid of ``Piece | None`` representing this position.
        old_cell: Square the moved piece came from; ``None`` at the root.
        new_cell: Square the moved piece landed on; ``None`` at the root.
        team_r: Copy of the ``team_r`` (row-0 side) identity used for utility
            calculation.
        team_l: Copy of the ``team_l`` (row-7 side) identity used for utility
            calculation.
    """

    def __init__(
        self,
        board_state: BoardGrid,
        old_cell: Cell | None,
        new_cell: Cell | None,
        team_r: Team,
        team_l: Team,
    ) -> None:
        """Create a game-tree node.

        Args:
            board_state: 8x8 grid representing the chess position at this node.
            old_cell: Origin square of the move that led to this node, or
                ``None`` for the root.
            new_cell: Destination square of the move that led to this node, or
                ``None`` for the root.
            team_r: The team occupying row 0 (back-rank side).
            team_l: The team occupying row 7 (opponent side).
        """
        self.children: list[Tree] = []
        self.board_state = board_state
        self.old_cell = old_cell
        self.new_cell = new_cell
        self.team_r = Team(team_r.r, team_r.g, team_r.b)
        self.team_l = Team(team_l.r, team_l.g, team_l.b)

    def add_child(self, child: Tree) -> None:
        """Append a child node to this node's successor list.

        Args:
            child: The ``Tree`` node to add as a child.
        """
        self.children.append(child)

    def get_board_state(self) -> BoardGrid:
        """Return the board-state grid stored at this node.

        Returns:
            The 8x8 ``BoardGrid`` (list of lists of ``Piece | None``) for this
            position.
        """
        return self.board_state

    def get_utility(self, team: Team) -> int:
        """Compute the material-balance utility of this position for ``team``.

        Sums ``get_value()`` for every piece on the board, separating totals by
        team side.  The raw score is ``team_r_total - team_l_total``; if
        ``team`` is ``team_l`` the sign is flipped so that a higher return value
        always means a better outcome for the requesting team.

        Args:
            team: The team from whose perspective the utility is computed.

        Returns:
            An integer utility score; positive values favour ``team``.
        """
        white_count = 0
        black_count = 0
        for r in range(8):
            for piece in self.board_state[r]:
                if piece is None:
                    continue
                elif piece.team.r == self.team_r.r:
                    white_count += piece.get_value(self.board_state)
                else:
                    black_count += piece.get_value(self.board_state)

        total = white_count - black_count
        if team.r == self.team_l.r:
            total = -total
        return total
