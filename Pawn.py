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
    def calcTargets(self, board):
        #check the squares diagonal in the direction of self.direction for an enemy Piece
        if (board[self.row + self.direction][])
        #check the square in front
        if (board[self.direction][self.column] != None and )
        #if row and col = starting row and col then check 2 in front


    def printPiece(self):
        print("Pawn at " + self.row + ", " + self.col)
