"""Headless LED matrix mock with frame capture for HIL testing.

HilRGBMatrix provides the same API as FakeRGBMatrix but captures frames
to memory instead of rendering to pygame, enabling external inspection.

Set HIL_REAL_PI_MODE=1 environment variable to use the real Pi rgbmatrix
convention (x=col, y=row) instead of the codebase convention (x=row, y=col).
This reveals the transpose bug that exists on the real hardware.
"""
from __future__ import annotations

import os
import time
from threading import Lock
from typing import Callable, Tuple

# If True, use real Pi rgbmatrix convention (x=col, y=row)
# If False, use codebase/simulator convention (x=row, y=col)
REAL_PI_MODE = os.environ.get("HIL_REAL_PI_MODE", "0") == "1"

FrameCallback = Callable[[list[list[Tuple[int, int, int]]], float], None]


class HilFrameCanvas:
    """Headless LED frame canvas - 32x32 pixel buffer."""

    def __init__(self) -> None:
        """Initialize a blank 32x32 black canvas."""
        self._pixels: list[list[Tuple[int, int, int]]] = [
            [(0, 0, 0)] * 32 for _ in range(32)
        ]
        self._lock = Lock()

    def SetPixel(self, x: int, y: int, r: int, g: int, b: int) -> None:
        """Set one LED pixel.

        Convention depends on HIL_REAL_PI_MODE environment variable:
        - HIL_REAL_PI_MODE=0 (default): codebase convention (x=row, y=col)
        - HIL_REAL_PI_MODE=1: real Pi rgbmatrix convention (x=col, y=row)

        Args:
            x: Row index (codebase) or Column index (real Pi).
            y: Column index (codebase) or Row index (real Pi).
            r: Red channel (0-255).
            g: Green channel (0-255).
            b: Blue channel (0-255).
        """
        if 0 <= x < 32 and 0 <= y < 32:
            with self._lock:
                if REAL_PI_MODE:
                    # Real Pi convention: x=col, y=row
                    # Codebase calls SetPixel(row, col), so store at [col][row] = [x][y]
                    # Wait, that's the same... let me think.
                    # Real lib: SetPixel(x, y) where x=horizontal, y=vertical
                    # So pixel at screen (x, y) = (col, row)
                    # Codebase calls SetPixel(row, col)
                    # Real lib interprets as SetPixel(x=row, y=col) → screen pos (row, col)
                    # Which means row controls horizontal (x), col controls vertical (y)
                    # To store for display: pixels[visual_row][visual_col] = pixels[y][x] = pixels[col][row]
                    self._pixels[y][x] = (r, g, b)
                else:
                    # Codebase/simulator convention: x=row, y=col
                    # Store at [row][col] = [x][y]
                    self._pixels[x][y] = (r, g, b)

    def Clear(self) -> None:
        """Set all pixels to black (all LEDs off)."""
        with self._lock:
            for row in range(32):
                for col in range(32):
                    self._pixels[row][col] = (0, 0, 0)

    def get_snapshot(self) -> list[list[Tuple[int, int, int]]]:
        """Return a copy of current pixel state.

        Returns:
            32x32 list of (r, g, b) tuples.
        """
        with self._lock:
            return [row[:] for row in self._pixels]


class HilRGBMatrixOptions:
    """Drop-in for RGBMatrixOptions - accepts all attribute assignments."""

    def __setattr__(self, name: str, value: object) -> None:
        pass


class HilRGBMatrix:
    """Headless LED matrix with frame capture for HIL testing.

    Captures frames on SwapOnVSync and notifies subscribers so tests
    can verify LED output without a display.
    """

    def __init__(self, options: object = None) -> None:
        """Initialize the matrix with no subscribers.

        Args:
            options: Ignored; present only for API compatibility.
        """
        self._canvas = HilFrameCanvas()
        self._frame_callbacks: list[FrameCallback] = []
        self._lock = Lock()
        self._last_frame: list[list[Tuple[int, int, int]]] | None = None
        self._last_frame_time: float = 0.0
        self._frame_count: int = 0

    def CreateFrameCanvas(self) -> HilFrameCanvas:
        """Return the single shared HilFrameCanvas.

        Returns:
            The canvas instance used for all pixel writes.
        """
        return self._canvas

    def SwapOnVSync(self, canvas: HilFrameCanvas) -> HilFrameCanvas:
        """Capture the current frame and notify subscribers.

        This is the double-buffer swap point where a new frame is "presented".
        We capture the frame here and notify any subscribed callbacks.

        Args:
            canvas: The canvas being swapped (returned unchanged).

        Returns:
            The same canvas for continued rendering.
        """
        frame = canvas.get_snapshot()
        timestamp = time.monotonic()

        with self._lock:
            self._last_frame = frame
            self._last_frame_time = timestamp
            self._frame_count += 1
            callbacks = self._frame_callbacks[:]

        for cb in callbacks:
            try:
                cb(frame, timestamp)
            except Exception:
                pass

        return canvas

    def subscribe_frames(self, callback: FrameCallback) -> None:
        """Register a callback to receive frames on SwapOnVSync.

        Args:
            callback: Function(frame, timestamp) called on each frame.
        """
        with self._lock:
            self._frame_callbacks.append(callback)

    def unsubscribe_frames(self, callback: FrameCallback) -> None:
        """Remove a frame callback.

        Args:
            callback: Previously registered callback to remove.
        """
        with self._lock:
            if callback in self._frame_callbacks:
                self._frame_callbacks.remove(callback)

    def get_last_frame(self) -> tuple[list[list[Tuple[int, int, int]]] | None, float]:
        """Get the most recently captured frame.

        Returns:
            Tuple of (frame or None, timestamp). Frame is a 32x32 RGB grid.
        """
        with self._lock:
            return self._last_frame, self._last_frame_time

    def get_frame_count(self) -> int:
        """Return total number of frames captured since init."""
        with self._lock:
            return self._frame_count
