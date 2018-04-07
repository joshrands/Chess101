#child class of Piece that represents a Bishop
from Piece import Piece
class Bishop(Piece):
    def calcTargets(self, checkerTown):

#Overwrite default print with special bishop print
    def printPiece(self):
        print("Bishop at " + self.row + ", " + self.col)
