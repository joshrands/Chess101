#!/usr/bin/env python3
"""Networked lockstep fuzzer — three-way parity: Python engine, JS engine, JS spectator.

Plays random games from the starting position, applying each move on all three
implementations simultaneously. At every ply, verifies:
  - Python engine grid matches JS spectator grid (type + team)
  - JS engine grid matches JS spectator grid (type + team)
  - Python board_hash matches JS board_hash (full state including touched/ep)

Disagreements are saved with full move history and flags for replay.

Usage::

    bazel run //harness:fuzz_networked -- --iterations 100
    .venv/bin/python harness/fuzz_networked.py --iterations 100
    .venv/bin/python harness/fuzz_networked.py --iterations 0   # run forever
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "harness"))

from python_bridge import JsBridge  # noqa: E402

from core.team import Team  # noqa: E402
from pieces.pawn import Pawn  # noqa: E402
from pieces.rook import Rook  # noqa: E402
from pieces.bishop import Bishop  # noqa: E402
from pieces.knight import Knight  # noqa: E402
from pieces.queen import Queen  # noqa: E402
from pieces.king import King  # noqa: E402
from network.protocol import board_hash, encode_grid  # noqa: E402

TEAM_R_RGB = (64, 180, 232)
TEAM_L_RGB = (255, 140, 0)

PIECE_MAP = {
    "Pawn": Pawn, "Rook": Rook, "Bishop": Bishop,
    "Knight": Knight, "Queen": Queen, "King": King,
}


# ── Python-side helpers (same as fuzz_chess.py) ───────────────────────────

def py_grid_to_json(grid, team_r):
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


def py_init_board(team_r, team_l):
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


def py_legal_moves(grid, team):
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


def py_apply_move(grid, fr, fc, tr, tc):
    """Apply a move, returning wire-protocol-style flags."""
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
        if abs(tc - fc) == 1 and pre_capture is None:
            flags["is_en_passant"] = True
        enemy = piece.move(tr, tc, grid)
        if enemy:
            grid[enemy.row][enemy.col] = None
            flags["captured_at"] = [enemy.row, enemy.col]
            flags["is_capture"] = True
        if (piece.starting_row + 6) % 12 == tr:
            grid[tr][tc] = Queen(tr, tc, piece.team)
            grid[tr][tc].touched = True
            flags["is_promotion"] = True
            flags["promoted_to"] = "Queen"
    elif isinstance(piece, King):
        if fr == tr and abs(tc - fc) == 2:
            flags["is_castling"] = True
            if tc == fc - 2:
                flags["rook_from"] = [fr, fc - 4]
                flags["rook_to"] = [fr, fc - 1]
            else:
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


def py_grid_snapshot(grid, team_r):
    return [
        [
            {"type": type(p).__name__, "team_r": p.team.r == team_r.r}
            if p is not None else None
            for p in row
        ]
        for row in grid
    ]


def js_grid_to_snapshot(js_grid):
    return [
        [
            {"type": c["type"], "team_r": c["team_key"] == "r"}
            if c is not None else None
            for c in row
        ]
        for row in js_grid
    ]


def grids_equal(a, b):
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


# ── fuzzer ────────────────────────────────────────────────────────────────

def run_fuzzer(iterations: int, seed: int, max_ply: int) -> None:
    rng = random.Random(seed)
    crashes_dir = ROOT / "harness" / "crashes" / "networked"
    crashes_dir.mkdir(parents=True, exist_ok=True)

    bridge = JsBridge()
    assert bridge.ping() == "pong"

    total = 0
    games_ok = 0
    disagree = 0
    errors = 0
    total_plies = 0
    t0 = time.time()

    try:
        i = 0
        while iterations == 0 or i < iterations:
            game_seed = rng.randint(0, 2**32)
            game_rng = random.Random(game_seed)
            team_r = Team(*TEAM_R_RGB)
            team_l = Team(*TEAM_L_RGB)
            py_grid = py_init_board(team_r, team_l)
            spec_grid = bridge.spectator_init()
            js_grid_json = bridge.chess_init(TEAM_R_RGB, TEAM_L_RGB)
            peace_time = 0
            current_key = "r"
            move_history = []
            game_ok = True

            for ply in range(max_ply):
                team = team_r if current_key == "r" else team_l

                # Clear en passant
                for row in py_grid:
                    for p in row:
                        if isinstance(p, Pawn) and p.team.r == team.r:
                            p.en_passantable = False

                grid_json = py_grid_to_json(py_grid, team_r)

                try:
                    py_moves = py_legal_moves(py_grid, team)
                except Exception as e:
                    errors += 1
                    print(f"[ERROR] game={total} ply={ply}: {e}")
                    game_ok = False
                    break

                if not py_moves:
                    break

                move = game_rng.choice(sorted(py_moves))
                fr, fc, tr, tc = move
                is_capture = py_grid[tr][tc] is not None
                is_pawn = isinstance(py_grid[fr][fc], Pawn)

                # Apply on Python engine
                flags = py_apply_move(py_grid, fr, fc, tr, tc)
                peace_time = 0 if (is_capture or is_pawn) else peace_time + 1
                next_key = "l" if current_key == "r" else "r"

                try:
                    # Apply on JS engine
                    js_result = bridge.chess_apply_move(
                        grid_json, TEAM_R_RGB, TEAM_L_RGB,
                        fr, fc, tr, tc, current_key, next_key, peace_time,
                    )
                    js_grid_json = js_result["grid"]

                    # Apply on JS spectator
                    spec_grid = bridge.spectator_apply_move(
                        spec_grid, fr, fc, tr, tc, flags,
                    )
                except Exception as e:
                    errors += 1
                    print(f"[ERROR] game={total} ply={ply} apply: {e}")
                    game_ok = False
                    break

                # Compare Python vs spectator
                py_snap = py_grid_snapshot(py_grid, team_r)
                match_ps, diff_ps = grids_equal(py_snap, spec_grid)

                # Compare JS engine vs spectator
                js_snap = js_grid_to_snapshot(js_grid_json)
                match_js, diff_js = grids_equal(js_snap, spec_grid)

                # Compare Python vs JS engine hash
                py_hash = board_hash(py_grid, peace_time, next_key, team_r)
                js_hash = js_result["board_hash"]

                if not match_ps or not match_js or py_hash != js_hash:
                    disagree += 1
                    fname = f"game{total:06d}_ply{ply}.json"
                    crash = {
                        "seed": game_seed,
                        "ply": ply,
                        "move": move,
                        "move_history": move_history,
                        "flags": flags,
                        "py_vs_spectator": diff_ps if not match_ps else "ok",
                        "js_vs_spectator": diff_js if not match_js else "ok",
                        "hash_match": py_hash == js_hash,
                        "py_hash": py_hash[:16],
                        "js_hash": js_hash[:16],
                    }
                    (crashes_dir / fname).write_text(json.dumps(crash, indent=2))
                    kind = []
                    if not match_ps:
                        kind.append(f"py↔spec:{diff_ps}")
                    if not match_js:
                        kind.append(f"js↔spec:{diff_js}")
                    if py_hash != js_hash:
                        kind.append("hash")
                    print(f"[DISAGREE] game={total} ply={ply} {'; '.join(kind)} → {fname}")
                    game_ok = False
                    break

                move_history.append(move)
                current_key = next_key
                total_plies += 1

                if js_result["status"] in ("checkmate", "stalemate"):
                    break

                # Periodic board_sync test: every 20 plies, resync spectator
                if ply > 0 and ply % 20 == 0:
                    encoded = encode_grid(py_grid, team_r)
                    spec_grid = bridge.spectator_apply_grid(encoded)

            total += 1
            if game_ok:
                games_ok += 1

            if total % 10 == 0:
                elapsed = time.time() - t0
                rate = total / elapsed if elapsed > 0 else 0
                print(f"  [{total}] ok={games_ok} disagree={disagree} "
                      f"errors={errors} plies={total_plies} ({rate:.1f} games/s)")

            i += 1

    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        bridge.close()

    elapsed = time.time() - t0
    print(f"\nDone. {total} games in {elapsed:.1f}s "
          f"({total_plies} total plies)")
    print(f"  ok={games_ok}  disagree={disagree}  errors={errors}")
    if disagree > 0:
        print(f"  Crash files in {crashes_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="Networked lockstep fuzzer — Python engine vs JS engine vs JS spectator",
    )
    parser.add_argument("--iterations", type=int, default=100,
                        help="Number of games (0 = infinite)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-ply", type=int, default=120,
                        help="Max half-moves per game")
    args = parser.parse_args()
    run_fuzzer(args.iterations, args.seed, args.max_ply)


if __name__ == "__main__":
    main()
