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
from Master import Master

class Board(SampleBase):

    def __init__(self, *args, **kwargs):
        super(Board, self).__init__(*args, **kwargs)
        self.teamR = Team(64, 180, 232)
        self.teamL = Team(255, 140, 0)
        self.grid = []
        self.master = Master()

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
    def detectLiftOff(self, team):
        # team is current team
#        print("Detecting lift off...")
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
                print("Yay you can move that good job")
                valid = True
                lifted = piece

        # if valid liftoff
        return valid, lifted

    def getTeamPieces(self, team):
        validPieces = []
        for row in self.grid:
            for piece in row:
                if (piece != None and piece.team == team):
                    validPieces.append(piece)

        return validPieces

    def detectLanding(self, piece):
        self.master.readData()
        # return false if back to original
        targets = piece.targets
        # piece is piece that is moving
        valid = False
        activatedTarget = None
        for cell in targets:
            state = self.master.getCellState(cell.row, cell.col):
            if (state == 0):
                print("Are you sure? Too bad")
                valid = True
                activatedTarget = cell

        # return true if valid target
        return valid, activatedTarget

    def victory(self, canvas, team):
        for i in range(0, 10):
            time.sleep(.01)
            x = random.randint(0, 8)
            y = random.randint(0, 8)
            canvas = self.matrix.CreateFrameCanvas()
            self.lightCell(canvas, x, y, team.r, team.g, team.b)
            canvas = self.matrix.SwapOnVSync(canvas)

    def sethVictory(self, canvas, team):
        if (team == self.teamL):
            team = self.teamR
        else:
            team = self.teamL
        for i in range(0, 10000):
            time.sleep(.01)
            canvas = self.matrix.CreateFrameCanvas()
            for m in range(0, 32):
                canvas.SetPixel(m, 0, team.r, team.g, team.b)
                canvas.SetPixel(m, 31, team.r, team.g, team.b)
                canvas.SetPixel(0, m, team.r, team.g, team.b)
                canvas.SetPixel(31, m, team.r, team.g, team.b)
            for j in range(1, 30):
                for k in range(0, 5):
                    x = random.randint(0, 29) + 1
                    canvas.SetPixel(x, j, random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                    time.sleep(.0001)
            for j in range(1, 30):
                for k in range(0, 5):
                    x = random.randint(0, 29) + 1
                    canvas.SetPixel(j, x, random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                    time.sleep(.0001)
            canvas = self.matrix.SwapOnVSync(canvas)


    def doTurn(self, canvas, team):
        # disable enPassantable
        # calculate targets for all pieces

        check = False
        checkMate = False
        kingRow = -1;
        kingCol = -1;

        for row in self.grid:
            for piece in row:
                if (isinstance(piece, King) and piece.team == team):
                    check = piece.calcTargets(self.grid)
                    kingRow = piece.row
                    kingCol = piece.col

        piecesWithMoves = 0

        for row in self.grid:
            for piece in row:
                if (isinstance(piece, Pawn) and piece.team == team):
                    piece.enPassantable = False
                if (isinstance(piece, King)):
                    if (len(piece.getTargets()) > 0 and piece.team == team):
                        piece.printPiece()
                elif (piece != None):
                    piece.calcTargets(self.grid)
                    if (check):
                        piece.skyFall(self.grid[kingRow][kingCol])
                    #print pieces that can be moved
                    if (len(piece.getTargets()) > 0 and piece.team == team):
                        piecesWithMoves = piecesWithMoves + 1
                        piece.printPiece()

        if (piecesWithMoves == 0 and len(self.grid[kingRow][kingCol].targets) == 0):
            checkMate = True

        if (checkMate):
            print("Check mate!")
            self.sethVictory(canvas, team)

        move = False
        row = 0
        col = 0
        print("Player:", team.name, "'s move.")

        while (move == False):
            # move a piece!
#            row = int(input("Enter row for desired piece: "))
#            col = int(input("Enter col for desired piece: "))
            pieceLifted = False
            liftedPiece = None
            while (pieceLifted == False):
                pieceLifted, liftedPiece = self.detectLiftOff(team)
                print("Waiting for player move...")

            row = liftedPiece.row
            col = liftedPiece.col
            print(row, col)
            if (self.grid[row][col] != None and self.grid[row][col].team == team and len(self.grid[row][col].getTargets()) > 0):
                move = True
            else:
                print("Invalid piece, pick again.")

        print("Calculating targets...")
        self.lightPieces(canvas, self.teamR)
        self.lightTargets(canvas, self.grid[row][col])
        canvas = self.matrix.SwapOnVSync(canvas)

        validMove = False
        # check if valid move
        while (validMove == False):
            # add detect lift off
            #targetRow = int(input("Enter a row for target: "))
            #targetCol = int(input("Enter a col for target: "))
            placed = False 
            while (not placed):
                print("Please choose a target already")
                placed, targetCell = self.detectLanding(self.grid[row][col])

            targetRow = targetCell.row
            targetCol = targetCell.col

            for cell in self.grid[row][col].getTargets():
                if (cell.row == targetRow and cell.col == targetCol):
                    validMove = True
                    print("Moving piece...")
                    self.grid[targetRow][targetCol] = self.grid[row][col]
                    if (isinstance(self.grid[targetRow][targetCol], Pawn)):
                        enemy = self.grid[targetRow][targetCol].move(targetRow, targetCol)
                        if (enemy != None):
                            self.grid[enemy.row][enemy.col] = None
                            print("enPassant!")

                    elif (isinstance(self.grid[targetRow][targetCol], King)):
                        rookLocation, rookTarget = self.grid[targetRow][targetCol].move(targetRow, targetCol)
                        if (rookLocation != None):
                            # do castling
                            self.grid[rookTarget.row][rookTarget.col] = self.grid[rookLocation.row][rookLocation.col]
                            self.grid[rookLocation.row][rookLocation.col] = None
                            self.grid[rookTarget.row][rookTarget.col].move(rookTarget.row, rookTarget.col)
                    else:
                        self.grid[targetRow][targetCol].move(targetRow, targetCol)

                    self.grid[row][col] = None

            if (validMove == False):
                print("Invalid target.")
            else:
                canvas = self.matrix.CreateFrameCanvas()
                self.lightPieces(canvas, self.teamR)
                canvas = self.matrix.SwapOnVSync(canvas)

    def clearBoard(self, canvas):
        for x in range(0, 8):
            for y in range(0, 8):
                self.lightCell(x, y, 0, 0, 0)

    def lightTargets(self, canvas, piece):
        #piece.calcTargets(self.grid)
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
        #self.teamR.setColor()

        nameL = input("Enter player 2 name: ")
        print("Enter player 2 colors (rgb): ")
        self.teamL.setName(nameL)
        #self.teamL.setColor()

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
