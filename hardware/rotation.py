"""Board rotation utilities for physical hardware mounting.

When the LED matrix and reed switch array are mounted at a non-standard
orientation, use these transforms to rotate the coordinate system so the
game appears correctly to the player.

Rotation values are clockwise degrees: 0, 90, 180, or 270.
Use 270 for 90 degrees counter-clockwise.
"""
from __future__ import annotations

from typing import Callable, Tuple

# Pixel-space transforms (32x32 LED matrix)
PIXEL_ROTATIONS: dict[int, Callable[[int, int], Tuple[int, int]]] = {
    0:   lambda x, y: (x, y),
    90:  lambda x, y: (31 - y, x),
    180: lambda x, y: (31 - x, 31 - y),
    270: lambda x, y: (y, 31 - x),
}

# Cell-space transforms (8x8 board)
CELL_ROTATIONS: dict[int, Callable[[int, int], Tuple[int, int]]] = {
    0:   lambda r, c: (r, c),
    90:  lambda r, c: (7 - c, r),
    180: lambda r, c: (7 - r, 7 - c),
    270: lambda r, c: (c, 7 - r),
}


class RotatingCanvas:
    """Canvas wrapper that applies rotation transform to SetPixel calls.

    Wraps an rgbmatrix canvas (or FakeFrameCanvas) and intercepts SetPixel
    to rotate coordinates before passing to the underlying canvas.
    """

    def __init__(self, canvas, rotation: int = 0) -> None:
        """Initialize with a canvas and rotation angle.

        Args:
            canvas: The underlying canvas to wrap.
            rotation: Clockwise rotation in degrees (0, 90, 180, or 270).
        """
        self._canvas = canvas
        self._transform = PIXEL_ROTATIONS.get(rotation % 360, PIXEL_ROTATIONS[0])

    def SetPixel(self, x: int, y: int, r: int, g: int, b: int) -> None:
        """Set a pixel with rotation applied."""
        rx, ry = self._transform(x, y)
        self._canvas.SetPixel(rx, ry, r, g, b)

    def Clear(self) -> None:
        """Clear the canvas."""
        self._canvas.Clear()

    def __getattr__(self, name: str):
        """Forward unknown attributes to the wrapped canvas."""
        return getattr(self._canvas, name)


def rotate_cell(row: int, col: int, rotation: int) -> tuple[int, int]:
    """Transform a board cell coordinate by the given rotation.

    Args:
        row: Board row (0-7).
        col: Board column (0-7).
        rotation: Clockwise rotation in degrees (0, 90, 180, or 270).

    Returns:
        Rotated (row, col) tuple.
    """
    transform = CELL_ROTATIONS.get(rotation % 360, CELL_ROTATIONS[0])
    return transform(row, col)
