//child class of Piece that represents a Pawn
import Piece.py
class Pawn(Piece):
    def __init__(self, row=0, col=0):
        super().__init__(self, row, col)
        self.startingRow = row
        self.startingCol = col
        if (self.row == 6):
            self.direction = -1
        else:
            self.direction = 1;

    //calcTargets, which is abstract in the parent
    def calcTargets(self):
        //check the squares diagonal in the direction of self.direction for an enemy Piece
        //check the square in front
        //if row and col = starting row and col then check 2 in front

    def printPiece(self):
        print("Pawn at " + self.row + ", " + self.col)
