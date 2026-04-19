"""Scripted HIL test scenarios.

Predefined sequences of reed switch events and expected LED states for
regression testing the hardware code path.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Generator, Tuple


class ActionType(Enum):
    """Types of actions in a scenario."""
    LIFT = auto()      # Lift piece from cell
    PLACE = auto()     # Place piece on cell
    WAIT = auto()      # Wait for N frames
    EXPECT = auto()    # Assert LED state


@dataclass
class Action:
    """A single action in a scenario."""
    type: ActionType
    row: int = 0
    col: int = 0
    frames: int = 0
    description: str = ""


def color_picker_team_r(color_idx: int = 0) -> Generator[Action, None, None]:
    """Select team_r's color in the color picker phase.

    Args:
        color_idx: Index of color to select (0-7, left to right on row 2).

    Yields:
        Actions to select the color.
    """
    yield Action(ActionType.WAIT, frames=10, description="Wait for color picker to render")
    yield Action(ActionType.PLACE, row=2, col=color_idx, description=f"Select color {color_idx} for team_r")
    yield Action(ActionType.WAIT, frames=5, description="Wait for selection to register")
    yield Action(ActionType.LIFT, row=2, col=color_idx, description="Release piece")


def color_picker_team_l(color_idx: int = 1) -> Generator[Action, None, None]:
    """Select team_l's color in the color picker phase.

    Args:
        color_idx: Index of color to select (0-7, left to right on row 5).

    Yields:
        Actions to select the color.
    """
    yield Action(ActionType.WAIT, frames=10, description="Wait for team_l's turn")
    yield Action(ActionType.PLACE, row=5, col=color_idx, description=f"Select color {color_idx} for team_l")
    yield Action(ActionType.WAIT, frames=5, description="Wait for selection to register")
    yield Action(ActionType.LIFT, row=5, col=color_idx, description="Release piece")


def war_games_both_human() -> Generator[Action, None, None]:
    """Select Human for both teams in war_games phase.

    Human option is columns 0-3, Computer is columns 4-7.
    team_r uses row 3, team_l uses row 4.
    """
    yield Action(ActionType.WAIT, frames=10, description="Wait for war_games to render")
    # team_r selects Human (col 0)
    yield Action(ActionType.PLACE, row=3, col=0, description="team_r selects Human")
    yield Action(ActionType.WAIT, frames=5)
    yield Action(ActionType.LIFT, row=3, col=0)
    yield Action(ActionType.WAIT, frames=10)
    # team_l selects Human (col 0)
    yield Action(ActionType.PLACE, row=4, col=0, description="team_l selects Human")
    yield Action(ActionType.WAIT, frames=5)
    yield Action(ActionType.LIFT, row=4, col=0)


def war_games_both_ai() -> Generator[Action, None, None]:
    """Select Computer for both teams in war_games phase."""
    yield Action(ActionType.WAIT, frames=10, description="Wait for war_games to render")
    # team_r selects Computer (col 4)
    yield Action(ActionType.PLACE, row=3, col=4, description="team_r selects Computer")
    yield Action(ActionType.WAIT, frames=5)
    yield Action(ActionType.LIFT, row=3, col=4)
    yield Action(ActionType.WAIT, frames=10)
    # team_l selects Computer (col 4)
    yield Action(ActionType.PLACE, row=4, col=4, description="team_l selects Computer")
    yield Action(ActionType.WAIT, frames=5)
    yield Action(ActionType.LIFT, row=4, col=4)


def setup_starting_position() -> Generator[Action, None, None]:
    """Place all pieces in starting position during interactive_setup.

    The Pi's interactive_setup waits for pieces to be placed one by one.
    This simulates placing all 32 pieces in the correct positions.
    """
    yield Action(ActionType.WAIT, frames=10, description="Wait for setup phase")

    # team_r back rank (row 0): Rook, Knight, Bishop, Queen, King, Bishop, Knight, Rook
    for col in range(8):
        yield Action(ActionType.PLACE, row=0, col=col, description=f"Place team_r back rank piece at (0, {col})")
        yield Action(ActionType.WAIT, frames=3)

    # team_r pawns (row 1)
    for col in range(8):
        yield Action(ActionType.PLACE, row=1, col=col, description=f"Place team_r pawn at (1, {col})")
        yield Action(ActionType.WAIT, frames=3)

    # team_l pawns (row 6)
    for col in range(8):
        yield Action(ActionType.PLACE, row=6, col=col, description=f"Place team_l pawn at (6, {col})")
        yield Action(ActionType.WAIT, frames=3)

    # team_l back rank (row 7)
    for col in range(8):
        yield Action(ActionType.PLACE, row=7, col=col, description=f"Place team_l back rank piece at (7, {col})")
        yield Action(ActionType.WAIT, frames=3)


def move_e2_e4() -> Generator[Action, None, None]:
    """Execute the move e2-e4 (1. e4).

    e2 is (6, 4), e4 is (4, 4) in our coordinate system.
    """
    yield Action(ActionType.LIFT, row=6, col=4, description="Lift pawn from e2")
    yield Action(ActionType.WAIT, frames=5)
    yield Action(ActionType.PLACE, row=4, col=4, description="Place pawn on e4")
    yield Action(ActionType.WAIT, frames=5)


def move_e7_e5() -> Generator[Action, None, None]:
    """Execute the move e7-e5 (1. ... e5).

    e7 is (1, 4), e5 is (3, 4) in our coordinate system.
    """
    yield Action(ActionType.LIFT, row=1, col=4, description="Lift pawn from e7")
    yield Action(ActionType.WAIT, frames=5)
    yield Action(ActionType.PLACE, row=3, col=4, description="Place pawn on e5")
    yield Action(ActionType.WAIT, frames=5)


def scholars_mate() -> Generator[Action, None, None]:
    """Execute Scholar's Mate (4-move checkmate).

    1. e4 e5  2. Qh5 Nc6  3. Bc4 Nf6  4. Qxf7#
    """
    # 1. e4
    yield from move_e2_e4()
    # 1. ... e5
    yield from move_e7_e5()

    # 2. Qh5 - Queen from d1 (7, 3) to h5 (3, 7)
    yield Action(ActionType.LIFT, row=7, col=3, description="Lift Queen from d1")
    yield Action(ActionType.WAIT, frames=5)
    yield Action(ActionType.PLACE, row=3, col=7, description="Place Queen on h5")
    yield Action(ActionType.WAIT, frames=10)

    # 2. ... Nc6 - Knight from b8 (0, 1) to c6 (2, 2)
    yield Action(ActionType.LIFT, row=0, col=1, description="Lift Knight from b8")
    yield Action(ActionType.WAIT, frames=5)
    yield Action(ActionType.PLACE, row=2, col=2, description="Place Knight on c6")
    yield Action(ActionType.WAIT, frames=10)

    # 3. Bc4 - Bishop from f1 (7, 5) to c4 (4, 2)
    yield Action(ActionType.LIFT, row=7, col=5, description="Lift Bishop from f1")
    yield Action(ActionType.WAIT, frames=5)
    yield Action(ActionType.PLACE, row=4, col=2, description="Place Bishop on c4")
    yield Action(ActionType.WAIT, frames=10)

    # 3. ... Nf6 - Knight from g8 (0, 6) to f6 (2, 5)
    yield Action(ActionType.LIFT, row=0, col=6, description="Lift Knight from g8")
    yield Action(ActionType.WAIT, frames=5)
    yield Action(ActionType.PLACE, row=2, col=5, description="Place Knight on f6")
    yield Action(ActionType.WAIT, frames=10)

    # 4. Qxf7# - Queen from h5 (3, 7) captures on f7 (1, 5)
    yield Action(ActionType.LIFT, row=3, col=7, description="Lift Queen from h5")
    yield Action(ActionType.WAIT, frames=5)
    yield Action(ActionType.LIFT, row=1, col=5, description="Remove captured pawn from f7")
    yield Action(ActionType.PLACE, row=1, col=5, description="Place Queen on f7 - CHECKMATE")
    yield Action(ActionType.WAIT, frames=30, description="Wait for checkmate animation")


def full_game_setup() -> Generator[Action, None, None]:
    """Complete game setup: color picker + war_games + piece placement."""
    yield from color_picker_team_r(color_idx=0)  # Blue
    yield from color_picker_team_l(color_idx=5)  # Orange
    yield from war_games_both_human()
    yield from setup_starting_position()


# Scenario registry for easy access
SCENARIOS = {
    "color_picker_team_r": color_picker_team_r,
    "color_picker_team_l": color_picker_team_l,
    "war_games_both_human": war_games_both_human,
    "war_games_both_ai": war_games_both_ai,
    "setup_starting_position": setup_starting_position,
    "move_e2_e4": move_e2_e4,
    "move_e7_e5": move_e7_e5,
    "scholars_mate": scholars_mate,
    "full_game_setup": full_game_setup,
}
