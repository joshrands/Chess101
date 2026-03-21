import logging
import signal
import sys

from game.board import Board

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_running = True


def _handle_signal(signum, frame):
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
