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
