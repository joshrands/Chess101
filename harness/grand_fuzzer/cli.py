#!/usr/bin/env python3
"""CLI for Grand Fuzzer Suite."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from harness.grand_fuzzer.fuzzers.grand_e2e import GrandE2EFuzzer, SlaveMode


def cmd_grand(args: argparse.Namespace) -> int:
    """Run the Grand E2E Lockstep Fuzzer."""
    mode_map = {
        "local": SlaveMode.LOCAL,
        "lan_host": SlaveMode.LAN_HOST,
        "lan_guest": SlaveMode.LAN_GUEST,
        "online_host": SlaveMode.ONLINE_HOST,
        "online_guest": SlaveMode.ONLINE_GUEST,
    }

    mode = mode_map.get(args.mode, SlaveMode.LOCAL)

    print(f"[INFO] Grand E2E Lockstep Fuzzer")
    print(f"[INFO] Mode: {mode.name}, Iterations: {args.iterations}, Seed: {args.seed}")

    if args.hil_url:
        print(f"[INFO] HIL: {args.hil_url}")

    fuzzer = GrandE2EFuzzer(
        seed=args.seed,
        mode=mode,
        max_ply=args.max_ply,
        hil_url=args.hil_url,
    )

    t0 = time.time()
    try:
        total, ok, failed = fuzzer.run_fuzzing(args.iterations)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 1

    elapsed = time.time() - t0
    print(f"\nDone. {total} games in {elapsed:.1f}s")
    print(f"  ok={ok}  failed={failed}")

    return 1 if failed > 0 else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Grand Fuzzer Suite")
    subparsers = parser.add_subparsers(dest="command", required=True)

    grand_parser = subparsers.add_parser("grand", help="Run Grand E2E Lockstep Fuzzer")
    grand_parser.add_argument("--iterations", "-n", type=int, default=100)
    grand_parser.add_argument("--seed", "-s", type=int, default=42)
    grand_parser.add_argument("--max-ply", type=int, default=120)
    grand_parser.add_argument(
        "--mode", choices=["local", "lan_host", "lan_guest", "online_host", "online_guest"],
        default="local"
    )
    grand_parser.add_argument("--hil-url", type=str, default=None)

    args = parser.parse_args()

    if args.command == "grand":
        return cmd_grand(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
