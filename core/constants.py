from enum import IntEnum


class PieceValue(IntEnum):
    PAWN   = 5
    KNIGHT = 13
    BISHOP = 15
    ROOK   = 27
    QUEEN  = 49
    KING   = 1000


class CellOccupancy(IntEnum):
    OCCUPIED = 0   # piece is physically present on the square
    EMPTY    = 1   # no piece on the square
