"""Lobby menu for the physical Chess101 board.

Two-level binary decision tree:
  Level 1: Local (amber) vs Network (rain)
  Level 2: Host (2,0) vs Join (5,0)
"""
from __future__ import annotations

import random
import time
from enum import Enum, auto

from core.constants import CellOccupancy

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


SPREAD_DURATION = 3.0


def _clamp(v: int) -> int:
    return max(0, min(255, v))


def spread_color(
    row: int, col: int, progress: float, chosen: str, t: float,
) -> tuple[int, int, int]:
    checker = is_checker(row, col)
    cols_taken = int(progress * 5)
    col_frac = (progress * 5) - cols_taken

    if chosen == "rain":
        if col >= 4:
            base = GREEN_LIT if checker else GREEN_DARK
            rb = rain_brightness(row, col, t)
            return (base[0], _clamp(base[1] + int(200 * rb)), base[2])

        amber_col_dist = 3 - col
        if amber_col_dist < cols_taken:
            base = GREEN_LIT if checker else GREEN_DARK
            rb = rain_brightness(row, col, t)
            return (base[0], _clamp(base[1] + int(200 * rb)), base[2])

        if amber_col_dist == cols_taken and cols_taken < 4:
            f = col_frac
            a = AMBER_LIT if checker else AMBER_DARK
            g = GREEN_LIT if checker else GREEN_DARK
            r = int(a[0] * (1 - f) + g[0] * f)
            gv = int(a[1] * (1 - f) + g[1] * f)
            b = int(a[2] * (1 - f) + g[2] * f)
            rb = rain_brightness(row, col, t)
            return (r, _clamp(gv + int(200 * rb * f)), b)

        return AMBER_LIT if checker else AMBER_DARK

    else:
        if col <= 3:
            return AMBER_LIT if checker else AMBER_DARK

        rain_col_dist = col - 4
        if rain_col_dist < cols_taken:
            return AMBER_LIT if checker else AMBER_DARK

        if rain_col_dist == cols_taken and cols_taken < 4:
            f = col_frac
            g = GREEN_LIT if checker else GREEN_DARK
            a = AMBER_LIT if checker else AMBER_DARK
            r = int(g[0] * (1 - f) + a[0] * f)
            gv = int(g[1] * (1 - f) + a[1] * f)
            b = int(g[2] * (1 - f) + a[2] * f)
            rb = rain_brightness(row, col, t)
            return (r, _clamp(gv + int(200 * rb * (1 - f))), b)

        base = GREEN_LIT if checker else GREEN_DARK
        rb = rain_brightness(row, col, t)
        return (base[0], _clamp(base[1] + int(200 * rb)), base[2])


CHOICE_HOST = (2, 0)
CHOICE_JOIN = (5, 0)
BLINK_PERIOD = 0.3
FRAME_SLEEP = 0.02


class _Phase(Enum):
    L1_IDLE = auto()
    L1_COUNTDOWN = auto()
    L2_IDLE = auto()
    L2_COUNTDOWN = auto()
    BLINK_REMOVE = auto()


class Lobby:
    def __init__(self, board: object) -> None:
        self._b = board

    def run(self) -> str:
        result = self._level1()
        if result == "local":
            self._blink_and_remove([result])
            return "local"
        rain_pos = result
        mode = self._level2(rain_pos)
        if mode == "__local__":
            return "local"
        self._blink_and_remove([rain_pos, CHOICE_HOST if mode == "host" else CHOICE_JOIN])
        return mode

    # -- Level 1 -------------------------------------------------------

    def _level1(self) -> "str | tuple[int, int]":
        """Run L1. Returns 'local' or (row, col) of the rain piece."""
        chosen_side = None
        piece_pos = None
        countdown_start = None

        while True:
            t = time.monotonic()
            self._b.master.read_data()

            if chosen_side is None:
                # Scan for any piece on rows 2-5
                found_side = None
                found_pos = None
                for row in range(2, 6):
                    for col in range(8):
                        if self._b.master.get_cell_state(row, col) == CellOccupancy.OCCUPIED:
                            found_side = "amber" if col <= 3 else "rain"
                            found_pos = (row, col)
                            break
                    if found_side:
                        break

                if found_side:
                    chosen_side = found_side
                    piece_pos = found_pos
                    countdown_start = t

                self._render_l1_idle(t)
            else:
                # Check piece is still there
                r, c = piece_pos
                if self._b.master.get_cell_state(r, c) != CellOccupancy.OCCUPIED:
                    chosen_side = None
                    piece_pos = None
                    countdown_start = None
                    continue

                elapsed = t - countdown_start
                progress = min(1.0, elapsed / SPREAD_DURATION)

                if progress >= 1.0:
                    if chosen_side == "amber":
                        return "local"
                    else:
                        return piece_pos

                self._render_l1_spread(t, progress, chosen_side)

            self._b.canvas = self._b.matrix.SwapOnVSync(self._b.canvas)
            self._b.canvas.Clear()
            time.sleep(FRAME_SLEEP)

    def _render_l1_idle(self, t: float) -> None:
        for row in range(8):
            for col in range(8):
                if col <= 3:
                    r, g, b = amber_color(row, col)
                else:
                    base = green_color(row, col)
                    rb = rain_brightness(row, col, t)
                    r, g, b = base[0], _clamp(base[1] + int(200 * rb)), base[2]
                self._b.light_cell(self._b.canvas, row, col, r, g, b)

    def _render_l1_spread(self, t: float, progress: float, chosen: str) -> None:
        for row in range(8):
            for col in range(8):
                r, g, b = spread_color(row, col, progress, chosen, t)
                self._b.light_cell(self._b.canvas, row, col, r, g, b)

    # -- Level 2 (placeholder — implemented in Task 5) --

    def _level2(self, rain_pos: "tuple[int, int]") -> str:
        raise NotImplementedError("L2 implemented in Task 5")

    # -- Blink and remove -----------------------------------------------

    def _blink_and_remove(self, positions: list) -> None:
        """Blink cells at given positions until all are empty."""
        # Filter out string values (like 'local')
        cells = [p for p in positions if isinstance(p, tuple)]
        if not cells:
            return

        while True:
            self._b.master.read_data()
            all_empty = all(
                self._b.master.get_cell_state(r, c) == CellOccupancy.EMPTY
                for r, c in cells
            )
            if all_empty:
                break

            t = time.monotonic()
            on = int(t / BLINK_PERIOD) % 2 == 0
            self._b.canvas.Clear()
            if on:
                for r, c in cells:
                    self._b.light_cell(self._b.canvas, r, c, 255, 255, 255)
            self._b.canvas = self._b.matrix.SwapOnVSync(self._b.canvas)
            self._b.canvas.Clear()
            time.sleep(FRAME_SLEEP)
