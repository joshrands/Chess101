#!/usr/bin/env python3
"""Chess gameplay lockstep fuzzer.

Plays random games from the starting position, comparing legal move sets
and board hashes at each step between Python, JS, and optionally HIL.
Disagreements are saved with full move history for replay, plus a
``.corpus.json`` file that can be replayed as a regression test or in the
interactive simulator.

Usage::

    bazel run //harness:fuzz_chess -- --iterations 100
    .venv/bin/python harness/fuzz_chess.py --iterations 100
    .venv/bin/python harness/fuzz_chess.py --iterations 0  # run forever

    # With HIL container (three-way comparison):
    .venv/bin/python harness/fuzz_chess.py --iterations 100 --hil-url ws://localhost:8766
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
from network.protocol import board_hash  # noqa: E402
from chess_helpers import (  # noqa: E402
    TEAM_R_RGB,
    TEAM_L_RGB,
    py_init_board,
    py_grid_to_json,
    py_legal_moves,
    py_apply_move,
    clear_en_passant,
)
from corpus import save_corpus  # noqa: E402

try:
    from hil.client import HilBridge
except ImportError:
    HilBridge = None  # type: ignore


def run_fuzzer(
    iterations: int, seed: int, max_ply: int, hil_url: str | None = None
) -> None:
    rng = random.Random(seed)
    crashes_dir = ROOT / "harness" / "crashes" / "chess"
    crashes_dir.mkdir(parents=True, exist_ok=True)

    bridge = JsBridge()
    assert bridge.ping() == "pong"

    # Optional HIL bridge for three-way comparison
    hil: HilBridge | None = None
    if hil_url and HilBridge:
        try:
            hil = HilBridge(url=hil_url, timeout=10.0)
            hil.connect(retries=3, delay=1.0)
            if not hil.ping():
                print(f"[WARN] HIL at {hil_url} not responding, continuing without HIL")
                hil = None
            else:
                print(f"[INFO] HIL connected at {hil_url}")
        except Exception as e:
            print(f"[WARN] HIL connection failed ({e}), continuing without HIL")
            hil = None

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
            peace_time = 0
            current_key = "r"
            move_history = []
            corpus_moves = []
            game_ok = True

            # Initialize HIL board at start of each game
            if hil:
                try:
                    hil.chess_init(TEAM_R_RGB, TEAM_L_RGB)
                except Exception as e:
                    print(f"[WARN] HIL init failed ({e}), skipping HIL for this game")

            for ply in range(max_ply):
                team = team_r if current_key == "r" else team_l

                # Clear en_passantable on current team (window expired)
                clear_en_passant(py_grid, team)

                grid_json = py_grid_to_json(py_grid, team_r)

                try:
                    py_moves = py_legal_moves(py_grid, team)
                    js_moves_raw = bridge.chess_legal_moves(
                        grid_json, TEAM_R_RGB, TEAM_L_RGB, current_key,
                    )
                    js_moves = {tuple(m) for m in js_moves_raw}

                    # HIL legal moves (optional)
                    hil_moves: set | None = None
                    if hil:
                        hil_moves_raw = hil.chess_legal_moves(current_key)
                        hil_moves = {tuple(m) for m in hil_moves_raw}
                except Exception as e:
                    errors += 1
                    print(f"[ERROR] game={total} ply={ply}: {e}")
                    game_ok = False
                    break

                # Check Python vs JS
                if py_moves != js_moves:
                    disagree += 1
                    fname = f"moves_game{total:06d}_ply{ply}.json"
                    crash = {
                        "seed": game_seed, "ply": ply,
                        "move_history": move_history,
                        "only_python": sorted(py_moves - js_moves),
                        "only_js": sorted(js_moves - py_moves),
                    }
                    (crashes_dir / fname).write_text(json.dumps(crash, indent=2))
                    save_corpus(
                        crashes_dir, "chess", "fuzz_chess",
                        TEAM_R_RGB, TEAM_L_RGB, corpus_moves,
                        {"ply": ply, "kind": "legal_moves",
                         "detail": f"only_python={sorted(py_moves - js_moves)} "
                                   f"only_js={sorted(js_moves - py_moves)}"},
                        game_seed,
                    )
                    print(f"[DISAGREE] game={total} ply={ply} "
                          f"py_extra={len(py_moves - js_moves)} "
                          f"js_extra={len(js_moves - py_moves)} → {fname}")
                    game_ok = False
                    break

                # Check Python vs HIL (if available)
                if hil_moves is not None and py_moves != hil_moves:
                    disagree += 1
                    fname = f"moves_hil_game{total:06d}_ply{ply}.json"
                    crash = {
                        "seed": game_seed, "ply": ply,
                        "move_history": move_history,
                        "only_python": sorted(py_moves - hil_moves),
                        "only_hil": sorted(hil_moves - py_moves),
                    }
                    (crashes_dir / fname).write_text(json.dumps(crash, indent=2))
                    print(f"[DISAGREE-HIL] game={total} ply={ply} "
                          f"py_extra={len(py_moves - hil_moves)} "
                          f"hil_extra={len(hil_moves - py_moves)} → {fname}")
                    game_ok = False
                    break

                if not py_moves:
                    break

                move = game_rng.choice(sorted(py_moves))
                fr, fc, tr, tc = move
                is_capture = py_grid[tr][tc] is not None
                is_pawn = isinstance(py_grid[fr][fc], Pawn)

                flags = py_apply_move(py_grid, fr, fc, tr, tc)

                peace_time = 0 if (is_capture or is_pawn) else peace_time + 1
                next_key = "l" if current_key == "r" else "r"

                try:
                    js_result = bridge.chess_apply_move(
                        grid_json, TEAM_R_RGB, TEAM_L_RGB,
                        fr, fc, tr, tc, current_key, next_key, peace_time,
                    )

                    # HIL apply move (optional)
                    hil_hash: str | None = None
                    if hil:
                        hil_result = hil.chess_apply_move(
                            fr, fc, tr, tc, current_key, next_key, peace_time
                        )
                        hil_hash = hil_result["board_hash"]
                except Exception as e:
                    errors += 1
                    print(f"[ERROR] game={total} ply={ply} apply: {e}")
                    game_ok = False
                    break

                py_hash = board_hash(py_grid, peace_time, next_key, team_r)
                js_hash = js_result["board_hash"]

                # Record move for corpus before checking hash
                corpus_moves.append({
                    "fr": fr, "fc": fc, "tr": tr, "tc": tc,
                    "team_key": current_key,
                    "flags": flags,
                })

                if py_hash != js_hash:
                    disagree += 1
                    fname = f"hash_game{total:06d}_ply{ply}.json"
                    crash = {
                        "seed": game_seed, "ply": ply,
                        "move": move, "move_history": move_history,
                        "py_hash": py_hash, "js_hash": js_hash,
                    }
                    (crashes_dir / fname).write_text(json.dumps(crash, indent=2))
                    save_corpus(
                        crashes_dir, "chess", "fuzz_chess",
                        TEAM_R_RGB, TEAM_L_RGB, corpus_moves,
                        {"ply": ply, "kind": "board_hash",
                         "detail": f"py={py_hash[:16]} js={js_hash[:16]}",
                         "py_hash": py_hash[:16], "js_hash": js_hash[:16]},
                        game_seed,
                    )
                    print(f"[DISAGREE] game={total} ply={ply} hash mismatch "
                          f"after {move} → {fname}")
                    game_ok = False
                    break

                # Check Python vs HIL hash (if available)
                if hil_hash is not None and py_hash != hil_hash:
                    disagree += 1
                    fname = f"hash_hil_game{total:06d}_ply{ply}.json"
                    crash = {
                        "seed": game_seed, "ply": ply,
                        "move": move, "move_history": move_history,
                        "py_hash": py_hash, "hil_hash": hil_hash,
                    }
                    (crashes_dir / fname).write_text(json.dumps(crash, indent=2))
                    print(f"[DISAGREE-HIL] game={total} ply={ply} hash mismatch "
                          f"py={py_hash[:16]} hil={hil_hash[:16]} → {fname}")
                    game_ok = False
                    break

                move_history.append(move)
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
        bridge.close()
        if hil:
            hil.close()

    elapsed = time.time() - t0
    print(f"\nDone. {total} games in {elapsed:.1f}s "
          f"({total_plies} total plies)")
    print(f"  ok={games_ok}  disagree={disagree}  errors={errors}")
    if hil_url:
        print(f"  HIL: {'connected' if hil else 'not available'}")
    if disagree > 0:
        print(f"  Crash files in {crashes_dir}")


def main():
    parser = argparse.ArgumentParser(description="Chess gameplay lockstep fuzzer")
    parser.add_argument("--hil-url", type=str, default=None,
                        help="HIL container WebSocket URL for three-way comparison")
    parser.add_argument("--iterations", type=int, default=100,
                        help="Number of games (0 = infinite)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-ply", type=int, default=120,
                        help="Max half-moves per game")
    args = parser.parse_args()
    run_fuzzer(args.iterations, args.seed, args.max_ply, args.hil_url)


if __name__ == "__main__":
    main()
