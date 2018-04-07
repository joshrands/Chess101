#child class of Piece that represents a King
from Piece import Piece
from Cell import Cell

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
        if (self.touched == false):
            if (isinstance(checkerTown[self.row][self.col - 5],Rook) and checkerTown[self.row][self.col - 5].touched == false):
                if (checkerTown[self.row][self.col - 1] == None && checkerTown[self.row][self.col - 2] == None && checkerTown[self.row][self.col - 3] == None and checkerTown[self.row][self.col - 4] == None):
                    self.targets.append(Cell(self.row, self.col - 3))
            elif (isinstance(checkerTown[self.row][self.col + 4], Rook) and checkerTown[self.row][self.col + 4].touched == false):
                if (checkerTown[self.row][self.col + 1] == None && checkerTown[self.row][self.col + 2] == None && checkerTown[self.row][self.col + 3] == None):
                    self.targets.append(Cell(self.row, self.col + 3))

	def move(self, newRow, newCol):
        oldRow = self.row
        oldCol = self.col
        #check if castled
        if (newRow == oldRow and newCol == oldCol - 3):
            return Cell(oldRow, oldCol - 5), Cell(oldRow, oldCol - 2)
        elif (newRow == oldRow and newCol == oldCol + 3):
            return Cell(oldRow, oldCol + 4), Cell(oldRow, oldCol + 2)
        else:
            return None
		# calculate new targets
		self.row = newRow
		self.col = newCol
		self.touched = True

#Overwrite default print with special King print
    def printPiece(self):
        print("King at", self.row ,"," , self.col)
