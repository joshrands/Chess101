
class Piece:
	# team?

	def __init__(self, row=0, col=0):
		self.row = row
		self.col = col
		self.targets = []

	# abstract method calcTargets
	def calcTargets(self):
		raise NotImplementedError()

	# abstract method move
	def move(self, newRow, newCol):
		# calculate new targets
		self.row = newRow
		self.col = newCol

	def print(self):
		raise NotImplementedError()

	def getTargets():
		return targets
