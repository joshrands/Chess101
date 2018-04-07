#!/usr/bin/env python
from samplebase import SampleBase
from Team import Team

class Board(SampleBase):
    
	def __init__(self, *args, **kwargs):
        super(Board, self).__init__(*args, **kwargs)
		self.teamR = Team(255, 255, 255)
		self.teamL = Team(255, 255, 255)
 
	# RUN GAME
    def run(self):
        print("Running game...")
       
		self.createPlayers()	
 
		while True:
            offset_canvas = self.matrix.CreateFrameCanvas()
            
            self.lightCell(offset_canvas, 4, 3, 64, 180, 232)

            offset_canvas = self.matrix.SwapOnVSync(offset_canvas)

	### Member Functions ###
	
	def initializeGameBoard():
		# create pieces in each team
		
		# light up starting cells
		# Right Team, starts at 0, 0
		for row in range(0, 8):
			for col in range(0, 2):
				

		# TODO: loop through pieces in team and light up cells		 

	def createPlayers(self):
		nameR = input("Enter player 1 name: ")
		print("Enter player 1 colors (rgb): ")	
		self.teamR.setName(nameR)
		self.teamR.setColor()

		nameL = input("Enter player 2 name: ")		
		print("Enter player 2 colors (rgb): ")
		self.teamL.setName(nameL)
		self.teamL.setColor()
 
    def lightCell(self, canvas, x, y, r, g, b):
        #offset_canvas = self.matrix.CreateFrameCanvas()
        for i in range(0, 4):
            for j in range(0, 4):
                canvas.SetPixel(x*4 + i, y*4 + j, r, g, b)


# Main function
#if __name__ == "__main__":
#    simple_square = Board()
#    if (not simple_square.process()):
#        simple_square.print_help()
