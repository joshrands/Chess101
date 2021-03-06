# child class of Piece that represents a Bishop
from Piece import Piece
from Cell import Cell


class Bishop(Piece):
    def bladeRunner(self, checkerTown, dir1, dir2, row, col):
        if (row + dir1 >= 0 and row + dir1 <= 7 and col + dir2 >= 0 and col + dir2 <= 7):
            if (checkerTown[row + dir1][col + dir2] == None):
                self.targets.append(Cell(row + dir1, col + dir2))
                self.bladeRunner(checkerTown, dir1, dir2,
                                 row + dir1, col + dir2)
            elif (checkerTown[row + dir1][col + dir2].team != self.team):
                self.targets.append(Cell(row + dir1, col + dir2))

    def calcTargets(self, checkerTown):
        self.targets = []
        # Run a recurssive function in all directions
        self.bladeRunner(checkerTown, 1, 1, self.row, self.col)
        self.bladeRunner(checkerTown, -1, 1, self.row, self.col)
        self.bladeRunner(checkerTown, 1, -1, self.row, self.col)
        self.bladeRunner(checkerTown, -1, -1, self.row, self.col)

        # if critical, check calculated targets against criticalTargets and only keep cells that appear on both
        if (self.critical):
            super().criticalMan()

    def getValue(self, board):
        total = 15
        self.calcTargets(board)
        for cell in self.targets:
            total = total + 1
            if ((cell.row == 3 or cell.row == 4) and (cell.col == 3 or cell.col == 4)):
                total = total + 1

        return total

# Overwrite default print with special bishop print
    def printPiece(self):
        print("Bishop at", self.row, ",", self.col)
