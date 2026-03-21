from __future__ import annotations

from core.constants import CellOccupancy
from hardware.sensor import BoardSensor


class SimSensor(BoardSensor):
    """Click-driven grid state for the Mac simulator — no physical hardware involved.

    The simulator updates cell occupancy directly via set_state() in response
    to mouse clicks instead of reading from I2C-connected Arduinos.
    """

    def __init__(self) -> None:
        """Initialize all 64 cells to EMPTY."""
        self._grid: list[list[CellOccupancy]] = [
            [CellOccupancy.EMPTY] * 8 for _ in range(8)
        ]

    def read_data(self) -> None:
        """No-op — the simulator grid is always up-to-date in memory."""
        pass  # state is always fresh

    def get_cell_state(self, row: int, col: int) -> int:
        """Return the occupancy value for a single cell.

        Args:
            row: Board row (0–7).
            col: Board column (0–7).

        Returns:
            CellOccupancy value for the requested cell.
        """
        return self._grid[row][col]

    def set_state(self, row: int, col: int, occupancy: CellOccupancy) -> None:
        """Directly set a cell's occupancy (called by the simulator on mouse clicks).

        Args:
            row: Board row (0–7).
            col: Board column (0–7).
            occupancy: New CellOccupancy value to store.
        """
        self._grid[row][col] = occupancy
