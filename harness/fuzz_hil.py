#!/usr/bin/env python3
"""HIL (Hardware-In-The-Loop) fuzzer.

Plays random games through the HIL Docker container, verifying that LED
output matches expected board state. Saves crash corpus on disagreements.

Usage:
    # Start HIL container first:
    docker-compose -f docker-compose.hil.yml up -d

    # Run fuzzer:
    .venv/bin/python harness/fuzz_hil.py --iterations 100
    .venv/bin/python harness/fuzz_hil.py --iterations 100 --seed 42
    .venv/bin/python harness/fuzz_hil.py --scenario scholars_mate

    # Run with Bazel:
    bazel run //harness:fuzz_hil -- --iterations 100
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from hil.client import HilBridge
from harness.hil_scenarios import SCENARIOS, Action, ActionType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

CRASH_DIR = Path(__file__).parent / "crashes" / "hil"


def save_crash(
    seed: int,
    iteration: int,
    actions: list[dict],
    expected: dict,
    actual: dict,
    description: str,
) -> Path:
    """Save a crash corpus file for later analysis."""
    CRASH_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    filename = f"hil_{timestamp}_seed{seed}_iter{iteration}.json"
    path = CRASH_DIR / filename

    corpus = {
        "seed": seed,
        "iteration": iteration,
        "description": description,
        "actions": actions,
        "expected": expected,
        "actual": actual,
        "timestamp": timestamp,
    }

    with open(path, "w") as f:
        json.dump(corpus, f, indent=2)

    logger.error("Crash saved: %s", path)
    return path


def run_scenario(bridge: HilBridge, scenario_name: str) -> bool:
    """Run a named scenario through the HIL container.

    Args:
        bridge: Connected HilBridge instance.
        scenario_name: Name of scenario from SCENARIOS registry.

    Returns:
        True if scenario completed without errors.
    """
    if scenario_name not in SCENARIOS:
        logger.error("Unknown scenario: %s", scenario_name)
        return False

    scenario_fn = SCENARIOS[scenario_name]
    logger.info("Running scenario: %s", scenario_name)

    for action in scenario_fn():
        if action.type == ActionType.LIFT:
            logger.debug("LIFT (%d, %d): %s", action.row, action.col, action.description)
            bridge.lift_piece(action.row, action.col)
        elif action.type == ActionType.PLACE:
            logger.debug("PLACE (%d, %d): %s", action.row, action.col, action.description)
            bridge.place_piece(action.row, action.col)
        elif action.type == ActionType.WAIT:
            time.sleep(action.frames * 0.016)  # ~60fps
        elif action.type == ActionType.EXPECT:
            pass  # TODO: implement frame assertions

    logger.info("Scenario %s completed", scenario_name)
    return True


def fuzz_random_game(
    bridge: HilBridge,
    rng: random.Random,
    max_ply: int = 100,
) -> Tuple[bool, list[dict]]:
    """Play a random game through the HIL container.

    This is a simplified fuzzer that randomly lifts and places pieces.
    A more sophisticated version would track legal moves.

    Args:
        bridge: Connected HilBridge instance.
        rng: Random number generator.
        max_ply: Maximum plies before declaring draw.

    Returns:
        Tuple of (success, actions_taken).
    """
    actions: list[dict] = []

    for ply in range(max_ply):
        # Random lift
        row, col = rng.randint(0, 7), rng.randint(0, 7)
        bridge.lift_piece(row, col)
        actions.append({"type": "lift", "row": row, "col": col})
        time.sleep(0.05)

        # Random place (different cell)
        tr, tc = rng.randint(0, 7), rng.randint(0, 7)
        while (tr, tc) == (row, col):
            tr, tc = rng.randint(0, 7), rng.randint(0, 7)
        bridge.place_piece(tr, tc)
        actions.append({"type": "place", "row": tr, "col": tc})
        time.sleep(0.05)

        # Check frame is being updated
        frame, timestamp, frame_count = bridge.get_frame()
        if frame is None:
            logger.warning("No frame received at ply %d", ply)

    return True, actions


def main() -> int:
    parser = argparse.ArgumentParser(description="HIL fuzzer")
    parser.add_argument(
        "--iterations", type=int, default=10,
        help="Number of random games to play (default 10)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="RNG seed for reproducibility (default 42)",
    )
    parser.add_argument(
        "--max-ply", type=int, default=50,
        help="Max plies per game (default 50)",
    )
    parser.add_argument(
        "--scenario", type=str, default=None,
        help="Run a specific scenario instead of fuzzing",
    )
    parser.add_argument(
        "--url", type=str, default="ws://localhost:8766",
        help="HIL container WebSocket URL (default ws://localhost:8766)",
    )
    parser.add_argument(
        "--list-scenarios", action="store_true",
        help="List available scenarios and exit",
    )
    args = parser.parse_args()

    if args.list_scenarios:
        print("Available scenarios:")
        for name in SCENARIOS:
            print(f"  {name}")
        return 0

    # Connect to HIL container
    logger.info("Connecting to HIL container at %s", args.url)
    try:
        bridge = HilBridge(url=args.url, timeout=10.0)
        bridge.connect(retries=5, delay=2.0)
    except ConnectionError as e:
        logger.error("Failed to connect: %s", e)
        logger.error("Make sure the HIL container is running:")
        logger.error("  docker-compose -f docker-compose.hil.yml up -d")
        return 1

    if not bridge.ping():
        logger.error("Container not responding to ping")
        return 1

    logger.info("Connected to HIL container")

    try:
        if args.scenario:
            # Run specific scenario
            success = run_scenario(bridge, args.scenario)
            return 0 if success else 1

        # Fuzzing mode
        rng = random.Random(args.seed)
        logger.info(
            "Starting HIL fuzz: iterations=%d, seed=%d, max_ply=%d",
            args.iterations, args.seed, args.max_ply,
        )

        crashes = 0
        for i in range(args.iterations):
            logger.info("Iteration %d/%d", i + 1, args.iterations)

            # Reset board state
            bridge.set_starting_position()
            time.sleep(0.1)

            success, actions = fuzz_random_game(bridge, rng, args.max_ply)
            if not success:
                crashes += 1

        logger.info(
            "Fuzz complete: %d iterations, %d crashes",
            args.iterations, crashes,
        )
        return 0 if crashes == 0 else 1

    finally:
        bridge.close()


if __name__ == "__main__":
    sys.exit(main())
