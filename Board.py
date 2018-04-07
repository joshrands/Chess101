#!/usr/bin/env python
from samplebase import SampleBase
from Team import Team
from Pawn import Pawn
from Bishop import Bishop
from Rook import Rook
from Knight import Knight
from King import King
from Queen import Queen

class Board(SampleBase):
    
    def __init__(self, *args, **kwargs):
        super(Board, self).__init__(*args, **kwargs)
        self.teamR = Team(255, 0, 0)
        self.teamL = Team(0, 0, 255)
        self.grid = []
        for row in range(0, 8):
            self.grid.append([None, None, None, None, None, None, None, None])	

    # RUN GAME
    def run(self):
        print("Running game...")

        self.createPlayers()
        self.initializeGameBoard()

        while True:
            offset_canvas = self.matrix.CreateFrameCanvas()

            #self.lightCell(offset_canvas, 4, 3, 64, 180, 232)
            self.lightPieces(offset_canvas, self.teamR)			

            offset_canvas = self.matrix.SwapOnVSync(offset_canvas)

    ### Member Functions ###
    def lightPieces(self, offset_canvas, team):
        r = 0
        c = 0
        for row in self.grid: 
            print("Row:", r)
            c = 0
            for piece in row:
                if (piece != None):
                    # there is something here, check if right team
                    #if (self.grid[row][col].team 	
                    # light up cell!
 #                   if (piece.team == self.teamR):
 #                       self.lightCell(offset_canvas, r, c, self.teamR.r, self.teamR.g, self.teamR.b)
                    #print(r, c, team.r, team.g, team.b)
                    self.lightCell(offset_canvas, r, c, piece.team.r, piece.team.g, piece.team.b)
                c = c + 1
            r = r + 1

    def initializeGameBoard(self):
        # create pieces in each team
        # TEAM R
        # create pawns for teamR
        for col in range(0, 8):
            self.grid[1][col] = Pawn(1, col, self.teamR)	
        # create bishop for teamR
        self.grid[0][2] = Bishop(0, 2, self.teamR)
        self.grid[0][5] = Bishop(0, 5, self.teamR)
        # create rook for teamR
        self.grid[0][0] = Rook(0, 0, self.teamR)
        self.grid[0][7] = Rook(0, 7, self.teamR)
        self.grid[0][1] = Knight(0, 1, self.teamR)
        self.grid[0][6] = Knight(0, 6, self.teamR)
        self.grid[0][3] = Queen(0, 3, self.teamR) 
        self.grid[0][4] = King(0, 4, self.teamR)

        # TEAM R
        # create pawns for teamR
        for col in range(0, 8):
            self.grid[6][col] = Pawn(6, col, self.teamL)	
        # create bishop for teamR
        self.grid[7][2] = Bishop(7, 2, self.teamL)
        self.grid[7][5] = Bishop(7, 5, self.teamL)
        # create rook for teamR
        self.grid[7][0] = Rook(7, 0, self.teamL)
        self.grid[7][7] = Rook(7, 7, self.teamL)
        self.grid[7][1] = Knight(7, 1, self.teamL)
        self.grid[7][6] = Knight(7, 6, self.teamL)
        self.grid[7][3] = Queen(7, 3, self.teamL) 
        self.grid[7][4] = King(7, 4, self.teamL)



    def createPlayers(self):
        nameR = input("Enter player 1 name: ")
        print("Enter player 1 colors (rgb): ")	
        self.teamR.setName(nameR)
#        self.teamR.setColor()

        nameL = input("Enter player 2 name: ")		
        print("Enter player 2 colors (rgb): ")
        self.teamL.setName(nameL)
#        self.teamL.setColor()

    def lightCell(self, canvas, x, y, r, g, b):
        #offset_canvas = self.matrix.CreateFrameCanvas()
        print(x, y, r, g, b)
        for i in range(0, 4):
            for j in range(0, 4):
                canvas.SetPixel(x*4 + i, y*4 + j, r, g, b)
                #canvas.SetPixel(x, y, 255, 255, 255)
# Main function
#if __name__ == "__main__":
#    simple_square = Board()
#    if (not simple_square.process()):
#        simple_square.print_help()
