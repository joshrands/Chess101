from __future__ import annotations

from abc import ABC, abstractmethod


class BoardSensor(ABC):
    """Interface for reading physical piece positions from the board hardware."""

    @abstractmethod
    def get_cell_state(self, row: int, col: int) -> int:
        """Return 0 if a piece is present, 1 if the cell is empty."""
        ...

    @abstractmethod
    def read_data(self) -> None:
        """Poll all rows and update internal state."""
        ...
