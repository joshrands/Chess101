from __future__ import annotations

from core.constants import CellOccupancy
from hardware.sensor import BoardSensor


class SimSensor(BoardSensor):
    """Click-driven grid state — no hardware involved."""

    def __init__(self) -> None:
        self._grid: list[list[CellOccupancy]] = [
            [CellOccupancy.EMPTY] * 8 for _ in range(8)
        ]

    def read_data(self) -> None:
        pass  # state is always fresh

    def get_cell_state(self, row: int, col: int) -> int:
        return self._grid[row][col]

    def set_state(self, row: int, col: int, occupancy: CellOccupancy) -> None:
        self._grid[row][col] = occupancy
