from Team import Team
from Cell import Cell


class Piece:
    def __init__(self, row, col, team):
        self.row = row
        self.col = col
        self.targets = []
        self.team = team
        self.touched = False
        self.critical = False
        self.critical_targets = []

    def calc_targets(self, board):
        raise NotImplementedError()

    def get_value(self, board):
        raise NotImplementedError()

    def move(self, new_row, new_col, board):
        self.row = new_row
        self.col = new_col
        self.touched = True

    def _ray_cast(self, board, current_row, current_col, dr, dc):
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
                return self._ray_cast(board, current_row + dr, current_col + dc, dr, dc)
        return -1, -1

    def filter_to_pin_ray(self):
        new_targets = []
        for critical_cell in self.critical_targets:
            for cell in self.targets:
                if critical_cell.row == cell.row and critical_cell.col == cell.col:
                    new_targets.append(cell)
        self.targets = new_targets

    def filter_to_king_escape(self, king):
        new_targets = []
        for target in self.targets:
            for saving_target in king.king_escape_cells:
                if target.row == saving_target.row and target.col == saving_target.col:
                    new_targets.append(target)
        self.targets = new_targets

    def print_piece(self, board):
        print("Piece at", self.row, ",", self.col)

    def get_targets(self):
        return self.targets
