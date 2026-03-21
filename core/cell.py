from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Cell:
    """Immutable (row, col) coordinate used to represent a board square or move target.

    Attributes:
        row: Zero-based row index (0 = team_r back rank, 7 = team_l back rank).
        col: Zero-based column index (0–7).
    """

    row: int = 0
    col: int = 0
