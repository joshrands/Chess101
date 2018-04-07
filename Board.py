#!/usr/bin/env python
from samplebase import SampleBase
from Team import Team
#from Pawn import Pawn
from Bishop import Bishop

class Board(SampleBase):
    
    def __init__(self, *args, **kwargs):
        super(Board, self).__init__(*args, **kwargs)
        self.teamR = Team(255, 255, 255)
        self.teamL = Team(255, 255, 255)
        self.grid = [] * 8
        for row in range(0, 8):
            self.grid[row] = [NONE, NONE, NONE, NONE, NONE, NONE, NONE, NONE]	

    # RUN GAME
    def run(self):
        print("Running game...")

        self.createPlayers()
        self.initializeGameBoard()

        while True:
            offset_canvas = self.matrix.CreateFrameCanvas()

            #self.lightCell(offset_canvas, 4, 3, 64, 180, 232)
            self.lightPieces(offset_canvas, teamR)			

            offset_canvas = self.matrix.SwapOnVSync(offset_canvas)

    ### Member Functions ###

    def lightPieces(self, offset_canvas, team):
        for row in self.grid:
            for col in self.grid:
                if (self.grid[row][col] != NONE):
                    # there is something here, check if right team
                    #if (self.grid[row][col].team 	
                    # light up cell!
                    self.lightCell(offset_canvas, row, col, team.r, team.g, team.b)

    def initializeGameBoard(self):
        # create pieces in each team
        # create pawns for teamR
#        for col in range(0, 8):
            #self.grid[1][col] = Pawn(1, col, self.teamR)	

        # create bishop for teamR
        self.grid[0][2] = Bishop(0, 2, self.teamR)
        self.grid[0][5] = Bishop(0, 5, self.teamR)

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
