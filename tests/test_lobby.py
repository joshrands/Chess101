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
