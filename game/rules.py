"""
game/rules.py — Pure draw-detection logic for Chess101.

Functions here receive a Board instance as their first argument so they
can read/write game state (peace_time, game_over) and call
board.declare_stalemate().  They contain no direct hardware I/O.
"""
from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Board import Board
    from Piece import BoardGrid
    from Team import Team

logger = logging.getLogger(__name__)


def check_fifty_move_rule(board: Board, team: Team, board_state: BoardGrid) -> bool:
    """Return True and trigger stalemate if 50 half-moves have passed without a capture or pawn move.

    Note: The threshold is intentionally 50 half-moves rather than the standard
    100 (50 full moves). This is a known bug locked in by existing tests.

    If the fifty-move threshold has not been reached, delegates to
    ``check_threefold_repetition`` using the history lists that belong to
    ``team``.

    Args:
        board: The active game board; ``board.peace_time`` is read and
            ``board.game_over`` / ``board.declare_stalemate()`` may be set.
        team: The team whose turn it is, used to select the correct
            repetition-history lists.
        board_state: Snapshot of the current 8x8 board grid.

    Returns:
        True if the game ended due to the fifty-move rule or threefold
        repetition, False otherwise.
    """
    logger.debug("peace_time=%s", board.peace_time)
    if board.peace_time >= 50:
        board.game_over = True
        board.declare_stalemate()
        return True
    else:
        if team == board.team_l:
            return check_threefold_repetition(
                board, team, board_state,
                board.days_left_since_injury, board.double_left_jeopardy)
        else:
            return check_threefold_repetition(
                board, team, board_state,
                board.days_right_since_injury, board.double_right_jeopardy)


def check_threefold_repetition(
    board: Board,
    team: Team,
    board_state: BoardGrid,
    days_since_injury: list,
    double_jeopardy: list,
) -> bool:
    """Return True and trigger stalemate when the current position has occurred three times.

    Position equality is determined by piece type alone (``type(piece)``), not
    by team identity. This is a known bug locked in by existing tests.

    History is maintained across calls via the two mutable lists passed in by
    the caller.  When ``board.peace_time`` is 0 both lists are cleared and the
    current state is recorded as the first occurrence.

    Args:
        board: The active game board; ``board.game_over`` /
            ``board.declare_stalemate()`` may be set on repetition.
        team: The team whose turn it is (unused directly but provided for
            symmetry with ``check_fifty_move_rule``).
        board_state: Snapshot of the current 8x8 board grid.
        days_since_injury: Mutable list of board-state snapshots recorded
            since the last capture or pawn move (first-occurrence pool).
        double_jeopardy: Mutable list of board-state snapshots that have
            already matched once (second-occurrence pool).

    Returns:
        True if the game ended due to threefold repetition, False otherwise.
    """
    if board.peace_time == 0:
        days_since_injury.clear()
        double_jeopardy.clear()
        days_since_injury.append(copy.deepcopy(board_state))
    else:
        second_match = False
        for state in double_jeopardy:
            second_match = True
            for row in range(8):
                for col in range(8):
                    if not type(state[row][col]) is type(board_state[row][col]):
                        second_match = False
                        break
                if not second_match:
                    break
            if second_match:
                break
        if second_match:
            board.game_over = True
            board.declare_stalemate()
            return True
        else:
            first_match = False
            for state in days_since_injury:
                first_match = True
                for row in range(8):
                    for col in range(8):
                        if not type(state[row][col]) is type(board_state[row][col]):
                            first_match = False
                            break
                    if not first_match:
                        break
                if first_match:
                    break
            if first_match:
                double_jeopardy.append(copy.deepcopy(board_state))
            else:
                days_since_injury.append(copy.deepcopy(board_state))
    return False
