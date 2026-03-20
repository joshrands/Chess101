from Tree import Tree


class AI:
    def __init__(self, game_tree, team):
        self.game_tree = game_tree
        self.team = team

    def alpha_beta_search(self):
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
        print(f"AlphaBeta:  Best Piece to move is located at: {best_state.old_cell.row}{best_state.old_cell.col}")
        print(f"AlphaBeta:  This piece should be moved to: {best_state.new_cell.row}{best_state.new_cell.col}")
        return best_state

    def max_value(self, node, alpha, beta):
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

    def min_value(self, node, alpha, beta):
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

    def get_successors(self, node):
        if node is None:
            raise ValueError("node must not be None")
        return node.children

    def is_terminal(self, node):
        if node is None:
            raise ValueError("node must not be None")
        return len(node.children) == 0
