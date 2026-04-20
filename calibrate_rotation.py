#!/usr/bin/env python3
"""Rotation calibration tool.

Lights up one board row at a time on the LED matrix and prints which
logical row the reed switches report when a piece is placed. Run with
different --display-rotation and --sensor-rotation values until the
highlighted row matches the reported row.

Usage:
    sudo .venv/bin/python3.9 calibrate_rotation.py --led-no-hardware-pulse 1
    sudo .venv/bin/python3.9 calibrate_rotation.py --display-rotation 270 --sensor-rotation 90 --led-no-hardware-pulse 1

Press Enter to advance to the next row. Ctrl-C to quit.
"""
import argparse
import sys
import time

sys.path.insert(0, ".")

from samplebase import SampleBase
from hardware.rotation import PIXEL_ROTATIONS, CELL_ROTATIONS, RotatingMatrix
import smbus

COLORS = [
    (255, 0,   0),
    (255, 165, 0),
    (255, 255, 0),
    (0,   255, 0),
    (0,   0,   255),
    (75,  0,   130),
    (238, 130, 238),
    (255, 255, 255),
]

ROW_ADDRESSES = [0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b]


def read_grid(bus):
    grid = [[0] * 8 for _ in range(8)]
    for i, addr in enumerate(ROW_ADDRESSES):
        try:
            bus.write_byte(addr, 42)
            time.sleep(0.01)
            val = bus.read_byte(addr)
        except IOError:
            continue
        for j in range(8):
            grid[i][j] = 1 if (val & (1 << j)) else 0
    return grid


def find_occupied(grid, cell_rot):
    occupied = []
    for r in range(8):
        for c in range(8):
            rr, rc = cell_rot(r, c)
            if grid[rc][rr] == 0:
                occupied.append((r, c))
    return occupied


class CalibrationApp(SampleBase):
    def __init__(self, display_rotation, sensor_rotation, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.display_rotation = display_rotation
        self.sensor_rotation = sensor_rotation

    def run(self, *args, **kwargs):
        self.matrix = RotatingMatrix(self.matrix, rotation=self.display_rotation)
        canvas = self.matrix.CreateFrameCanvas()

        cell_rot = CELL_ROTATIONS.get(self.sensor_rotation % 360, CELL_ROTATIONS[0])

        try:
            bus = smbus.SMBus(1)
        except Exception as e:
            print(f"Could not open I2C bus: {e}")
            bus = None

        print(f"\nDisplay rotation: {self.display_rotation}°  |  Sensor rotation: {self.sensor_rotation}°")
        print("Place a piece on the highlighted row, then press Enter.\n")

        for row in range(8):
            r, g, b = COLORS[row]

            canvas.Clear()
            for col in range(8):
                for dy in range(4):
                    for dx in range(4):
                        canvas.SetPixel(col * 4 + dx, row * 4 + dy, r, g, b)
            canvas = self.matrix.SwapOnVSync(canvas)

            print(f"Row {row} lit ({r},{g},{b}) — place piece and press Enter: ", end="", flush=True)
            input()

            if bus:
                grid = read_grid(bus)
                occupied = find_occupied(grid, cell_rot)
                if occupied:
                    print(f"  Sensor sees piece at logical: {occupied}")
                else:
                    print("  Sensor sees no piece.")
            print()

        canvas.Clear()
        self.matrix.SwapOnVSync(canvas)
        print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rotation calibration tool")
    parser.add_argument("--display-rotation", type=int, default=270,
                        choices=[0, 90, 180, 270])
    parser.add_argument("--sensor-rotation", type=int, default=270,
                        choices=[0, 90, 180, 270])
    args, remaining = parser.parse_known_args()

    sys.argv = [sys.argv[0]] + remaining

    app = CalibrationApp(args.display_rotation, args.sensor_rotation)
    app.process()
