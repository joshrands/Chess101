#child class of Piece that represents a Queen
from Piece import Piece
class Queen(Piece):
    def calcTargets(self, checkerTown):

#Overwrite default print with special Queen print
    def printPiece(self):
        print("Queen at " + self.row + ", " + self.col)
