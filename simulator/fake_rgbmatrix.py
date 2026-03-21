"""Fake LED matrix implementation for the Mac Pygame simulator.

Redirects SetPixel calls to a pygame.Surface so that Board's rendering
methods work without any Pi hardware.
"""
from __future__ import annotations

import pygame


class FakeFrameCanvas:
    def __init__(self) -> None:
        self._surface = pygame.Surface((32, 32))

    def SetPixel(self, x: int, y: int, r: int, g: int, b: int) -> None:
        if 0 <= x < 32 and 0 <= y < 32:
            # pygame uses (col, row) — swap x/y
            self._surface.set_at((y, x), (r, g, b))

    def Clear(self) -> None:
        self._surface.fill((0, 0, 0))


class FakeRGBMatrixOptions:
    """Drop-in for RGBMatrixOptions — accepts all attribute assignments."""


class FakeRGBMatrix:
    SCALE = 30  # each 4×4 LED cell → 120×120 px; 32*30 = 960 px window

    def __init__(self, options=None) -> None:
        self._screen: pygame.Surface | None = None
        self._canvas = FakeFrameCanvas()

    def CreateFrameCanvas(self) -> FakeFrameCanvas:
        return self._canvas

    def SwapOnVSync(self, canvas: FakeFrameCanvas) -> FakeFrameCanvas:
        """No-op — callers continue writing to the same canvas after this."""
        return canvas

    def blit_to_screen(self) -> None:
        """Scale and blit the 32×32 LED surface to the pygame screen.
        Does NOT call pygame.display.flip() — caller controls when to present."""
        if self._screen is None:
            return
        scaled = pygame.transform.scale(
            self._canvas._surface,
            (32 * self.SCALE, 32 * self.SCALE),
        )
        self._screen.blit(scaled, (0, 0))

    def flip(self) -> None:
        """Scale, blit, and present to screen."""
        self.blit_to_screen()
        pygame.display.flip()
