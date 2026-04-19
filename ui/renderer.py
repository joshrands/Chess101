"""
ui/renderer.py — LED matrix rendering helpers for Chess101.

Functions here operate on an rgbmatrix canvas object and contain no
chess-logic or game-state dependencies.
"""
from __future__ import annotations


def light_cell(canvas, row: int, col: int, r: int, g: int, b: int) -> None:
    """Light a single 4×4 pixel cell at board position (row, col).

    Maps row to y (vertical) and col to x (horizontal) to match
    standard graphics convention where x=horizontal, y=vertical.
    """
    for di in range(4):
        for dj in range(4):
            canvas.SetPixel(col * 4 + dj, row * 4 + di, r, g, b)
