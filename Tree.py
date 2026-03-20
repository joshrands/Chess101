from Team import Team
from Piece import Piece
import copy
from King import King


class Tree:
    def __init__(self, board_state, old_cell, new_cell, team_r, team_l):
        self.children = []
        self.board_state = board_state
        self.old_cell = old_cell
        self.new_cell = new_cell
        self.team_r = Team(team_r.r, team_r.g, team_r.b)
        self.team_l = Team(team_l.r, team_l.g, team_l.b)

    def add_child(self, child):
        self.children.append(child)

    def get_board_state(self):
        return self.board_state

    def get_utility(self, team):
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
