#!/usr/bin/env python
from samplebase import SampleBase
from rgbmatrix import RGBMatrix, RGBMatrixOptions
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
from Master import Master
from Tree import Tree
from AI import AI
import copy
import argparse
import os
import numpy as np

class Board(SampleBase):

    def __init__(self, *args, **kwargs):
        super(Board, self).__init__(*args, **kwargs)

        self.teamR = Team(64, 180, 232)
        self.teamL = Team(255, 140, 0)
        #self.teamR = Team(0, 153, 76)
        #self.teamL = Team(81, 0, 153)
        #self.teamR = Team(255, 255, 0)
        #self.teamL = Team(254, 0, 255)
        self.grid = []
        self.master = Master()
        self.computerPlayerR = False
        self.computerPlayerL = False

        self.checkerBrightness = 0
        self.checkerBrightnessDir = 2

        self.gameOver = False

        self.teamArray = []
        self.teamArray.append(Team(64, 180, 232)) #Blue
        self.teamArray.append(Team(190, 25, 255)) #Purple
        self.teamArray.append(Team(254, 220, 0)) #Yellow
        self.teamArray.append(Team(250, 125, 125)) #Pink
        self.teamArray.append(Team(25, 255, 35)) #Green
        self.teamArray.append(Team(245, 125, 0)) #Orange
        self.teamArray.append(Team(0, 25, 230)) #Dark Blue
        self.teamArray.append(Team(28, 225, 180)) #Cyan

        for row in range(0, 8):
            self.grid.append([None, None, None, None, None, None, None, None])

    # RUN GAME
    def run(self):
        print("Running game...")
        self.canvas = self.matrix.CreateFrameCanvas()

        self.colorPicker()

        self.warGames()

        self.createPlayers()

        # Josh added this, hopefully it's okay
        offset_canvas = self.matrix.CreateFrameCanvas()

   #     self.lightCheckerTown(offset_canvas)
   #     offset_canvas = self.matrix.SwapOnVSync(offset_canvas)
   #     time.sleep(1)
        # begin interactive setup
        self.interactiveSetup(offset_canvas, self.teamR)
        self.interactiveSetup(offset_canvas, self.teamL)

        self.initializeGameBoard()

        while (not self.gameOver):
            offset_canvas = self.matrix.CreateFrameCanvas()
            #self.lightPieces(offset_canvas, self.teamR)
            self.lightCheckerTown(offset_canvas)
            offset_canvas = self.matrix.SwapOnVSync(offset_canvas)

            # Do player 1's turn
            offset_canvas = self.matrix.CreateFrameCanvas()

            if (self.computerPlayerR):
                self.computerMove(self.teamR, offset_canvas)
            else:
                self.doTurn(offset_canvas, self.teamR)
                offset_canvas = self.matrix.CreateFrameCanvas()

            if (self.gameOver):
                break

            if (self.computerPlayerL):
                self.computerMove(self.teamL, offset_canvas)
            else:
                self.doTurn(offset_canvas, self.teamL)
                offset_canvas = self.matrix.CreateFrameCanvas()

            offset_canvas = self.matrix.SwapOnVSync(offset_canvas)
            del self.matrix
            self.matrix = RGBMatrix(options = self.options)
            self.canvas = self.matrix.CreateFrameCanvas()
        del self.matrix
        self.matrix = RGBMatrix(options = self.options)
        self.canvas = self.matrix.CreateFrameCanvas()

    ### Member Functions ###
    def lightPath(self, canvas, startRow, startCol, endRow, endCol):
        rowIncrement = (endRow - startRow) / 8.0
        colIncrement = (endCol - startCol) / 8.0

    def lightCheckerTown(self, canvas):
        r = 255
        g = 255
        b = 255
        for x in range(4):
            for y in range(4):
                self.lightCell(canvas, 1 + (2*x), 2*y, r, g, b)
        for x in range(4):
            for y in range(4):
                self.lightCell(canvas, (2*x), 1 + 2*y, r, g, b)

    def chooseLightCheckerTown(self, canvas):
        r = self.checkerBrightness
        g = self.checkerBrightness
        b = self.checkerBrightness
        for x in range(4):
            for y in range(4):
                self.lightCell(canvas, 1 + (2*x), 2*y, r, g, b)
        for x in range(4):
            for y in range(4):
                self.lightCell(canvas, (2*x), 1 + 2*y, r, g, b)

    def interactiveSetup(self, canvas, team):
#        canvas = self.matrix.SwapOnVSync(canvas)
        if (team == self.teamR):
            # setup Rook
            self.detectPiece(canvas, team, "Rook", 0, 0)
            self.lightCell(canvas, 0, 0, team.r, team.g, team.b) # light team color
            self.detectPiece(canvas, team, "Rook", 0, 7)
            # setup Knight
            self.detectPiece(canvas, team, "Knight", 0, 1)
            self.detectPiece(canvas, team, "Knight", 0, 6)
            # setup bishop
            self.detectPiece(canvas, team, "Bishop", 0, 2)
            self.detectPiece(canvas, team, "Bishop", 0, 5)
            # setup Queen
            self.detectPiece(canvas, team, "Queen", 0, 3)
            # setup King
            self.detectPiece(canvas, team, "King", 0, 4)
            # setup Pawns
            self.detectPawns(canvas, team, 1)
        else:
            # setup Rook
            self.detectPiece(canvas, team, "Rook", 7, 0)
            self.detectPiece(canvas, team, "Rook", 7, 7)
            # setup Knight
            self.detectPiece(canvas, team, "Knight", 7, 1)
            self.detectPiece(canvas, team, "Knight", 7, 6)
            # setup bishop
            self.detectPiece(canvas, team, "Bishop", 7, 2)
            self.detectPiece(canvas, team, "Bishop", 7, 5)
            # setup Queen
            self.detectPiece(canvas, team, "Queen", 7, 3)
            # setup King
            self.detectPiece(canvas, team, "King", 7, 4)
            # setup Pawns
            self.detectPawns(canvas, team, 6)

    def detectMismatch(self, canvas):
        # read data into master
        self.master.readData()
        # set color of piece that needs correction
        r = 255
        g = 0
        b = 0
        # loop through valid pieces and make sure they are there
        teamRPieces = self.getTeamPieces(self.teamR)
        teamLPieces = self.getTeamPieces(self.teamL)
        mismatch = True
        canvas = self.matrix.CreateFrameCanvas()
        #self.lightPieces(canvas, self.teamR)
        #self.lightPieces(canvas, self.teamL)
        self.lightCheckerTown(canvas)
        canvas = self.matrix.SwapOnVSync(canvas)

        while mismatch:
            mismatch = False
            self.master.readData()
            time.sleep(0.2)
            canvas = self.matrix.CreateFrameCanvas()
            #self.lightPieces(canvas, self.teamR)
            #self.lightPieces(canvas, self.teamL)
            self.lightCheckerTown(canvas)
            for piece in teamRPieces:
                state = self.master.getCellState(piece.row, piece.col)
                if state == 1:
                    mismatch = True
                    #print("Piece should be here")
                    #print(piece.row, piece.col)
                    # light cell warning color
                    self.lightCell(canvas, piece.row, piece.col, r, g, b)
                    #time.sleep(0.01)
            canvas = self.matrix.SwapOnVSync(canvas)

        mismatch = True
        canvas = self.matrix.CreateFrameCanvas()
        #self.lightPieces(canvas, self.teamR)
        #self.lightPieces(canvas, self.teamL)
        self.lightCheckerTown(canvas)
        canvas = self.matrix.SwapOnVSync(canvas)

        while mismatch:
            mismatch = False
            self.master.readData()
            canvas = self.matrix.CreateFrameCanvas()
            #self.lightPieces(canvas, self.teamR)
            #self.lightPieces(canvas, self.teamL)
            self.lightCheckerTown(canvas)

            for piece in teamLPieces:
                state = self.master.getCellState(piece.row, piece.col)
                if state == 1:
                    mismatch = True
                    #print("Piece should be here")
                    #print(piece.row, piece.col)
                    # light cell warning color
                    self.lightCell(canvas, piece.row, piece.col, r, g, b)
                    time.sleep(0.01)
            canvas = self.matrix.SwapOnVSync(canvas)

        del self.matrix
        self.matrix = RGBMatrix(options = self.options)
        self.canvas = self.matrix.CreateFrameCanvas()
        # mismatch complete return true
        return True

    def detectPawns(self, canvas, team, row):
        #print("Please place pawns")
        for col in range(8):
            self.lightCell(canvas, row, col, 255, 255, 255)
        placed = False
        while not placed:
            placed = True
            self.master.readData()
            for col in range(8):
                # why read every time? self.master.readData()
                if (self.master.getCellState(row, col) == 1):
                    placed = False
                    self.lightCell(canvas, row, col, 255, 255, 255)
                else:
                    self.lightCell(canvas, row, col, team.r, team.g, team.b)
                    # pawn was placed, light cell team color
            time.sleep(0.1)
        #print("Pawns placed.")

    def detectPiece(self, canvas, team, piece, row, col):
        # setup teamR
        #print("Place " + piece + " here:")
        # light up cell white
        self.lightCell(canvas, row, col, 255, 255, 255)
        canvas = self.matrix.SwapOnVSync(canvas)
        placed = False
        while not placed:
            self.master.readData()
            if (self.master.getCellState(row, col) == 0):
                placed = True
            time.sleep(0.01)
        #print(piece + " set.")
        self.lightCell(canvas, row, col, team.r, team.g, team.b) # light team color
        # just added
        #canvas = self.matrix.SwapOnVSync(canvas)
        del self.matrix
        self.matrix = RGBMatrix(options = self.options)
        self.canvas = self.matrix.CreateFrameCanvas()

    # detect lift off
    def detectLiftOff(self, team):
        # team is current team
        #print("Detecting lift off...")
        # get all valid pieces that can move
        validPieces = self.getTeamPieces(team)
        # update board data
        self.master.readData()
        # check each piece and see if any have been lifted
        valid = False
        lifted = None
        for piece in validPieces:
            state = self.master.getCellState(piece.row, piece.col)
            if (state == 1 and valid == False):
                #print("Yay you can move that good job")
                valid = True
                lifted = piece

        # if valid liftoff
        return valid, lifted

    def getTeamPieces(self, team, grid=None):
        if (grid == None):
            grid = self.grid
        validPieces = []

        for row in grid:
            for piece in row:
                if (piece != None and piece.team.r == team.r):
                    validPieces.append(piece)

        return validPieces

    def detectLanding(self, canvas, piece):
        tempMatrix = self.matrix
        self.master.readData()
        targets = piece.targets
        # piece is piece that is moving
        valid = False
        activatedTarget = None
        # check regret
        state = self.master.getCellState(piece.row, piece.col)
        if (state == 0):
            returnCell = Cell(piece.row, piece.col)
            return True, returnCell
        for cell in targets:
            state = self.master.getCellState(cell.row, cell.col)
            # if the piece is an enemy piece, lift yours then lift enemy, then take
            if (self.grid[cell.row][cell.col] != None):
                # there is a piece here
                if (state == 1):
                    # enter while loop, wait for player to place theres
                    activatedTarget = cell
                    while (state == 1):
                        canvas = self.matrix.CreateFrameCanvas()
                        self.lightCheckerTown(canvas)
                        self.lightCell(canvas, cell.row, cell.col, piece.team.r, piece.team.g, piece.team.b)
                        canvas = self.matrix.SwapOnVSync(canvas)

                        self.master.readData()
                        #print("You are taking an enemy, please place your piece")
                        state = self.master.getCellState(cell.row, cell.col)

                        canvas = self.matrix.CreateFrameCanvas()
                        self.lightCheckerTown(canvas)
                        canvas = self.matrix.SwapOnVSync(canvas)
                        self.master.readData()

                    valid = True

            elif (state == 0):
                #print("Are you sure? Too bad")
                valid = True
                activatedTarget = cell

        del self.matrix
        self.matrix = RGBMatrix(options = self.options)
        self.canvas = self.matrix.CreateFrameCanvas()
        return valid, activatedTarget

    def victory(self, canvas, team):
        for i in range(0, 1000):
            time.sleep(0.5)
            x = random.randint(0, 8)
            y = random.randint(0, 8)
            canvas = self.matrix.CreateFrameCanvas()
            self.lightCell(canvas, x, y, team.r, team.g, team.b)
            canvas = self.matrix.SwapOnVSync(canvas)

    def sethVictoryOld(self, canvas, team):
        if (team == self.teamL):
            team = self.teamR
        else:
            team = self.teamL
        for i in range(0, 10000):
            time.sleep(.001)
            canvas = self.matrix.CreateFrameCanvas()
            for m in range(0, 32):
                for z in range(0, 4):
                    canvas.SetPixel(m, z, team.r, team.g, team.b)
                    canvas.SetPixel(z, m, team.r, team.g, team.b)
                for z in range (28, 32):
                    canvas.SetPixel(m, z, team.r, team.g, team.b)
                    canvas.SetPixel(z, m, team.r, team.g, team.b)
            for j in range(4, 28):
                for k in range(4, 28):
                    #x = random.randint(0, 29) + 1
                    canvas.SetPixel(j, k, random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                    #time.sleep(.0001)
            canvas = self.matrix.SwapOnVSync(canvas)

    def sethVictory(self, canvas, team):
        if (team == self.teamL):
            team = self.teamR
        else:
            team = self.teamL
        canvasList = []
        for i in range(0, 100):
            if self.checkNewGame():
                return
            time.sleep(0.1)
            canvas = self.matrix.CreateFrameCanvas()
            for m in range(0, 8):
                self.lightCell(canvas, m, 0, team.r, team.g, team.b)
                self.lightCell(canvas, 0, m, team.r, team.g, team.b)
                self.lightCell(canvas, m, 7, team.r, team.g, team.b)
                self.lightCell(canvas, 7, m, team.r, team.g, team.b)
            for j in range(1, 7):
                for k in range(1, 7):
                    #x = random.randint(0, 29) + 1
                    self.lightCell(canvas, j, k, random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                    #time.sleep(.0001)
            self.matrix.SwapOnVSync(canvas)
            canvasList.append(canvas)

        index = 0
        while (True):
            if (self.checkNewGame()):
                return
            index = (index + random.randint(0,98)) % 100
            self.matrix.SwapOnVSync(canvasList[index])
            time.sleep(0.1)
        del self.matrix
        self.matrix = RGBMatrix(options = self.options)
        self.canvas = self.matrix.CreateFrameCanvas()

    def staleMate(self, canvas):
        canvas = self.matrix.CreateFrameCanvas()
        for i in range(0, 4):
            for j in range(0, 8):
                self.lightCell(canvas, i, j, self.teamR.r, self.teamR.g, self.teamR.b)
        for i in range(4, 8):
            for j in range(0, 8):
                self.lightCell(canvas, i, j, self.teamL.r, self.teamL.g, self.teamL.b)
        canvas = self.matrix.SwapOnVSync(canvas)
        while True:
            if self.checkNewGame():
                return


    def doTurn(self, canvas, team):
        # disable enPassantable
        # calculate targets for all pieces

        check = False
        checkMate = False
        kingRow = -1
        kingCol = -1
        piecesWithMoves = 0

        #self.computerMove(team)

        #count total targets for this team for stalemate purposes
        #count = 0;
        for row in self.grid:
            for piece in row:
                if (piece != None):
                    #increment number of moves
                    #count += len(piece.getTargets());
                    if (isinstance(piece, King) and piece.team == team):
                        check = piece.calcTargets(self.grid)
                        if (len(piece.getTargets()) > 0):
                            piecesWithMoves = piecesWithMoves + 1
                        kingRow = piece.row
                        kingCol = piece.col

        for row in self.grid:
            for piece in row:
                if (isinstance(piece, Pawn) and piece.team == team):
                    piece.enPassantable = False
                if (piece != None and not (isinstance(piece, King))):
                    piece.calcTargets(self.grid)
                    if (check):
                        piece.skyFall(self.grid[kingRow][kingCol])
                    #print pieces that can be moved
                    if (len(piece.getTargets()) > 0 and piece.team == team):
                        piecesWithMoves = piecesWithMoves + 1

        #check if there are no legal moves
        if (piecesWithMoves == 0):
            #stalemate
            if (not check):
                self.gameOver = True
                self.staleMate(canvas)
                return

            elif (check):
                #print("Check mate!")
                self.gameOver = True
                self.sethVictory(canvas, team)
                return

        # check for mismatch
        self.detectMismatch(canvas)

        time.sleep(0.25)

        #self.lightPieces(canvas, self.teamR)
        #self.lightPieces(canvas, self.teamL)

        move = False
        row = 0
        col = 0
        print("Player:", team.name, "'s move.")

        while (move == False):

            canvas = self.matrix.CreateFrameCanvas()

            # move a piece!
#            row = int(input("Enter row for desired piece: "))
#            col = int(input("Enter col for desired piece: "))
            pieceLifted = False
            liftedPiece = None
            while (pieceLifted == False):
                pieceLifted, liftedPiece = self.detectLiftOff(team)
                #print("Waiting for player move...")

            row = liftedPiece.row
            col = liftedPiece.col
            #print("Calculating targets...")
            #self.lightPieces(canvas, self.teamR)
            self.lightCheckerTown(canvas)
            self.lightTargets(canvas, self.grid[row][col])
            canvas = self.matrix.SwapOnVSync(canvas)

            move = True # the player is moving a piece, is it valid? Will they continue?
            validMove = False
            # check if valid move
            while (validMove == False):
                # add detect lift off
                #targetRow = int(input("Enter a row for target: "))
                #targetCol = int(input("Enter a col for target: "))
                placed = False
                returned = False
                while (not placed):
                    #print("Please choose a target already")
                    placed, targetCell = self.detectLanding(canvas, self.grid[row][col])
                    #print(placed, targetCell.row, targetCell.col, row, col)
                    if placed:
                        #print(targetCell.row, targetCell.col, row, col)
                        if (targetCell.row == row and targetCell.col == col):
                            #print("Piece returned.")
                            returned = True
                if returned:
                    # go back to detecting which piece player wants to move
                    move = False
                    validMove = True # jank but whatever it'll work
                    #self.clearBoard(canvas)
                    canvas = self.matrix.CreateFrameCanvas()
                    self.lightCheckerTown(canvas)
                    #self.lightPieces(canvas, self.teamR)
                    canvas = self.matrix.SwapOnVSync(canvas)
                    #print("Regret.")
                    #continue

                if move:
                    targetRow = targetCell.row
                    targetCol = targetCell.col

                    for cell in self.grid[row][col].getTargets():
                        if (cell.row == targetRow and cell.col == targetCol):
                            validMove = True
                            #print("Moving piece...")
                            self.grid[targetRow][targetCol] = self.grid[row][col]
                            if (isinstance(self.grid[targetRow][targetCol], Pawn)):
                                enemy = self.grid[targetRow][targetCol].move(targetRow, targetCol, self.grid)
                                if (enemy != None):
                                    self.grid[enemy.row][enemy.col] = None
                                    #print("enPassant!")
                                    # make player remove piece
                                    state = self.master.getCellState(enemy.row, enemy.col)
                                    while state == 0:
                                        self.master.readData()
                                        time.sleep(0.4)
                                        # fade in red
                                        for r in range(201):
                                            canvas = self.matrix.CreateFrameCanvas()
                                            self.lightCheckerTown(canvas)
                                            self.lightCell(canvas, enemy.row, enemy.col, 50+r, 0, 0)
                                            canvas = self.matrix.SwapOnVSync(canvas)
                                            time.sleep(0.002)

                                        self.master.readData()
                                        time.sleep(0.4)
                                        # fade out red
                                        for r in range(201):
                                            canvas = self.matrix.CreateFrameCanvas()
                                            self.lightCheckerTown(canvas)
                                            self.lightCell(canvas, enemy.row, enemy.col, 255-r, 0, 0)
                                            canvas = self.matrix.SwapOnVSync(canvas)
                                            time.sleep(0.002)

                                        state = self.master.getCellState(enemy.row, enemy.col)

                            elif (isinstance(self.grid[targetRow][targetCol], King)):
                                rookLocation, rookTarget = self.grid[targetRow][targetCol].move(targetRow, targetCol, self.grid)
                                if (rookLocation != None):
                                    # do castling
                                    self.grid[rookTarget.row][rookTarget.col] = self.grid[rookLocation.row][rookLocation.col]
                                    self.grid[rookLocation.row][rookLocation.col] = None
                                    self.grid[rookTarget.row][rookTarget.col].move(rookTarget.row, rookTarget.col, self.grid)
                            else:
                                self.grid[targetRow][targetCol].move(targetRow, targetCol,self.grid)

                            self.grid[row][col] = None

                    if (validMove == False):
                        print("Invalid target.")
                    else:
                        canvas = self.matrix.CreateFrameCanvas()
                        self.lightCheckerTown(canvas)
                        #self.lightPieces(canvas, self.teamR)
                        canvas = self.matrix.SwapOnVSync(canvas)

    def lightTargets(self, canvas, piece):
        #piece.calcTargets(self.grid)
        #:canvas = self.matrix.CreateFrameCanvas()
        r = piece.team.r
        g = piece.team.g
        b = piece.team.b
        # light your cell
        self.lightCell(canvas, piece.row, piece.col, r, g, b)

        targets = piece.getTargets()
        for cell in targets:
            #print("Target: ", cell.row, cell.col)
            self.lightCell(canvas, cell.row, cell.col, r, g, b)

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

        # TEAM L
        # create pawns for teamL
        for col in range(0, 8):
            self.grid[6][col] = Pawn(6, col, self.teamL)
        # create bishop for teamL
        self.grid[7][2] = Bishop(7, 2, self.teamL)
        self.grid[7][5] = Bishop(7, 5, self.teamL)
        # create rook for teamL
        self.grid[7][0] = Rook(7, 0, self.teamL)
        self.grid[7][7] = Rook(7, 7, self.teamL)
        self.grid[7][1] = Knight(7, 1, self.teamL)
        self.grid[7][6] = Knight(7, 6, self.teamL)
        self.grid[7][3] = Queen(7, 3, self.teamL)
        self.grid[7][4] = King(7, 4, self.teamL)

    def createPlayers(self):
        if (self.computerPlayerR):
            self.teamR.setName("Computer")
            self.teamL.setName("Human")
        elif (self.computerPlayerL):
            self.teamL.setName("Computer")
            self.teamR.setName("Human")
        else:
            self.teamL.setName("Player 1")
            self.teamR.setName("Player 2")
        #self.teamL.setColor()

    def lightCell(self, canvas, x, y, r, g, b):
        #offset_canvas = self.matrix.CreateFrameCanvas()
        #print(x, y, r, g, b)
        for i in range(0, 4):
            for j in range(0, 4):
                canvas.SetPixel(x*4 + i, y*4 + j, r, g, b)
                #canvas.SetPixel(x, y, 255, 255, 255)

    def printBoardStates(self, grid = []):
        if (grid == []):
            grid = self.grid
        for r in range(8):
            print(grid[r])

    def computerMove(self, team, canvas, depth=2):
        check = False
        checkMate = False
        kingRow = -1
        kingCol = -1
        piecesWithMoves = 0
        self.checkerBrightness = 255;

        #self.computerMove(team)

        #count total targets for this team for stalemate purposes
        #count = 0;
        for row in self.grid:
            for piece in row:
                if (piece != None):
                    #increment number of moves
                    #count += len(piece.getTargets());
                    if (isinstance(piece, King) and piece.team == team):
                        check = piece.calcTargets(self.grid)
                        if (len(piece.getTargets()) > 0):
                            piecesWithMoves = piecesWithMoves + 1
                        kingRow = piece.row
                        kingCol = piece.col

        for row in self.grid:
            for piece in row:
                if (isinstance(piece, Pawn) and piece.team == team):
                    piece.enPassantable = False
                if (piece != None and not isinstance(piece, King)):
                    piece.calcTargets(self.grid)
                    if (check):
                        piece.skyFall(self.grid[kingRow][kingCol])
                    #print pieces that can be moved
                    if (len(piece.getTargets()) > 0 and piece.team == team):
                        piecesWithMoves = piecesWithMoves + 1

        #check if there are no legal moves
        if (piecesWithMoves == 0):
            #stalemate
            if (not check):
                self.gameOver = True
                self.staleMate(canvas)
                return

            elif (check):
                #print("Check mate!")
                self.gameOver = True
                self.sethVictory(canvas, team)
                return

        #Create the whole tree recursively
        root = Tree(self.grid, None, None, self.teamR, self.teamL)
        self.addNodes(root, team, depth)

        #Create a new AI object with tree
        computerPlayer = AI(root, team)

        #Tell the AI to return the best state (node)
        bestMove = computerPlayer.alpha_beta_search()

        #For now, print out the old/new cell of the
        print ("the best move involves moving the piece at square " + str(bestMove.oldCell.row) + str(bestMove.oldCell.col) + " to " + str(bestMove.newCell.row) + str(bestMove.newCell.col))

        # move piece from bestMove.oldCell to bestMove.newCell
        state = 0

        canvas = self.matrix.CreateFrameCanvas()
        self.lightCheckerTown(canvas)
        canvas = self.matrix.SwapOnVSync(canvas)
        self.detectMismatch(canvas)
        self.detectMismatch(canvas)

        if (self.grid[bestMove.newCell.row][bestMove.newCell.col] == None):
            while state == 0:
                self.master.readData()

                canvas = self.matrix.CreateFrameCanvas()
            #self.lightPieces(canvas, self.teamL)
                self.lightCheckerTown(canvas)
                self.lightCell(canvas, bestMove.oldCell.row, bestMove.oldCell.col, team.r, team.g, team.b)

                canvas = self.matrix.SwapOnVSync(canvas)

                state = self.master.getCellState(bestMove.oldCell.row, bestMove.oldCell.col)
            while state == 1:
                self.master.readData()

                canvas = self.matrix.CreateFrameCanvas()
                self.lightCheckerTown(canvas)
                self.lightCell(canvas, bestMove.newCell.row, bestMove.newCell.col, team.r, team.g, team.b)
                canvas = self.matrix.SwapOnVSync(canvas)
                time.sleep(.1)
                canvas = self.matrix.CreateFrameCanvas()
                self.lightCheckerTown(canvas)
                canvas = self.matrix.SwapOnVSync(canvas)

                state = self.master.getCellState(bestMove.newCell.row, bestMove.newCell.col)
        else:
            # detect removal of other piece and then move of this guy
            state = 0
            while state == 0:
                self.master.readData()

                canvas = self.matrix.CreateFrameCanvas()
            #self.lightPieces(canvas, self.teamL)
                self.lightCheckerTown(canvas)
                self.lightCell(canvas, bestMove.oldCell.row, bestMove.oldCell.col, team.r, team.g, team.b)
                #self.lightCell(canvas, bestMove.newCell.row, bestMove.newCell.col, team.r, team.g, team.b)

                canvas = self.matrix.SwapOnVSync(canvas)

                state = self.master.getCellState(bestMove.oldCell.row, bestMove.oldCell.col)
            state = 0
            while state == 0:
                self.master.readData()
                canvas = self.matrix.CreateFrameCanvas()
            #self.lightPieces(canvas, self.teamL)
                self.lightCheckerTown(canvas)
                #self.lightCell(canvas, bestMove.oldCell.row, bestMove.oldCell.col, team.r, team.g, team.b)
                self.lightCell(canvas, bestMove.newCell.row, bestMove.newCell.col, team.r, team.g, team.b)

                canvas = self.matrix.SwapOnVSync(canvas)

                state = self.master.getCellState(bestMove.newCell.row, bestMove.newCell.col)
            time.sleep(.1)
            while state == 1:
                self.master.readData()

                canvas = self.matrix.CreateFrameCanvas()
                self.lightCheckerTown(canvas)
                self.lightCell(canvas, bestMove.newCell.row, bestMove.newCell.col, team.r, team.g, team.b)
                canvas = self.matrix.SwapOnVSync(canvas)
                time.sleep(.1)
                canvas = self.matrix.CreateFrameCanvas()
                self.lightCheckerTown(canvas)
                canvas = self.matrix.SwapOnVSync(canvas)

                state = self.master.getCellState(bestMove.newCell.row, bestMove.newCell.col)


        self.grid[bestMove.oldCell.row][bestMove.oldCell.col].move(bestMove.newCell.row, bestMove.newCell.col, self.grid)
        self.grid[bestMove.newCell.row][bestMove.newCell.col] = self.grid[bestMove.oldCell.row][bestMove.oldCell.col]
        self.grid[bestMove.oldCell.row][bestMove.oldCell.col] = None

        canvas = self.matrix.CreateFrameCanvas()
        self.lightCheckerTown(canvas)
        canvas = self.matrix.SwapOnVSync(canvas)


#                input("press enter when ready to continue")

    def drawBoard(self, boardState):
        self.canvas.Clear()
        self.checkerBrightness = self.checkerBrightness + self.checkerBrightnessDir
        if (self.checkerBrightness <= 0):
            self.checkerBrightnessDir = self.checkerBrightnessDir * -1
            self.checkerBrightness = 0
        elif (self.checkerBrightness >= 255):
            self.checkerBrightnessDir = self.checkerBrightnessDir * -1
            self.checkerBrightness = 255

        #self.chooseLightCheckerTown(canvas)
        for row in boardState:
            for piece in row:
                if (piece != None):
                    self.lightCell(self.canvas, piece.row, piece.col, piece.team.r, piece.team.g, piece.team.b)

        self.chooseLightCheckerTown(self.canvas)

        self.canvas = self.matrix.SwapOnVSync(self.canvas)

    def colorPicker(self):
        self.canvas.Clear()

        for i in range (0, 8):
            self.lightCell(self.canvas, 2, i, self.teamArray[i].r, self.teamArray[i].g, self.teamArray[i].b) # colorpicker
            self.lightCell(self.canvas, 5, i, self.teamArray[i].r, self.teamArray[i].g, self.teamArray[i].b) # colorpicker

        team1Found = False
        team2Found = False
        shutDownKey1 = False
        shutDownKey2 = False
        restartKey1 = False
        restartKey2 = False

        self.canvas = self.matrix.SwapOnVSync(self.canvas)

        while not (team1Found and team2Found):
            team1Found = False
            team2Found = False
            shutDownKey1 = False
            shutDownKey2 = False
            restartKey1 = False
            restartKey2 = False
            self.master.readData()
            for i in range(0, 8):
                if (self.master.getCellState(2, i) == 0):
                    team1Found = True
                    self.teamR.r = self.teamArray[i].r
                    self.teamR.g = self.teamArray[i].g
                    self.teamR.b = self.teamArray[i].b
                if (self.master.getCellState(5, i) == 0):
                    team2Found = True
                    self.teamL.r = self.teamArray[i].r
                    self.teamL.g = self.teamArray[i].g
                    self.teamL.b = self.teamArray[i].b
            for i in range (0, 8):
                if (self.master.getCellState(3, i) == 0):
                    shutDownKey1 = True
                    if (i = 7):
                        restartKey1 = True
                if (self.master.getCellState(4, i) == 0):
                    shutDownKey2 = True
                    if (i = 7):
                        restartKey2 = True

            if (shutDownKey1 and shutDownKey2):
                self.canvas.Clear()

                for i in range (0, 12):
                    self.canvas.Clear()
                    for j in range (i, 32 - i):
                        #color these rows
                        for k in range (0, 32):
                            self.canvas.SetPixel(j, k, 255, 0, 0)
                    self.canvas = self.matrix.SwapOnVSync(self.canvas)
                    #sleep here
                    time.sleep(0.035 * np.exp(-1/16*(i - 12)))

                for i in range (0, 16):
                    self.canvas.Clear()
                    for j in range (i, 32 - i):
                        #color these rows
                        for k in range (12, 20):
                            self.canvas.SetPixel(k, j, 255, 0, 0)
                    self.canvas = self.matrix.SwapOnVSync(self.canvas)
                    #sleep here
                    time.sleep(0.025 * np.exp(-1/16*(i - 16)))
                self.canvas.Clear()
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                if (restartKey1 and restartKey2):
                    os.system("sudo reboot now")
                    while True:
                        time.sleep(1)
                else:
                    os.system("sudo shutdown now")
                    while True:
                        time.sleep(1)


            #canvas = self.matrix.CreateFrameCanvas()
            self.canvas.Clear()
            if (team1Found and team2Found):
                for i in range(0, 8):
                    if (self.master.getCellState(2, i) == 0):
                        self.lightCell(self.canvas, 2, i, self.teamArray[i].r, self.teamArray[i].g, self.teamArray[i].b)
                    if (self.master.getCellState(5, i) == 0):
                        self.lightCell(self.canvas, 5, i, self.teamArray[i].r, self.teamArray[i].g, self.teamArray[i].b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                time.sleep(2)
            elif (team1Found):
                for i in range(0, 8):
                    if (self.master.getCellState(2, i) == 0):
                        self.lightCell(self.canvas, 2, i, self.teamArray[i].r, self.teamArray[i].g, self.teamArray[i].b)
                for i in range (0, 8):
                    self.lightCell(self.canvas, 5, i, self.teamArray[i].r, self.teamArray[i].g, self.teamArray[i].b) # colorpicker
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
            elif (team2Found):
                for i in range(0, 8):
                    if (self.master.getCellState(5, i) == 0):
                        self.lightCell(self.canvas, 5, i, self.teamArray[i].r, self.teamArray[i].g, self.teamArray[i].b)
                for i in range (0, 8):
                    self.lightCell(self.canvas, 2, i, self.teamArray[i].r, self.teamArray[i].g, self.teamArray[i].b) # colorpicker
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
            else:
                for i in range (0, 8):
                    self.lightCell(self.canvas, 2, i, self.teamArray[i].r, self.teamArray[i].g, self.teamArray[i].b) # colorpicker
                    self.lightCell(self.canvas, 5, i, self.teamArray[i].r, self.teamArray[i].g, self.teamArray[i].b) # colorpicker
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
        self.teamR.r = self.teamR.r + 1

    def warGames(self):
        self.canvas.Clear()
        print("The only winning move is not to play")

        team1Decided = False
        team2Decided = False

        think = 0
        thinkL = 0
        thinkR = 0

        while True:
            team1Decided = False
            team2Decided = False
            self.master.readData()

            for i in range (0, 8):
                if (i < 4):
                    if (self.master.getCellState(3, i) == 0 and not team1Decided):
                        team1Decided = True
                        self.computerPlayerR = False
                    elif (self.master.getCellState(4, i) == 0 and not team2Decided):
                        team2Decided = True
                        self.computerPlayerL = True
                else:
                    if (self.master.getCellState(3, i) == 0 and not team1Decided):
                        team1Decided = True
                        self.computerPlayerR = True
                    elif (self.master.getCellState(4, i) == 0 and not team2Decided):
                        team2Decided = True
                        self.computerPlayerL = False
                if (team1Decided and team2Decided):
                    break

            #light teamR's squares
            if (team1Decided):
                if (self.computerPlayerR):
                    for i in range (0, 8):
                        if (i == (7 - thinkR)):
                            self.lightCell(self.canvas, 3, 7 - thinkR, self.teamR.r, self.teamR.g, self.teamR.b)
                        else:
                            self.lightCell(self.canvas, 3, i, 255, 255, 255)
                else:
                    for i in range (0, 8):
                        self.lightCell(self.canvas, 3, i, self.teamR.r, self.teamR.g, self.teamR.b)
            else:
                for i in range (0, 8):
                    if (i < 4):
                        self.lightCell(self.canvas, 3, i, self.teamR.r, self.teamR.g, self.teamR.b)
                    else:
                        if (i == (7 - think)):
                            self.lightCell(self.canvas, 3, 7 - think, self.teamR.r, self.teamR.g, self.teamR.b)
                        else:
                            self.lightCell(self.canvas, 3, i, 255, 255, 255)

            #light teamL's squares
            if (team2Decided):
                if (self.computerPlayerL):
                    for i in range (0, 8):
                        if (i == thinkL):
                            self.lightCell(self.canvas, 4, thinkL, self.teamL.r, self.teamL.g, self.teamL.b)
                        else:
                            self.lightCell(self.canvas, 4, i, 255, 255, 255)
                else:
                    for i in range (0, 8):
                        self.lightCell(self.canvas, 4, i, self.teamL.r, self.teamL.g, self.teamL.b)
            else:
                for i in range (0, 8):
                    if (i < 4):
                        if (i == think):
                            self.lightCell(self.canvas, 4, think, self.teamL.r, self.teamL.g, self.teamL.b)
                        else:
                            self.lightCell(self.canvas, 4, i, 255, 255, 255)
                    else:
                        self.lightCell(self.canvas, 4, i, self.teamL.r, self.teamL.g, self.teamL.b)

            self.canvas = self.matrix.SwapOnVSync(self.canvas)

            self.canvas.Clear()

            time.sleep(0.2)

            think = (think + 1) % 4
            thinkL = (thinkL + 1) % 8
            thinkR = (thinkR + 1) % 8

            if (team1Decided and team2Decided):
                break


    def addNodes(self, currentNode, team, depth=2):
        #print ("depth remaining: " + str(depth))

        #if the depth is 0, we've reached the "bottom" of the tree (as far as we initially told it to go)
        if (depth == 0):
            return

        #change how the pieces are grabbed
        for piece in self.getTeamPieces(team, currentNode.boardState):
            #TODO Parameter for this guy?
            #print("found a piece")
            piece.calcTargets(currentNode.boardState)
            for target in piece.targets:
                newBoard = copy.deepcopy(currentNode.boardState)
                newPiece = newBoard[piece.row][piece.col]
                #If it is, make the move and add the child to the current node
                newPiece.move(target.row, target.col, self.grid)
                newBoard[piece.row][piece.col] = None
                newBoard[target.row][target.col] = newPiece
                #TODO comment this out once boardstates was complete
                self.drawBoard(newBoard)
                #self.printBoardStates(newBoard)
                currentNode.addChild(Tree(newBoard, Cell(piece.row, piece.col), Cell(target.row, target.col), self.teamR, self.teamL))

        #Once all children for this node are found, go another level deep
        print ("done adding children for depth " + str(depth) + "! boards created = " + str(len(currentNode.children)))

        if (depth == 0):
            return

        if (team == self.teamL):
            team = self.teamR
        else:
            team = self.teamL

        for child in currentNode.children:
            self.addNodes(child, team, depth-1)

    def checkNewGame(self):
        self.master.readData()
        sum = [0,0,0,0,0,0,0,0]
        total = 0
        for i in range (0,8):
            for j in range (0,8):
                    sum[i] = sum[i] + (self.master.getCellState(i, j) + 1) % 2
                    total = total + (self.master.getCellState(i, j) + 1) % 2
        if (total == 0):
            return True
        elif (sum[0] == 8 and sum[1] == 8 and sum[6] == 8 and sum [7] == 8):
            return True
        else:
            return False
