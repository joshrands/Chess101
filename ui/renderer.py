"""
ui/renderer.py — LED matrix rendering helpers for Chess101.

Functions here operate on an rgbmatrix canvas object and contain no
chess-logic or game-state dependencies.
"""
from __future__ import annotations


def light_cell(canvas, x: int, y: int, r: int, g: int, b: int) -> None:
    """Light a single 4×4 pixel cell at board position (x, y)."""
    for i in range(4):
        for j in range(4):
            canvas.SetPixel(x * 4 + i, y * 4 + j, r, g, b)
