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
from pieces.rook import Rook  # noqa: E402
from pieces.bishop import Bishop  # noqa: E402
from pieces.knight import Knight  # noqa: E402
from pieces.queen import Queen  # noqa: E402
from pieces.king import King  # noqa: E402
from network.protocol import encode_grid  # noqa: E402

# ── constants ────────────────────────────────────────────────────────────

TEAM_R_RGB = (64, 180, 232)
TEAM_L_RGB = (255, 140, 0)

PIECE_MAP = {
    "Pawn": Pawn, "Rook": Rook, "Bishop": Bishop,
    "Knight": Knight, "Queen": Queen, "King": King,
}


# ── fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def bridge():
    b = JsBridge()
    assert b.ping() == "pong"
    yield b
    b.close()


# ── helpers ──────────────────────────────────────────────────────────────

def py_init_board(team_r: Team, team_l: Team) -> list:
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


def py_legal_moves(grid: list, team: Team) -> set[tuple[int, int, int, int]]:
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
    """Apply a move on Python side. Returns wire-protocol-style flags dict."""
    piece = grid[fr][fc]
    pre_capture = grid[tr][tc]
    is_capture = pre_capture is not None
    flags = {
        "is_capture": is_capture,
        "is_en_passant": False,
        "is_castling": False,
        "is_promotion": False,
        "promoted_to": None,
        "captured_at": None,
        "rook_from": None,
        "rook_to": None,
    }

    grid[tr][tc] = piece
    grid[fr][fc] = None

    if isinstance(piece, Pawn):
        # Detect en passant before calling move
        if abs(tc - fc) == 1 and pre_capture is None:
            flags["is_en_passant"] = True

        enemy = piece.move(tr, tc, grid)
        if enemy:
            grid[enemy.row][enemy.col] = None
            flags["captured_at"] = [enemy.row, enemy.col]
            flags["is_capture"] = True

        # Promotion
        if (piece.starting_row + 6) % 12 == tr:
            grid[tr][tc] = Queen(tr, tc, piece.team)
            grid[tr][tc].touched = True
            flags["is_promotion"] = True
            flags["promoted_to"] = "Queen"

    elif isinstance(piece, King):
        # Detect castling
        if fr == tr and abs(tc - fc) == 2:
            flags["is_castling"] = True
            if tc == fc - 2:  # queen-side
                flags["rook_from"] = [fr, fc - 4]
                flags["rook_to"] = [fr, fc - 1]
            else:  # king-side
                flags["rook_from"] = [fr, fc + 3]
                flags["rook_to"] = [fr, fc + 1]

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


def py_grid_snapshot(grid: list, team_r: Team) -> list:
    """Convert Python grid to spectator-compatible snapshot for comparison."""
    return [
        [
            {"type": type(p).__name__, "team_r": p.team.r == team_r.r}
            if p is not None else None
            for p in row
        ]
        for row in grid
    ]


def grids_equal(a: list, b: list) -> tuple[bool, str]:
    """Compare two spectator-format grids. Returns (match, diff_description)."""
    for r in range(8):
        for c in range(8):
            ca, cb = a[r][c], b[r][c]
            if ca is None and cb is None:
                continue
            if ca is None or cb is None:
                return False, f"({r},{c}): {ca} vs {cb}"
            if ca["type"] != cb["type"] or ca["team_r"] != cb["team_r"]:
                return False, f"({r},{c}): {ca} vs {cb}"
    return True, ""


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
    """board_sync via encode_grid → spectator applyGrid must round-trip."""

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
            for row in py_grid:
                for p in row:
                    if isinstance(p, Pawn) and p.team.r == team.r:
                        p.en_passantable = False
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
            for row in py_grid:
                for p in row:
                    if isinstance(p, Pawn) and p.team.r == team.r:
                        p.en_passantable = False

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
                f"({fr},{fc})→({tr},{tc}) flags={flags}: {diff}"
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
            for row in py_grid:
                for p in row:
                    if isinstance(p, Pawn) and p.team.r == team.r:
                        p.en_passantable = False
            moves = py_legal_moves(py_grid, team)
            if not moves:
                break
            move = rng.choice(sorted(moves))
            py_apply_move(py_grid, *move)
            current_key = "l" if current_key == "r" else "r"

        # Now sync spectator via board_sync (encode_grid → applyGrid)
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
            for row in py_grid:
                for p in row:
                    if isinstance(p, Pawn) and p.team.r == team.r:
                        p.en_passantable = False
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
            for row in py_grid:
                for p in row:
                    if isinstance(p, Pawn) and p.team.r == team.r:
                        p.en_passantable = False

            # Python: serialize and get legal moves
            py_grid_json = _py_grid_to_json(py_grid, team_r)
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
            js_snap = _js_grid_to_snapshot(js_grid_json)
            match, diff = grids_equal(js_snap, spec_grid)
            assert match, (
                f"Seed {seed}, ply {ply}: JS Engine vs Spectator mismatch: {diff}"
            )

            current_key = next_key
            if js_result["status"] in ("checkmate", "stalemate"):
                break


# ── internal helpers ─────────────────────────────────────────────────────

def _py_grid_to_json(grid: list, team_r: Team) -> list:
    """Serialize Python grid to JSON for the JS chess engine bridge."""
    result = []
    for row in grid:
        json_row = []
        for p in row:
            if p is None:
                json_row.append(None)
            else:
                obj = {
                    "type": type(p).__name__,
                    "row": p.row, "col": p.col,
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


def _js_grid_to_snapshot(js_grid: list) -> list:
    """Convert JS engine grid JSON to spectator-comparable snapshot."""
    return [
        [
            {"type": cell["type"], "team_r": cell["team_key"] == "r"}
            if cell is not None else None
            for cell in row
        ]
        for row in js_grid
    ]
