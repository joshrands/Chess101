from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ai.tree import Tree
from core.team import Team

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AI:
    """Alpha-beta minimax agent that selects the best move for a given team.

    Attributes:
        game_tree: Root node of the pre-built game tree to search.
        team: The team on whose behalf the AI is choosing a move.
    """

    def __init__(self, game_tree: Tree, team: Team) -> None:
        """Initialize the AI with a game tree and the team it plays for.

        Args:
            game_tree: Root ``Tree`` node containing all candidate positions.
            team: The ``Team`` instance whose utility the AI maximises.
        """
        self.game_tree = game_tree
        self.team = team

    def alpha_beta_search(self) -> Tree:
        """Run alpha-beta search from the root and return the best child node.

        Iterates over the immediate children of ``self.game_tree``, calls
        ``min_value`` on each, and returns the child with the highest utility.

        Returns:
            The ``Tree`` node (direct successor of the root) representing the
            best move found by the search.
        """
        infinity = float('inf')
        best_val = -infinity
        beta = infinity

        successors = self.get_successors(self.game_tree)
        best_state = None
        for state in successors:
            value = self.min_value(state, best_val, beta)
            if value > best_val:
                best_val = value
                best_state = state
        logger.debug("AlphaBeta:  Best Piece to move is located at: %s%s", best_state.old_cell.row, best_state.old_cell.col)
        logger.debug("AlphaBeta:  This piece should be moved to: %s%s", best_state.new_cell.row, best_state.new_cell.col)
        return best_state

    def max_value(self, node: Tree, alpha: float, beta: float) -> float:
        """Return the maximum utility reachable from ``node`` (maximiser's turn).

        Applies beta pruning: stops expanding children once a value at or above
        ``beta`` is found.

        Args:
            node: Current game-tree node being evaluated.
            alpha: Current lower bound (best value the maximiser can guarantee).
            beta: Current upper bound (best value the minimiser can guarantee).

        Returns:
            The backed-up utility value for this node.
        """
        if self.is_terminal(node):
            return node.get_utility(self.team)
        infinity = float('inf')
        value = -infinity
        for state in self.get_successors(node):
            value = max(value, self.min_value(state, alpha, beta))
            if value >= beta:
                return value
            alpha = max(alpha, value)
        return value

    def min_value(self, node: Tree, alpha: float, beta: float) -> float:
        """Return the minimum utility reachable from ``node`` (minimiser's turn).

        Applies alpha pruning: stops expanding children once a value at or below
        ``alpha`` is found.

        Args:
            node: Current game-tree node being evaluated.
            alpha: Current lower bound (best value the maximiser can guarantee).
            beta: Current upper bound (best value the minimiser can guarantee).

        Returns:
            The backed-up utility value for this node.
        """
        if self.is_terminal(node):
            return node.get_utility(self.team)
        infinity = float('inf')
        value = infinity
        for state in self.get_successors(node):
            value = min(value, self.max_value(state, alpha, beta))
            if value <= alpha:
                return value
            beta = min(beta, value)
        return value

    def get_successors(self, node: Tree) -> list[Tree]:
        """Return the list of child nodes for ``node``.

        Args:
            node: The game-tree node whose children are requested.

        Returns:
            A list of ``Tree`` children; may be empty at leaf nodes.

        Raises:
            ValueError: If ``node`` is ``None``.
        """
        if node is None:
            raise ValueError("node must not be None")
        return node.children

    def is_terminal(self, node: Tree) -> bool:
        """Return ``True`` if ``node`` is a leaf (has no children).

        Args:
            node: The game-tree node to test.

        Returns:
            ``True`` when the node has no children, ``False`` otherwise.

        Raises:
            ValueError: If ``node`` is ``None``.
        """
        if node is None:
            raise ValueError("node must not be None")
        return len(node.children) == 0
