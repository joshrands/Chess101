"""Lobby menu for the physical Chess101 board.

Two-level binary decision tree:
  Level 1: Local (amber) vs Network (rain)
  Level 2: Host (2,0) vs Join (5,0)
"""
from __future__ import annotations

import random
import time

AMBER_LIT = (160, 105, 25)
AMBER_DARK = (10, 7, 2)
GREEN_LIT = (0, 55, 18)
GREEN_DARK = (0, 10, 4)

RAIN_COL_OFFSETS = [0.0, -0.5, -1.1, -0.3, 0.0, -0.7, -1.3, -0.4]
RAIN_PERIOD = 2.4
RAIN_ROW_DELAY = 0.15


def is_checker(row: int, col: int) -> bool:
    return (row + col) % 2 == 0


def amber_color(row: int, col: int) -> tuple[int, int, int]:
    return AMBER_LIT if is_checker(row, col) else AMBER_DARK


def green_color(row: int, col: int) -> tuple[int, int, int]:
    return GREEN_LIT if is_checker(row, col) else GREEN_DARK


def rain_brightness(row: int, col: int, t: float) -> float:
    offset = RAIN_COL_OFFSETS[col] - row * RAIN_ROW_DELAY
    phase = ((t + offset) % RAIN_PERIOD + RAIN_PERIOD) % RAIN_PERIOD / RAIN_PERIOD
    if phase < 0.08:
        return 1.0
    if phase < 0.16:
        return 0.6
    if phase < 0.24:
        return 0.3
    if phase < 0.35:
        return 0.1
    return 0.0
