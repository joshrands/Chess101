"""HIL (Hardware-In-The-Loop) integration tests.

Tests the HIL infrastructure locally (without Docker) to verify:
- HilSensor correctly implements BoardSensor
- HilRGBMatrix captures frames on SwapOnVSync
- ControlServer responds to JSON-RPC commands
"""
from __future__ import annotations

import json
import sys
import threading
import time
import types
from typing import TYPE_CHECKING

import pytest

# Inject mocks before importing game code
if "rgbmatrix" not in sys.modules:
    from hil.rgbmatrix import HilRGBMatrix, HilFrameCanvas, HilRGBMatrixOptions
    _rmod = types.ModuleType("rgbmatrix")
    _rmod.RGBMatrix = HilRGBMatrix
    _rmod.RGBMatrixOptions = HilRGBMatrixOptions
    _rmod.FrameCanvas = HilFrameCanvas
    sys.modules["rgbmatrix"] = sys.modules["rgbmatrix.core"] = _rmod

if "smbus" not in sys.modules:
    _smbus = types.ModuleType("smbus")
    class _SMBus:
        def __init__(self, *a, **kw): pass
        def read_byte(self, *a, **kw): return 0
        def write_byte(self, *a, **kw): pass
    _smbus.SMBus = _SMBus
    sys.modules["smbus"] = _smbus

from hil.sensor import HilSensor
from hil.rgbmatrix import HilRGBMatrix
from hil.control_server import ControlServer
from core.constants import CellOccupancy


class TestHilSensor:
    """Test HilSensor BoardSensor implementation."""

    def test_initial_state_is_empty(self) -> None:
        sensor = HilSensor()
        for row in range(8):
            for col in range(8):
                assert sensor.get_cell_state(row, col) == CellOccupancy.EMPTY

    def test_inject_piece(self) -> None:
        sensor = HilSensor()
        sensor.inject_state(3, 4, occupied=True)
        assert sensor.get_cell_state(3, 4) == CellOccupancy.OCCUPIED
        sensor.inject_state(3, 4, occupied=False)
        assert sensor.get_cell_state(3, 4) == CellOccupancy.EMPTY

    def test_starting_position(self) -> None:
        sensor = HilSensor()
        sensor.set_starting_position()
        # Back ranks should be occupied
        for col in range(8):
            assert sensor.get_cell_state(0, col) == CellOccupancy.OCCUPIED
            assert sensor.get_cell_state(1, col) == CellOccupancy.OCCUPIED
            assert sensor.get_cell_state(6, col) == CellOccupancy.OCCUPIED
            assert sensor.get_cell_state(7, col) == CellOccupancy.OCCUPIED
        # Middle ranks should be empty
        for row in range(2, 6):
            for col in range(8):
                assert sensor.get_cell_state(row, col) == CellOccupancy.EMPTY

    def test_grid_snapshot(self) -> None:
        sensor = HilSensor()
        sensor.inject_state(0, 0, occupied=True)
        sensor.inject_state(7, 7, occupied=True)
        grid = sensor.get_grid_snapshot()
        assert grid[0][0] == CellOccupancy.OCCUPIED
        assert grid[7][7] == CellOccupancy.OCCUPIED
        assert grid[4][4] == CellOccupancy.EMPTY
        # Verify it's a copy
        grid[0][0] = CellOccupancy.EMPTY
        assert sensor.get_cell_state(0, 0) == CellOccupancy.OCCUPIED

    def test_read_data_is_noop(self) -> None:
        sensor = HilSensor()
        sensor.inject_state(2, 3, occupied=True)
        sensor.read_data()  # Should not change state
        assert sensor.get_cell_state(2, 3) == CellOccupancy.OCCUPIED


class TestHilRGBMatrix:
    """Test HilRGBMatrix frame capture."""

    def test_set_pixel_and_capture(self) -> None:
        matrix = HilRGBMatrix()
        canvas = matrix.CreateFrameCanvas()
        # SetPixel(x=row, y=col) - codebase convention
        canvas.SetPixel(10, 20, 255, 128, 64)  # row=10, col=20
        matrix.SwapOnVSync(canvas)
        frame, timestamp = matrix.get_last_frame()
        assert frame is not None
        # frame is stored as [row][col] = [x][y]
        assert frame[10][20] == (255, 128, 64)
        assert timestamp > 0

    def test_clear(self) -> None:
        matrix = HilRGBMatrix()
        canvas = matrix.CreateFrameCanvas()
        canvas.SetPixel(5, 5, 100, 100, 100)  # row=5, col=5
        canvas.Clear()
        matrix.SwapOnVSync(canvas)
        frame, _ = matrix.get_last_frame()
        assert frame[5][5] == (0, 0, 0)

    def test_frame_count(self) -> None:
        matrix = HilRGBMatrix()
        canvas = matrix.CreateFrameCanvas()
        assert matrix.get_frame_count() == 0
        matrix.SwapOnVSync(canvas)
        assert matrix.get_frame_count() == 1
        matrix.SwapOnVSync(canvas)
        assert matrix.get_frame_count() == 2

    def test_frame_callback(self) -> None:
        matrix = HilRGBMatrix()
        canvas = matrix.CreateFrameCanvas()
        received_frames: list = []

        def callback(frame, timestamp):
            received_frames.append((frame, timestamp))

        matrix.subscribe_frames(callback)
        canvas.SetPixel(0, 0, 1, 2, 3)
        matrix.SwapOnVSync(canvas)

        assert len(received_frames) == 1
        assert received_frames[0][0][0][0] == (1, 2, 3)

    def test_pixel_bounds(self) -> None:
        matrix = HilRGBMatrix()
        canvas = matrix.CreateFrameCanvas()
        # Out of bounds should not crash
        canvas.SetPixel(-1, 0, 255, 0, 0)
        canvas.SetPixel(0, 32, 255, 0, 0)
        canvas.SetPixel(32, 0, 255, 0, 0)
        matrix.SwapOnVSync(canvas)
        # Should complete without error


_next_port = 38766  # Start high to avoid conflicts


class TestControlServer:
    """Test ControlServer JSON-RPC interface."""

    @pytest.fixture
    def server_fixture(self):
        """Start a control server on a unique port."""
        global _next_port
        port = _next_port
        _next_port += 1

        sensor = HilSensor()
        matrix = HilRGBMatrix()
        # Set a pixel so get_frame returns data
        # SetPixel(x=row, y=col) - codebase convention
        canvas = matrix.CreateFrameCanvas()
        canvas.SetPixel(1, 2, 10, 20, 30)  # row=1, col=2
        matrix.SwapOnVSync(canvas)

        server = ControlServer(sensor, matrix, port=port)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        time.sleep(0.3)  # Let server start
        yield sensor, matrix, server, port
        # Server thread is daemon, will die with test

    def _call_rpc(self, port: int, method: str, params: dict = None, req_id: int = 1) -> dict:
        """Helper to make sync WebSocket RPC call."""
        import asyncio
        import websockets

        async def _do_call():
            async with websockets.connect(f"ws://localhost:{port}") as ws:
                await ws.send(json.dumps({
                    "method": method,
                    "params": params or {},
                    "id": req_id
                }))
                return json.loads(await ws.recv())

        return asyncio.get_event_loop().run_until_complete(_do_call())

    def test_ping(self, server_fixture) -> None:
        sensor, matrix, server, port = server_fixture
        resp = self._call_rpc(port, "ping", req_id=1)
        assert resp["result"] == "pong"
        assert resp["id"] == 1

    def test_reed_switch(self, server_fixture) -> None:
        sensor, matrix, server, port = server_fixture
        resp = self._call_rpc(port, "reed_switch", {"row": 5, "col": 6, "state": "placed"}, 2)
        assert resp["result"] == "ok"
        assert sensor.get_cell_state(5, 6) == CellOccupancy.OCCUPIED

    def test_get_frame(self, server_fixture) -> None:
        sensor, matrix, server, port = server_fixture
        resp = self._call_rpc(port, "get_frame", req_id=3)
        assert resp["result"] is not None
        # Fixture sets SetPixel(row=1, col=2), stored as pixels[row][col] = pixels[1][2]
        assert resp["result"]["pixels"][1][2] == [10, 20, 30]

    def test_get_sensor_state(self, server_fixture) -> None:
        sensor, matrix, server, port = server_fixture
        sensor.inject_state(7, 0, occupied=True)
        resp = self._call_rpc(port, "get_sensor_state", req_id=4)
        assert resp["result"]["grid"][7][0] == CellOccupancy.OCCUPIED

    def test_set_starting_position(self, server_fixture) -> None:
        sensor, matrix, server, port = server_fixture
        resp = self._call_rpc(port, "set_starting_position", req_id=5)
        assert resp["result"] == "ok"
        assert sensor.get_cell_state(0, 0) == CellOccupancy.OCCUPIED
        assert sensor.get_cell_state(4, 4) == CellOccupancy.EMPTY


class TestChessMatrixOrientation:
    """Test ChessMatrix rendering via HIL.

    These tests verify ChessMatrix renders correctly in the HIL environment.
    The actual Pi transposition bug needs investigation - it only affects
    ChessMatrix in online host mode on Pi, not the simulator or other LED rendering.
    """

    def test_chessmatrix_renders_anchors(self) -> None:
        """Verify ChessMatrix anchors render at expected positions.

        ChessMatrix anchor positions (board cells):
        - K (black): (1, 1)
        - R (red):   (1, 6)
        - G (green): (6, 1)
        - B (blue):  (6, 6)

        Each board cell maps to a 4x4 LED block.
        """
        from network.chessmatrix import encode, render_to_led
        from hil.rgbmatrix import HilFrameCanvas

        canvas = HilFrameCanvas()
        grid = encode("AAAAAA")
        render_to_led(grid, canvas)

        pixels = canvas.get_snapshot()

        # With codebase convention (SetPixel(row, col)), cell (r, c) maps to pixels[r*4:r*4+4][c*4:c*4+4]
        # K anchor at board (1,1) → pixels[4][4]
        k_pixel = pixels[4][4]
        assert k_pixel[0] < 50, f"K anchor should be dark, got {k_pixel}"

        # R anchor at board (1,6) → pixels[4][24]
        r_pixel = pixels[4][24]
        assert r_pixel[0] > 150, f"R anchor should be red, got {r_pixel}"

        # G anchor at board (6,1) → pixels[24][4]
        g_pixel = pixels[24][4]
        assert g_pixel[1] > 100, f"G anchor should be green, got {g_pixel}"

        # B anchor at board (6,6) → pixels[24][24]
        b_pixel = pixels[24][24]
        assert b_pixel[2] > 150, f"B anchor should be blue, got {b_pixel}"
