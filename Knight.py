#child class of Piece that represents a Knight
from Piece import Piece
from Cell import Cell

class Knight(Piece):

    def deathLoc(self, checkerTown, row, col):
        if (checkerTown[row + dir1][col + dir2] == None):
            self.targets.append(Cell(row + dir1, col + dir2))
        elif (checkerTown[row + dir1][col + dir2].team != self.team):
            self.targets.append(Cell(row + dir1, col + dir2))

    def calcTargets(self, checkerTown):
        #check each of the knighty locations
        self.deathLoc(checkerTown, 2, 1)
        self.deathLoc(checkerTown, 2, -1)
        self.deathLoc(checkerTown, -2, 1)
        self.deathLoc(checkerTown, -2, -1)
        self.deathLoc(checkerTown, 1, 2)
        self.deathLoc(checkerTown, 1, -2)
        self.deathLoc(checkerTown, -1, 2)
        self.deathLoc(checkerTown, -1, -2)

#Overwrite default print with special Knight print
    def printPiece(self):
        print("Knight at " + self.row + ", " + self.col)
