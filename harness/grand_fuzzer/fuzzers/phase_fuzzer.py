"""Phase Fuzzer - tests pre-PLAYING game phases.

Tests COLOR_PICK, WAR_GAMES, and SETUP phases for:
- Duplicate messages
- Out-of-order messages
- Invalid values
- Missing config
- Protocol violations
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from harness.chess_helpers import TEAM_R_RGB, TEAM_L_RGB
from harness.corpus import save_corpus


class Scenario(Enum):
    """Phase test scenarios."""
    # COLOR_PICK
    NORMAL_COLOR_PICK = auto()
    DUPLICATE_COLOR_CHOSEN = auto()
    INVALID_COLOR_IDX_NEGATIVE = auto()
    INVALID_COLOR_IDX_OVERFLOW = auto()
    SAME_COLOR_BOTH_TEAMS = auto()
    COLOR_IDX_WRONG_TYPE = auto()

    # WAR_GAMES
    NORMAL_WAR_GAMES = auto()
    DUPLICATE_WAR_GAMES = auto()
    IS_AI_WRONG_TYPE = auto()
    WAR_GAMES_BEFORE_COLOR = auto()

    # GAME_START
    GAME_START_BEFORE_CONFIG = auto()
    GAME_START_MISSING_COLOR = auto()
    GAME_START_MISSING_WAR_GAMES = auto()
    DUPLICATE_GAME_START = auto()

    # SETUP
    SETUP_COMPLETE_BEFORE_GAME_START = auto()
    DUPLICATE_SETUP_COMPLETE = auto()


@dataclass
class ScenarioResult:
    """Result of a scenario test."""
    scenario: Scenario
    passed: bool
    message: str
    events: list[dict]


class PhaseStateMachine:
    """Simulates game phase state for testing."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.color_r: int | None = None
        self.color_l: int | None = None
        self.is_ai_r: bool | None = None
        self.is_ai_l: bool | None = None
        self.game_started: bool = False
        self.setup_complete_r: bool = False
        self.setup_complete_l: bool = False
        self.errors: list[str] = []
        self.events: list[dict] = []

    def handle_color_chosen(self, msg: dict) -> bool:
        """Handle color_chosen message. Returns True if valid."""
        self.events.append(msg)

        team_key = msg.get("team_key")
        color_idx = msg.get("color_idx")

        # Type check
        if not isinstance(color_idx, int):
            self.errors.append(f"color_idx not int: {type(color_idx)}")
            return False

        # Bounds check
        if not (0 <= color_idx <= 5):
            self.errors.append(f"color_idx out of range: {color_idx}")
            return False

        # Duplicate check
        if team_key == "r":
            if self.color_r is not None:
                self.errors.append(f"duplicate color_chosen for team_r")
                return False
            self.color_r = color_idx
        elif team_key == "l":
            if self.color_l is not None:
                self.errors.append(f"duplicate color_chosen for team_l")
                return False
            self.color_l = color_idx
        else:
            self.errors.append(f"invalid team_key: {team_key}")
            return False

        # Same color check (only if both set)
        if self.color_r is not None and self.color_l is not None:
            if self.color_r == self.color_l:
                self.errors.append(f"both teams chose same color: {self.color_r}")
                return False

        return True

    def handle_war_games_choice(self, msg: dict) -> bool:
        """Handle war_games_choice message. Returns True if valid."""
        self.events.append(msg)

        team_key = msg.get("team_key")
        is_ai = msg.get("is_ai")

        # Type check
        if not isinstance(is_ai, bool):
            self.errors.append(f"is_ai not bool: {type(is_ai)}")
            return False

        # Duplicate check
        if team_key == "r":
            if self.is_ai_r is not None:
                self.errors.append(f"duplicate war_games_choice for team_r")
                return False
            self.is_ai_r = is_ai
        elif team_key == "l":
            if self.is_ai_l is not None:
                self.errors.append(f"duplicate war_games_choice for team_l")
                return False
            self.is_ai_l = is_ai
        else:
            self.errors.append(f"invalid team_key: {team_key}")
            return False

        return True

    def handle_game_start(self, msg: dict) -> bool:
        """Handle game_start message. Returns True if valid."""
        self.events.append(msg)

        # Check config complete
        if self.color_r is None:
            self.errors.append("game_start before color_r set")
            return False
        if self.color_l is None:
            self.errors.append("game_start before color_l set")
            return False
        if self.is_ai_r is None:
            self.errors.append("game_start before is_ai_r set")
            return False
        if self.is_ai_l is None:
            self.errors.append("game_start before is_ai_l set")
            return False

        # Duplicate check
        if self.game_started:
            self.errors.append("duplicate game_start")
            return False

        self.game_started = True
        return True

    def handle_setup_complete(self, msg: dict) -> bool:
        """Handle setup_complete message. Returns True if valid."""
        self.events.append(msg)

        team_key = msg.get("team_key")

        # Must be after game_start
        if not self.game_started:
            self.errors.append("setup_complete before game_start")
            return False

        if team_key == "r":
            if self.setup_complete_r:
                self.errors.append("duplicate setup_complete for team_r")
                return False
            self.setup_complete_r = True
        elif team_key == "l":
            if self.setup_complete_l:
                self.errors.append("duplicate setup_complete for team_l")
                return False
            self.setup_complete_l = True
        else:
            self.errors.append(f"invalid team_key: {team_key}")
            return False

        return True

    def config_complete(self) -> bool:
        return all([
            self.color_r is not None,
            self.color_l is not None,
            self.is_ai_r is not None,
            self.is_ai_l is not None,
        ])


class PhaseFuzzer:
    """Fuzzer for pre-PLAYING game phases."""

    def __init__(self, seed: int, crashes_dir: Path | None = None):
        self._seed = seed
        self._rng = random.Random(seed)
        self._crashes_dir = crashes_dir or ROOT / "harness" / "crashes" / "phase"
        self._crashes_dir.mkdir(parents=True, exist_ok=True)

    def run_scenario(self, scenario: Scenario) -> ScenarioResult:
        """Run a single scenario."""
        sm = PhaseStateMachine()

        if scenario == Scenario.NORMAL_COLOR_PICK:
            sm.handle_color_chosen({"team_key": "r", "color_idx": 0})
            sm.handle_color_chosen({"team_key": "l", "color_idx": 1})
            passed = len(sm.errors) == 0 and sm.color_r == 0 and sm.color_l == 1
            return ScenarioResult(scenario, passed, "normal flow", sm.events)

        if scenario == Scenario.DUPLICATE_COLOR_CHOSEN:
            sm.handle_color_chosen({"team_key": "r", "color_idx": 0})
            sm.handle_color_chosen({"team_key": "r", "color_idx": 1})  # duplicate
            passed = len(sm.errors) > 0  # should have error
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.INVALID_COLOR_IDX_NEGATIVE:
            result = sm.handle_color_chosen({"team_key": "r", "color_idx": -1})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.INVALID_COLOR_IDX_OVERFLOW:
            result = sm.handle_color_chosen({"team_key": "r", "color_idx": 99})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.SAME_COLOR_BOTH_TEAMS:
            sm.handle_color_chosen({"team_key": "r", "color_idx": 2})
            result = sm.handle_color_chosen({"team_key": "l", "color_idx": 2})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.COLOR_IDX_WRONG_TYPE:
            result = sm.handle_color_chosen({"team_key": "r", "color_idx": "zero"})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.NORMAL_WAR_GAMES:
            sm.handle_war_games_choice({"team_key": "r", "is_ai": False})
            sm.handle_war_games_choice({"team_key": "l", "is_ai": True})
            passed = len(sm.errors) == 0
            return ScenarioResult(scenario, passed, "normal flow", sm.events)

        if scenario == Scenario.DUPLICATE_WAR_GAMES:
            sm.handle_war_games_choice({"team_key": "r", "is_ai": False})
            sm.handle_war_games_choice({"team_key": "r", "is_ai": True})  # dup
            passed = len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.IS_AI_WRONG_TYPE:
            result = sm.handle_war_games_choice({"team_key": "r", "is_ai": "yes"})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.WAR_GAMES_BEFORE_COLOR:
            # This should actually be allowed - order shouldn't matter
            sm.handle_war_games_choice({"team_key": "r", "is_ai": False})
            sm.handle_color_chosen({"team_key": "r", "color_idx": 0})
            # Both should succeed
            passed = len(sm.errors) == 0
            return ScenarioResult(scenario, passed, "order flexible", sm.events)

        if scenario == Scenario.GAME_START_BEFORE_CONFIG:
            result = sm.handle_game_start({})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.GAME_START_MISSING_COLOR:
            sm.handle_war_games_choice({"team_key": "r", "is_ai": False})
            sm.handle_war_games_choice({"team_key": "l", "is_ai": False})
            result = sm.handle_game_start({})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.GAME_START_MISSING_WAR_GAMES:
            sm.handle_color_chosen({"team_key": "r", "color_idx": 0})
            sm.handle_color_chosen({"team_key": "l", "color_idx": 1})
            result = sm.handle_game_start({})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.DUPLICATE_GAME_START:
            sm.handle_color_chosen({"team_key": "r", "color_idx": 0})
            sm.handle_color_chosen({"team_key": "l", "color_idx": 1})
            sm.handle_war_games_choice({"team_key": "r", "is_ai": False})
            sm.handle_war_games_choice({"team_key": "l", "is_ai": False})
            sm.handle_game_start({})
            result = sm.handle_game_start({})  # duplicate
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.SETUP_COMPLETE_BEFORE_GAME_START:
            result = sm.handle_setup_complete({"team_key": "r"})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.DUPLICATE_SETUP_COMPLETE:
            sm.handle_color_chosen({"team_key": "r", "color_idx": 0})
            sm.handle_color_chosen({"team_key": "l", "color_idx": 1})
            sm.handle_war_games_choice({"team_key": "r", "is_ai": False})
            sm.handle_war_games_choice({"team_key": "l", "is_ai": False})
            sm.handle_game_start({})
            sm.handle_setup_complete({"team_key": "r"})
            result = sm.handle_setup_complete({"team_key": "r"})  # dup
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        return ScenarioResult(scenario, False, "unknown scenario", [])

    def run_all_scenarios(self) -> list[ScenarioResult]:
        """Run all scenarios."""
        results = []
        for scenario in Scenario:
            result = self.run_scenario(scenario)
            results.append(result)
        return results

    def run_fuzzing(self, iterations: int) -> tuple[int, int, int]:
        """Run all scenarios. Returns (total, passed, failed)."""
        results = self.run_all_scenarios()

        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = total - passed

        for r in results:
            status = "PASS" if r.passed else "FAIL"
            print(f"  {status}: {r.scenario.name} - {r.message}")

        if failed > 0:
            for r in results:
                if not r.passed:
                    self._save_failure(r)

        return total, passed, failed

    def _save_failure(self, result: ScenarioResult) -> Path:
        """Save failed scenario to corpus."""
        failure = {
            "ply": 0,
            "kind": "phase_violation",
            "scenario": result.scenario.name,
            "message": result.message,
            "events": result.events,
        }
        return save_corpus(
            self._crashes_dir, "chess", "phase_fuzzer",
            TEAM_R_RGB, TEAM_L_RGB, [], failure, self._seed,
        )


def main() -> int:
    """Run phase fuzzer."""
    import argparse

    parser = argparse.ArgumentParser(description="Phase Fuzzer")
    parser.add_argument("--iterations", "-n", type=int, default=100)
    parser.add_argument("--seed", "-s", type=int, default=42)
    args = parser.parse_args()

    print(f"[INFO] Phase Fuzzer: seed={args.seed}")

    fuzzer = PhaseFuzzer(seed=args.seed)
    total, passed, failed = fuzzer.run_fuzzing(args.iterations)

    print(f"\nDone. {total} scenarios")
    print(f"  passed={passed}  failed={failed}")

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
