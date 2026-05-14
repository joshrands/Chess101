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


def monotonic_random_path(
    from_r: int, from_c: int, to_r: int, to_c: int,
    exclude: tuple[int, int],
) -> list[tuple[int, int]]:
    steps: list[tuple[int, int]] = []
    r, c = from_r, from_c
    rows_left = abs(to_r - from_r)
    cols_left = abs(to_c - from_c)
    row_dir = 1 if to_r > from_r else (-1 if to_r < from_r else 0)
    col_dir = 1 if to_c > from_c else (-1 if to_c < from_c else 0)

    if (r, c) != exclude:
        steps.append((r, c))

    while rows_left > 0 or cols_left > 0:
        if rows_left > 0 and cols_left > 0:
            if random.random() < 0.5:
                r += row_dir
                rows_left -= 1
            else:
                c += col_dir
                cols_left -= 1
        elif rows_left > 0:
            r += row_dir
            rows_left -= 1
        else:
            c += col_dir
            cols_left -= 1

        if (r, c) != exclude:
            steps.append((r, c))

    return steps


SIGNAL_TRAIL_BRIGHTNESSES = [1.0, 0.5, 0.2]


def add_signal_trail(
    colors: dict[tuple[int, int], tuple[int, int, int]],
    path: list[tuple[int, int]],
    step_idx: int,
    trail_len: int = 3,
) -> None:
    for ti in range(trail_len):
        idx = step_idx - ti
        if 0 <= idx < len(path):
            b = SIGNAL_TRAIL_BRIGHTNESSES[ti]
            val = int(255 * b)
            colors[path[idx]] = (val, val, val)
