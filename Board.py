# Board class - controls hardware and holds pieces

from samplebase import SampleBase

class Board(SampleBase):
	
	def __init__(self):
		# initialize stuff

	def lightCell(self, x=0, y=0, r=255, g=255, b=255):
		canvas = self.matrix.CreateFrameCanvas()	
		for i in range(0, 4):
			for j in range(0, 4):
				canvas.SetPixel(x + i, y + j, r, g, b)	
	
	def turnOffCell(self, x='A', y='0'):

board = Board()
board.lightCell(0, 1, 255, 0, 0)

