#child class of Piece that represents a King
from Piece import Piece
from Cell import Cell
from Rook import Rook

class King(Piece):

    def bladeWalker(self, checkerTown, dir1, dir2, row, col):
        if (row + dir1 >= 0 and row + dir1 <= 7 and col + dir2 >= 0 and col + dir2 <= 7):
            if (checkerTown[row + dir1][col + dir2] == None):
                self.targets.append(Cell(row + dir1, col + dir2))
            elif (checkerTown[row + dir1][col + dir2].team != self.team):
                self.targets.append(Cell(row + dir1, col + dir2))

    def calcTargets(self, checkerTown):
        self.targets = []
        #Run a recurssive function in all directions
        self.bladeWalker(checkerTown, 1, 1, self.row, self.col)
        self.bladeWalker(checkerTown, -1, 1, self.row, self.col)
        self.bladeWalker(checkerTown, 1, -1, self.row, self.col)
        self.bladeWalker(checkerTown, -1, -1, self.row, self.col)
        self.bladeWalker(checkerTown, 1, 0, self.row, self.col)
        self.bladeWalker(checkerTown, -1, 0, self.row, self.col)
        self.bladeWalker(checkerTown, 0, 1, self.row, self.col)
        self.bladeWalker(checkerTown, 0, -1, self.row, self.col)

        #castling situation
        if (self.touched == False):
            if (isinstance(checkerTown[self.row][self.col - 4], Rook) and checkerTown[self.row][self.col - 4].touched == False):
                if (checkerTown[self.row][self.col - 1] == None and checkerTown[self.row][self.col - 2] == None and checkerTown[self.row][self.col - 3] == None):
                    self.targets.append(Cell(self.row, self.col - 2))
            if (isinstance(checkerTown[self.row][self.col + 3], Rook) and checkerTown[self.row][self.col + 3].touched == False):
                if (checkerTown[self.row][self.col + 1] == None and checkerTown[self.row][self.col + 2] == None):
                    self.targets.append(Cell(self.row, self.col + 2))

    def move(self, newRow, newCol):
		# calculate new targets
        oldRow = self.row
        oldCol = self.col
        self.row = newRow
        self.col = newCol
        self.touched = True
        #check if castled
        if (newRow == oldRow and newCol == oldCol - 2):
            return Cell(oldRow, oldCol - 4), Cell(oldRow, oldCol - 1)
        elif (newRow == oldRow and newCol == oldCol + 2):
            return Cell(oldRow, oldCol + 3), Cell(oldRow, oldCol + 1)
        else:
            return None, None

    def amIGonnaDie(self, checkerTown, enemies, checkRow, checkCol, dir1, dir2):
        #check if I am in check
        #there are 8 possible directions that could be hindering me, plus knights
        #check perpindicular directions for rooks and queens, and kings for one space
        if (enemies == "all"):
            dangerRow, dangerCol = amIGonnaDie(checkerTown, "dia", checkRow, checkCol, dir1, dir2)
            if (dangerRow == -1 and dangerCol == -1):
                dangerRow, dangerCol = amIGonnaDie(checkerTown, "diaShort", checkRow, checkCol, dir1, dir2)
            if (dangerRow == -1 and dangerCol == -1):
                dangerRow, dangerCol = amIGonnaDie(checkerTown, "perp", checkRow, checkCol, dir1, dir2)
            if (dangerRow == -1 and dangerCol == -1):
                dangerRow, dangerCol = amIGonnaDie(checkerTown, "perpShort", checkRow, checkCol, dir1, dir2)
            if (dangerRow == -1 and dangerCol == -1):
                dangerRow, dangerCol = amIGonnaDie(checkerTown, "knight", checkRow, checkCol, dir1, dir2)
            return dangerRow, dangerCol
        elif (enemies == "dia"):
            

#Overwrite default print with special King print
    def printPiece(self):
        print("King at", self.row ,"," , self.col)
