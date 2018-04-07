#!/usr/bin/env python
from samplebase import SampleBase
from Team import Team
from Pawn import Pawn
from Bishop import Bishop
from Rook import Rook
from Knight import Knight
from King import King
from Queen import Queen
import time
from Cell import Cell
import random

class Board(SampleBase):

    def __init__(self, *args, **kwargs):
        super(Board, self).__init__(*args, **kwargs)
        self.teamR = Team(64, 180, 232)
        self.teamL = Team(255, 140, 0)
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
            self.lightPieces(offset_canvas, self.teamR)
            offset_canvas = self.matrix.SwapOnVSync(offset_canvas)

            # Do player 1's turn
            offset_canvas = self.matrix.CreateFrameCanvas()
            self.doTurn(offset_canvas, self.teamR)
            offset_canvas = self.matrix.CreateFrameCanvas()
            self.doTurn(offset_canvas, self.teamL)
            offset_canvas = self.matrix.CreateFrameCanvas()

            offset_canvas = self.matrix.SwapOnVSync(offset_canvas)

    ### Member Functions ###
    def victory(self, canvas, team):
        for i in range(0, 100):
            time.sleep(1)
            x = random.randint(0, 8)
            y = random.randint(0, 8)
            canvas = self.matrix.CreateFrameCanvas()
            self.lightCell(canvas, x, y, team.r, team.g, team.b)
            canvas = self.matrix.SwapOnVSync(canvas)

    def doTurn(self, canvas, team):
        # disable enPassantable
        # calculate targets for all pieces
        for row in self.grid:
            for piece in row:
                if (isinstance(piece, Pawn) and piece.team == team):
                    piece.enPassantable = False
                    #print("Yay")
                if (piece != None):
                    piece.calcTargets(self.grid)
                    #print pieces that can be moved
                    if (len(piece.getTargets()) > 0 and piece.team == team):
                        piece.printPiece()

        checkMate = False
        if (checkMate):
            print("Check mate!")

        check = False
        if (check):
            print("Check!")

        move = False
        row = 0
        col = 0
        print("Player:", team.name, "'s move.")

        while (move == False):
            # move a piece!
            row = int(input("Enter row for desired piece: "))
            col = int(input("Enter col for desired piece: "))
            # TODO: Make sure to check if this is valid piece
            if (self.grid[row][col] != None and self.grid[row][col].team == team and len(self.grid[row][col].getTargets()) > 0):
                move = True
            else:
                print("Invalid piece, pick again.")

        print("Calculating targets...")
        self.lightTargets(canvas, self.grid[row][col])
        self.lightPieces(canvas, self.teamR)
        canvas = self.matrix.SwapOnVSync(canvas)

        validMove = False
        # check if valid move
        while (validMove == False):
            targetRow = int(input("Enter a row for target: "))
            targetCol = int(input("Enter a col for target: "))
            for cell in self.grid[row][col].getTargets():
                if (cell.row == targetRow and cell.col == targetCol):
                    validMove = True
                    print("Moving piece...")
                    self.grid[targetRow][targetCol] = self.grid[row][col]
                    if (isinstance(self.grid[targetRow][targetCol], Pawn)):
                        enemy = self.grid[targetRow][targetCol].move(targetRow, targetCol)
                        if (enemy != None):
                            self.grid[enemy.row][enemy.col]
                    elif (isinstance(self.grid[targetRow][targetCol], King)):
                        rookLocation, rookTarget = self.grid[targetRow][targetCol].move(targetRow, targetCol)
                        if (rookLocation != None):
                            # do castling
                            self.grid[rookTarget.row][rookTarget.col] = self.grid[rookLocation.row][rookLocation.col]
                            self.grid[rookLocation.row][rookTarget.col] = None
                    else:
                        self.grid[targetRow][targetCol].move(targetRow, targetCol)

                    self.grid[row][col] = None

            canvas = self.matrix.CreateFrameCanvas()
            self.lightPieces(canvas, self.teamR)
            canvas = self.matrix.SwapOnVSync(canvas)

    def clearBoard(self, canvas):
        for x in range(0, 8):
            for y in range(0, 8):
                self.lightCell(x, y, 0, 0, 0)

    def lightTargets(self, canvas, piece):
        piece.calcTargets(self.grid)
        targets = piece.getTargets()
        for cell in targets:
            print("Target: ", cell.row, cell.col)
            self.lightCell(canvas, cell.row, cell.col, 255, 255, 255)

    def lightPieces(self, offset_canvas, team):
        r = 0
        c = 0
        for row in self.grid:
            #print("Row:", r)
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
        self.teamR.setColor()

        nameL = input("Enter player 2 name: ")
        print("Enter player 2 colors (rgb): ")
        self.teamL.setName(nameL)
        self.teamL.setColor()

    def lightCell(self, canvas, x, y, r, g, b):
        #offset_canvas = self.matrix.CreateFrameCanvas()
        #print(x, y, r, g, b)
        for i in range(0, 4):
            for j in range(0, 4):
                canvas.SetPixel(x*4 + i, y*4 + j, r, g, b)
                #canvas.SetPixel(x, y, 255, 255, 255)
# Main function
#if __name__ == "__main__":
#    simple_square = Board()
#    if (not simple_square.process()):
#        simple_square.print_help()
