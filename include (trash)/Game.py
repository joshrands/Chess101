'''
Game
Description: Create a new game
Author(s): Josh Rands
'''
#import sys
#sys.path.append('../include')

import Board
import Piece

class Game:

	def __init__(self, pawn):
		self.pawn = Piece(0, 1, "Pawn", [])

game = Game()
game.pawn.print()
	
