"""Entry point for the Chess101 physical board game.

Starts an infinite game loop on the Raspberry Pi, creating a fresh Board
(or NetworkedBoard) instance for each game and calling board.process() to
run the full color-selection → piece-setup → gameplay → end-screen lifecycle.
SIGINT and SIGTERM are caught so the loop exits cleanly after the current
game finishes rather than mid-frame.

Networked play
~~~~~~~~~~~~~~
  sudo python3 GameManager.py --host              # Host, wait for a Sim to join
  sudo python3 GameManager.py --join 192.168.1.42  # Join a Sim host at given IP
  sudo python3 GameManager.py --host --port 65200  # Custom port
"""
import argparse
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


def _build_board(args) -> Board:
    """Instantiate the right Board subclass based on CLI flags.

    Args:
        args: Parsed argparse namespace.

    Returns:
        A ``NetworkedBoard`` if ``--host`` or ``--join`` was given, otherwise
        a plain ``Board``.
    """
    if args.host or args.join:
        # Inject stub smbus before importing game code that may import it
        import sys
        import types
        if "smbus" not in sys.modules:
            _smbus = types.ModuleType("smbus")
            class _SMBus:
                def __init__(self, *a, **kw):   pass
                def read_byte(self, *a, **kw):  return 0
                def write_byte(self, *a, **kw): pass
            _smbus.SMBus = _SMBus
            sys.modules["smbus"] = _smbus

        from game.networked_board import NetworkedBoard
        from network.server import GameServer
        from network.client import GameClient

        if args.host:
            net = GameServer(port=args.port)
            board = NetworkedBoard(net=net, local_team_key="r")
            net.on_connected    = board.on_connected
            net.on_disconnected = board.on_disconnected
            net.start()
            logger.info("Hosting on port %d — waiting for opponent...", args.port)
        else:
            net = GameClient(host_ip=args.join, port=args.port)
            board = NetworkedBoard(net=net, local_team_key="l")
            net.on_connected    = board.on_connected
            net.on_disconnected = board.on_disconnected
            connected = net.connect(timeout=15.0)
            if not connected:
                logger.error("Could not connect to %s:%d", args.join, args.port)
                sys.exit(1)

        return board

    return Board()


def main():
    parser = argparse.ArgumentParser(description="Chess101 physical board game")
    parser.add_argument("--host",  action="store_true",
                        help="Host a networked game (Pi is team_r)")
    parser.add_argument("--join",  metavar="IP",
                        help="Join a networked game at the given IP (Pi is team_l)")
    parser.add_argument("--port",  type=int, default=65101,
                        help="WebSocket port (default 65101)")
    # Pass remaining unknown args through to samplebase / LED matrix flags
    args, _unknown = parser.parse_known_args()

    global _running
    while _running:
        board = _build_board(args)
        board.process()

    logger.info("GameManager exited cleanly.")
    sys.exit(0)


if __name__ == "__main__":
    main()
