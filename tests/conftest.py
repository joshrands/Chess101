"""
conftest.py — shared fixtures and hardware stubs for Chess101 tests.

Hardware stubs MUST be inserted into sys.modules before any chess module is
imported, because Board.py and samplebase.py perform module-level imports of
rgbmatrix, and Master.py imports smbus.  Placing them here at module scope
ensures they exist before pytest collects any test file.
"""
import sys
import os
from unittest.mock import MagicMock
import pytest

# ── Hardware/external stubs (module-level so they exist before collection) ────

_mock_rgb = MagicMock()
sys.modules.setdefault("rgbmatrix", _mock_rgb)
sys.modules.setdefault("rgbmatrix.core", _mock_rgb)

_mock_smbus = MagicMock()
# read_byte must return an int so Master.update_row_states arithmetic doesn't crash
_mock_smbus.SMBus.return_value.read_byte.return_value = 0
sys.modules.setdefault("smbus", _mock_smbus)

sys.modules.setdefault("RPi", MagicMock())
sys.modules.setdefault("RPi.GPIO", MagicMock())

# Stub the Master modules so imports of Master resolve to MagicMock
# without touching real smbus at all.
_mock_master_mod = MagicMock()
sys.modules.setdefault("Master", _mock_master_mod)
sys.modules.setdefault("hardware.master", _mock_master_mod)

# ── Chess module imports (safe now that stubs are in place) ───────────────────

from Team import Team          # noqa: E402
from Cell import Cell          # noqa: E402
from Rook import Rook          # noqa: E402
from Bishop import Bishop      # noqa: E402
from Knight import Knight      # noqa: E402
from Pawn import Pawn          # noqa: E402
from Queen import Queen        # noqa: E402
from King import King          # noqa: E402

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def team_r():
    """Default team_r — blue, matching Board.py defaults."""
    return Team(64, 180, 232)


@pytest.fixture
def team_l():
    """Default team_l — orange, matching Board.py defaults."""
    return Team(255, 140, 0)


@pytest.fixture
def empty_board():
    """8×8 grid of None values (the standard board shape)."""
    return [[None] * 8 for _ in range(8)]


@pytest.fixture
def make_board():
    """
    Factory fixture.  Call make_board({(row, col): piece, ...}) to get an
    8×8 grid pre-populated with the given pieces.
    """
    def _factory(pieces):
        board = [[None] * 8 for _ in range(8)]
        for (row, col), piece in pieces.items():
            board[row][col] = piece
        return board
    return _factory


@pytest.fixture
def board_instance():
    """
    A Board object constructed with all hardware mocked out.
    canvas and matrix are MagicMocks so rendering methods don't crash.
    """
    from Board import Board

    b = Board()
    b.canvas = MagicMock()
    b.matrix = MagicMock()
    b.matrix.SwapOnVSync.return_value = MagicMock()
    b.master = MagicMock()
    b.master.get_cell_state.return_value = 0  # 0 = piece present
    return b


# ── Relay test fixtures ───────────────────────────────────────────────────────


def pytest_addoption(parser):
    parser.addoption(
        "--relay-docker",
        action="store_true",
        default=False,
        help="Run relay tests against a locally-built Docker container.",
    )


@pytest.fixture(scope="session")
def relay_docker_url():
    """Build chess101-relay Docker image once, run a container for the session.

    Only used when --relay-docker is passed.  Skips automatically if Docker
    is not available or the build fails.
    """
    import socket
    import subprocess
    import time
    import urllib.request

    sock = socket.socket()
    sock.bind(("", 0))
    port = sock.getsockname()[1]
    sock.close()

    result = subprocess.run(
        ["docker", "build", "-f", "Dockerfile.relay", "-t", "chess101-relay-test", "."],
        capture_output=True,
    )
    if result.returncode != 0:
        pytest.skip(f"Docker build failed:\n{result.stderr.decode()}")

    proc = subprocess.Popen(
        [
            "docker", "run", "--rm",
            "--name", f"chess101-relay-test-{port}",
            "-p", f"{port}:8765",
            "-e", "RELAY_PORT=8765",
            "-e", "RELAY_MAX_ROOMS=50",
            "-e", "RELAY_ROOM_TIMEOUT=600",
            "chess101-relay-test",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    deadline = time.time() + 20.0
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.3)
    else:
        proc.terminate()
        pytest.skip("Docker relay failed to start within 20s")

    yield f"ws://127.0.0.1:{port}"

    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture
def relay_url(request, monkeypatch):
    """Relay WebSocket URL for relay protocol tests.

    Modes (checked in order):
      1. RELAY_URL env var  — point at any running relay (live or Docker)
      2. --relay-docker      — use the session-scoped Docker container
      3. default             — spin up an in-process relay on a random port

    In in-process mode the module-level ``_rooms`` dict is reset between
    tests so each test starts with a clean relay state.
    """
    import asyncio
    import os
    import socket
    import threading

    import websockets

    live = os.environ.get("RELAY_URL")
    if live:
        yield live
        return

    if request.config.getoption("--relay-docker", default=False):
        yield request.getfixturevalue("relay_docker_url")
        return

    # ── In-process relay ────────────────────────────────────────────────────
    import network.relay as relay_mod

    monkeypatch.setattr(relay_mod, "_rooms", {})

    sock = socket.socket()
    sock.bind(("", 0))
    port = sock.getsockname()[1]
    sock.close()

    ready = threading.Event()
    loop = asyncio.new_event_loop()
    stop_holder: list = []

    async def _serve() -> None:
        stop_event = asyncio.Event()
        stop_holder.append(stop_event)
        async with websockets.serve(
            relay_mod._handle,
            "127.0.0.1",
            port,
            process_request=relay_mod._process_request,
        ):
            ready.set()
            await stop_event.wait()

    threading.Thread(
        target=lambda: loop.run_until_complete(_serve()),
        daemon=True,
    ).start()
    assert ready.wait(timeout=5.0), "In-process relay failed to start"

    yield f"ws://127.0.0.1:{port}"

    if stop_holder:
        loop.call_soon_threadsafe(stop_holder[0].set)
