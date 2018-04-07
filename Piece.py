from Team import Team
from Cell import Cell

class Piece:
	# team?

	def __init__(self, row, col, team):
		self.row = row
		self.col = col
		self.targets = []
		self.team = team

	# abstract method calcTargets
	def calcTargets(self, checkerTown):
		raise NotImplementedError()

	# abstract method move
	def move(self, newRow, newCol):
		# calculate new targets
		self.row = newRow
		self.col = newCol
		return None

	def printPiece(self, board):
		print ("Piece at " + self.row + ", " + self.col)

	def getTargets(self):
		return self.targets
