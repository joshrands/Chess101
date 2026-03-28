"""Shared Python-side chess helpers for lockstep testing and fuzzing.

Provides board initialization, grid serialization, legal move computation,
and move application functions used by fuzzers, lockstep tests, and the
corpus replay engine.
"""

from __future__ import annotations

from core.team import Team
from pieces.pawn import Pawn
from pieces.rook import Rook
from pieces.bishop import Bishop
from pieces.knight import Knight
from pieces.queen import Queen
from pieces.king import King

# ── constants ────────────────────────────────────────────────────────────

TEAM_R_RGB = (64, 180, 232)
TEAM_L_RGB = (255, 140, 0)

PIECE_MAP: dict[str, type] = {
    "Pawn": Pawn, "Rook": Rook, "Bishop": Bishop,
    "Knight": Knight, "Queen": Queen, "King": King,
}


# ── board initialization ─────────────────────────────────────────────────

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


# ── grid serialization (Python <-> JSON) ─────────────────────────────────

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
    from core.cell import Cell

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
                        p.en_passant_loc = Cell(
                            cell["en_passant_loc"][0],
                            cell["en_passant_loc"][1],
                        )
                py_row.append(p)
        grid.append(py_row)
    return grid


# ── legal move computation ───────────────────────────────────────────────

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


def clear_en_passant(grid: list, team: Team) -> None:
    """Clear en_passantable on all pawns of *team* (window expired)."""
    for row in grid:
        for p in row:
            if isinstance(p, Pawn) and p.team.r == team.r:
                p.en_passantable = False


# ── move application ─────────────────────────────────────────────────────

def py_apply_move(grid: list, fr: int, fc: int, tr: int, tc: int) -> dict:
    """Apply a move on the Python side. Returns wire-protocol-style flags dict."""
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


# ── grid snapshot / comparison ───────────────────────────────────────────

def py_grid_snapshot(grid: list, team_r: Team) -> list:
    """Convert Python grid to spectator-compatible snapshot ({type, team_r})."""
    return [
        [
            {"type": type(p).__name__, "team_r": p.team.r == team_r.r}
            if p is not None else None
            for p in row
        ]
        for row in grid
    ]


def js_grid_to_snapshot(js_grid: list) -> list:
    """Convert JS bridge grid JSON to spectator-compatible snapshot."""
    return [
        [
            {"type": c["type"], "team_r": c["team_key"] == "r"}
            if c is not None else None
            for c in row
        ]
        for row in js_grid
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
