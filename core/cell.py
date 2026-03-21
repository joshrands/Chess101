from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Cell:
    row: int = 0
    col: int = 0
