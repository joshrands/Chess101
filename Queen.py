#child class of Piece that represents a Queen
from Piece import Piece
from Cell import Cell

class Queen(Piece):
    def bladeRunner(self, checkerTown, dir1, dir2, row, col):
        if (checkerTown[row + dir1][col + dir2] == None):
            self.targets.append(Cell(row + dir1, col + dir2))
            bladeRunner(checkerTown, dir1, dir2, row + dir1, col + dir2)
        elif (checkerTown[row + dir1][col + dir2].team != self.team):
            self.targets.append(Cell(row + dir1, col + dir2))

    def calcTargets(self, checkerTown):
        #Run a recurssive function in all directions
        bladeRunner(checkerTown, 1, 1, self.row, self.col)
        bladeRunner(checkerTown, -1, 1, self.row, self.col)
        bladeRunner(checkerTown, 1, -1, self.row, self.col)
        bladeRunner(checkerTown, -1, -1, self.row, self.col)
        bladeRunner(checkerTown, 1, 0, self.row, self.col)
        bladeRunner(checkerTown, -1, 0, self.row, self.col)
        bladeRunner(checkerTown, 0, 1, self.row, self.col)
        bladeRunner(checkerTown, 0, -1, self.row, self.col)

#Overwrite default print with special Queen print
    def printPiece(self):
        print("Queen at " + self.row + ", " + self.col)
