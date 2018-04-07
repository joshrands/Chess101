#child class of Piece that represents a King
from Piece import Piece
from Cell import Cell

class King(Piece):
    def bladeWalker(self, checkerTown, dir1, dir2, row, col):
        if (checkerTown[row + dir1][col + dir2] == None):
            self.targets.append(Cell(row + dir1, col + dir2))
        elif (checkerTown[row + dir1][col + dir2].team != self.team):
            self.targets.append(Cell(row + dir1, col + dir2))

    def calcTargets(self, checkerTown):
        #Run a recurssive function in all directions
        self.bladeWalker(checkerTown, 1, 1, self.row, self.col)
        self.bladeWalker(checkerTown, -1, 1, self.row, self.col)
        self.bladeWalker(checkerTown, 1, -1, self.row, self.col)
        self.bladeWalker(checkerTown, -1, -1, self.row, self.col)
        self.bladeWalker(checkerTown, 1, 0, self.row, self.col)
        self.bladeWalker(checkerTown, -1, 0, self.row, self.col)
        self.bladeWalker(checkerTown, 0, 1, self.row, self.col)
        self.bladeWalker(checkerTown, 0, -1, self.row, self.col)

#Overwrite default print with special King print
    def printPiece(self):
        print("King at " + self.row + ", " + self.col)
