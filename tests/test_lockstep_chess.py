"""Lockstep tests: Python vs JS chess engine must agree on legal moves and board state.

Plays random games from the starting position, comparing legal move sets and
board hashes at each step. Both implementations must produce identical results.

Running
-------
    bazel test //tests:test_lockstep_chess
    .venv/bin/python -m pytest tests/test_lockstep_chess.py -v
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
from network.protocol import board_hash  # noqa: E402
from chess_helpers import (  # noqa: E402
    TEAM_R_RGB,
    TEAM_L_RGB,
    py_grid_to_json,
    json_to_py_grid,
    py_init_board,
    py_legal_moves,
    py_apply_move,
    clear_en_passant,
)


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def bridge():
    b = JsBridge()
    assert b.ping() == "pong"
    yield b
    b.close()


# ── tests ───────────────────────────────────────────────────────────────────

class TestBoardHashParity:
    """board_hash must be identical on both sides for the same position."""

    def test_starting_position(self, bridge):
        team_r = Team(*TEAM_R_RGB)
        team_l = Team(*TEAM_L_RGB)
        py_grid = py_init_board(team_r, team_l)
        grid_json = py_grid_to_json(py_grid, team_r)
        py_hash = board_hash(py_grid, 0, "r", team_r)
        js_hash = bridge.chess_board_hash(grid_json, TEAM_R_RGB, TEAM_L_RGB, 0, "r")
        assert py_hash == js_hash, f"Hash mismatch: py={py_hash[:16]}... js={js_hash[:16]}..."

    def test_after_e4(self, bridge):
        team_r = Team(*TEAM_R_RGB)
        team_l = Team(*TEAM_L_RGB)
        py_grid = py_init_board(team_r, team_l)
        py_apply_move(py_grid, 1, 4, 3, 4)  # e2-e4
        grid_json = py_grid_to_json(py_grid, team_r)
        py_hash = board_hash(py_grid, 0, "l", team_r)
        js_hash = bridge.chess_board_hash(grid_json, TEAM_R_RGB, TEAM_L_RGB, 0, "l")
        assert py_hash == js_hash


class TestLegalMovesParity:
    """Legal move sets must agree at the starting position."""

    def test_starting_moves(self, bridge):
        team_r = Team(*TEAM_R_RGB)
        team_l = Team(*TEAM_L_RGB)
        py_grid = py_init_board(team_r, team_l)
        grid_json = py_grid_to_json(py_grid, team_r)

        py_moves = py_legal_moves(py_grid, team_r)
        js_moves_raw = bridge.chess_legal_moves(grid_json, TEAM_R_RGB, TEAM_L_RGB, "r")
        js_moves = {tuple(m) for m in js_moves_raw}

        assert py_moves == js_moves, (
            f"Move set mismatch.\n"
            f"  Only in Python: {py_moves - js_moves}\n"
            f"  Only in JS: {js_moves - py_moves}"
        )

    def test_starting_moves_team_l(self, bridge):
        team_r = Team(*TEAM_R_RGB)
        team_l = Team(*TEAM_L_RGB)
        py_grid = py_init_board(team_r, team_l)
        # Apply e4 first so it's team_l's turn
        py_apply_move(py_grid, 1, 4, 3, 4)
        grid_json = py_grid_to_json(py_grid, team_r)

        py_moves = py_legal_moves(py_grid, team_l)
        js_moves_raw = bridge.chess_legal_moves(grid_json, TEAM_R_RGB, TEAM_L_RGB, "l")
        js_moves = {tuple(m) for m in js_moves_raw}

        assert py_moves == js_moves


class TestRandomGames:
    """Play random games and verify both sides agree at every step."""

    @pytest.mark.parametrize("seed", range(10))
    def test_random_game(self, bridge, seed):
        rng = random.Random(seed)
        team_r = Team(*TEAM_R_RGB)
        team_l = Team(*TEAM_L_RGB)
        py_grid = py_init_board(team_r, team_l)
        peace_time = 0
        current_key = "r"

        for ply in range(80):  # max 80 half-moves per game
            team = team_r if current_key == "r" else team_l

            # Clear en_passantable on the current team's pawns (window expired)
            clear_en_passant(py_grid, team)

            grid_json = py_grid_to_json(py_grid, team_r)

            # Compare legal moves
            py_moves = py_legal_moves(py_grid, team)
            js_moves_raw = bridge.chess_legal_moves(
                grid_json, TEAM_R_RGB, TEAM_L_RGB, current_key,
            )
            js_moves = {tuple(m) for m in js_moves_raw}

            assert py_moves == js_moves, (
                f"Seed {seed}, ply {ply}: move set mismatch.\n"
                f"  Only in Python: {py_moves - js_moves}\n"
                f"  Only in JS: {js_moves - py_moves}"
            )

            if not py_moves:
                break  # checkmate or stalemate

            # Pick a random legal move
            move = rng.choice(sorted(py_moves))
            fr, fc, tr, tc = move

            # Check if it's a capture or pawn move (for peace_time)
            is_capture = py_grid[tr][tc] is not None
            is_pawn = isinstance(py_grid[fr][fc], Pawn)

            # Apply on Python side
            py_apply_move(py_grid, fr, fc, tr, tc)

            if is_capture or is_pawn:
                peace_time = 0
            else:
                peace_time += 1

            next_key = "l" if current_key == "r" else "r"

            # Apply on JS side
            js_result = bridge.chess_apply_move(
                grid_json, TEAM_R_RGB, TEAM_L_RGB,
                fr, fc, tr, tc,
                current_key, next_key, peace_time,
            )

            # Compare board hashes
            py_hash = board_hash(py_grid, peace_time, next_key, team_r)
            js_hash = js_result["board_hash"]
            assert py_hash == js_hash, (
                f"Seed {seed}, ply {ply}: hash mismatch after {move}.\n"
                f"  py={py_hash[:16]}... js={js_hash[:16]}..."
            )

            # Update JS grid for next iteration
            current_key = next_key

            # Check for game over
            if js_result["status"] in ("checkmate", "stalemate"):
                break
