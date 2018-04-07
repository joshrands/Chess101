#child class of Piece that represents a Pawn
import Piece.py
class Pawn(Piece):
    def __init__(self, row=0, col=0, team):
        super().__init__(self, row, col, team)
        self.startingRow = row
        self.startingCol = col
        if (self.row == 6):
            self.direction = -1
        else:
            self.direction = 1;

    #calcTargets, which is abstract in the parent
    def calcTargets(self, checkerTown):
        if (self.row == 0 or self.row == 7):
            #check the squares diagonal in the direction of self.direction for an enemy Piece
            if (checkerTown[self.row + self.direction][])
            #check the square in front
            if (checkerTown[self.row + self.direction][self.column] != None and )
            #if row and col = starting row and col then check 2 in front

            #check for en passant


    def printPiece(self):
        print("Pawn at " + self.row + ", " + self.col)
