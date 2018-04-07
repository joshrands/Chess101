
class Piece:
	# team? 

	def __init__(self, row=0, col=0, targets=[]):
		self.row = row
		self.col = col

	# abstract method calcTargets
	def calcTargets(self): 
		raise NotImplementedError()
	
	# abstract method move
	def move(self, newRow, newCol):
		# calculate new targets
		self.row = newRow
		self.col = newCol 	

	def print(self):
		print(name, " at ", row, ", ", col)

