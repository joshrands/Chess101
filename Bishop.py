#child class of Piece that represents a Bishop
from Piece import Piece
from Cell import Cell

class Bishop(Piece):
    def calcTargets(self, checkerTown):
        #Run a recurssive function in all directions
        bladeRunner(checkerTown, 1, 1, self.row, self.col)
        bladeRunner(checkerTown, -1, 1, self.row, self.col)
        bladeRunner(checkerTown, 1, -1, self.row, self.col)
        bladeRunner(checkerTown, -1, -1, self.row, self.col)

    def bladeRunner(self, checkerTown, dir1, dir2, row, col):
        if (checkerTown[row + dir1][col + dir2] == None):
            self.targets.append(Cell(row + dir1, col + dir2))
            bladeRunner(checkerTown, dir1, dir2, row + dir1, col + dir2)
        elif (checkerTown[row + dir1][col + dir2].team != self.team):
            self.targets.append(Cell(row + dir1, col + dir2))

#Overwrite default print with special bishop print
    def printPiece(self):
        print("Bishop at " + self.row + ", " + self.col)
