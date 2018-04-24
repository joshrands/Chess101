from Team import Team
from Piece import Piece

#Basic tree structure for holding the score/children of each node

class Tree(object):
    def __init__(self, boardState, oldCell = None, newCell = None):
        self.children = []
        self.boardState = boardState

        #Instead of tracking the piece that's moving, just track the cells and handle it appropriately further up
        self.oldCell = oldCell
        self.newCell = newCell
        #white is right
        self.teamR = Team(64, 180, 232)
        self.teamL = Team(255, 140, 0)

    def addChild(self, child):
    	self.children.append(child)

    def getBoardState(self):
    	return self.boardState

    #Heuristic function, for now this will work until the tree is fully made
    def getUtility(self):
        whiteCount = 0
        blackCount = 0
        for r in range(0,8):
            for piece in self.boardState[r]:
                if (piece == None):
                    continue
                elif (piece.team == self.teamR):
                    whiteCount += piece.getValue()
                else:
                    blackCount += piece.getValue()
        total = whiteCount-blackCount
        return total
