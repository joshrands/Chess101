from Board import Board
from Team import Team
class Piece:
	# team?

	def __init__(self, row=0, col=0, team):
		self.row = row
		self.col = col
		self.targets = []
		self.team = team

	# abstract method calcTargets
	def calcTargets(self):
		raise NotImplementedError()

	# abstract method move
	def move(self, newRow, newCol):
		# calculate new targets
		self.row = newRow
		self.col = newCol

	def printPiece(self, board):
		print ("Piece at " + self.row + ", " + self.col)

	def getTargets():
		return targets
