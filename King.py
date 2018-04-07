#child class of Piece that represents a King
from Piece import Piece
class King(Piece):
    def calcTargets(self, checkerTown):

#Overwrite default print with special King print
    def printPiece(self):
        print("King at " + self.row + ", " + self.col)
