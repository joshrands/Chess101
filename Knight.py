#child class of Piece that represents a Knight
from Piece import Piece
class Knight(Piece):
    def calcTargets(self, checkerTown):

#Overwrite default print with special Knight print
    def printPiece(self):
        print("Knight at " + self.row + ", " + self.col)
