#child class of Piece that represents a Pawn
from Piece import Piece
from Cell import Cell

class Pawn(Piece):
    def __init__(self, row, col, team):
        self.row = row
        self.col = col
        self.targets = []
        self.team = team
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
        if (self.row != 0 and self.row != 7):
            #check the squares diagonal in the direction of self.direction for an enemy Piece
            #
            if (self.col != 0 and isinstance(checkerTown[self.row + self.direction][self.col - 1], Piece)):
                if (checkerTown[self.row + self.direction][self.col - 1].team != self.team):
                    targets.append(Cell(self.row + self.direction, self.col - 1))

            #Check the diagonal to the right
            if (self.col != 7 and isinstance(checkerTown[self.row + self.direction][self.col + 1], Piece)):
                if (checkerTown[self.row + self.direction][self.col + 1].team != self.team):
                    targets.append(Cell(self.row + self.direction, self.col + 1))

            #check the square in front
            if (checkerTown[self.row + self.direction][self.col] == None):
                targets.append(Cell(self.row + self.direction, self.col))
            #if row and col = starting row and col then check 2 in front
            if (self.row == self.startingRow):
                if (checkerTown[self.row + 2 * self.direction][self.col] == None):
                    targets.append(Cell(self.row + 2 * self.direction, self.col))
            #check for en passant
            #check left
            if (self.col != 0 and checkerTown[self.row][self.col - 1] is Pawn and checkerTown[self.row][self.col - 1].team != self.team):
                if (checkerTown[self.row][self.col - 1].enPassantable):
                    targets.append(Cell(self.row, self.col - 1))
            #check right
            if (self.col != 7 and checkerTown[self.row][self.col + 1] is Pawn and checkerTown[self.row][self.col + 1].team != self.team):
                if (checkerTown[self.row][self.col + 1].enPassantable):
                    targets.append(Cell(self.row, self.col + 1))

    #override move method to set enPassantable
    def move(self, newRow, newCol):
        super().move(self, newRow, newCol)
        if (self.enPassantable):
            self.enPassantable = False
        if (self.row == self.startingRow and self.col == self.startingCol):
            self.enPassantable = True

    def printPiece(self):
        print("Pawn at " + self.row + ", " + self.col)
