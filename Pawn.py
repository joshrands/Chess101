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
            self.direction = 1
        self.enPassantable = False
        self.enPassantLoc = None

    #calcTargets, which is abstract in the parent
    def calcTargets(self, checkerTown):
        self.targets = []
        if (self.row != 0 and self.row != 7):
            #check the squares diagonal in the direction of self.direction for an enemy Piece
            #
            if (self.col != 0 and isinstance(checkerTown[self.row + self.direction][self.col - 1], Piece)):
                if (checkerTown[self.row + self.direction][self.col - 1].team != self.team):
                    self.targets.append(Cell(self.row + self.direction, self.col - 1))

            #Check the diagonal to the right
            if (self.col != 7 and isinstance(checkerTown[self.row + self.direction][self.col + 1], Piece)):
                if (checkerTown[self.row + self.direction][self.col + 1].team != self.team):
                    self.targets.append(Cell(self.row + self.direction, self.col + 1))

            #check the square in front
            if (checkerTown[self.row + self.direction][self.col] == None):
                self.targets.append(Cell(self.row + self.direction, self.col))
            #if row and col = starting row and col then check 2 in front
            if (self.row == self.startingRow):
                if (checkerTown[self.row + 2 * self.direction][self.col] == None):
                    self.targets.append(Cell(self.row + 2 * self.direction, self.col))
            #check for en passant
            #check left
            if (self.col != 0 and isinstance(checkerTown[self.row][self.col - 1], Pawn) and checkerTown[self.row][self.col - 1].team != self.team):
                #if (checkerTown[self.row][self.col - 1].enPassantable):
                    print("Gonna kill him")
                    self.targets.append(Cell(self.row + self.direction, self.col - 1))
                    self.enPassantLoc = Cell(self.row + self.direction, self.col - 1)
            #check right
            if (self.col != 7 and isinstance(checkerTown[self.row][self.col + 1], Pawn) and checkerTown[self.row][self.col + 1].team != self.team):
                if (checkerTown[self.row][self.col + 1].enPassantable):
                    print("Gonna kill him")
                    self.targets.append(Cell(self.row + self.direction, self.col + 1))
                    self.enPassantLoc = Cell(self.row + self.direction, self.col + 1)

    #override move method to set enPassantable
    def move(self, newRow, newCol):
        # calculate new targets
        oldRow = self.row
        oldCol = self.col

        self.row = newRow
        self.col = newCol
        if (oldRow == self.startingRow and oldCol == self.startingCol and (newRow - oldRow) == 2 * self.direction):
            self.enPassantable = True
        if (self.enPassantLoc != None and newRow == self.enPassantLoc.row and newCol == self.enPassantLoc.col):
            return Cell(enPassantLoc.row - self.direction, enPassantLoc.col)
        else:
            return None

    def printPiece(self):
        print("Pawn at", self.row, ",", self.col)
