#child class of Piece that represents a Pawn
from Piece import Piece

class Pawn(Piece):
    def __init__(self, row=0, col=0, team):
        super().__init__(self, row, col, team)
        self.startingRow = row
        self.startingCol = col
        if (self.row == 6):
            self.direction = -1
        else:
            self.direction = 1;
        self.enPassantable = False

    #calcTargets, which is abstract in the parent
    def calcTargets(self, checkerTown):
        targets = []
        if (self.row == 0 or self.row == 7):
            #should technically be a queen or something else now
        else:
            #check the squares diagonal in the direction of self.direction for an enemy Piece
            #
            if (self.col != 0 and isinstance(Piece, checkerTown[self.row + self.direction][self.col - 1]):
                if (checkerTown[self.row + self.direction][self.col - 1].team != self.team):
                    targets.append(Cell(self.row + self.direction, self.col - 1))

            #Check the diagonal to the right
            if (self.col != 7 and isinstance(Piece, checkerTown[self.row + self.direction][self.col + 1]):
                if (checkerTown[self.row + self.direction][self.col - 1].team != self.team):
                    targets.append(Cell(self.row + self.direction, self.col - 1))

            #check the square in front
            if (checkerTown[self.row + self.direction][self.column] != None):
            #if row and col = starting row and col then check 2 in front
            if (self.row == self.startingRow and self.col == self.startingCol):
                if (checkerTown[self.row + 2 * self.direction][self.col] == None):
            #check for en passant

    #override move method to set enPassantable
    def move(self, newRow, newCol):
		super().move(self, newRow, newCol)
        if (self.row == self.startingRow and self.col == self.startingCol):
            self.enPassantable = True
        if (self.enPassantable):
            self.enPassantable = false;

    def printPiece(self):
        print("Pawn at " + self.row + ", " + self.col)
