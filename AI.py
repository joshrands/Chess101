from Tree import Tree

class AI:
    # print utility value of root node (assuming it is max)
    # print names of all nodes visited during search
    def __init__(self, game_tree, team):
        self.game_tree = game_tree  # Whole tree (only the root node, but this node will contain the children)
        self.team = team
        return

    def alpha_beta_search(self):

        infinity = float('inf')
        best_val = -infinity
        beta = infinity

        successors = self.getSuccessors(self.game_tree)
        best_state = None
        for state in successors: # for every node..
            value = self.min_value(state, best_val, beta)
            if value > best_val:
                best_val = value
                best_state = state
        print "AlphaBeta:  Utility Value of Root Node: = " + str(best_val)
        print "AlphaBeta:  Best Piece to move is located at: " + best_state.getOldCell
        print "AlphaBeta:  This piece should be moved to: " + best_state.getNewCell
        return best_state

    def max_value(self, node, alpha, beta):
        print "AlphaBeta-->MAX: Visited Node :: " + node.getOldCell + " to " + node.getNewCell
        if self.isTerminal(node):
            return node.getUtility()
        infinity = float('inf')
        value = -infinity

        successors = self.getSuccessors(node)
        for state in successors:
            value = max(value, self.min_value(state, alpha, beta))
            if value >= beta:
                return value
            alpha = max(alpha, value)
        return value

    def min_value(self, node, alpha, beta):
        print "AlphaBeta-->MIN: Visited Node :: " + node.getOldCell + " to " + node.getNewCell
        if self.isTerminal(node):
            return node.getUtility()
        infinity = float('inf')
        value = infinity

        successors = self.getSuccessors(node)
        for state in successors:
            value = min(value, self.max_value(state, alpha, beta))
            if value <= alpha:
                return value
            beta = min(beta, value)

        return value
    #                     #
    #   UTILITY METHODS   #
    #                     #

    # successor states in a game tree are the child nodes...
    def getSuccessors(self, node):
        assert node is not None
        return node.children

    # return true if the node has NO children (successor states)
    # return false if the node has children (successor states)
    def isTerminal(self, node):
        assert node is not None
        return len(node.children) == 0
