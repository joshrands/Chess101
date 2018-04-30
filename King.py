#child class of Piece that represents a King
from Piece import Piece
from Cell import Cell
from Rook import Rook
from Bishop import Bishop
from Knight import Knight
from Pawn import Pawn
from Queen import Queen
from Team import Team

class King(Piece):

    def __init__(self, row, col, team):
        self.row = row
        self.col = col
        self.targets = []
        self.team = team
        if (self.row == 7):
            self.direction = -1
        else:
            self.direction = 1
        self.touched = False
        self.critical = False
        self.godSaveTheKing = []

    def bladeWalker(self, checkerTown, dir1, dir2, row, col):
        if (row + dir1 >= 0 and row + dir1 <= 7 and col + dir2 >= 0 and col + dir2 <= 7):
            if (checkerTown[row + dir1][col + dir2] == None):
                self.targets.append(Cell(row + dir1, col + dir2))
            elif (checkerTown[row + dir1][col + dir2].team != self.team):
                self.targets.append(Cell(row + dir1, col + dir2))

    def calcTargets(self, checkerTown):
        self.targets = []
        #Run a recurssive function in all directions
        self.bladeWalker(checkerTown, 1, 1, self.row, self.col)
        self.bladeWalker(checkerTown, -1, 1, self.row, self.col)
        self.bladeWalker(checkerTown, 1, -1, self.row, self.col)
        self.bladeWalker(checkerTown, -1, -1, self.row, self.col)
        self.bladeWalker(checkerTown, 1, 0, self.row, self.col)
        self.bladeWalker(checkerTown, -1, 0, self.row, self.col)
        self.bladeWalker(checkerTown, 0, 1, self.row, self.col)
        self.bladeWalker(checkerTown, 0, -1, self.row, self.col)

        #store variables for King's original position and such
        oldRow = self.row
        oldCol = self.col

        #castling situation
        if (self.touched == False):
            if (isinstance(checkerTown[self.row][self.col - 4], Rook) and checkerTown[self.row][self.col - 4].touched == False):
                if (checkerTown[self.row][self.col - 1] == None and checkerTown[self.row][self.col - 2] == None and checkerTown[self.row][self.col - 3] == None):
                    self.targets.append(Cell(self.row, self.col - 2))
            if (isinstance(checkerTown[self.row][self.col + 3], Rook) and checkerTown[self.row][self.col + 3].touched == False):
                if (checkerTown[self.row][self.col + 1] == None and checkerTown[self.row][self.col + 2] == None):
                    self.targets.append(Cell(self.row, self.col + 2))

        #now that all targets have been calculated, iterate through them all and
        #check amIGonnaDie() with a board and position changed
        targetsToRemove = []

        castleLeft = False;
        castleLeftStep = True;
        castleRight = False;
        castleRightStep = True;
        castleLeftCell = Cell(-1, -1)
        castleRightCell = Cell(-1, -1)

        for cell in self.targets:
            if (cell.row == oldRow and cell.col == (oldCol - 2)):
                castleLeft = True
                castleLeftCell = cell
            if (cell.row == oldRow and cell.col == (oldCol + 2)):
                castleRight = True
                castleRightCell = cell
            originalPiece = checkerTown[cell.row][cell.col]
            checkerTown[cell.row][cell.col] = self
            checkerTown[self.row][self.col] = None
            self.row = cell.row
            self.col = cell.col
            threat1, threat2 = self.amIGonnaDie(checkerTown)
            if (threat1 != -1 and threat2 != -1):
                if (cell.row == oldRow and cell.col == (oldCol - 2)):
                    castleLeft = False
                if (cell.row == oldRow and cell.col == (oldCol + 2)):
                    castleRight = False

                if (cell.row == oldRow and cell.col == (oldCol - 1)):
                    castleLeftStep = False
                if (cell.row == oldRow and cell.col == (oldCol + 1)):
                    castleRightStep = False
                targetsToRemove.append(cell)

            #reset the board to its original config
            checkerTown[oldRow][oldCol] = self
            checkerTown[cell.row][cell.col] = originalPiece
            self.row = oldRow
            self.col = oldCol

        if (castleLeft == True and castleLeftStep == False):
            self.targets.remove(castleLeftCell)
        if (castleRight == True and castleRightStep == False):
            self.targets.remove(castleRightCell)
        #now iterate through targetsToRemove and remove them from targets
        for toRemove in targetsToRemove:
            self.targets.remove(toRemove)

        #re-run amIGonnaDie with the King's original values
        useless1, useless2 = self.amIGonnaDie(checkerTown)
        if (useless1 != -1 and useless2 != -1):
            return True
        else:
            return False

    def getValue(self, board):
        return 1000

    def move(self, newRow, newCol):
    # calculate new targets
        oldRow = self.row
        oldCol = self.col
        self.row = newRow
        self.col = newCol
        self.touched = True
        #check if castled
        if (newRow == oldRow and newCol == oldCol - 2):
            return Cell(oldRow, oldCol - 4), Cell(oldRow, oldCol - 1)
        elif (newRow == oldRow and newCol == oldCol + 2):
            return Cell(oldRow, oldCol + 3), Cell(oldRow, oldCol + 1)
        else:
            return None, None

    def amIGonnaDie(self, checkerTown):
        #check if I am in check
        #there are 8 possible directions that could be hindering me, plus knights
        #check perpindicular directions for rooks and queens, and kings for one space

        #iterate over the entire board and set every piece to not critical
        for row in checkerTown:
            for piece in row:
                if (piece != None and piece.team == self.team):
                    piece.critical = False

        #checking diagonally to the upper right (or 1,1 direction)
        for i in ([-1,0,1]):
            for j in ([-1,0,1]):
                if (i == 0 and j == 0):
                    continue

                enemyRow, enemyCol, scoutRow, scoutCol = self.iSpy(checkerTown, self.row + i, self.col + j, i, j)

                if (i == 0 or j == 0):
                    if (scoutRow != -1):
                        if (enemyRow != -1):
                            #scout found an enemy piece
                            #check if it is a perpindicular moving piece making the scout critical
                            if (isinstance(checkerTown[enemyRow][enemyCol], Rook) or isinstance(checkerTown[enemyRow][enemyCol], Queen)):
                                #scout is critical, mark him as such
                                checkerTown[scoutRow][scoutCol].critical = True
                                checkerTown[scoutRow][scoutCol].criticalTargets = self.pleaseGodSaveTheKing(enemyRow, enemyCol)
                    elif (enemyRow != -1):
                        if (isinstance(checkerTown[enemyRow][enemyCol], Rook) or isinstance(checkerTown[enemyRow][enemyCol], Queen)):
                            #enemy placing the king in check has been found
                            #return its location
                            self.godSaveTheKing = self.pleaseGodSaveTheKing(enemyRow, enemyCol)
                            return enemyRow, enemyCol
                        elif (isinstance(checkerTown[enemyRow][enemyCol], King)):
                            if ((abs(enemyRow - self.row) + abs(enemyCol - self.col)) == 1):
                                #enemy is a king one spot away so it could hypothetically put the king in check
                                self.godSaveTheKing = self.pleaseGodSaveTheKing(enemyRow, enemyCol)
                                return enemyRow, enemyCol
                else:
                    if (scoutRow != -1):
                        if (enemyRow != -1):
                            #scout found an enemy piece
                            #check if it is a diagonal moving piece making the scout critical
                            if (isinstance(checkerTown[enemyRow][enemyCol], Bishop) or isinstance(checkerTown[enemyRow][enemyCol], Queen)):
                                #scout is critical, mark him as such
                                checkerTown[scoutRow][scoutCol].critical = True
                                checkerTown[scoutRow][scoutCol].criticalTargets = self.pleaseGodSaveTheKing(enemyRow, enemyCol)
                    elif (enemyRow != -1):
                        if (isinstance(checkerTown[enemyRow][enemyCol], Bishop) or isinstance(checkerTown[enemyRow][enemyCol], Queen)):
                            #enemy placing the king in check has been found
                            #return its location
                            self.godSaveTheKing = self.pleaseGodSaveTheKing(enemyRow, enemyCol)
                            return enemyRow, enemyCol
                        elif (isinstance(checkerTown[enemyRow][enemyCol], King)):
                            if ((abs(enemyRow - self.row) + abs(enemyCol - self.col)) == 2):
                                #enemy is a king one spot away so it could hupothetically put the king in check
                                self.godSaveTheKing = self.pleaseGodSaveTheKing(enemyRow, enemyCol)
                                return enemyRow, enemyCol
                        elif (isinstance(checkerTown[enemyRow][enemyCol], Pawn)):
                            if ((enemyRow - self.row) == self.direction):
                                self.godSaveTheKing = self.pleaseGodSaveTheKing(enemyRow, enemyCol)
                                return enemyRow, enemyCol

        rowTargets = [2, 2, -2, -2, 1, 1, -1, -1]
        colTargets = [1, -1, 1, -1, 2, -2, 2, -2]
        for i in range(0, 8):
            knightRow, knightCol = self.knightInShiningArmor(checkerTown, rowTargets[i], colTargets[i], self.row, self.col)
            if (knightRow != -1 and knightCol != -1):
                self.godSaveTheKing = [Cell(knightRow, knightCol)]
                return knightRow, knightCol

        return -1, -1



    def iSpy(self, checkerTown, currentRow, currentCol, dir1, dir2):
        nextLoc = False
        if (currentRow + dir1 >= 0 and currentRow + dir1 < 8 and currentCol + dir2 >= 0 and currentCol + dir2 < 8):
            nextLoc = True
        if (currentRow >= 0 and currentRow < 8 and currentCol >= 0 and currentCol < 8):
            if (checkerTown[currentRow][currentCol] != None):
                if (checkerTown[currentRow][currentCol].team != self.team):
                    #enemy piece encountered
                    return currentRow, currentCol, -1, -1
                elif (nextLoc):
                    scoutRow, scoutCol = checkerTown[currentRow][currentCol].Kingsman(checkerTown, currentRow + dir1, currentCol + dir2, dir1, dir2)
                    return scoutRow, scoutCol, currentRow, currentCol
            elif (nextLoc):
                return1, return2, return3, return4 = self.iSpy(checkerTown, currentRow + dir1, currentCol + dir2, dir1, dir2)
                return return1, return2, return3, return4
        return -1, -1, -1, -1


    def knightInShiningArmor(self, checkerTown, dir1, dir2, row, col):
        if (row + dir1 >= 0 and row + dir1 <= 7 and col + dir2 >= 0 and col + dir2 <= 7):
            if (isinstance(checkerTown[row + dir1][col + dir2], Knight) and checkerTown[row + dir1][col + dir2].team != self.team):
                return (row + dir1), (col + dir2)
        return -1, -1

    def pleaseGodSaveTheKing(self, enemyRow, enemyCol):
        dir1, dir2 = self.determineDirectionFromEnemyTowardsKing(enemyRow, enemyCol)
        saveTheKing = []
        while (not (enemyRow == self.row and enemyCol == self.col)):
            saveTheKing.append(Cell(enemyRow, enemyCol))
            enemyRow = enemyRow + dir1
            enemyCol = enemyCol + dir2
        return saveTheKing


    def determineDirectionFromEnemyTowardsKing(self, enemyRow, enemyCol):
        if (enemyRow == self.row):
            return 0, -1 * (enemyCol - self.col) / abs(enemyCol - self.col)
        elif (enemyCol == self.col):
            return -1 * (enemyRow - self.row) / abs(enemyRow - self.row), 0
        else:
            return -1 * (enemyRow - self.row) / abs(enemyRow - self.row), -1 * (enemyCol - self.col) / abs(enemyCol - self.col)



#Overwrite default print with special King print
    def printPiece(self):
        print("King at", self.row ,"," , self.col)
