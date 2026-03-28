"""Lockstep tests: spectator applyMove must agree with the chess engines.

Plays random games from the starting position using the Python chess engine,
builds MoveFlags for each move (mirroring the wire protocol), and applies the
same move via the JS spectator engine's applyMove.  After every move the
spectator's simplified grid ({type, team_r} per cell) must match the
authoritative Python grid.

This catches bugs in the spectator's independent move-application logic —
en passant clearing, castling rook movement, and pawn promotion — which are
reimplemented separately from the chess engines.

Also tests the board_sync path: encode_grid on the Python side, applyGrid on
the JS spectator side, and verify the resulting grid matches.

Running
-------
    bazel test //tests:test_lockstep_networked
    bazel test //tests:test_lockstep_networked --test_output=streamed --test_arg=-v
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))

from python_bridge import JsBridge  # noqa: E402

from core.team import Team  # noqa: E402
from pieces.pawn import Pawn  # noqa: E402
from network.protocol import encode_grid  # noqa: E402
from chess_helpers import (  # noqa: E402
    TEAM_R_RGB,
    TEAM_L_RGB,
    py_init_board,
    py_grid_to_json,
    py_legal_moves,
    py_apply_move,
    py_grid_snapshot,
    js_grid_to_snapshot,
    grids_equal,
    clear_en_passant,
)


# ── fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def bridge():
    b = JsBridge()
    assert b.ping() == "pong"
    yield b
    b.close()


# ── tests ────────────────────────────────────────────────────────────────

class TestSpectatorInit:
    """Spectator starting position must match the standard board."""

    def test_starting_position_matches(self, bridge):
        team_r = Team(*TEAM_R_RGB)
        team_l = Team(*TEAM_L_RGB)
        py_grid = py_init_board(team_r, team_l)
        py_snap = py_grid_snapshot(py_grid, team_r)

        spec_grid = bridge.spectator_init()

        match, diff = grids_equal(py_snap, spec_grid)
        assert match, f"Starting position mismatch: {diff}"


class TestSpectatorApplyGrid:
    """board_sync via encode_grid -> spectator applyGrid must round-trip."""

    def test_starting_position_sync(self, bridge):
        team_r = Team(*TEAM_R_RGB)
        team_l = Team(*TEAM_L_RGB)
        py_grid = py_init_board(team_r, team_l)

        encoded = encode_grid(py_grid, team_r)
        spec_grid = bridge.spectator_apply_grid(encoded)

        py_snap = py_grid_snapshot(py_grid, team_r)
        match, diff = grids_equal(py_snap, spec_grid)
        assert match, f"board_sync mismatch: {diff}"

    def test_midgame_sync(self, bridge):
        """Encode a mid-game position and verify spectator reproduces it."""
        team_r = Team(*TEAM_R_RGB)
        team_l = Team(*TEAM_L_RGB)
        py_grid = py_init_board(team_r, team_l)

        # Play a few moves
        rng = random.Random(99)
        current_key = "r"
        for _ in range(10):
            team = team_r if current_key == "r" else team_l
            clear_en_passant(py_grid, team)
            moves = py_legal_moves(py_grid, team)
            if not moves:
                break
            move = rng.choice(sorted(moves))
            py_apply_move(py_grid, *move)
            current_key = "l" if current_key == "r" else "r"

        encoded = encode_grid(py_grid, team_r)
        spec_grid = bridge.spectator_apply_grid(encoded)
        py_snap = py_grid_snapshot(py_grid, team_r)
        match, diff = grids_equal(py_snap, spec_grid)
        assert match, f"Mid-game board_sync mismatch: {diff}"


class TestSpectatorApplyMove:
    """spectator.applyMove with MoveFlags must keep the grid in sync."""

    def test_simple_pawn_move(self, bridge):
        """e2-e4: no flags, just piece movement."""
        spec_grid = bridge.spectator_init()
        spec_grid = bridge.spectator_apply_move(spec_grid, 1, 4, 3, 4, {})

        team_r = Team(*TEAM_R_RGB)
        team_l = Team(*TEAM_L_RGB)
        py_grid = py_init_board(team_r, team_l)
        py_apply_move(py_grid, 1, 4, 3, 4)
        py_snap = py_grid_snapshot(py_grid, team_r)

        match, diff = grids_equal(py_snap, spec_grid)
        assert match, f"Simple pawn move mismatch: {diff}"

    def test_castling(self, bridge):
        """King-side castling requires rook_from/rook_to flags."""
        team_r = Team(*TEAM_R_RGB)
        team_l = Team(*TEAM_L_RGB)
        py_grid = py_init_board(team_r, team_l)
        spec_grid = bridge.spectator_init()

        # Clear path for king-side castling (remove knight and bishop)
        py_grid[0][5] = None
        py_grid[0][6] = None
        spec_grid[0][5] = None
        spec_grid[0][6] = None

        flags = py_apply_move(py_grid, 0, 4, 0, 6)
        spec_grid = bridge.spectator_apply_move(spec_grid, 0, 4, 0, 6, flags)

        py_snap = py_grid_snapshot(py_grid, team_r)
        match, diff = grids_equal(py_snap, spec_grid)
        assert match, f"Castling mismatch: {diff}"
        # Verify rook moved
        assert spec_grid[0][5] is not None, "Rook should be at f1 after castling"
        assert spec_grid[0][7] is None, "h1 should be empty after castling"

    def test_promotion(self, bridge):
        """Pawn reaching back rank should become Queen via is_promotion flag."""
        team_r = Team(*TEAM_R_RGB)
        team_l = Team(*TEAM_L_RGB)
        py_grid = py_init_board(team_r, team_l)
        spec_grid = bridge.spectator_init()

        # Set up a pawn about to promote (team_r pawn at row 6, target row 7)
        py_grid[6][0] = Pawn(6, 0, team_r)
        py_grid[6][0].starting_row = 1
        py_grid[6][0].direction = 1
        py_grid[6][0].touched = True
        py_grid[7][0] = None  # clear the rook
        spec_grid[6][0] = {"type": "Pawn", "team_r": True}
        spec_grid[7][0] = None

        flags = py_apply_move(py_grid, 6, 0, 7, 0)
        assert flags["is_promotion"], "Should detect promotion"
        spec_grid = bridge.spectator_apply_move(spec_grid, 6, 0, 7, 0, flags)

        py_snap = py_grid_snapshot(py_grid, team_r)
        match, diff = grids_equal(py_snap, spec_grid)
        assert match, f"Promotion mismatch: {diff}"
        assert spec_grid[7][0]["type"] == "Queen", "Promoted piece should be Queen"


class TestSpectatorRandomGames:
    """Play random games and verify spectator stays in sync at every move."""

    @pytest.mark.parametrize("seed", range(10))
    def test_random_game(self, bridge, seed):
        rng = random.Random(seed)
        team_r = Team(*TEAM_R_RGB)
        team_l = Team(*TEAM_L_RGB)
        py_grid = py_init_board(team_r, team_l)
        spec_grid = bridge.spectator_init()
        current_key = "r"

        for ply in range(80):
            team = team_r if current_key == "r" else team_l

            # Clear en_passantable on current team
            clear_en_passant(py_grid, team)

            moves = py_legal_moves(py_grid, team)
            if not moves:
                break

            move = rng.choice(sorted(moves))
            fr, fc, tr, tc = move

            flags = py_apply_move(py_grid, fr, fc, tr, tc)
            spec_grid = bridge.spectator_apply_move(
                spec_grid, fr, fc, tr, tc, flags,
            )

            py_snap = py_grid_snapshot(py_grid, team_r)
            match, diff = grids_equal(py_snap, spec_grid)
            assert match, (
                f"Seed {seed}, ply {ply}: spectator mismatch after "
                f"({fr},{fc})->({tr},{tc}) flags={flags}: {diff}"
            )

            current_key = "l" if current_key == "r" else "r"

    @pytest.mark.parametrize("seed", range(5))
    def test_board_sync_recovery(self, bridge, seed):
        """Mid-game board_sync must bring spectator back in sync."""
        rng = random.Random(seed + 100)
        team_r = Team(*TEAM_R_RGB)
        team_l = Team(*TEAM_L_RGB)
        py_grid = py_init_board(team_r, team_l)
        current_key = "r"

        # Play 20 moves without spectator tracking
        for _ in range(20):
            team = team_r if current_key == "r" else team_l
            clear_en_passant(py_grid, team)
            moves = py_legal_moves(py_grid, team)
            if not moves:
                break
            move = rng.choice(sorted(moves))
            py_apply_move(py_grid, *move)
            current_key = "l" if current_key == "r" else "r"

        # Now sync spectator via board_sync (encode_grid -> applyGrid)
        encoded = encode_grid(py_grid, team_r)
        spec_grid = bridge.spectator_apply_grid(encoded)

        py_snap = py_grid_snapshot(py_grid, team_r)
        match, diff = grids_equal(py_snap, spec_grid)
        assert match, (
            f"Seed {seed}: board_sync recovery mismatch: {diff}"
        )

        # Continue playing with spectator tracking from sync point
        for ply in range(20):
            team = team_r if current_key == "r" else team_l
            clear_en_passant(py_grid, team)
            moves = py_legal_moves(py_grid, team)
            if not moves:
                break
            move = rng.choice(sorted(moves))
            fr, fc, tr, tc = move
            flags = py_apply_move(py_grid, fr, fc, tr, tc)
            spec_grid = bridge.spectator_apply_move(
                spec_grid, fr, fc, tr, tc, flags,
            )
            py_snap = py_grid_snapshot(py_grid, team_r)
            match, diff = grids_equal(py_snap, spec_grid)
            assert match, (
                f"Seed {seed}, post-sync ply {ply}: mismatch: {diff}"
            )
            current_key = "l" if current_key == "r" else "r"


class TestThreeWayParity:
    """All three implementations must agree: Python engine, JS engine, JS spectator."""

    @pytest.mark.parametrize("seed", range(5))
    def test_three_way_random_game(self, bridge, seed):
        """Play a game and verify all three grids stay in sync."""
        rng = random.Random(seed + 200)
        team_r = Team(*TEAM_R_RGB)
        team_l = Team(*TEAM_L_RGB)

        # Python engine
        py_grid = py_init_board(team_r, team_l)
        # JS spectator
        spec_grid = bridge.spectator_init()
        # JS engine (via chess_init)
        js_grid_json = bridge.chess_init(TEAM_R_RGB, TEAM_L_RGB)

        current_key = "r"
        peace_time = 0

        for ply in range(60):
            team = team_r if current_key == "r" else team_l

            # Clear en passant
            clear_en_passant(py_grid, team)

            # Python: serialize and get legal moves
            py_grid_json = py_grid_to_json(py_grid, team_r)
            moves = py_legal_moves(py_grid, team)
            if not moves:
                break

            move = rng.choice(sorted(moves))
            fr, fc, tr, tc = move

            is_capture = py_grid[tr][tc] is not None
            is_pawn = isinstance(py_grid[fr][fc], Pawn)

            # Apply on Python engine
            flags = py_apply_move(py_grid, fr, fc, tr, tc)
            peace_time = 0 if (is_capture or is_pawn) else peace_time + 1
            next_key = "l" if current_key == "r" else "r"

            # Apply on JS engine
            js_result = bridge.chess_apply_move(
                py_grid_json, TEAM_R_RGB, TEAM_L_RGB,
                fr, fc, tr, tc, current_key, next_key, peace_time,
            )
            js_grid_json = js_result["grid"]

            # Apply on JS spectator
            spec_grid = bridge.spectator_apply_move(
                spec_grid, fr, fc, tr, tc, flags,
            )

            # Compare Python vs spectator
            py_snap = py_grid_snapshot(py_grid, team_r)
            match, diff = grids_equal(py_snap, spec_grid)
            assert match, (
                f"Seed {seed}, ply {ply}: Python vs Spectator mismatch: {diff}"
            )

            # Compare JS engine vs spectator (type + team only)
            js_snap = js_grid_to_snapshot(js_grid_json)
            match, diff = grids_equal(js_snap, spec_grid)
            assert match, (
                f"Seed {seed}, ply {ply}: JS Engine vs Spectator mismatch: {diff}"
            )

            current_key = next_key
            if js_result["status"] in ("checkmate", "stalemate"):
                break
