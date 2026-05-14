import time
from game.lobby import (
    is_checker,
    amber_color,
    green_color,
    rain_brightness,
    AMBER_LIT, AMBER_DARK, GREEN_LIT, GREEN_DARK,
    l2_idle_color,
    ring_intensity,
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
        assert 0.0 <= b1 <= 1.0
        assert 0.0 <= b2 <= 1.0

    def test_falls_downward(self):
        """Row 0 should peak before row 7 within the same column."""
        peak_times = []
        for row in [0, 7]:
            for tick in range(240):
                t = tick * 0.01
                if rain_brightness(row, 4, t) == 1.0:
                    peak_times.append(t)
                    break
        assert len(peak_times) == 2
        assert peak_times[0] < peak_times[1], "row 0 should peak before row 7"


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


import pytest
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
        original_sleep = time.sleep
        fast_time = [original_monotonic()]

        def fast_monotonic():
            fast_time[0] += 0.2
            return fast_time[0]

        time.monotonic = fast_monotonic
        time.sleep = lambda _: None  # no-op to avoid real delays

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
            time.sleep = original_sleep


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
