"""
test_simulator_extras.py — unit tests for SimSensor and FakeRGBMatrix.

These tests target the uncovered lines in:
  - simulator/sensor.py  (read_data, get_cell_state, set_state)
  - simulator/fake_rgbmatrix.py  (SwapOnVSync, blit_to_screen early-return,
    flip, FakeFrameCanvas.SetPixel out-of-bounds)

Pygame is initialised with dummy SDL drivers so no display is required.
"""
from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest
from unittest.mock import MagicMock, patch


# ── SimSensor ─────────────────────────────────────────────────────────────────

class TestSimSensor:
    def _sensor(self):
        from simulator.sensor import SimSensor
        return SimSensor()

    def test_all_cells_empty_on_init(self):
        from core.constants import CellOccupancy
        sensor = self._sensor()
        for r in range(8):
            for c in range(8):
                assert sensor.get_cell_state(r, c) == CellOccupancy.EMPTY

    def test_read_data_is_noop(self):
        # read_data must exist and return None without raising.
        sensor = self._sensor()
        result = sensor.read_data()
        assert result is None

    def test_get_cell_state_returns_occupancy(self):
        from core.constants import CellOccupancy
        sensor = self._sensor()
        sensor._grid[3][5] = CellOccupancy.OCCUPIED
        assert sensor.get_cell_state(3, 5) == CellOccupancy.OCCUPIED

    def test_set_state_updates_cell(self):
        from core.constants import CellOccupancy
        sensor = self._sensor()
        sensor.set_state(2, 7, CellOccupancy.OCCUPIED)
        assert sensor._grid[2][7] == CellOccupancy.OCCUPIED

    def test_set_state_then_get_cell_state_round_trip(self):
        from core.constants import CellOccupancy
        sensor = self._sensor()
        sensor.set_state(6, 1, CellOccupancy.OCCUPIED)
        assert sensor.get_cell_state(6, 1) == CellOccupancy.OCCUPIED
        sensor.set_state(6, 1, CellOccupancy.EMPTY)
        assert sensor.get_cell_state(6, 1) == CellOccupancy.EMPTY


# ── FakeFrameCanvas ───────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def _pygame_init():
    pygame.init()
    yield
    pygame.quit()


class TestFakeFrameCanvas:
    def test_set_pixel_in_bounds_does_not_raise(self, _pygame_init):
        from simulator.fake_rgbmatrix import FakeFrameCanvas
        canvas = FakeFrameCanvas()
        canvas.SetPixel(0, 0, 255, 0, 0)
        canvas.SetPixel(31, 31, 0, 255, 0)

    def test_set_pixel_out_of_bounds_does_not_raise(self, _pygame_init):
        # Out-of-bounds SetPixel calls are silently ignored (guarded by if).
        from simulator.fake_rgbmatrix import FakeFrameCanvas
        canvas = FakeFrameCanvas()
        canvas.SetPixel(-1, 0, 255, 0, 0)
        canvas.SetPixel(0, -1, 0, 255, 0)
        canvas.SetPixel(32, 0, 0, 0, 255)
        canvas.SetPixel(0, 32, 128, 128, 128)

    def test_clear_fills_with_black(self, _pygame_init):
        from simulator.fake_rgbmatrix import FakeFrameCanvas
        canvas = FakeFrameCanvas()
        canvas.SetPixel(5, 5, 200, 100, 50)
        canvas.Clear()
        color = canvas._surface.get_at((5, 5))
        assert color[:3] == (0, 0, 0)


# ── FakeRGBMatrix ─────────────────────────────────────────────────────────────

class TestFakeRGBMatrix:
    def test_swap_on_vsync_returns_same_canvas(self, _pygame_init):
        # Covers simulator/fake_rgbmatrix.py line 69 (return canvas).
        from simulator.fake_rgbmatrix import FakeRGBMatrix
        matrix = FakeRGBMatrix()
        canvas = matrix.CreateFrameCanvas()
        result = matrix.SwapOnVSync(canvas)
        assert result is canvas

    def test_blit_to_screen_early_return_when_no_screen(self, _pygame_init):
        # Covers line 75: early return when _screen is None.
        from simulator.fake_rgbmatrix import FakeRGBMatrix
        matrix = FakeRGBMatrix()
        assert matrix._screen is None
        # Must not raise even though _screen is None
        matrix.blit_to_screen()

    def test_blit_to_screen_with_screen_blits_surface(self, _pygame_init):
        from simulator.fake_rgbmatrix import FakeRGBMatrix
        matrix = FakeRGBMatrix()
        matrix._screen = MagicMock()
        matrix._canvas.SetPixel(0, 0, 255, 0, 0)
        with patch("pygame.draw.rect"):
            matrix.blit_to_screen()
        assert matrix._screen.blit.called

    def test_flip_calls_blit_and_display_flip(self, _pygame_init):
        from simulator.fake_rgbmatrix import FakeRGBMatrix
        matrix = FakeRGBMatrix()
        matrix._screen = MagicMock()
        matrix._canvas.SetPixel(0, 0, 255, 0, 0)
        with patch("pygame.draw.rect"), patch("pygame.display.flip") as mock_flip:
            matrix.flip()
        mock_flip.assert_called_once()
        assert matrix._screen.blit.called
