from Team import Team
from Piece import Piece

#Basic tree structure for holding the score/children of each node

class Tree(object):
    def __init__(self, boardState, oldCell, newCell, teamR, teamL):
        self.children = []
        self.boardState = boardState

        #Instead of tracking the piece that's moving, just track the cells and handle it appropriately further up
        self.oldCell = oldCell
        self.newCell = newCell
        #white is right
        self.teamR = Team(teamR.r, teamR.g, teamR.b)
        self.teamL = Team(teamL.r, teamL.g, teamL.b)

    def addChild(self, child):
    	self.children.append(child)

    def getBoardState(self):
    	return self.boardState

    #Heuristic function, for now this will work until the tree is fully made
    def getUtility(self, team):
        whiteCount = 0
        blackCount = 0
        for r in range(0,8):
            for piece in self.boardState[r]:
                if (piece == None):
                    continue
                elif (piece.team.r ==  self.teamR.r):
                    whiteCount += piece.getValue(self.boardState)
                else:
                    blackCount += piece.getValue(self.boardState)

        #print("White piece value is " + str(whiteCount))
        #print("Black piece value is " + str(blackCount))


        total = whiteCount-blackCount
        if (team.r == 255):
            total = -total
       #    will be used for testing once we integrate AI into actual game
       #    print("Blacks move")
#        input("press enter to continue.. the value of this board is " + str(total))

        return total
