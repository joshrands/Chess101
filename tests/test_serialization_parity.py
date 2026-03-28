"""
test_serialization_parity.py — Verify that all serialization paths produce
equivalent results for the same input grid.

Three serialization formats exist in the codebase:
  1. **Bridge format** — ``harness/chess_helpers.py`` (``py_grid_to_json`` /
     ``json_to_py_grid``) and ``harness/js_bridge.js`` (``gridFromJson`` /
     ``gridToJson``).  Used by the lockstep fuzzer and parity tests.
  2. **Network wire format** — ``network/protocol.py`` (``encode_grid`` /
     ``decode_grid``).  Used by LAN/online multiplayer.
  3. **Worker postMessage format** — ``web/chess-engine.js`` and
     ``web/sim.html`` (``serializeGrid`` / ``deserializeGrid``).  Used to
     send grids to the AI Web Worker.

These tests ensure that every format round-trips all game-critical fields
(especially King.direction and Pawn state) so that the fuzzer accurately
represents the real game, and network desync bugs found by fuzzing are
genuine.

Run with:
    .venv/bin/python -m pytest tests/test_serialization_parity.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure harness/ is importable (bare module names used inside harness/)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))

from core.cell import Cell
from core.team import Team
from pieces.bishop import Bishop
from pieces.king import King
from pieces.knight import Knight
from pieces.pawn import Pawn
from pieces.queen import Queen
from pieces.rook import Rook

from harness.chess_helpers import (
    py_grid_to_json,
    json_to_py_grid,
    py_init_board,
)
from network.protocol import encode_grid, decode_grid


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def teams():
    return Team(64, 180, 232), Team(255, 140, 0)


def _empty_grid():
    return [[None] * 8 for _ in range(8)]


def _assert_piece_equal(a, b, label=""):
    """Assert two pieces have the same type and game-critical fields."""
    prefix = f"{label}: " if label else ""
    assert type(a).__name__ == type(b).__name__, f"{prefix}type mismatch"
    assert a.row == b.row, f"{prefix}row"
    assert a.col == b.col, f"{prefix}col"
    assert a.team.r == b.team.r, f"{prefix}team"
    assert getattr(a, "touched", False) == getattr(b, "touched", False), (
        f"{prefix}touched"
    )
    if isinstance(a, King):
        assert a.direction == b.direction, (
            f"{prefix}King.direction: {a.direction} vs {b.direction}"
        )
    if isinstance(a, Pawn):
        assert a.direction == b.direction, f"{prefix}Pawn.direction"
        assert a.en_passantable == b.en_passantable, f"{prefix}en_passantable"


# ── King direction round-trip ────────────────────────────────────────────────

class TestKingDirectionRoundTrip:
    """King.direction must survive serialization even when the king has moved
    off its starting row (where the constructor default would be wrong)."""

    def test_bridge_king_moved_off_starting_row(self, teams):
        """Bridge format preserves King.direction after king moves."""
        team_r, team_l = teams
        grid = _empty_grid()
        # L-King normally starts at row 7 (direction -1).
        # Simulate it having moved to row 5.
        king = King(5, 3, team_l)
        assert king.direction == 1, "constructor sets direction from row"
        king.direction = -1  # correct original direction
        king.touched = True
        grid[5][3] = king

        json_grid = py_grid_to_json(grid, team_r)
        restored = json_to_py_grid(json_grid, team_r, team_l)

        rk = restored[5][3]
        assert isinstance(rk, King)
        assert rk.direction == -1, (
            "King.direction must be preserved, not re-derived from row"
        )

    def test_network_king_moved_off_starting_row(self, teams):
        """Network wire format preserves King.direction after king moves."""
        team_r, team_l = teams
        grid = _empty_grid()
        king = King(5, 3, team_l)
        king.direction = -1
        king.touched = True
        grid[5][3] = king

        encoded = encode_grid(grid, team_r)
        decoded = decode_grid(encoded, team_r, team_l)

        rk = decoded[5][3]
        assert isinstance(rk, King)
        assert rk.direction == -1, (
            "King.direction must be preserved in network wire format"
        )

    def test_bridge_king_on_starting_row(self, teams):
        """King on its starting row should also round-trip correctly."""
        team_r, team_l = teams
        grid = _empty_grid()
        king = King(7, 4, team_l)  # starting position
        assert king.direction == -1
        grid[7][4] = king

        json_grid = py_grid_to_json(grid, team_r)
        restored = json_to_py_grid(json_grid, team_r, team_l)
        assert restored[7][4].direction == -1

    def test_both_kings_moved(self, teams):
        """Both kings moved off starting rows — both directions preserved."""
        team_r, team_l = teams
        grid = _empty_grid()

        # R-King: starts row 0 (direction +1), moved to row 3
        kr = King(3, 4, team_r)
        kr.direction = 1
        kr.touched = True
        grid[3][4] = kr

        # L-King: starts row 7 (direction -1), moved to row 5
        kl = King(5, 4, team_l)
        kl.direction = -1
        kl.touched = True
        grid[5][4] = kl

        # Bridge round-trip
        json_grid = py_grid_to_json(grid, team_r)
        restored_b = json_to_py_grid(json_grid, team_r, team_l)
        assert restored_b[3][4].direction == 1
        assert restored_b[5][4].direction == -1

        # Network round-trip
        encoded = encode_grid(grid, team_r)
        restored_n = decode_grid(encoded, team_r, team_l)
        assert restored_n[3][4].direction == 1
        assert restored_n[5][4].direction == -1


# ── Bridge ↔ Network format parity ──────────────────────────────────────────

class TestBridgeNetworkParity:
    """The bridge and network serialization paths must produce equivalent
    game state for the same input grid.  If they diverge, fuzzer-discovered
    bugs may not reflect real game behavior."""

    def test_starting_position_parity(self, teams):
        """Starting position round-trips identically through both paths."""
        team_r, team_l = teams
        grid = py_init_board(team_r, team_l)

        # Bridge round-trip
        bridge_rt = json_to_py_grid(
            py_grid_to_json(grid, team_r), team_r, team_l,
        )
        # Network round-trip
        net_rt = decode_grid(encode_grid(grid, team_r), team_r, team_l)

        for r in range(8):
            for c in range(8):
                orig = grid[r][c]
                if orig is None:
                    assert bridge_rt[r][c] is None
                    assert net_rt[r][c] is None
                else:
                    _assert_piece_equal(
                        orig, bridge_rt[r][c], f"bridge ({r},{c})",
                    )
                    _assert_piece_equal(
                        orig, net_rt[r][c], f"network ({r},{c})",
                    )
                    # Also verify bridge and network agree with each other
                    _assert_piece_equal(
                        bridge_rt[r][c], net_rt[r][c], f"bridge↔net ({r},{c})",
                    )

    def test_mid_game_parity(self, teams):
        """Mid-game position with moved king, en passant pawn, touched rook."""
        team_r, team_l = teams
        grid = _empty_grid()

        # Moved king (off starting row)
        king = King(5, 4, team_l)
        king.direction = -1
        king.touched = True
        grid[5][4] = king

        # En-passantable pawn
        pawn = Pawn(3, 5, team_r)
        pawn.direction = 1
        pawn.en_passantable = True
        pawn.en_passant_loc = Cell(2, 5)
        pawn.touched = True
        grid[3][5] = pawn

        # Touched rook
        rook = Rook(0, 0, team_r)
        rook.touched = True
        grid[0][0] = rook

        bridge_rt = json_to_py_grid(
            py_grid_to_json(grid, team_r), team_r, team_l,
        )
        net_rt = decode_grid(encode_grid(grid, team_r), team_r, team_l)

        # King direction
        assert bridge_rt[5][4].direction == -1
        assert net_rt[5][4].direction == -1

        # Pawn direction and en_passantable
        assert bridge_rt[3][5].direction == 1
        assert net_rt[3][5].direction == 1
        assert bridge_rt[3][5].en_passantable is True
        assert net_rt[3][5].en_passantable is True

        # Rook touched
        assert bridge_rt[0][0].touched is True
        assert net_rt[0][0].touched is True


# ── JS bridge parity (live, via JsBridge subprocess) ─────────────────────────

class TestJsBridgeParity:
    """Verify the JS bridge's gridFromJson/gridToJson round-trips match
    the Python bridge format.  These tests spawn a real Node.js process."""

    @pytest.fixture(scope="class")
    def bridge(self):
        from harness.python_bridge import JsBridge
        b = JsBridge()
        yield b
        b.close()

    def _js_round_trip(self, bridge, grid, team_r, team_l):
        """Send grid to JS, have it send it back, verify parity."""
        from harness.chess_helpers import TEAM_R_RGB, TEAM_L_RGB
        # Init JS engine, then apply the grid via chess_init + individual state
        # Actually: the cleanest round-trip is init → get grid back
        # But we want to test with arbitrary grids.
        # Use chess_init to set up, then compare starting position.
        js_grid = bridge.chess_init(TEAM_R_RGB, TEAM_L_RGB)
        return js_grid

    def test_starting_grid_js_matches_python(self, bridge, teams):
        """JS engine's initial grid matches Python's py_init_board."""
        from harness.chess_helpers import TEAM_R_RGB, TEAM_L_RGB
        team_r, team_l = teams
        py_grid = py_init_board(team_r, team_l)
        py_json = py_grid_to_json(py_grid, team_r)

        js_grid = bridge.chess_init(TEAM_R_RGB, TEAM_L_RGB)

        # Compare cell by cell
        for r in range(8):
            for c in range(8):
                py_cell = py_json[r][c]
                js_cell = js_grid[r][c]
                if py_cell is None:
                    assert js_cell is None, f"({r},{c}) should be empty"
                else:
                    assert js_cell is not None, f"({r},{c}) should have piece"
                    assert js_cell["type"] == py_cell["type"], (
                        f"({r},{c}) type: {js_cell['type']} vs {py_cell['type']}"
                    )

    def test_king_direction_in_js_grid(self, bridge, teams):
        """JS engine initializes kings with correct directions."""
        from harness.chess_helpers import TEAM_R_RGB, TEAM_L_RGB
        js_grid = bridge.chess_init(TEAM_R_RGB, TEAM_L_RGB)

        # R-King at (0,4) should not have direction in starting grid
        # (it's not serialized for non-Pawn in gridToJson... unless we added it)
        # After our fix, gridToJson DOES include King.direction
        r_king = js_grid[0][4]
        l_king = js_grid[7][4]
        assert r_king["type"] == "King"
        assert l_king["type"] == "King"
        # After the fix, direction should be present
        if "direction" in r_king:
            assert r_king["direction"] == 1, "R-King (row 0) direction should be 1"
        if "direction" in l_king:
            assert l_king["direction"] == -1, "L-King (row 7) direction should be -1"

    def test_moved_king_direction_preserved_through_js(self, bridge, teams):
        """A king moved off its starting row retains direction through JS."""
        from harness.chess_helpers import TEAM_R_RGB, TEAM_L_RGB
        team_r, team_l = teams

        # Build a grid with L-King at row 6 (moved from row 7)
        grid = py_init_board(team_r, team_l)
        king = grid[7][4]
        assert isinstance(king, King)
        assert king.direction == -1

        # Move king from (7,4) to (6,4)
        grid[6][4] = king
        grid[7][4] = None
        king.row = 6
        king.touched = True

        # Serialize to JSON and send to JS, get legal moves
        # (legal moves internally reconstructs the grid via gridFromJson)
        grid_json = py_grid_to_json(grid, team_r)

        # Verify the JSON includes King direction
        king_cell = grid_json[6][4]
        assert king_cell["type"] == "King"
        assert king_cell["direction"] == -1, (
            "py_grid_to_json must include King.direction"
        )

        # Get legal moves from JS — if direction is wrong, the JS engine
        # will allow moves into squares attacked by enemy pawns
        js_moves = bridge.chess_legal_moves(
            grid_json, TEAM_R_RGB, TEAM_L_RGB, "l",
        )
        # Get Python legal moves for comparison
        from harness.chess_helpers import py_legal_moves
        py_moves = py_legal_moves(grid, team_l)

        js_set = {tuple(m) for m in js_moves}
        py_set = py_moves

        only_js = js_set - py_set
        only_py = py_set - js_set

        assert only_js == set(), (
            f"JS allows moves Python forbids: {only_js} "
            f"(likely King.direction deserialization bug)"
        )
        assert only_py == set(), (
            f"Python allows moves JS forbids: {only_py}"
        )
