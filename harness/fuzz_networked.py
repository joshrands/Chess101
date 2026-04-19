#!/usr/bin/env python3
"""Networked lockstep fuzzer — four-way parity: Python, JS engine, JS spectator, HIL.

Plays random games from the starting position, applying each move on all
implementations simultaneously. At every ply, verifies:
  - Python engine grid matches JS spectator grid (type + team)
  - JS engine grid matches JS spectator grid (type + team)
  - Python board_hash matches JS board_hash (full state including touched/ep)
  - HIL board_hash matches Python board_hash (when HIL is connected)

Disagreements are saved with full move history and flags for replay, plus a
``.corpus.json`` file for regression testing and interactive replay.

Usage::

    bazel run //harness:fuzz_networked -- --iterations 100
    .venv/bin/python harness/fuzz_networked.py --iterations 100
    .venv/bin/python harness/fuzz_networked.py --iterations 0   # run forever

    # With HIL container (four-way comparison):
    .venv/bin/python harness/fuzz_networked.py --iterations 100 --hil-url ws://localhost:8766
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
from network.protocol import board_hash, encode_grid  # noqa: E402
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
from corpus import save_corpus  # noqa: E402

try:
    from hil.client import HilBridge
except ImportError:
    HilBridge = None  # type: ignore


# ── fuzzer ────────────────────────────────────────────────────────────────

def run_fuzzer(
    iterations: int, seed: int, max_ply: int, hil_url: str | None = None
) -> None:
    rng = random.Random(seed)
    crashes_dir = ROOT / "harness" / "crashes" / "networked"
    crashes_dir.mkdir(parents=True, exist_ok=True)

    bridge = JsBridge()
    assert bridge.ping() == "pong"

    # Optional HIL bridge for four-way comparison
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

            # Initialize HIL board
            if hil:
                try:
                    hil.chess_init(TEAM_R_RGB, TEAM_L_RGB)
                except Exception as e:
                    print(f"[WARN] HIL init failed ({e}), skipping HIL for this game")

            peace_time = 0
            current_key = "r"
            move_history = []
            corpus_moves = []
            game_ok = True

            for ply in range(max_ply):
                team = team_r if current_key == "r" else team_l

                # Clear en passant
                clear_en_passant(py_grid, team)

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

                    # Apply on HIL (optional)
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

                # Compare Python vs spectator
                py_snap = py_grid_snapshot(py_grid, team_r)
                match_ps, diff_ps = grids_equal(py_snap, spec_grid)

                # Compare JS engine vs spectator
                js_snap = js_grid_to_snapshot(js_grid_json)
                match_js, diff_js = grids_equal(js_snap, spec_grid)

                # Compare Python vs JS engine hash
                py_hash = board_hash(py_grid, peace_time, next_key, team_r)
                js_hash = js_result["board_hash"]

                # Compare Python vs HIL hash (if available)
                match_hil = hil_hash is None or py_hash == hil_hash

                # Record move for corpus before checking disagreement
                corpus_moves.append({
                    "fr": fr, "fc": fc, "tr": tr, "tc": tc,
                    "team_key": current_key,
                    "flags": flags,
                })

                if not match_ps or not match_js or py_hash != js_hash or not match_hil:
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
                        "hil_hash_match": match_hil,
                        "py_hash": py_hash[:16],
                        "js_hash": js_hash[:16],
                        "hil_hash": hil_hash[:16] if hil_hash else None,
                    }
                    (crashes_dir / fname).write_text(json.dumps(crash, indent=2))

                    # Build failure detail
                    kind_parts = []
                    if not match_ps or not match_js:
                        kind_parts.append("grid_mismatch")
                    if py_hash != js_hash:
                        kind_parts.append("board_hash")
                    if not match_hil:
                        kind_parts.append("hil_hash")
                    failure_kind = kind_parts[0] if len(kind_parts) == 1 else "grid_mismatch"

                    detail_parts = []
                    if not match_ps:
                        detail_parts.append(f"py↔spec:{diff_ps}")
                    if not match_js:
                        detail_parts.append(f"js↔spec:{diff_js}")
                    if py_hash != js_hash:
                        detail_parts.append(f"hash: py={py_hash[:16]} js={js_hash[:16]}")
                    if not match_hil:
                        detail_parts.append(f"hil: py={py_hash[:16]} hil={hil_hash[:16] if hil_hash else 'N/A'}")

                    save_corpus(
                        crashes_dir, "networked", "fuzz_networked",
                        TEAM_R_RGB, TEAM_L_RGB, corpus_moves,
                        {"ply": ply, "kind": failure_kind,
                         "detail": "; ".join(detail_parts),
                         "py_hash": py_hash[:16], "js_hash": js_hash[:16]},
                        game_seed,
                    )

                    kind = []
                    if not match_ps:
                        kind.append(f"py↔spec:{diff_ps}")
                    if not match_js:
                        kind.append(f"js↔spec:{diff_js}")
                    if py_hash != js_hash:
                        kind.append("hash")
                    if not match_hil:
                        kind.append("hil")
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
    parser = argparse.ArgumentParser(
        description="Networked lockstep fuzzer — Python vs JS engine vs JS spectator vs HIL",
    )
    parser.add_argument("--hil-url", type=str, default=None,
                        help="HIL container WebSocket URL for four-way comparison")
    parser.add_argument("--iterations", type=int, default=100,
                        help="Number of games (0 = infinite)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-ply", type=int, default=120,
                        help="Max half-moves per game")
    args = parser.parse_args()
    run_fuzzer(args.iterations, args.seed, args.max_ply, args.hil_url)


if __name__ == "__main__":
    main()
