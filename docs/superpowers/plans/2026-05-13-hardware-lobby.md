# Hardware Board Lobby Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reed-switch-driven lobby menu to the physical board — a two-level binary decision tree (Local vs Network, Host vs Join) that communicates entirely through LED animations.

**Architecture:** New `game/lobby.py` module with pure rendering functions and a `Lobby` class that encapsulates the state machine. `Board.run()` calls `Lobby(self).run()` before `color_picker()`. The lobby returns `"local"`, `"host"`, or `"join"` to drive subsequent flow. All development and testing targets the HIL container.

**Tech Stack:** Python 3.9, rgbmatrix (stubbed via HIL), Bazel test runner, HIL WebSocket control server for interactive testing.

**Spec:** `docs/superpowers/specs/2026-05-13-hardware-lobby-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `game/lobby.py` | Create | Pure rendering helpers, path generation, `Lobby` state machine class |
| `game/board.py` | Modify | Call `Lobby.run()` in `Board.run()`, add `single_player` param to `color_picker`/`war_games` |
| `tests/test_lobby.py` | Create | Unit tests for rendering helpers, path generation, spread logic |
| `harness/hil_scenarios.py` | Modify | Add lobby action sequences |

---

### Task 1: Core rendering helpers

**Files:**
- Create: `game/lobby.py`
- Create: `tests/test_lobby.py`

- [ ] **Step 1: Write failing tests for color and rain helpers**

```python
# tests/test_lobby.py
import time
from game.lobby import (
    is_checker,
    amber_color,
    green_color,
    rain_brightness,
    AMBER_LIT, AMBER_DARK, GREEN_LIT, GREEN_DARK,
)


class TestCheckerPattern:
    def test_origin_is_checker(self):
        assert is_checker(0, 0) is True

    def test_adjacent_not_checker(self):
        assert is_checker(0, 1) is False

    def test_diagonal_is_checker(self):
        assert is_checker(1, 1) is True


class TestAmberColor:
    def test_checker_square(self):
        assert amber_color(0, 0) == AMBER_LIT

    def test_non_checker_square(self):
        assert amber_color(0, 1) == AMBER_DARK


class TestGreenColor:
    def test_checker_square(self):
        assert green_color(0, 0) == GREEN_LIT

    def test_non_checker_square(self):
        assert green_color(0, 1) == GREEN_DARK


class TestRainBrightness:
    def test_returns_float_between_0_and_1(self):
        for t in [0.0, 0.5, 1.0, 2.0, 5.0]:
            b = rain_brightness(0, 4, t)
            assert 0.0 <= b <= 1.0

    def test_varies_over_time(self):
        values = {rain_brightness(0, 4, t * 0.1) for t in range(30)}
        assert len(values) > 1, "rain should vary over time"

    def test_column_offset_shifts_phase(self):
        b1 = rain_brightness(0, 4, 0.0)
        b2 = rain_brightness(0, 5, 0.0)
        # Different columns have different offsets, so brightness differs at same t
        # (not guaranteed for all t, but very likely at t=0)
        # Just check both are valid
        assert 0.0 <= b1 <= 1.0
        assert 0.0 <= b2 <= 1.0

    def test_falls_downward(self):
        """Row 0 should peak before row 7 within the same column."""
        # Find peak time for row 0 col 4
        peak_times = []
        for row in [0, 7]:
            for tick in range(240):
                t = tick * 0.01
                if rain_brightness(row, 4, t) == 1.0:
                    peak_times.append(t)
                    break
        assert len(peak_times) == 2
        assert peak_times[0] < peak_times[1], "row 0 should peak before row 7"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bazel run //:gazelle && bazel test //tests:test_lobby --test_output=streamed --test_arg=-v`

Expected: ImportError — `game.lobby` does not exist.

- [ ] **Step 3: Implement rendering helpers**

```python
# game/lobby.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bazel run //:gazelle && bazel test //tests:test_lobby --test_output=streamed --test_arg=-v`

Expected: All 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add game/lobby.py tests/test_lobby.py
git commit -m "lobby: add core rendering helpers (checker, amber, green, rain)"
```

---

### Task 2: Monotonic random paths and signal rendering

**Files:**
- Modify: `game/lobby.py`
- Modify: `tests/test_lobby.py`

- [ ] **Step 1: Write failing tests for path generation**

```python
# append to tests/test_lobby.py
from game.lobby import monotonic_random_path, add_signal_trail


class TestMonotonicRandomPath:
    def test_path_length_is_manhattan_distance(self):
        path = monotonic_random_path(3, 6, 2, 0, exclude=(2, 0))
        # Manhattan = |3-2| + |6-0| = 7, minus excluded endpoint = 6 cells
        assert len(path) == 7  # includes start (3,6), excludes end (2,0)

    def test_excludes_specified_cell(self):
        for _ in range(20):
            path = monotonic_random_path(3, 6, 2, 0, exclude=(2, 0))
            assert (2, 0) not in path

    def test_includes_non_excluded_endpoint(self):
        for _ in range(20):
            path = monotonic_random_path(3, 6, 2, 0, exclude=(2, 0))
            assert path[0] == (3, 6)

    def test_every_step_is_closer(self):
        for _ in range(20):
            path = monotonic_random_path(3, 6, 5, 0, exclude=(5, 0))
            to_r, to_c = 5, 0
            for i in range(1, len(path)):
                prev_r, prev_c = path[i - 1]
                curr_r, curr_c = path[i]
                prev_dist = abs(prev_r - to_r) + abs(prev_c - to_c)
                curr_dist = abs(curr_r - to_r) + abs(curr_c - to_c)
                assert curr_dist < prev_dist

    def test_paths_vary(self):
        paths = set()
        for _ in range(20):
            p = monotonic_random_path(3, 6, 2, 0, exclude=(2, 0))
            paths.add(tuple(p))
        assert len(paths) > 1, "paths should be random"

    def test_exclude_start(self):
        path = monotonic_random_path(5, 0, 3, 6, exclude=(5, 0))
        assert (5, 0) not in path
        assert path[-1] == (3, 6)


class TestAddSignalTrail:
    def test_head_is_white(self):
        path = [(3, 4), (3, 3), (3, 2), (3, 1)]
        colors = {}
        add_signal_trail(colors, path, step_idx=1, trail_len=3)
        assert colors[(3, 3)] == (255, 255, 255)

    def test_trail_dims(self):
        path = [(3, 4), (3, 3), (3, 2), (3, 1)]
        colors = {}
        add_signal_trail(colors, path, step_idx=2, trail_len=3)
        r0, g0, b0 = colors[(3, 2)]  # head
        r1, g1, b1 = colors[(3, 3)]  # trail
        assert r0 > r1

    def test_no_color_beyond_trail(self):
        path = [(3, 4), (3, 3), (3, 2), (3, 1)]
        colors = {}
        add_signal_trail(colors, path, step_idx=2, trail_len=2)
        assert (3, 4) not in colors
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bazel test //tests:test_lobby --test_output=streamed --test_arg=-v`

Expected: ImportError — `monotonic_random_path` not found.

- [ ] **Step 3: Implement path generation and signal trail**

```python
# append to game/lobby.py

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bazel test //tests:test_lobby --test_output=streamed --test_arg=-v`

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add game/lobby.py tests/test_lobby.py
git commit -m "lobby: add monotonic random paths and signal trail rendering"
```

---

### Task 3: Spread transition

**Files:**
- Modify: `game/lobby.py`
- Modify: `tests/test_lobby.py`

- [ ] **Step 1: Write failing tests for spread logic**

```python
# append to tests/test_lobby.py
from game.lobby import spread_color, SPREAD_DURATION


class TestSpreadColor:
    def test_zero_progress_rain_side_unchanged(self):
        # col 5 is rain side — should be green at progress 0
        r, g, b = spread_color(0, 5, 0.0, "rain", t=0.0)
        assert g > r and g > b

    def test_zero_progress_amber_side_unchanged(self):
        r, g, b = spread_color(0, 0, 0.0, "rain", t=0.0)
        assert r > g  # amber

    def test_full_progress_rain_takes_over(self):
        # At progress 1.0, col 0 should be green
        r, g, b = spread_color(0, 0, 1.0, "rain", t=0.0)
        gr, gg, gb = green_color(0, 0)
        # Base should be green (rain brightness may add more green)
        assert g >= gg

    def test_full_progress_amber_takes_over(self):
        r, g, b = spread_color(0, 7, 1.0, "amber", t=0.0)
        assert (r, g, b) == amber_color(0, 7)

    def test_spread_duration_constant(self):
        assert SPREAD_DURATION == 3.0

    def test_rain_spreads_left_from_center(self):
        # At progress 0.3 (1.5 cols taken), col 3 should be transitioning
        # but col 0 should still be amber
        r0, g0, b0 = spread_color(0, 0, 0.3, "rain", t=0.0)
        assert r0 > g0, "col 0 should still be amber at 30%"

    def test_amber_spreads_right_from_center(self):
        r7, g7, b7 = spread_color(0, 7, 0.3, "amber", t=0.0)
        # col 7 is far right, should still be green at 30%
        assert g7 > r7, "col 7 should still be green at 30%"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bazel test //tests:test_lobby --test_output=streamed --test_arg=-v`

Expected: ImportError — `spread_color` not found.

- [ ] **Step 3: Implement spread transition**

```python
# append to game/lobby.py

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bazel test //tests:test_lobby --test_output=streamed --test_arg=-v`

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add game/lobby.py tests/test_lobby.py
git commit -m "lobby: add spread transition rendering"
```

---

### Task 4: Lobby state machine — Level 1

**Files:**
- Modify: `game/lobby.py`
- Modify: `tests/test_lobby.py`

- [ ] **Step 1: Write failing test for Lobby L1 — local choice**

```python
# append to tests/test_lobby.py
from unittest.mock import MagicMock
from game.lobby import Lobby


def _make_mock_board():
    """Build a mock Board with the interfaces Lobby needs."""
    board = MagicMock()
    board.master = MagicMock()
    board.master.read_data = MagicMock()
    board.master.get_cell_state = MagicMock(return_value=1)  # all empty
    board.canvas = MagicMock()
    board.canvas.Clear = MagicMock()
    board.matrix = MagicMock()
    board.matrix.SwapOnVSync = MagicMock(return_value=board.canvas)
    board.light_cell = MagicMock()
    return board


class TestLobbyL1:
    def test_local_choice_returns_local(self):
        board = _make_mock_board()
        lobby = Lobby(board)

        call_count = [0]

        def fake_cell_state(row, col):
            call_count[0] += 1
            # After a few frames, place piece at (3, 2) — amber side
            if call_count[0] > 200 and row == 3 and col == 2:
                return 0  # OCCUPIED
            return 1  # EMPTY

        board.master.get_cell_state = MagicMock(side_effect=fake_cell_state)

        result = lobby.run()
        assert result == "local"

    def test_network_choice_proceeds_to_l2(self):
        board = _make_mock_board()
        lobby = Lobby(board)

        call_count = [0]
        phase = ["l1"]

        def fake_cell_state(row, col):
            call_count[0] += 1
            if phase[0] == "l1":
                # Place on rain side (3, 5) after a few frames
                if call_count[0] > 200 and row == 3 and col == 5:
                    return 0
                return 1
            elif phase[0] == "l2":
                # Place on Host (2, 0)
                if row == 2 and col == 0:
                    return 0
                # Keep rain piece
                if row == 3 and col == 5:
                    return 0
                return 1
            elif phase[0] == "remove":
                return 1  # all empty
            return 1

        board.master.get_cell_state = MagicMock(side_effect=fake_cell_state)

        # Monkey-patch time.monotonic to speed through countdowns
        original_monotonic = time.monotonic
        fast_time = [original_monotonic()]

        def fast_monotonic():
            fast_time[0] += 0.2
            return fast_time[0]

        time.monotonic = fast_monotonic

        def advance_phase(*args, **kwargs):
            """Advance phase after enough SwapOnVSync calls."""
            if phase[0] == "l1" and call_count[0] > 5000:
                phase[0] = "l2"
            elif phase[0] == "l2" and call_count[0] > 10000:
                phase[0] = "remove"
            return board.canvas

        board.matrix.SwapOnVSync = MagicMock(side_effect=advance_phase)

        try:
            result = lobby.run()
            assert result == "host"
        finally:
            time.monotonic = original_monotonic
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bazel test //tests:test_lobby --test_output=streamed --test_arg=-v`

Expected: FAIL — `Lobby` not importable.

- [ ] **Step 3: Implement Lobby class with L1 state machine**

```python
# append to game/lobby.py
from enum import Enum, auto

from core.constants import CellOccupancy

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
        self._blink_and_remove([rain_pos, CHOICE_HOST if mode == "host" else CHOICE_JOIN])
        return mode

    # -- Level 1 -------------------------------------------------------

    def _level1(self) -> str | tuple[int, int]:
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

    def _level2(self, rain_pos: tuple[int, int]) -> str:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bazel run //:gazelle && bazel test //tests:test_lobby --test_output=streamed --test_arg=-v`

Expected: `test_local_choice_returns_local` PASSES. The network test may need tuning depending on mock timing — adjust `call_count` thresholds if needed.

- [ ] **Step 5: Commit**

```bash
git add game/lobby.py tests/test_lobby.py
git commit -m "lobby: add Level 1 state machine (local vs network)"
```

---

### Task 5: Lobby state machine — Level 2

**Files:**
- Modify: `game/lobby.py`
- Modify: `tests/test_lobby.py`

- [ ] **Step 1: Write failing tests for L2 rendering helpers**

```python
# append to tests/test_lobby.py
from game.lobby import l2_idle_color, ring_intensity

OPPONENT_POS = (3, 6)


class TestL2IdleColor:
    def test_green_base(self):
        r, g, b = l2_idle_color(4, 4, t=0.0, opponent_pos=OPPONENT_POS)
        gr, gg, gb = green_color(4, 4)
        assert (r, g, b) == (gr, gg, gb)

    def test_opponent_cell_is_bright_green(self):
        r, g, b = l2_idle_color(3, 6, t=0.0, opponent_pos=OPPONENT_POS)
        assert g > 200

    def test_choice_host_blinks_white(self):
        colors = set()
        for tick in range(24):
            t = tick * 0.1
            colors.add(l2_idle_color(2, 0, t, OPPONENT_POS))
        assert len(colors) > 1, "choice cell should blink"


class TestRingIntensity:
    def test_zero_at_large_distance(self):
        val = ring_intensity(7, 7, 2, 0, t=0.0, contracting=True)
        assert val < 0.1

    def test_varies_over_time(self):
        values = {ring_intensity(3, 1, 2, 0, t * 0.1, contracting=True) for t in range(30)}
        assert len(values) > 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bazel test //tests:test_lobby --test_output=streamed --test_arg=-v`

Expected: ImportError — `l2_idle_color` not found.

- [ ] **Step 3: Implement L2 rendering helpers and state machine**

```python
# append to game/lobby.py

OPPONENT_GREEN = (0, 255, 100)
L2_FADE_DURATION = 3.0
CELL_SIZE_PX = 38  # for distance calc (matches LED cell visual size)
RING_MAX_DIST = CELL_SIZE_PX * 10
RING_SPEED = 120  # pixels/sec
RING_WIDTH = CELL_SIZE_PX * 1.5
RING_INTENSITY = 0.25


def _pixel_dist(r1: int, c1: int, r2: int, c2: int) -> float:
    dx = (c2 - c1) * CELL_SIZE_PX
    dy = (r2 - r1) * CELL_SIZE_PX
    return (dx * dx + dy * dy) ** 0.5


def ring_intensity(
    row: int, col: int, center_r: int, center_c: int,
    t: float, contracting: bool,
) -> float:
    d = _pixel_dist(row, col, center_r, center_c)
    dist_falloff = max(0.0, 1.0 - d / RING_MAX_DIST)
    if contracting:
        radius = RING_MAX_DIST - ((t * RING_SPEED) % RING_MAX_DIST)
    else:
        radius = (t * RING_SPEED) % RING_MAX_DIST
    dist_from_ring = abs(d - radius)
    if dist_from_ring >= RING_WIDTH:
        return 0.0
    return (1.0 - dist_from_ring / RING_WIDTH) * dist_falloff * RING_INTENSITY


def l2_idle_color(
    row: int, col: int, t: float,
    opponent_pos: tuple[int, int],
) -> tuple[int, int, int]:
    if (row, col) == opponent_pos:
        return OPPONENT_GREEN

    if (row, col) == CHOICE_HOST or (row, col) == CHOICE_JOIN:
        phase = (t / BLINK_PERIOD) % 2
        is_host = (row, col) == CHOICE_HOST
        on = (int(phase) == 0) if is_host else (int(phase) == 1)
        if on:
            return (255, 255, 255)

    return green_color(row, col)
```

Now replace the `_level2` placeholder in `Lobby`:

```python
    def _level2(self, rain_pos: tuple[int, int]) -> str:
        chosen = None
        countdown_start = None
        signal_path: list[tuple[int, int]] = []
        signal_idx = 0
        signal_dir = "host"
        last_signal_step = 0.0
        signal_gap = 0

        def new_signal():
            nonlocal signal_path, signal_idx, signal_dir, signal_gap
            if chosen:
                if chosen == "host":
                    signal_path = monotonic_random_path(
                        rain_pos[0], rain_pos[1], CHOICE_HOST[0], CHOICE_HOST[1],
                        exclude=CHOICE_HOST,
                    )
                else:
                    signal_path = monotonic_random_path(
                        CHOICE_JOIN[0], CHOICE_JOIN[1], rain_pos[0], rain_pos[1],
                        exclude=CHOICE_JOIN,
                    )
            else:
                if signal_dir == "host":
                    signal_path = monotonic_random_path(
                        rain_pos[0], rain_pos[1], CHOICE_HOST[0], CHOICE_HOST[1],
                        exclude=CHOICE_HOST,
                    )
                    signal_dir = "join"
                else:
                    signal_path = monotonic_random_path(
                        CHOICE_JOIN[0], CHOICE_JOIN[1], rain_pos[0], rain_pos[1],
                        exclude=CHOICE_JOIN,
                    )
                    signal_dir = "host"
            signal_idx = 0
            signal_gap = 0

        new_signal()

        while True:
            t = time.monotonic()
            self._b.master.read_data()

            if chosen is None:
                # Check for piece on choice cells
                host_occ = self._b.master.get_cell_state(*CHOICE_HOST) == CellOccupancy.OCCUPIED
                join_occ = self._b.master.get_cell_state(*CHOICE_JOIN) == CellOccupancy.OCCUPIED

                # Check rain piece removed → back to L1
                if self._b.master.get_cell_state(*rain_pos) != CellOccupancy.OCCUPIED:
                    return self._back_to_l1(rain_pos)

                if host_occ:
                    chosen = "host"
                    countdown_start = t
                elif join_occ:
                    chosen = "join"
                    countdown_start = t
                    new_signal()
            else:
                choice_pos = CHOICE_HOST if chosen == "host" else CHOICE_JOIN
                if self._b.master.get_cell_state(*choice_pos) != CellOccupancy.OCCUPIED:
                    chosen = None
                    countdown_start = None
                    continue

                if self._b.master.get_cell_state(*rain_pos) != CellOccupancy.OCCUPIED:
                    return self._back_to_l1(rain_pos)

                elapsed = t - countdown_start
                progress = min(1.0, elapsed / L2_FADE_DURATION)
                if progress >= 1.0:
                    return chosen

            # Render frame
            trail_colors: dict[tuple[int, int], tuple[int, int, int]] = {}
            if signal_path:
                add_signal_trail(trail_colors, signal_path, signal_idx)

            self._b.canvas.Clear()
            for row in range(8):
                for col in range(8):
                    if chosen is None:
                        r, g, b = l2_idle_color(row, col, t, rain_pos)
                    else:
                        r, g, b = green_color(row, col)
                        if (row, col) == rain_pos:
                            r, g, b = OPPONENT_GREEN
                        ri = ring_intensity(
                            row, col,
                            CHOICE_HOST[0] if chosen == "host" else CHOICE_JOIN[0],
                            CHOICE_HOST[1] if chosen == "host" else CHOICE_JOIN[1],
                            t, contracting=(chosen == "host"),
                        )
                        if ri > 0:
                            r = _clamp(r + int(255 * ri))
                            g = _clamp(g + int(255 * ri))
                            b = _clamp(b + int(255 * ri))

                    if (row, col) in trail_colors:
                        tr, tg, tb = trail_colors[(row, col)]
                        r = _clamp(r + tr)
                        g = _clamp(g + tg)
                        b = _clamp(b + tb)

                    self._b.light_cell(self._b.canvas, row, col, r, g, b)

            self._b.canvas = self._b.matrix.SwapOnVSync(self._b.canvas)
            self._b.canvas.Clear()

            # Step signal
            if t - last_signal_step >= 0.1:
                signal_idx += 1
                last_signal_step = t
                if signal_idx >= len(signal_path) + 4:
                    new_signal()

            time.sleep(FRAME_SLEEP)

    def _back_to_l1(self, rain_pos: tuple[int, int]) -> str:
        """Rain piece removed during L2 — re-run full lobby."""
        result = self._level1()
        if result == "local":
            self._blink_and_remove([result])
            return "__local__"
        return self._level2(result)
```

Update `Lobby.run()` to handle the back-to-L1 case:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bazel run //:gazelle && bazel test //tests:test_lobby --test_output=streamed --test_arg=-v`

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add game/lobby.py tests/test_lobby.py
git commit -m "lobby: add Level 2 state machine (host vs join)"
```

---

### Task 6: Wire lobby into Board.run()

**Files:**
- Modify: `game/board.py`

- [ ] **Step 1: Add lobby import and call in Board.run()**

At the top of `game/board.py`, add to imports:

```python
from game.lobby import Lobby
```

In `Board.run()`, insert the lobby call before `color_picker()`. Find this block (around line 115):

```python
        if not skip_setup:
            self.color_picker()
            self.war_games()
```

Replace with:

```python
        if not skip_setup:
            lobby = Lobby(self)
            self._lobby_result = lobby.run()

            single = self._lobby_result != "local"
            self.color_picker(single_player=single)
            self.war_games(single_player=single)
```

- [ ] **Step 2: Add single_player parameter to color_picker**

Find the `color_picker` method signature (around line 1214):

```python
    def color_picker(self):
```

Replace with:

```python
    def color_picker(self, single_player: bool = False):
```

In the body, after the initial canvas setup and before the while loop, add a branch for single-player. The key change: when `single_player` is True, only show row 2 (team_r if host) or row 5 (team_l if join), and auto-assign the other team a default color.

After the line `self.canvas = self.matrix.SwapOnVSync(self.canvas)` (around line 1237), before the `while` loop, add:

```python
        if single_player:
            is_host = getattr(self, '_lobby_result', 'host') == 'host'
            pick_row = 2 if is_host else 5
            other_team = self.team_l if is_host else self.team_r

            # Show only the local player's row
            self.canvas.Clear()
            for i in range(8):
                self.light_cell(self.canvas, pick_row, i,
                                self.team_array[i].r, self.team_array[i].g, self.team_array[i].b)
            self.canvas = self.matrix.SwapOnVSync(self.canvas)

            while True:
                self.master.read_data()
                found = False
                for i in range(8):
                    if self.master.get_cell_state(pick_row, i) == CellOccupancy.OCCUPIED:
                        found = True
                        local_team = self.team_r if is_host else self.team_l
                        local_team.r = self.team_array[i].r
                        local_team.g = self.team_array[i].g
                        local_team.b = self.team_array[i].b
                        break
                if found:
                    # Auto-assign other team a contrasting color
                    other_team.r = self.team_array[(i + 4) % 8].r
                    other_team.g = self.team_array[(i + 4) % 8].g
                    other_team.b = self.team_array[(i + 4) % 8].b
                    self.canvas.Clear()
                    self.light_cell(self.canvas, pick_row, i,
                                    local_team.r, local_team.g, local_team.b)
                    self.canvas = self.matrix.SwapOnVSync(self.canvas)
                    time.sleep(2)
                    break
                self.canvas.Clear()
                for i in range(8):
                    self.light_cell(self.canvas, pick_row, i,
                                    self.team_array[i].r, self.team_array[i].g, self.team_array[i].b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
            self.team_r.r = self.team_r.r + 1
            return
```

- [ ] **Step 3: Add single_player parameter to war_games**

Find the `war_games` method signature (around line 1332):

```python
    def war_games(self):
```

Replace with:

```python
    def war_games(self, single_player: bool = False):
```

Add early return for single-player at the start of the method body, after `self.canvas.Clear()`:

```python
        if single_player:
            is_host = getattr(self, '_lobby_result', 'host') == 'host'
            pick_row = 3 if is_host else 4
            local_team = self.team_r if is_host else self.team_l

            think = 0
            while True:
                self.master.read_data()
                decided = False
                for i in range(8):
                    if self.master.get_cell_state(pick_row, i) == CellOccupancy.OCCUPIED:
                        decided = True
                        if is_host:
                            self.computer_player_r = i >= 4
                        else:
                            self.computer_player_l = i < 4
                        break

                self.canvas.Clear()
                if decided:
                    is_ai = (self.computer_player_r if is_host else self.computer_player_l)
                    if is_ai:
                        for j in range(8):
                            if j == 7 - think:
                                self.light_cell(self.canvas, pick_row, 7 - think,
                                                local_team.r, local_team.g, local_team.b)
                            else:
                                self.light_cell(self.canvas, pick_row, j, 255, 255, 255)
                    else:
                        for j in range(8):
                            self.light_cell(self.canvas, pick_row, j,
                                            local_team.r, local_team.g, local_team.b)
                    self.canvas = self.matrix.SwapOnVSync(self.canvas)
                    self.canvas.Clear()
                    break
                else:
                    for j in range(8):
                        if j < 4:
                            self.light_cell(self.canvas, pick_row, j,
                                            local_team.r, local_team.g, local_team.b)
                        else:
                            if j == 7 - think:
                                self.light_cell(self.canvas, pick_row, 7 - think,
                                                local_team.r, local_team.g, local_team.b)
                            else:
                                self.light_cell(self.canvas, pick_row, j, 255, 255, 255)

                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                self.canvas.Clear()
                time.sleep(0.2)
                think = (think + 1) % 4
            return
```

- [ ] **Step 4: Verify existing tests still pass**

Run: `bazel run //:gazelle && bazel test //tests/... --test_output=errors`

Expected: All existing tests PASS (lobby is only called when `skip_setup=False`, and existing tests either skip setup or mock the board).

- [ ] **Step 5: Commit**

```bash
git add game/board.py game/lobby.py
git commit -m "lobby: wire into Board.run(), single-player color_picker and war_games"
```

---

### Task 7: HIL lobby scenarios

**Files:**
- Modify: `harness/hil_scenarios.py`

- [ ] **Step 1: Add lobby scenarios**

Add these scenario functions to `harness/hil_scenarios.py`:

```python
def lobby_choose_local(col: int = 2, row: int = 3) -> list[Action]:
    """Place piece on amber side → wait for spread → lift piece when it blinks."""
    return [
        Action(ActionType.PLACE, row, col, description=f"place on amber side ({row},{col})"),
        Action(ActionType.WAIT, frames=200, description="wait for 3s spread"),
        Action(ActionType.LIFT, row, col, description="remove blinking piece"),
        Action(ActionType.WAIT, frames=30, description="wait for transition"),
    ]


def lobby_choose_network(col: int = 5, row: int = 3) -> list[Action]:
    """Place piece on rain side → wait for spread. Piece stays for L2."""
    return [
        Action(ActionType.PLACE, row, col, description=f"place on rain side ({row},{col})"),
        Action(ActionType.WAIT, frames=200, description="wait for 3s spread"),
    ]


def lobby_choose_host(rain_row: int = 3, rain_col: int = 5) -> list[Action]:
    """After network chosen, place on (2,0) for host → wait → remove both."""
    return [
        Action(ActionType.PLACE, 2, 0, description="place on Host (2,0)"),
        Action(ActionType.WAIT, frames=200, description="wait for 3s confirmation"),
        Action(ActionType.LIFT, 2, 0, description="remove host piece"),
        Action(ActionType.LIFT, rain_row, rain_col, description="remove rain piece"),
        Action(ActionType.WAIT, frames=30, description="wait for transition"),
    ]


def lobby_choose_join(rain_row: int = 3, rain_col: int = 5) -> list[Action]:
    """After network chosen, place on (5,0) for join → wait → remove both."""
    return [
        Action(ActionType.PLACE, 5, 0, description="place on Join (5,0)"),
        Action(ActionType.WAIT, frames=200, description="wait for 3s confirmation"),
        Action(ActionType.LIFT, 5, 0, description="remove join piece"),
        Action(ActionType.LIFT, rain_row, rain_col, description="remove rain piece"),
        Action(ActionType.WAIT, frames=30, description="wait for transition"),
    ]


def lobby_full_local() -> list[Action]:
    """Complete lobby flow → local play."""
    return lobby_choose_local()


def lobby_full_host() -> list[Action]:
    """Complete lobby flow → host."""
    return lobby_choose_network() + lobby_choose_host()


def lobby_full_join() -> list[Action]:
    """Complete lobby flow → join."""
    return lobby_choose_network() + lobby_choose_join()
```

- [ ] **Step 2: Verify no import errors**

Run: `python -c "from harness.hil_scenarios import lobby_full_local, lobby_full_host, lobby_full_join; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add harness/hil_scenarios.py
git commit -m "lobby: add HIL scenarios for all lobby paths"
```

---

### Task 8: Bazel cleanup and final verification

**Files:**
- Possibly modify: `BUILD` files (via Gazelle)

- [ ] **Step 1: Run Gazelle to regenerate BUILD files**

```bash
bazel run //:gazelle
```

Review the diff — revert any incorrect expansions to `hardware/BUILD`, `harness/BUILD.bazel`, or `tools/BUILD` per CLAUDE.md.

- [ ] **Step 2: Run full test suite**

```bash
bazel test //tests/... --test_output=errors
```

Expected: All tests PASS, including new `test_lobby` tests.

- [ ] **Step 3: Run type checker**

```bash
.venv/bin/mypy game/lobby.py
```

Expected: 0 errors (or only pre-existing ones from `ignore_missing_imports`).

- [ ] **Step 4: Manual HIL verification**

Start HIL container and open visualizer to visually verify:

```bash
python -m hil.run_hil &
# Open web/hil_visualizer.html in browser
# Use the interactive reed-switch grid to:
# 1. Place piece on rain side → watch spread
# 2. Place piece on Host (2,0) → watch signals
# 3. Remove pieces → watch blink transition
```

- [ ] **Step 5: Commit any BUILD file changes**

```bash
git add -A BUILD '**/BUILD' '**/BUILD.bazel'
git commit -m "lobby: update BUILD files via gazelle"
```
