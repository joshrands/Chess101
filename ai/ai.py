from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ai.tree import Tree
from core.team import Team

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AI:
    def __init__(self, game_tree: Tree, team: Team) -> None:
        self.game_tree = game_tree
        self.team = team

    def alpha_beta_search(self) -> Tree:
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
        if node is None:
            raise ValueError("node must not be None")
        return node.children

    def is_terminal(self, node: Tree) -> bool:
        if node is None:
            raise ValueError("node must not be None")
        return len(node.children) == 0
