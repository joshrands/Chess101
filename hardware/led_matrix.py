from __future__ import annotations

from abc import ABC, abstractmethod


class LEDDisplay(ABC):
    """Interface for rendering to an 8x8 RGB LED matrix."""

    @abstractmethod
    def set_pixel(self, x: int, y: int, r: int, g: int, b: int) -> None:
        """Set a single pixel on the canvas."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """Clear the canvas."""
        ...

    @abstractmethod
    def swap(self) -> None:
        """Swap the canvas to the display (VSync)."""
        ...
