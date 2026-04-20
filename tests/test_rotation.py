"""Unit tests for hardware/rotation.py rotation utilities."""
from __future__ import annotations

import pytest

from hardware.rotation import (
    rotate_cell,
    RotatingCanvas,
    PIXEL_ROTATIONS,
    CELL_ROTATIONS,
)


class TestRotateCell:
    """Test rotate_cell function for all four rotations."""

    def test_rotate_cell_0_identity(self) -> None:
        """0 degree rotation is identity transform."""
        assert rotate_cell(0, 0, 0) == (0, 0)
        assert rotate_cell(7, 7, 0) == (7, 7)
        assert rotate_cell(3, 5, 0) == (3, 5)

    def test_rotate_cell_90(self) -> None:
        """90 degree CW rotation."""
        assert rotate_cell(0, 0, 90) == (7, 0)   # top-left → bottom-left
        assert rotate_cell(0, 7, 90) == (0, 0)   # top-right → top-left
        assert rotate_cell(7, 7, 90) == (0, 7)   # bottom-right → top-right
        assert rotate_cell(7, 0, 90) == (7, 7)   # bottom-left → bottom-right

    def test_rotate_cell_180(self) -> None:
        """180 degree rotation."""
        assert rotate_cell(0, 0, 180) == (7, 7)  # top-left → bottom-right
        assert rotate_cell(0, 7, 180) == (7, 0)  # top-right → bottom-left
        assert rotate_cell(7, 7, 180) == (0, 0)  # bottom-right → top-left
        assert rotate_cell(7, 0, 180) == (0, 7)  # bottom-left → top-right

    def test_rotate_cell_270(self) -> None:
        """270 degree CW (= 90 CCW) rotation."""
        assert rotate_cell(0, 0, 270) == (0, 7)  # top-left → top-right
        assert rotate_cell(0, 7, 270) == (7, 7)  # top-right → bottom-right
        assert rotate_cell(7, 7, 270) == (7, 0)  # bottom-right → bottom-left
        assert rotate_cell(7, 0, 270) == (0, 0)  # bottom-left → top-left

    def test_rotate_cell_modulo_360(self) -> None:
        """Rotation values wrap at 360."""
        assert rotate_cell(3, 5, 360) == rotate_cell(3, 5, 0)
        assert rotate_cell(3, 5, 450) == rotate_cell(3, 5, 90)
        assert rotate_cell(3, 5, -90) == rotate_cell(3, 5, 270)

    def test_rotate_cell_four_rotations_cycle(self) -> None:
        """Four 90-degree rotations return to original position."""
        r, c = 2, 5
        r1, c1 = rotate_cell(r, c, 90)
        r2, c2 = rotate_cell(r1, c1, 90)
        r3, c3 = rotate_cell(r2, c2, 90)
        r4, c4 = rotate_cell(r3, c3, 90)
        assert (r4, c4) == (r, c)


class TestRotatingCanvas:
    """Test RotatingCanvas wrapper."""

    class MockCanvas:
        """Fake canvas that records SetPixel calls."""
        def __init__(self):
            self.pixels = []
            self.cleared = False

        def SetPixel(self, x: int, y: int, r: int, g: int, b: int) -> None:
            self.pixels.append((x, y, r, g, b))

        def Clear(self) -> None:
            self.cleared = True

    def test_rotation_0_passthrough(self) -> None:
        """0 degree rotation passes coordinates unchanged."""
        mock = self.MockCanvas()
        canvas = RotatingCanvas(mock, rotation=0)
        canvas.SetPixel(10, 20, 255, 128, 64)
        assert mock.pixels == [(10, 20, 255, 128, 64)]

    def test_rotation_90(self) -> None:
        """90 degree CW rotation transforms pixel coordinates."""
        mock = self.MockCanvas()
        canvas = RotatingCanvas(mock, rotation=90)
        canvas.SetPixel(0, 0, 255, 0, 0)
        assert mock.pixels == [(31, 0, 255, 0, 0)]

    def test_rotation_180(self) -> None:
        """180 degree rotation transforms pixel coordinates."""
        mock = self.MockCanvas()
        canvas = RotatingCanvas(mock, rotation=180)
        canvas.SetPixel(0, 0, 255, 0, 0)
        assert mock.pixels == [(31, 31, 255, 0, 0)]

    def test_rotation_270(self) -> None:
        """270 degree CW (90 CCW) rotation transforms pixel coordinates."""
        mock = self.MockCanvas()
        canvas = RotatingCanvas(mock, rotation=270)
        canvas.SetPixel(0, 0, 255, 0, 0)
        assert mock.pixels == [(0, 31, 255, 0, 0)]

    def test_clear_forwarded(self) -> None:
        """Clear() is forwarded to underlying canvas."""
        mock = self.MockCanvas()
        canvas = RotatingCanvas(mock, rotation=90)
        canvas.Clear()
        assert mock.cleared

    def test_getattr_forwarded(self) -> None:
        """Unknown attributes are forwarded to underlying canvas."""
        mock = self.MockCanvas()
        mock.custom_attr = "test_value"
        canvas = RotatingCanvas(mock, rotation=0)
        assert canvas.custom_attr == "test_value"


class TestPixelRotationsConsistency:
    """Test that pixel rotations form a proper rotation group."""

    def test_four_pixel_rotations_cycle(self) -> None:
        """Four 90-degree pixel rotations return to original position."""
        x, y = 10, 20
        x1, y1 = PIXEL_ROTATIONS[90](x, y)
        x2, y2 = PIXEL_ROTATIONS[90](x1, y1)
        x3, y3 = PIXEL_ROTATIONS[90](x2, y2)
        x4, y4 = PIXEL_ROTATIONS[90](x3, y3)
        assert (x4, y4) == (x, y)

    def test_180_equals_two_90s(self) -> None:
        """180 rotation equals two 90-degree rotations."""
        x, y = 15, 25
        via_180 = PIXEL_ROTATIONS[180](x, y)
        x1, y1 = PIXEL_ROTATIONS[90](x, y)
        via_90_90 = PIXEL_ROTATIONS[90](x1, y1)
        assert via_180 == via_90_90
