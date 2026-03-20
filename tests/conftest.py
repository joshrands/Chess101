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

# Stub the entire Master module so Board.py's "from Master import Master"
# resolves to a MagicMock class without touching real smbus at all.
_mock_master_mod = MagicMock()
sys.modules.setdefault("Master", _mock_master_mod)

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
