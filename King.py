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

        #castling situation
        if (self.touched == False):
            if (isinstance(checkerTown[self.row][self.col - 4], Rook) and checkerTown[self.row][self.col - 4].touched == False):
                if (checkerTown[self.row][self.col - 1] == None and checkerTown[self.row][self.col - 2] == None and checkerTown[self.row][self.col - 3] == None):
                    self.targets.append(Cell(self.row, self.col - 2))
            if (isinstance(checkerTown[self.row][self.col + 3], Rook) and checkerTown[self.row][self.col + 3].touched == False):
                if (checkerTown[self.row][self.col + 1] == None and checkerTown[self.row][self.col + 2] == None):
                    self.targets.append(Cell(self.row, self.col + 2))

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
                    elif (enemyRow != -1):
                        if (isinstance(checkerTown[enemyRow][enemyCol], Rook) or isinstance(checkerTown[enemyRow][enemyCol], Queen)):
                            #enemy placing the king in check has been found
                            #return its location
                            print("ello 1")
                            return enemyRow, enemyCol
                        elif (isinstance(checkerTown[enemyRow][enemyCol], King)):
                            if ((abs(enemyRow - self.row) + abs(enemyCol - self.col)) == 1):
                                #enemy is a king one spot away so it could hypothetically put the king in check
                                print("ello 2")
                                return enemyRow, enemyCol
                else:
                    if (scoutRow != -1):
                        if (enemyRow != -1):
                            #scout found an enemy piece
                            #check if it is a diagonal moving piece making the scout critical
                            if (isinstance(checkerTown[enemyRow][enemyCol], Bishop) or isinstance(checkerTown[enemyRow][enemyCol], Queen)):
                                #scout is critical, mark him as such
                                checkerTown[scoutRow][scoutCol].critical = True
                    elif (enemyRow != -1):
                        if (isinstance(checkerTown[enemyRow][enemyCol], Bishop) or isinstance(checkerTown[enemyRow][enemyCol], Queen)):
                            #enemy placing the king in check has been found
                            #return its location
                            print("ello 3")
                            return enemyRow, enemyCol
                        elif (isinstance(checkerTown[enemyRow][enemyCol], King)):
                            if ((abs(enemyRow - self.row) + abs(enemyCol - self.col)) == 2):
                                #enemy is a king one spot away so it could hupothetically put the king in check
                                print("ello 4")
                                return enemyRow, enemyCol
                        elif (isinstance(checkerTown[enemyRow][enemyCol], Pawn)):
                            if ((enemyRow - self.row) == self.direction):
                                print("ello 5")
                                return enemyRow, enemyCol

        rowTargets = [2, 2, -2, -2, 1, 1, -1, -1]
        colTargets = [1, -1, 1, -1, 2, -2, 2, -2]
        for i in range(0, 8):
            knightRow, knightCol = self.knightInShiningArmor(checkerTown, rowTargets[i], colTargets[i], self.row, self.col)
            if (knightRow != -1 and knightCol != -1):
                print("ello 6")
                return knightRow, knightCol

        print("ello 7")
        return -1, -1



    def iSpy(self, checkerTown, currentRow, currentCol, dir1, dir2):
        print("What do I spy, with my little eye?")
        nextLoc = False
        if (currentRow + dir1 >= 0 and currentRow + dir1 < 8 and currentCol + dir2 >= 0 and currentCol + dir2 < 8):
            nextLoc = True
        if (currentRow >= 0 and currentRow < 8 and currentCol >= 0 and currentCol < 8):
            print("Checking", currentRow,",",currentCol)
            if (checkerTown[currentRow][currentCol] != None):
                if (checkerTown[currentRow][currentCol].team != self.team):
                    #enemy piece encountered
                    print("Ho! An enemy afar!")
                    return currentRow, currentCol, -1, -1
                elif (nextLoc):
                    print("Ho, boy! Look for an enemy there behind yourself, won't you?")
                    scoutRow, scoutCol = checkerTown[currentRow][currentCol].Kingsman(checkerTown, currentRow + dir1, currentCol + dir2, dir1, dir2)
                    return scoutRow, scoutCol, currentRow, currentCol
            elif (nextLoc):
                print("I must search farther!")
                return1, return2, return3, return4 = self.iSpy(checkerTown, currentRow + dir1, currentCol + dir2, dir1, dir2)
                return return1, return2, return3, return4
        return -1, -1, -1, -1


    def knightInShiningArmor(self, checkerTown, dir1, dir2, row, col):
        if (row + dir1 >= 0 and row + dir1 <= 7 and col + dir2 >= 0 and col + dir2 <= 7):
            if (isinstance(checkerTown[row + dir1][col + dir2], Knight) and checkerTown[row + dir1][col + dir2].team != self.team):
                return (row + dir1), (col + dir2)
        return -1, -1


#Overwrite default print with special King print
    def printPiece(self):
        print("King at", self.row ,"," , self.col)


#test the check features of the king
grid = []
for row in range(0, 8):
    grid.append([None, None, None, None, None, None, None, None])

teamL = Team(255, 0, 0)
teamL.name = "Zach Test L"

teamR = Team(0, 255, 0)
teamR.name = "Zach Test R"

#place pieces that let us check the many king functionality
#can attack directly
#grid[6][6] = Bishop(6,6,teamL)
#can attack directly but only one always
#grid[0][1] = King(0,1,teamL)
#our king that we see if is in check
grid[1][1] = King(1,1,teamR)
#can attack from far
#grid[4][1] = Queen(4,1,teamL)
#critical piece
#grid[2][1] = Knight(2,1,teamR)
#critical piece
#grid[2][2] = Bishop(2,2,teamR)
#enemy behind above
#grid[4][4] = Bishop(4,4,teamL)
#can attack like a knight
grid[3][0] = Knight(3,0,teamL)

#check for check
att1, att2 = grid[1][1].amIGonnaDie(grid)
if (att1 == -1 and att2 == -1):
    print("King is not in check")
else:
    print("King is in check from ")
    grid[att1][att2].printPiece()
