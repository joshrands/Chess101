#child class of Piece that represents a Rook
from Piece import Piece
class Rook(Piece):
    def calcTargets(self, checkerTown):

#Overwrite default print with special bishop print
    def printPiece(self):
        print("Rook at " + self.row + ", " + self.col)
