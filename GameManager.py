# GameManager class

from Board import Board

class GameManager:

    def __init__(self):
        # make stuff
        print("Hello world!")
        self.board = Board()

    def startGame(self):
        self.board.process()

#    def setGameProperties():

game = GameManager()
while True:
    game.startGame()
    again = raw_input("Do you want to play again? (y/n)")
    if (again == "y") break;
