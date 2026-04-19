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
        "--hil-docker",
        action="store_true",
        default=False,
        help="Run HIL tests against the ARM64 Docker container (requires QEMU).",
    )


@pytest.fixture(scope="session")
def relay_docker_url():
    """Build chess101-relay Docker image once, run a container for the session.

    Skips automatically if Docker is not available or the build fails.
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

    container_name = f"chess101-relay-test-{port}"
    proc = subprocess.Popen(
        [
            "docker", "run", "--rm",
            "--name", container_name,
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
        subprocess.run(["docker", "kill", container_name], capture_output=True)
        pytest.skip("Docker relay failed to start within 20s")

    yield f"ws://127.0.0.1:{port}"

    subprocess.run(["docker", "kill", container_name], capture_output=True)


@pytest.fixture
def relay_url(request):
    """Relay WebSocket URL for relay protocol tests.

    Modes (checked in order):
      1. RELAY_URL env var  — point at any running relay (live or Docker)
      2. default            — build and use session-scoped Docker container

    No in-process fallback. Tests require Docker or an external relay.
    """
    import os

    live = os.environ.get("RELAY_URL")
    if live:
        yield live
        return

    # Default: use Docker container
    yield request.getfixturevalue("relay_docker_url")


# ── HIL Docker fixtures ──────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def hil_docker_url(request):
    """Build chess101-hil Docker image, run container for the session.

    Only used when --hil-docker is passed. Requires QEMU for ARM64 emulation.
    The container takes several minutes to build on first run due to
    Python 3.9 compilation.

    Skips if:
      - Docker is not available
      - QEMU is not set up for ARM64
      - The build fails
    """
    if not request.config.getoption("--hil-docker", default=False):
        pytest.skip("HIL Docker tests require --hil-docker flag")

    import socket
    import subprocess
    import time

    # Find a free port
    sock = socket.socket()
    sock.bind(("", 0))
    port = sock.getsockname()[1]
    sock.close()

    # Check Docker is available
    result = subprocess.run(["docker", "version"], capture_output=True)
    if result.returncode != 0:
        pytest.skip("Docker not available")

    # Enable QEMU for ARM64 (idempotent)
    subprocess.run(
        ["docker", "run", "--rm", "--privileged",
         "multiarch/qemu-user-static", "--reset", "-p", "yes"],
        capture_output=True,
    )

    # Build the HIL image (may take 15-20 minutes on first run due to OpenSSL + Python)
    print("\nBuilding HIL Docker image (this may take a while on first run)...")
    result = subprocess.run(
        ["docker", "buildx", "build",
         "--platform", "linux/arm64",
         "-f", "hil/Dockerfile",
         "-t", "chess101-hil-test",
         "--load",
         "."],
        capture_output=True,
        timeout=2400,  # 40 minute timeout for build (OpenSSL + Python compilation)
    )
    if result.returncode != 0:
        pytest.skip(f"HIL Docker build failed:\n{result.stderr.decode()[:500]}")

    # Run the container
    container_name = f"chess101-hil-test-{port}"
    proc = subprocess.Popen(
        [
            "docker", "run", "--rm",
            "--platform", "linux/arm64",
            "--name", container_name,
            "-p", f"{port}:8766",
            "-e", "HIL_PORT=8766",
            "-e", "HIL_FAST_MODE=1",
            "chess101-hil-test",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for container to be ready (WebSocket accepting connections)
    deadline = time.time() + 60.0  # ARM64 emulation is slow
    url = f"ws://127.0.0.1:{port}"
    while time.time() < deadline:
        try:
            import asyncio
            import websockets

            async def _check():
                async with websockets.connect(url, open_timeout=2):
                    pass

            asyncio.get_event_loop().run_until_complete(_check())
            break
        except Exception:
            if proc.poll() is not None:
                stderr = proc.stderr.read().decode() if proc.stderr else ""
                pytest.skip(f"HIL container exited early:\n{stderr[:500]}")
            time.sleep(1.0)
    else:
        proc.terminate()
        pytest.skip("HIL container failed to start within 60s")

    yield url

    # Cleanup
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", container_name], capture_output=True)


@pytest.fixture
def hil_bridge(request):
    """HilBridge connected to the HIL Docker container.

    Requires --hil-docker flag. Uses the session-scoped hil_docker_url fixture.
    """
    from hil.client import HilBridge

    url = request.getfixturevalue("hil_docker_url")
    bridge = HilBridge(url=url, timeout=30.0)
    bridge.connect(retries=3, delay=2.0)

    yield bridge

    bridge.close()
