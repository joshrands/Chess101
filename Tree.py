#Basic tree structure for holding the score/children of each node

class Tree(object):
    def __init__(self, boardState, oldCell = None, newCell = None):
        self.children = []
        self.boardState = boardState

        #Instead of tracking the piece that's moving, just track the cells and handle it appropriately further up
        self.oldCell = oldCell
        self.newCell = newCell

    def addChild(self, child):
    	assert ininstance(child, Tree)
    	self.children.append(child)

    def getBoardState(self):
    	return self.boardState

    #Heuristic function, for now this will work until the tree is fully made
    def getUtility(self):
    	return 5
