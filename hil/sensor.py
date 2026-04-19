"""Thread-safe board sensor for HIL testing.

HilSensor implements the BoardSensor ABC with external injection points
so tests can simulate piece lifts and placements via the control server.
"""
from __future__ import annotations

from threading import Lock

from core.constants import CellOccupancy
from hardware.sensor import BoardSensor


class HilSensor(BoardSensor):
    """Programmatically-controlled sensor for HIL testing.

    Thread-safe implementation that allows external code to inject reed
    switch state changes while the game loop polls get_cell_state().
    """

    def __init__(self) -> None:
        """Initialize all 64 cells to EMPTY."""
        self._grid: list[list[int]] = [
            [CellOccupancy.EMPTY] * 8 for _ in range(8)
        ]
        self._lock = Lock()

    def read_data(self) -> None:
        """No-op - state is set externally via inject_state()."""
        pass

    def get_cell_state(self, row: int, col: int) -> int:
        """Return the occupancy value for a single cell.

        Transposes the lookup (col, row) to align physical reed switch layout
        with the corrected visual rendering.

        Args:
            row: Board row (0-7).
            col: Board column (0-7).

        Returns:
            0 if piece present, 1 if empty.
        """
        with self._lock:
            return self._grid[col][row]

    def inject_state(self, row: int, col: int, occupied: bool) -> None:
        """External control point - set a cell's occupancy.

        Called by ControlServer to simulate piece lift/place events.
        Transposes (col, row) to match get_cell_state() transposition.

        Args:
            row: Board row (0-7).
            col: Board column (0-7).
            occupied: True if piece present, False if empty.
        """
        with self._lock:
            self._grid[col][row] = (
                CellOccupancy.OCCUPIED if occupied else CellOccupancy.EMPTY
            )

    def set_starting_position(self) -> None:
        """Set reed switches to standard chess starting position.

        Pieces on rows 0-1 (team_r) and 6-7 (team_l), empty middle.
        Stores transposed to match get_cell_state() transposition.
        """
        with self._lock:
            for r in range(8):
                for c in range(8):
                    # Store at [col][row] to match transposition
                    self._grid[c][r] = (
                        CellOccupancy.OCCUPIED if r in (0, 1, 6, 7)
                        else CellOccupancy.EMPTY
                    )

    def get_grid_snapshot(self) -> list[list[int]]:
        """Return a copy of the current grid state in logical (row, col) order.

        Internal storage is transposed (col, row) to match get_cell_state.
        This method un-transposes for external API consumption.

        Returns:
            8x8 list of occupancy values (0=piece, 1=empty), indexed [row][col].
        """
        with self._lock:
            return [[self._grid[c][r] for c in range(8)] for r in range(8)]
