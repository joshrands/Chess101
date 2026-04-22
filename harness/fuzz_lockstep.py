#!/usr/bin/env python3
"""Unified lockstep chess fuzzer.

Tests Python, JS, Swift, and HIL chess engines in lockstep, comparing
legal moves and board hashes at each ply. Disagreements are saved as
crash files for replay.

Usage::

    bazel run //harness:fuzz_lockstep -- --iterations 100
    .venv/bin/python harness/fuzz_lockstep.py --iterations 100
    .venv/bin/python harness/fuzz_lockstep.py --engines python,js,swift
    .venv/bin/python harness/fuzz_lockstep.py --hil-url ws://localhost:8766
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.lockstep_runner import (
    PythonEngine,
    JsEngine,
    SwiftEngine,
    HilEngine,
    LockstepRunner,
)


AVAILABLE_ENGINES = {
    "python": PythonEngine,
    "js": JsEngine,
    "swift": SwiftEngine,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Unified lockstep chess fuzzer"
    )
    parser.add_argument(
        "--iterations", type=int, default=100,
        help="Number of games (0 = infinite)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="RNG seed for reproducibility",
    )
    parser.add_argument(
        "--max-ply", type=int, default=120,
        help="Max half-moves per game",
    )
    parser.add_argument(
        "--engines", type=str, default="python,js,swift",
        help="Comma-separated engine names (default: python,js,swift)",
    )
    parser.add_argument(
        "--hil-url", type=str, default=None,
        help="HIL container WebSocket URL (adds HIL engine)",
    )
    args = parser.parse_args()

    crashes_dir = ROOT / "harness" / "crashes" / "lockstep"

    engine_names = [e.strip() for e in args.engines.split(",")]
    engines = []

    for name in engine_names:
        if name not in AVAILABLE_ENGINES:
            print(f"[ERROR] Unknown engine: {name}")
            print(f"Available: {', '.join(AVAILABLE_ENGINES.keys())}")
            return 1
        engines.append(AVAILABLE_ENGINES[name]())

    hil = None
    if args.hil_url:
        try:
            hil = HilEngine(args.hil_url)
            hil.connect(retries=3, delay=1.0)
            engines.append(hil)
            print(f"[INFO] HIL connected at {args.hil_url}")
        except Exception as e:
            print(f"[WARN] HIL connection failed ({e}), continuing without HIL")

    if len(engines) < 2:
        print("[ERROR] Need at least 2 engines for lockstep testing")
        return 1

    engine_list = ", ".join(e.name for e in engines)
    print(f"[INFO] Engines: {engine_list}")
    print(f"[INFO] Starting lockstep fuzz: iterations={args.iterations}, "
          f"seed={args.seed}, max_ply={args.max_ply}")

    runner = LockstepRunner(
        engines=engines,
        crashes_dir=crashes_dir,
        seed=args.seed,
        max_ply=args.max_ply,
    )

    t0 = time.time()
    try:
        total, ok, disagree = runner.run_fuzzing(args.iterations)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        total, ok, disagree = 0, 0, 0
    finally:
        for e in engines:
            e.close()

    elapsed = time.time() - t0
    print(f"\nDone. {total} games in {elapsed:.1f}s")
    print(f"  ok={ok}  disagree={disagree}")
    if disagree > 0:
        print(f"  Crash files in {crashes_dir}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
