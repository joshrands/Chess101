#!/usr/bin/env python3
"""Unified lockstep chess fuzzer.

Tests Python, JS, Swift, and HIL chess engines in lockstep, comparing
legal moves and board hashes at each ply. Disagreements are saved as
crash files for replay.

Usage::

    # Fuzz testing (random games):
    bazel run //harness:fuzz_lockstep -- --iterations 100
    .venv/bin/python harness/fuzz_lockstep.py --iterations 100
    .venv/bin/python harness/fuzz_lockstep.py --engines python,js,swift
    .venv/bin/python harness/fuzz_lockstep.py --hil-url ws://localhost:8766

    # Corpus regression tests (replay saved disagreements):
    bazel run //harness:fuzz_lockstep -- --test-corpus
    .venv/bin/python harness/fuzz_lockstep.py --test-corpus
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
from harness.corpus import discover_corpus


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
        help="Comma-separated engine names (default: python,js,swift). "
             "WARNING: Omitting engines means those platforms are NOT tested.",
    )
    parser.add_argument(
        "--require-all", action="store_true", default=True,
        help="Fail if any engine cannot be initialized (default: true)",
    )
    parser.add_argument(
        "--no-require-all", action="store_false", dest="require_all",
        help="Allow partial engine list (for debugging only)",
    )
    parser.add_argument(
        "--hil-url", type=str, default=None,
        help="HIL container WebSocket URL (adds HIL engine)",
    )
    parser.add_argument(
        "--test-corpus", action="store_true",
        help="Run corpus regression tests instead of fuzzing",
    )
    parser.add_argument(
        "--corpus-dir", type=str, default=None,
        help="Directory to search for corpus files (default: harness/crashes/)",
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
        try:
            engines.append(AVAILABLE_ENGINES[name]())
        except Exception as e:
            if args.require_all:
                print(f"[ERROR] Failed to initialize {name} engine: {e}")
                print("All engines must initialize. Use --no-require-all to skip (debug only).")
                return 1
            print(f"[WARN] Skipping {name} engine: {e}")

    hil = None
    if args.hil_url:
        hil = HilEngine(args.hil_url)
        hil.connect(retries=3, delay=1.0)
        engines.append(hil)
        print(f"[INFO] HIL connected at {args.hil_url}")

    if len(engines) < 2:
        print("[ERROR] Need at least 2 engines for lockstep testing")
        return 1

    engine_list = ", ".join(e.name for e in engines)
    print(f"[INFO] Engines: {engine_list}")

    runner = LockstepRunner(
        engines=engines,
        crashes_dir=crashes_dir,
        seed=args.seed,
        max_ply=args.max_ply,
    )

    if args.test_corpus:
        return run_corpus_tests(runner, engines, args, ROOT)

    print(f"[INFO] Starting lockstep fuzz: iterations={args.iterations}, "
          f"seed={args.seed}, max_ply={args.max_ply}")

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


def run_corpus_tests(
    runner: LockstepRunner,
    engines: list,
    args: argparse.Namespace,
    root: Path,
) -> int:
    """Run corpus regression tests. Returns exit code."""
    corpus_dir = Path(args.corpus_dir) if args.corpus_dir else root / "harness" / "crashes"
    corpus_files = discover_corpus(corpus_dir, corpus_type="chess")

    if not corpus_files:
        print(f"[WARN] No corpus files found in {corpus_dir}")
        return 0

    print(f"[INFO] Running {len(corpus_files)} corpus regression tests")

    passed = 0
    failed = 0
    failures: list[tuple[Path, str]] = []

    t0 = time.time()
    try:
        for corpus_path in corpus_files:
            ok, msg = runner.replay_corpus(corpus_path)
            if ok:
                print(f"  PASS: {corpus_path.name}")
                passed += 1
            else:
                print(f"  FAIL: {corpus_path.name} - {msg}")
                failed += 1
                failures.append((corpus_path, msg))
    finally:
        for e in engines:
            e.close()

    elapsed = time.time() - t0
    print(f"\nCorpus tests done in {elapsed:.1f}s")
    print(f"  passed={passed}  failed={failed}")

    if failures:
        print("\nFailed tests:")
        for path, msg in failures:
            print(f"  {path}: {msg}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
