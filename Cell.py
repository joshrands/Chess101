#cell class
class Cell:
    def __init__(self, row=0, col=0):
        self.row = row
        self.col = col

    def __eq__(self, other):
        return self.row == other.row and self.col == other.col
