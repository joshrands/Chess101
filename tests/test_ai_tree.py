"""
test_ai_tree.py — tests for Tree (utility calculation) and AI (alpha-beta).

Tree.get_utility has a known red-channel-only team comparison bug.
AI.alpha_beta_search is tested with manually constructed tree nodes so no
Board hardware is needed.
"""
import pytest
from Team import Team
from Cell import Cell
from Tree import Tree
from AI import AI
from Rook import Rook
from Pawn import Pawn
from King import King
from Queen import Queen


def empty_board():
    return [[None] * 8 for _ in range(8)]


def make_tree(board, old_cell, new_cell, team_r, team_l):
    return Tree(board, old_cell, new_cell, team_r, team_l)


# ─────────────────────────────────────────────────────────────────────────────
# Tree
# ─────────────────────────────────────────────────────────────────────────────

class TestTree:
    def _teams(self):
        return Team(64, 180, 232), Team(255, 140, 0)

    def test_stores_board_state(self):
        tr, tl = self._teams()
        board = empty_board()
        board[0][0] = Rook(0, 0, tr)
        t = Tree(board, Cell(0, 0), Cell(1, 0), tr, tl)
        # LOCK-IN: Tree stores the board reference directly — no deep copy.
        assert t.get_board_state() is board
        assert isinstance(t.get_board_state()[0][0], Rook)

    def test_board_state_is_same_reference(self):
        # LOCK-IN: Tree.__init__ does NOT deep-copy board_state.
        # Mutating the original board DOES affect the tree's stored state.
        tr, tl = self._teams()
        board = empty_board()
        rook = Rook(0, 0, tr)
        board[0][0] = rook
        t = Tree(board, Cell(0, 0), Cell(1, 0), tr, tl)
        board[0][0] = None  # mutate original
        assert t.get_board_state()[0][0] is None  # tree sees the mutation

    def test_copies_teams_by_value(self):
        tr, tl = self._teams()
        board = empty_board()
        t = Tree(board, None, None, tr, tl)
        assert t.team_r is not tr
        assert t.team_l is not tl
        assert t.team_r.r == tr.r
        assert t.team_l.r == tl.r

    def test_add_child_appends(self):
        tr, tl = self._teams()
        board = empty_board()
        parent = Tree(board, None, None, tr, tl)
        child = Tree(board, Cell(0, 0), Cell(1, 0), tr, tl)
        parent.add_child(child)
        assert len(parent.children) == 1
        assert parent.children[0] is child

    def test_get_board_state_returns_board(self):
        tr, tl = self._teams()
        board = empty_board()
        t = Tree(board, None, None, tr, tl)
        assert t.get_board_state() is t.board_state

    def test_utility_empty_board_is_zero(self):
        tr, tl = self._teams()
        board = empty_board()
        t = Tree(board, None, None, tr, tl)
        assert t.get_utility(tr) == 0

    def test_utility_teamR_advantage_positive(self):
        tr, tl = self._teams()
        board = empty_board()
        board[0][0] = Rook(0, 0, tr)
        t = Tree(board, None, None, tr, tl)
        # Only team_r has a piece → utility > 0 from team_r's perspective
        assert t.get_utility(tr) > 0

    def test_utility_teamL_material_advantage_negative_from_teamR(self):
        tr, tl = self._teams()
        board = empty_board()
        board[0][0] = Rook(0, 0, tl)
        t = Tree(board, None, None, tr, tl)
        # Only team_l has a piece → utility < 0 from team_r's perspective
        assert t.get_utility(tr) < 0

    def test_utility_perspective_flip(self):
        tr, tl = self._teams()
        board = empty_board()
        board[0][0] = Rook(0, 0, tr)
        board[1][0] = Pawn(1, 0, tl)
        t = Tree(board, None, None, tr, tl)
        util_r = t.get_utility(tr)
        util_l = t.get_utility(tl)
        assert util_r == -util_l

    def test_utility_uses_only_red_channel_for_team_id(self):
        # BUG #2 LOCK-IN: get_utility checks piece.team.r == self.team_r.r.
        # A piece whose team has the SAME red channel as team_r but different
        # green/blue is incorrectly counted as a team_r piece.
        team_r_real = Team(100, 0, 0)
        team_r_impostor = Team(100, 200, 50)   # same r=100, different g/b
        team_l = Team(50, 50, 50)

        board = empty_board()
        board[0][0] = Rook(0, 0, team_r_real)
        board[0][1] = Rook(0, 1, team_r_impostor)  # different team object!

        t = Tree(board, None, None, team_r_real, team_l)
        utility = t.get_utility(team_r_real)

        # Both rooks are counted as team_r (r=100 == r=100), so black_count=0
        # and utility = sum of both rook values > 0
        # If team comparison were correct, one rook would be black_count,
        # and utility would be approximately 0 (equal material).
        assert utility > 0

    def test_utility_equal_same_piece_types_is_zero(self):
        tr, tl = self._teams()
        board = empty_board()
        board[0][0] = Rook(0, 0, tr)
        board[7][7] = Rook(7, 7, tl)
        t = Tree(board, None, None, tr, tl)
        # Both rooks have same type and position symmetry — utility should be 0
        assert t.get_utility(tr) == 0


# ─────────────────────────────────────────────────────────────────────────────
# AI
# ─────────────────────────────────────────────────────────────────────────────

class TestAI:
    def _teams(self):
        return Team(64, 180, 232), Team(255, 140, 0)

    def _leaf_tree(self, utility_pieces, tr, tl):
        """Create a leaf Tree node with pieces that yield a known utility."""
        board = empty_board()
        for (row, col), piece in utility_pieces.items():
            board[row][col] = piece
        return Tree(board, Cell(0, 0), Cell(1, 0), tr, tl)

    def test_stores_game_tree_and_team(self):
        tr, tl = self._teams()
        board = empty_board()
        root = Tree(board, None, None, tr, tl)
        ai = AI(root, tr)
        assert ai.game_tree is root
        assert ai.team is tr

    def test_is_terminal_true_when_no_children(self):
        tr, tl = self._teams()
        board = empty_board()
        node = Tree(board, None, None, tr, tl)
        ai = AI(node, tr)
        assert ai.is_terminal(node) is True

    def test_is_terminal_false_when_has_children(self):
        tr, tl = self._teams()
        board = empty_board()
        root = Tree(board, None, None, tr, tl)
        child = Tree(board, Cell(0, 0), Cell(1, 0), tr, tl)
        root.add_child(child)
        ai = AI(root, tr)
        assert ai.is_terminal(root) is False

    def test_get_successors_returns_children(self):
        tr, tl = self._teams()
        board = empty_board()
        root = Tree(board, None, None, tr, tl)
        child = Tree(board, Cell(0, 0), Cell(1, 0), tr, tl)
        root.add_child(child)
        ai = AI(root, tr)
        assert ai.get_successors(root) == [child]

    def test_min_value_terminal_returns_utility(self):
        tr, tl = self._teams()
        # Leaf with one rook for team_r → utility > 0
        board = empty_board()
        board[0][0] = Rook(0, 0, tr)
        leaf = Tree(board, Cell(0, 0), Cell(1, 0), tr, tl)
        ai = AI(leaf, tr)
        val = ai.min_value(leaf, float('-inf'), float('inf'))
        assert val > 0

    def test_max_value_terminal_returns_utility(self):
        tr, tl = self._teams()
        board = empty_board()
        board[0][0] = Rook(0, 0, tr)
        leaf = Tree(board, Cell(0, 0), Cell(1, 0), tr, tl)
        ai = AI(leaf, tr)
        val = ai.max_value(leaf, float('-inf'), float('inf'))
        assert val > 0

    def test_alpha_beta_returns_best_state_from_two_leaves(self, capsys):
        # Root has two leaf children: child_A has a Queen (high value),
        # child_B has only a Pawn (low value).  AI should pick child_A.
        tr, tl = self._teams()

        board_a = empty_board()
        board_a[0][0] = Queen(0, 0, tr)  # high material value
        child_a = Tree(board_a, Cell(0, 0), Cell(1, 0), tr, tl)

        board_b = empty_board()
        board_b[0][0] = Pawn(1, 0, tr)  # low material value
        board_b[0][0].row = 0
        child_b = Tree(board_b, Cell(0, 1), Cell(1, 1), tr, tl)

        root_board = empty_board()
        root = Tree(root_board, None, None, tr, tl)
        root.add_child(child_a)
        root.add_child(child_b)

        ai = AI(root, tr)
        best = ai.alpha_beta_search()
        assert best is child_a

    def test_alpha_beta_single_child_always_returned(self, capsys):
        tr, tl = self._teams()
        root_board = empty_board()
        root = Tree(root_board, None, None, tr, tl)

        child_board = empty_board()
        child_board[0][0] = Rook(0, 0, tr)
        child = Tree(child_board, Cell(0, 0), Cell(1, 0), tr, tl)
        root.add_child(child)

        ai = AI(root, tr)
        best = ai.alpha_beta_search()
        assert best is child

    def test_alpha_beta_pruning_selects_optimal(self, capsys):
        # Build a 2-level tree:
        # root → [child_1, child_2]
        # child_1 → [leaf_1a (utility=50), leaf_1b (utility=10)]
        # child_2 → [leaf_2a (utility=5)]
        # AI (max at root via min_value calls) should prefer child_1 path.
        tr, tl = self._teams()

        def make_leaf(queen_for_r):
            b = empty_board()
            if queen_for_r:
                b[0][0] = Queen(0, 0, tr)
            else:
                b[0][0] = Pawn(1, 0, tr)
                b[0][0].row = 0
            return Tree(b, Cell(0, 0), Cell(1, 0), tr, tl)

        leaf_1a = make_leaf(True)   # high
        leaf_1b = make_leaf(False)  # low

        child_board = empty_board()
        child_1 = Tree(child_board, Cell(1, 0), Cell(2, 0), tr, tl)
        child_1.add_child(leaf_1a)
        child_1.add_child(leaf_1b)

        leaf_2a = make_leaf(False)  # low
        child_2 = Tree(child_board, Cell(1, 1), Cell(2, 1), tr, tl)
        child_2.add_child(leaf_2a)

        root_board = empty_board()
        root = Tree(root_board, None, None, tr, tl)
        root.add_child(child_1)
        root.add_child(child_2)

        ai = AI(root, tr)
        best = ai.alpha_beta_search()
        # child_1 leads to higher utility (50 in best subtree leaf)
        assert best is child_1

    def test_max_value_with_non_terminal_node(self):
        # max_value on a non-terminal node should recurse into min_value on each child.
        # Covers the non-terminal body of max_value (lines 76-83).
        tr, tl = self._teams()
        board = empty_board()
        board[0][0] = Rook(0, 0, tr)
        leaf = Tree(board, Cell(0, 0), Cell(1, 0), tr, tl)

        root_board = empty_board()
        non_terminal = Tree(root_board, None, None, tr, tl)
        non_terminal.add_child(leaf)

        ai = AI(non_terminal, tr)
        val = ai.max_value(non_terminal, float('-inf'), float('inf'))
        # leaf has a rook for team_r → utility > 0
        assert val > 0

    def test_max_value_beta_pruning(self):
        # If the first child already beats beta, max_value should return early
        # (pruning subsequent children).  Covers lines 80-81.
        tr, tl = self._teams()
        board_high = empty_board()
        board_high[0][0] = Queen(0, 0, tr)  # high utility
        leaf_high = Tree(board_high, Cell(0, 0), Cell(1, 0), tr, tl)

        board_low = empty_board()
        board_low[0][0] = Pawn(1, 0, tr)
        board_low[0][0].row = 0
        leaf_low = Tree(board_low, Cell(0, 1), Cell(1, 1), tr, tl)

        root_board = empty_board()
        node = Tree(root_board, None, None, tr, tl)
        node.add_child(leaf_high)
        node.add_child(leaf_low)

        ai = AI(node, tr)
        # beta = 0: first child returns value > 0 → triggers beta pruning
        val = ai.max_value(node, float('-inf'), 0)
        # Pruned early; value exceeds beta
        assert val > 0

    def test_get_successors_raises_for_none(self):
        tr, tl = self._teams()
        ai = AI(Tree(empty_board(), None, None, tr, tl), tr)
        with pytest.raises(ValueError):
            ai.get_successors(None)

    def test_is_terminal_raises_for_none(self):
        tr, tl = self._teams()
        ai = AI(Tree(empty_board(), None, None, tr, tl), tr)
        with pytest.raises(ValueError):
            ai.is_terminal(None)
