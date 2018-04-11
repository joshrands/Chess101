from Team import Team
from Cell import Cell

class Piece:
	# team?

	def __init__(self, row, col, team):
		self.row = row
		self.col = col
		self.targets = []
		self.team = team
		self.touched = False
        self.critical = False

	# abstract method calcTargets
	def calcTargets(self, checkerTown):
		raise NotImplementedError()

	# abstract method move
	def move(self, newRow, newCol):
		# calculate new targets
		self.row = newRow
		self.col = newCol
		self.touched = True

	def Kingsman(self, checkerTown, currentRow, currentCol, dir1, dir2):
		if (currentRow >= 0 and currentRow < 8 and currentCol >= 0 and currentCol < 8):
			nextLoc = (currentRow + dir1 >= 0 and currentRow + dir1 < 8 and currentCol + dir2 >= 0 and currentCol + dir2 < 8)
			if (checkerTown[currentRow][currentCol] != None):
				if (checkerTown[currentRow][currentCol].team != self.team):
					return currentRow, currentCol
				else:
					return -1, -1
			elif nextLoc:
				return self.Kingsman(checkerTown, currentRow + dir1, currentCol + dir2, dir1, dir2)
		else:
			return -1, -1




	def printPiece(self, board):
		print ("Piece at", self.row , "," , self.col)

	def getTargets(self):
		return self.targets
