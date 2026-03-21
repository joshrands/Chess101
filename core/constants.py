from enum import IntEnum


class PieceValue(IntEnum):
    """Point values assigned to each chess piece type for AI evaluation.

    These values are used by ``Tree.get_utility()`` to compute material
    balance when scoring a board position.
    """

    PAWN   = 5
    KNIGHT = 13
    BISHOP = 15
    ROOK   = 27
    QUEEN  = 49
    KING   = 1000


class CellOccupancy(IntEnum):
    """Reed-switch sensor values reported by the Arduino rows over I2C.

    The polarity is inverted relative to intuition: a magnet (piece) closes
    the reed switch and pulls the line low, so ``OCCUPIED`` maps to ``0``.
    """

    OCCUPIED = 0   # piece is physically present on the square
    EMPTY    = 1   # no piece on the square
