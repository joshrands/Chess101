"""Fake LED matrix implementation for the Mac Pygame simulator.

Redirects SetPixel calls to a pygame.Surface so that Board's rendering
methods work without any Pi hardware.  Each LED pixel is rendered as a
round dot with a soft glow, matching the JS simulator's aesthetic.
"""
from __future__ import annotations

import pygame


class FakeFrameCanvas:
    """Simulated LED frame canvas backed by a 32x32 pygame.Surface."""

    def __init__(self) -> None:
        """Initialize a blank 32x32 surface."""
        self._surface = pygame.Surface((32, 32))

    def SetPixel(self, x: int, y: int, r: int, g: int, b: int) -> None:
        """Set one LED pixel on the surface.

        Args:
            x: Row index (0–31).
            y: Column index (0–31).
            r: Red channel (0–255).
            g: Green channel (0–255).
            b: Blue channel (0–255).
        """
        if 0 <= x < 32 and 0 <= y < 32:
            # pygame uses (col, row) — swap x/y
            self._surface.set_at((y, x), (r, g, b))

    def Clear(self) -> None:
        """Fill the entire surface with black (all LEDs off)."""
        self._surface.fill((0, 0, 0))


class FakeRGBMatrixOptions:
    """Drop-in for RGBMatrixOptions — accepts all attribute assignments silently."""


class FakeRGBMatrix:
    """Simulated RGBMatrix for the Mac Pygame simulator.

    Replaces the Pi's hardware RGBMatrix. Renders to a pygame.Surface
    with per-pixel LED dot rendering (round circles with glow) so each
    LED pixel looks like a real LED instead of a blocky scaled square.
    """

    SCALE = 30  # each LED pixel → 30×30 px region; 32*30 = 960 px window

    def __init__(self, options=None) -> None:
        """Initialize with no attached screen; caller must set _screen before rendering.

        Args:
            options: Ignored; present only for API compatibility.
        """
        self._screen: pygame.Surface | None = None
        self._canvas = FakeFrameCanvas()
        self._led_template: pygame.Surface | None = None
        self._tinted: pygame.Surface | None = None  # reusable scratch surface

    def _build_led_template(self) -> pygame.Surface:
        """Build a grayscale LED dot template with glow, body, and highlight.

        The template is a white-on-transparent surface that gets color-tinted
        per pixel via BLEND_RGB_MULT at render time.
        """
        s = self.SCALE
        surf = pygame.Surface((s, s), pygame.SRCALPHA)
        cx, cy = s // 2, s // 2

        # Soft outer glow
        glow_r = int(s * 0.48)
        pygame.draw.circle(surf, (255, 255, 255, 40), (cx, cy), glow_r)

        # Main LED body
        body_r = int(s * 0.38)
        pygame.draw.circle(surf, (255, 255, 255, 255), (cx, cy), body_r)

        return surf

    def CreateFrameCanvas(self) -> FakeFrameCanvas:
        """Return the single shared FakeFrameCanvas.

        Returns:
            The canvas instance used for all pixel writes.
        """
        return self._canvas

    def SwapOnVSync(self, canvas: FakeFrameCanvas) -> FakeFrameCanvas:
        """No-op — callers continue writing to the same canvas after this."""
        return canvas

    def blit_to_screen(self) -> None:
        """Render the 32×32 LED surface to the pygame screen as glowing dots.
        Does NOT call pygame.display.flip() — caller controls when to present."""
        if self._screen is None:
            return

        # Lazy-init the template (pygame must be initialized first)
        if self._led_template is None:
            self._led_template = self._build_led_template()
            self._tinted = self._led_template.copy()

        s = self.SCALE
        board_w = 32 * s
        board_h = 32 * s

        # Clear the board area to dark background
        pygame.draw.rect(self._screen, (5, 8, 16), (0, 0, board_w, board_h))

        raw = self._canvas._surface
        template = self._led_template
        tinted = self._tinted
        assert tinted is not None

        for ly in range(32):
            for lx in range(32):
                r, g, b, _a = raw.get_at((lx, ly))
                if r == 0 and g == 0 and b == 0:
                    continue
                # Tint the reusable scratch surface with this pixel's color
                tinted.blit(template, (0, 0))
                tinted.fill((r, g, b), special_flags=pygame.BLEND_RGB_MULT)
                self._screen.blit(tinted, (lx * s, ly * s))

    def flip(self) -> None:
        """Render LEDs, blit to the pygame screen, and present the frame."""
        self.blit_to_screen()
        pygame.display.flip()
