#!/usr/bin/env python3
"""Swift ↔ JS ↔ Python lockstep chess fuzzer.

Plays random games from the starting position, comparing legal move sets and
board hashes at every ply across all three engines.  Any disagreement is saved
as a crash JSON + corpus file for later replay.

Usage::

    .venv/bin/python harness/fuzz_lockstep_swift.py --iterations 100
    .venv/bin/python harness/fuzz_lockstep_swift.py --iterations 0   # infinite
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

from python_bridge import JsBridge      # noqa: E402
from swift_bridge  import SwiftBridge   # noqa: E402

from core.team     import Team          # noqa: E402
from pieces.pawn   import Pawn          # noqa: E402
from network.protocol import board_hash # noqa: E402
from chess_helpers import (             # noqa: E402
    TEAM_R_RGB,
    TEAM_L_RGB,
    py_init_board,
    py_grid_to_json,
    py_legal_moves,
    py_apply_move,
    clear_en_passant,
)
from corpus import save_corpus          # noqa: E402


# --------------------------------------------------------------------------- #
# Grid format conversion                                                        #
# The Python fuzzer keeps a "flat" Python grid (8×8 list of Piece|None).       #
# JS bridge uses the same flat grid serialised as json (py_grid_to_json).      #
# Swift bridge expects the same 8×8 JSON format.                               #
# --------------------------------------------------------------------------- #

def _js_to_swift_grid(js_grid: list) -> list:
    """
    js_grid is an 8×8 row-major list (list[list[dict|None]]) as returned by
    JsBridge.chess_apply_move.  SwiftBridge uses the same shape — no conversion
    needed; both bridges share the same 8×8 JSON format.
    """
    return js_grid


def run_fuzzer(iterations: int, seed: int, max_ply: int) -> None:
    rng = random.Random(seed)
    crashes_dir = ROOT / "harness" / "crashes" / "swift_lockstep"
    crashes_dir.mkdir(parents=True, exist_ok=True)

    js    = JsBridge()
    swift = SwiftBridge()
    assert js.ping()    == "pong", "JS bridge not responding"
    assert swift.ping() == "pong", "Swift bridge not responding"

    total       = 0
    games_ok    = 0
    disagree    = 0
    errors      = 0
    total_plies = 0
    t0 = time.time()

    try:
        i = 0
        while iterations == 0 or i < iterations:
            game_seed = rng.randint(0, 2**32)
            game_rng  = random.Random(game_seed)
            team_r    = Team(*TEAM_R_RGB)
            team_l    = Team(*TEAM_L_RGB)
            py_grid   = py_init_board(team_r, team_l)

            # Initialise JS and Swift from the standard starting position
            js_grid    = js.chess_init(TEAM_R_RGB, TEAM_L_RGB)
            swift_grid = swift.chess_init(TEAM_R_RGB, TEAM_L_RGB)

            peace_time   = 0
            current_key  = "r"
            corpus_moves = []
            game_ok      = True

            for ply in range(max_ply):
                team = team_r if current_key == "r" else team_l

                # ── legal moves ──────────────────────────────────────────── #
                clear_en_passant(py_grid, team)
                py_json = py_grid_to_json(py_grid, team_r)

                try:
                    py_moves    = py_legal_moves(py_grid, team)
                    js_moves_r  = js.chess_legal_moves(
                        py_json, TEAM_R_RGB, TEAM_L_RGB, current_key)
                    sw_moves_r  = swift.chess_legal_moves(
                        swift_grid, TEAM_R_RGB, TEAM_L_RGB, current_key)
                except Exception as exc:
                    errors += 1
                    print(f"[ERROR] game={total} ply={ply}: {exc}")
                    game_ok = False; break

                js_moves    = {tuple(m) for m in js_moves_r}
                swift_moves = {tuple(m) for m in sw_moves_r}

                # Check all three agree
                disagreement = None
                if py_moves != js_moves:
                    disagreement = ("py_vs_js",
                                    sorted(py_moves - js_moves),
                                    sorted(js_moves - py_moves))
                elif py_moves != swift_moves:
                    disagreement = ("py_vs_swift",
                                    sorted(py_moves - swift_moves),
                                    sorted(swift_moves - py_moves))

                if disagreement:
                    disagree += 1
                    tag, extra_a, extra_b = disagreement
                    fname = f"moves_game{total:06d}_ply{ply}_{tag}.json"
                    crash = {
                        "seed": game_seed, "ply": ply,
                        "tag": tag,
                        "move_history": corpus_moves,
                        "extra_a": extra_a,
                        "extra_b": extra_b,
                    }
                    (crashes_dir / fname).write_text(json.dumps(crash, indent=2))
                    save_corpus(
                        crashes_dir, "chess", "fuzz_lockstep_swift",
                        TEAM_R_RGB, TEAM_L_RGB, corpus_moves,
                        {"ply": ply, "kind": "legal_moves",
                         "detail": tag,
                         "extra_a": extra_a[:8], "extra_b": extra_b[:8]},
                        game_seed,
                    )
                    print(f"[DISAGREE-MOVES] game={total} ply={ply} {tag} "
                          f"extra_a={len(extra_a)} extra_b={len(extra_b)} → {fname}")
                    game_ok = False; break

                if not py_moves:
                    break  # game over — no moves

                # ── pick & apply move ────────────────────────────────────── #
                move = game_rng.choice(sorted(py_moves))
                fr, fc, tr, tc = move

                is_capture = py_grid[tr][tc] is not None
                is_pawn    = isinstance(py_grid[fr][fc], Pawn)
                py_apply_move(py_grid, fr, fc, tr, tc)
                next_key   = "l" if current_key == "r" else "r"
                peace_time = 0 if (is_capture or is_pawn) else peace_time + 1

                try:
                    js_result = js.chess_apply_move(
                        py_json, TEAM_R_RGB, TEAM_L_RGB,
                        fr, fc, tr, tc, current_key, next_key, peace_time)
                    sw_result = swift.chess_apply_move(
                        swift_grid, TEAM_R_RGB, TEAM_L_RGB,
                        fr, fc, tr, tc, current_key, next_key, peace_time)
                except Exception as exc:
                    errors += 1
                    print(f"[ERROR] game={total} ply={ply} apply: {exc}")
                    game_ok = False; break

                py_hash = board_hash(py_grid, peace_time, next_key, team_r)
                js_hash = js_result["board_hash"]
                sw_hash = sw_result["board_hash"]

                corpus_moves.append({
                    "fr": fr, "fc": fc, "tr": tr, "tc": tc,
                    "team_key": current_key,
                    "flags": {},
                })

                hash_mismatch = None
                if py_hash != js_hash:
                    hash_mismatch = ("py_vs_js", py_hash, js_hash)
                elif py_hash != sw_hash:
                    hash_mismatch = ("py_vs_swift", py_hash, sw_hash)

                if hash_mismatch:
                    disagree += 1
                    tag, ha, hb = hash_mismatch
                    fname = f"hash_game{total:06d}_ply{ply}_{tag}.json"
                    crash = {
                        "seed": game_seed, "ply": ply,
                        "tag": tag, "move": move,
                        "hash_a": ha, "hash_b": hb,
                        "move_history": corpus_moves,
                    }
                    (crashes_dir / fname).write_text(json.dumps(crash, indent=2))
                    save_corpus(
                        crashes_dir, "chess", "fuzz_lockstep_swift",
                        TEAM_R_RGB, TEAM_L_RGB, corpus_moves,
                        {"ply": ply, "kind": "board_hash",
                         "detail": tag,
                         "hash_a": ha[:16], "hash_b": hb[:16]},
                        game_seed,
                    )
                    print(f"[DISAGREE-HASH] game={total} ply={ply} {tag} "
                          f"after {move} → {fname}")
                    game_ok = False; break

                # Advance Swift grid to the post-move state
                js_grid    = js_result["grid"]
                swift_grid = sw_result["grid"]
                current_key = next_key
                total_plies += 1

                if js_result["status"] in ("checkmate", "stalemate"):
                    break

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
        js.close()
        swift.close()

    elapsed = time.time() - t0
    print(f"\nDone. {total} games in {elapsed:.1f}s "
          f"({total_plies} total plies)")
    print(f"  ok={games_ok}  disagree={disagree}  errors={errors}")
    if disagree > 0:
        print(f"  Crash files in {crashes_dir}")
    if disagree > 0:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Swift ↔ JS ↔ Python lockstep chess fuzzer")
    parser.add_argument("--iterations", type=int, default=100,
                        help="Number of games (0 = infinite)")
    parser.add_argument("--seed",       type=int, default=42)
    parser.add_argument("--max-ply",    type=int, default=120,
                        help="Max half-moves per game")
    args = parser.parse_args()
    run_fuzzer(args.iterations, args.seed, args.max_ply)


if __name__ == "__main__":
    main()
