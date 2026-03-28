"""Lockstep tests: Python vs JS chess engine must agree on legal moves and board state.

Plays random games from the starting position, comparing legal move sets and
board hashes at each step. Both implementations must produce identical results.

Running
-------
    bazel test //tests:test_lockstep_chess
    .venv/bin/python -m pytest tests/test_lockstep_chess.py -v
"""

from __future__ import annotations

import hashlib
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))

from python_bridge import JsBridge  # noqa: E402

# ── Python chess imports ────────────────────────────────────────────────────

from core.team import Team  # noqa: E402
from pieces.pawn import Pawn  # noqa: E402
from pieces.rook import Rook  # noqa: E402
from pieces.bishop import Bishop  # noqa: E402
from pieces.knight import Knight  # noqa: E402
from pieces.queen import Queen  # noqa: E402
from pieces.king import King  # noqa: E402
from network.protocol import board_hash  # noqa: E402


# ── constants ───────────────────────────────────────────────────────────────

TEAM_R_RGB = (64, 180, 232)
TEAM_L_RGB = (255, 140, 0)

PIECE_MAP = {
    "Pawn": Pawn, "Rook": Rook, "Bishop": Bishop,
    "Knight": Knight, "Queen": Queen, "King": King,
}


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def bridge():
    b = JsBridge()
    assert b.ping() == "pong"
    yield b
    b.close()


# ── grid serialization (Python ↔ JSON) ─────────────────────────────────────

def py_grid_to_json(grid: list, team_r: Team) -> list:
    """Serialize Python grid to the JSON format expected by the JS bridge."""
    result = []
    for row in grid:
        json_row = []
        for p in row:
            if p is None:
                json_row.append(None)
            else:
                obj = {
                    "type": type(p).__name__,
                    "row": p.row,
                    "col": p.col,
                    "team_key": "r" if p.team.r == team_r.r else "l",
                    "touched": getattr(p, "touched", False),
                }
                if isinstance(p, Pawn):
                    obj["starting_row"] = p.starting_row
                    obj["direction"] = p.direction
                    obj["en_passantable"] = p.en_passantable
                    obj["en_passant_loc"] = (
                        [p.en_passant_loc.row, p.en_passant_loc.col]
                        if p.en_passant_loc else None
                    )
                json_row.append(obj)
        result.append(json_row)
    return result


def json_to_py_grid(data: list, team_r: Team, team_l: Team) -> list:
    """Deserialize JSON grid back to Python piece objects."""
    grid = []
    for row in data:
        py_row = []
        for cell in row:
            if cell is None:
                py_row.append(None)
            else:
                team = team_r if cell["team_key"] == "r" else team_l
                Cls = PIECE_MAP[cell["type"]]
                p = Cls(cell["row"], cell["col"], team)
                p.touched = cell["touched"]
                if isinstance(p, Pawn):
                    p.starting_row = cell["starting_row"]
                    p.direction = cell["direction"]
                    p.en_passantable = cell["en_passantable"]
                    if cell["en_passant_loc"]:
                        from core.cell import Cell
                        p.en_passant_loc = Cell(
                            cell["en_passant_loc"][0],
                            cell["en_passant_loc"][1],
                        )
                py_row.append(p)
        grid.append(py_row)
    return grid


# ── Python-side legal move computation ──────────────────────────────────────

def py_legal_moves(grid: list, team: Team) -> set[tuple[int, int, int, int]]:
    """Compute all legal moves for *team* on the Python side."""
    pieces = []
    king = None
    for row in grid:
        for p in row:
            if p is not None and p.team.r == team.r:
                pieces.append(p)
                if isinstance(p, King):
                    king = p

    check = king.calc_targets(grid)
    moves = set()
    for t in king.targets:
        moves.add((king.row, king.col, t.row, t.col))

    for p in pieces:
        if isinstance(p, King):
            continue
        p.calc_targets(grid)
        if check:
            p.sky_fall(king)
        for t in p.targets:
            moves.add((p.row, p.col, t.row, t.col))

    return moves


def py_apply_move(grid: list, fr: int, fc: int, tr: int, tc: int) -> dict:
    """Apply a move on the Python side. Returns flags dict."""
    piece = grid[fr][fc]
    captured = grid[tr][tc]
    grid[tr][tc] = piece
    grid[fr][fc] = None
    flags = {"captured": captured is not None}

    if isinstance(piece, Pawn):
        enemy = piece.move(tr, tc, grid)
        if enemy:
            grid[enemy.row][enemy.col] = None
            flags["captured"] = True
        # auto-promote
        if (piece.starting_row + 6) % 12 == tr:
            grid[tr][tc] = Queen(tr, tc, piece.team)
            grid[tr][tc].touched = True
            flags["promoted"] = True
    elif isinstance(piece, King):
        result = piece.move(tr, tc, grid)
        if result is not None and result[0] is not None:
            rook_from, rook_to = result
            grid[rook_to.row][rook_to.col] = grid[rook_from.row][rook_from.col]
            grid[rook_from.row][rook_from.col] = None
            rook = grid[rook_to.row][rook_to.col]
            if rook:
                rook.move(rook_to.row, rook_to.col, grid)
    else:
        piece.move(tr, tc, grid)

    return flags


def py_init_board(team_r: Team, team_l: Team) -> list:
    """Set up the standard starting position on the Python side."""
    grid = [[None] * 8 for _ in range(8)]
    grid[0][0] = Rook(0, 0, team_r); grid[0][1] = Knight(0, 1, team_r)
    grid[0][2] = Bishop(0, 2, team_r); grid[0][3] = Queen(0, 3, team_r)
    grid[0][4] = King(0, 4, team_r); grid[0][5] = Bishop(0, 5, team_r)
    grid[0][6] = Knight(0, 6, team_r); grid[0][7] = Rook(0, 7, team_r)
    for c in range(8):
        grid[1][c] = Pawn(1, c, team_r)
    for c in range(8):
        grid[6][c] = Pawn(6, c, team_l)
    grid[7][0] = Rook(7, 0, team_l); grid[7][1] = Knight(7, 1, team_l)
    grid[7][2] = Bishop(7, 2, team_l); grid[7][3] = Queen(7, 3, team_l)
    grid[7][4] = King(7, 4, team_l); grid[7][5] = Bishop(7, 5, team_l)
    grid[7][6] = Knight(7, 6, team_l); grid[7][7] = Rook(7, 7, team_l)
    return grid


def clear_en_passant(grid: list, team: Team) -> None:
    """Clear en_passantable on all pawns of *team* except the one that just moved."""
    for row in grid:
        for p in row:
            if isinstance(p, Pawn) and p.team.r == team.r:
                p.en_passantable = False


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
            for row in py_grid:
                for p in row:
                    if isinstance(p, Pawn) and p.team.r == team.r:
                        p.en_passantable = False

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
            py_flags = py_apply_move(py_grid, fr, fc, tr, tc)

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
