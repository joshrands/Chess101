"""Entry point for the Chess101 physical board game.

Starts an infinite game loop on the Raspberry Pi, creating a fresh Board
instance for each game and calling board.process() to run the full
color-selection → piece-setup → gameplay → end-screen lifecycle.
SIGINT and SIGTERM are caught so the loop exits cleanly after the current
game finishes rather than mid-frame.
"""
import logging
import signal
import sys

from game.board import Board

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_running = True


def _handle_signal(signum, frame):
    """Set the global stop flag on SIGINT or SIGTERM.

    Args:
        signum: Signal number received.
        frame: Current stack frame (unused).
    """
    global _running
    logger.info("Signal %s received — shutting down after current game.", signum)
    _running = False


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

while _running:
    board = Board()
    board.process()

logger.info("GameManager exited cleanly.")
sys.exit(0)
