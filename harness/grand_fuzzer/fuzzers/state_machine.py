"""State Machine Fuzzer - tests game phase violations.

Tests:
- move during GAME_OVER
- color_chosen during PLAYING
- game_start sent twice
- setup_complete during PLAYING
- undo during wrong phases
"""
from __future__ import annotations

import random
import sys
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from harness.chess_helpers import TEAM_R_RGB, TEAM_L_RGB
from harness.corpus import save_corpus


class GamePhase(Enum):
    """Game phases from simulator/app.py."""
    LOBBY = auto()
    COLOR_PICK = auto()
    WAR_GAMES = auto()
    SETUP = auto()
    PLAYING = auto()
    GAME_OVER = auto()


class MessageType(Enum):
    """Message types that can be sent."""
    COLOR_CHOSEN = auto()
    WAR_GAMES_CHOICE = auto()
    GAME_START = auto()
    SETUP_COMPLETE = auto()
    MOVE = auto()
    UNDO_REQUEST = auto()
    UNDO_ACCEPT = auto()
    RESIGN = auto()


class Scenario(Enum):
    """State machine violation scenarios."""
    # Valid transitions
    VALID_FULL_FLOW = auto()

    # Phase violations
    MOVE_DURING_LOBBY = auto()
    MOVE_DURING_COLOR_PICK = auto()
    MOVE_DURING_WAR_GAMES = auto()
    MOVE_DURING_SETUP = auto()
    MOVE_DURING_GAME_OVER = auto()

    COLOR_CHOSEN_DURING_LOBBY = auto()
    COLOR_CHOSEN_DURING_PLAYING = auto()
    COLOR_CHOSEN_DURING_GAME_OVER = auto()

    WAR_GAMES_DURING_LOBBY = auto()
    WAR_GAMES_DURING_PLAYING = auto()

    GAME_START_DURING_LOBBY = auto()
    GAME_START_TWICE = auto()

    SETUP_COMPLETE_DURING_LOBBY = auto()
    SETUP_COMPLETE_DURING_PLAYING = auto()
    SETUP_COMPLETE_TWICE = auto()

    UNDO_DURING_SETUP = auto()
    RESIGN_DURING_SETUP = auto()


@dataclass
class ScenarioResult:
    """Result of a scenario test."""
    scenario: Scenario
    passed: bool
    message: str
    events: list[dict]


class GameStateMachine:
    """Simulates game phase state machine for testing."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.phase = GamePhase.LOBBY
        self.color_r_set = False
        self.color_l_set = False
        self.war_games_r_set = False
        self.war_games_l_set = False
        self.game_started = False
        self.setup_r_complete = False
        self.setup_l_complete = False
        self.errors: list[str] = []
        self.events: list[dict] = []

    def _allowed_in_phase(self, msg_type: MessageType) -> bool:
        """Check if message type is allowed in current phase."""
        allowed = {
            GamePhase.LOBBY: set(),  # No game messages in lobby
            GamePhase.COLOR_PICK: {MessageType.COLOR_CHOSEN},
            GamePhase.WAR_GAMES: {MessageType.WAR_GAMES_CHOICE},
            GamePhase.SETUP: {MessageType.GAME_START, MessageType.SETUP_COMPLETE},
            GamePhase.PLAYING: {
                MessageType.MOVE,
                MessageType.UNDO_REQUEST,
                MessageType.UNDO_ACCEPT,
                MessageType.RESIGN,
            },
            GamePhase.GAME_OVER: {MessageType.RESIGN},  # Can resign to acknowledge
        }
        return msg_type in allowed.get(self.phase, set())

    def handle_message(self, msg_type: MessageType, msg: dict) -> bool:
        """Handle a message. Returns True if valid."""
        self.events.append({"type": msg_type.name, "phase": self.phase.name, **msg})

        if not self._allowed_in_phase(msg_type):
            self.errors.append(
                f"{msg_type.name} not allowed in {self.phase.name}"
            )
            return False

        if msg_type == MessageType.COLOR_CHOSEN:
            return self._handle_color_chosen(msg)
        elif msg_type == MessageType.WAR_GAMES_CHOICE:
            return self._handle_war_games(msg)
        elif msg_type == MessageType.GAME_START:
            return self._handle_game_start(msg)
        elif msg_type == MessageType.SETUP_COMPLETE:
            return self._handle_setup_complete(msg)
        elif msg_type == MessageType.MOVE:
            return self._handle_move(msg)
        elif msg_type == MessageType.UNDO_REQUEST:
            return True  # Always allowed in PLAYING
        elif msg_type == MessageType.UNDO_ACCEPT:
            return True
        elif msg_type == MessageType.RESIGN:
            self.phase = GamePhase.GAME_OVER
            return True

        return False

    def _handle_color_chosen(self, msg: dict) -> bool:
        team_key = msg.get("team_key")
        if team_key == "r":
            if self.color_r_set:
                self.errors.append("duplicate color_chosen for team_r")
                return False
            self.color_r_set = True
        elif team_key == "l":
            if self.color_l_set:
                self.errors.append("duplicate color_chosen for team_l")
                return False
            self.color_l_set = True

        if self.color_r_set and self.color_l_set:
            self.phase = GamePhase.WAR_GAMES
        return True

    def _handle_war_games(self, msg: dict) -> bool:
        team_key = msg.get("team_key")
        if team_key == "r":
            if self.war_games_r_set:
                self.errors.append("duplicate war_games for team_r")
                return False
            self.war_games_r_set = True
        elif team_key == "l":
            if self.war_games_l_set:
                self.errors.append("duplicate war_games for team_l")
                return False
            self.war_games_l_set = True

        if self.war_games_r_set and self.war_games_l_set:
            self.phase = GamePhase.SETUP
        return True

    def _handle_game_start(self, msg: dict) -> bool:
        if self.game_started:
            self.errors.append("game_start sent twice")
            return False
        self.game_started = True
        return True

    def _handle_setup_complete(self, msg: dict) -> bool:
        team_key = msg.get("team_key")
        if team_key == "r":
            if self.setup_r_complete:
                self.errors.append("duplicate setup_complete for team_r")
                return False
            self.setup_r_complete = True
        elif team_key == "l":
            if self.setup_l_complete:
                self.errors.append("duplicate setup_complete for team_l")
                return False
            self.setup_l_complete = True

        if self.setup_r_complete and self.setup_l_complete:
            self.phase = GamePhase.PLAYING
        return True

    def _handle_move(self, msg: dict) -> bool:
        # In real game, would validate move
        return True

    def start_color_pick(self):
        """Transition from LOBBY to COLOR_PICK."""
        self.phase = GamePhase.COLOR_PICK


class StateMachineFuzzer:
    """Fuzzer for game state machine violations."""

    def __init__(self, seed: int, crashes_dir: Path | None = None):
        self._seed = seed
        self._rng = random.Random(seed)
        self._crashes_dir = crashes_dir or ROOT / "harness" / "crashes" / "state_machine"
        self._crashes_dir.mkdir(parents=True, exist_ok=True)

    def run_scenario(self, scenario: Scenario) -> ScenarioResult:
        """Run a single scenario."""
        sm = GameStateMachine()

        if scenario == Scenario.VALID_FULL_FLOW:
            sm.start_color_pick()
            sm.handle_message(MessageType.COLOR_CHOSEN, {"team_key": "r", "color_idx": 0})
            sm.handle_message(MessageType.COLOR_CHOSEN, {"team_key": "l", "color_idx": 1})
            sm.handle_message(MessageType.WAR_GAMES_CHOICE, {"team_key": "r", "is_ai": False})
            sm.handle_message(MessageType.WAR_GAMES_CHOICE, {"team_key": "l", "is_ai": False})
            sm.handle_message(MessageType.GAME_START, {})
            sm.handle_message(MessageType.SETUP_COMPLETE, {"team_key": "r"})
            sm.handle_message(MessageType.SETUP_COMPLETE, {"team_key": "l"})
            sm.handle_message(MessageType.MOVE, {"from_row": 6, "to_row": 4})
            passed = len(sm.errors) == 0 and sm.phase == GamePhase.PLAYING
            return ScenarioResult(scenario, passed, "full valid flow", sm.events)

        # Move violations
        if scenario == Scenario.MOVE_DURING_LOBBY:
            result = sm.handle_message(MessageType.MOVE, {})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.MOVE_DURING_COLOR_PICK:
            sm.start_color_pick()
            result = sm.handle_message(MessageType.MOVE, {})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.MOVE_DURING_WAR_GAMES:
            sm.start_color_pick()
            sm.handle_message(MessageType.COLOR_CHOSEN, {"team_key": "r", "color_idx": 0})
            sm.handle_message(MessageType.COLOR_CHOSEN, {"team_key": "l", "color_idx": 1})
            result = sm.handle_message(MessageType.MOVE, {})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.MOVE_DURING_SETUP:
            sm.start_color_pick()
            sm.handle_message(MessageType.COLOR_CHOSEN, {"team_key": "r", "color_idx": 0})
            sm.handle_message(MessageType.COLOR_CHOSEN, {"team_key": "l", "color_idx": 1})
            sm.handle_message(MessageType.WAR_GAMES_CHOICE, {"team_key": "r", "is_ai": False})
            sm.handle_message(MessageType.WAR_GAMES_CHOICE, {"team_key": "l", "is_ai": False})
            result = sm.handle_message(MessageType.MOVE, {})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.MOVE_DURING_GAME_OVER:
            sm.phase = GamePhase.GAME_OVER
            result = sm.handle_message(MessageType.MOVE, {})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        # color_chosen violations
        if scenario == Scenario.COLOR_CHOSEN_DURING_LOBBY:
            result = sm.handle_message(MessageType.COLOR_CHOSEN, {"team_key": "r"})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.COLOR_CHOSEN_DURING_PLAYING:
            sm.phase = GamePhase.PLAYING
            result = sm.handle_message(MessageType.COLOR_CHOSEN, {"team_key": "r"})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.COLOR_CHOSEN_DURING_GAME_OVER:
            sm.phase = GamePhase.GAME_OVER
            result = sm.handle_message(MessageType.COLOR_CHOSEN, {"team_key": "r"})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        # war_games violations
        if scenario == Scenario.WAR_GAMES_DURING_LOBBY:
            result = sm.handle_message(MessageType.WAR_GAMES_CHOICE, {"team_key": "r"})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.WAR_GAMES_DURING_PLAYING:
            sm.phase = GamePhase.PLAYING
            result = sm.handle_message(MessageType.WAR_GAMES_CHOICE, {"team_key": "r"})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        # game_start violations
        if scenario == Scenario.GAME_START_DURING_LOBBY:
            result = sm.handle_message(MessageType.GAME_START, {})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.GAME_START_TWICE:
            sm.phase = GamePhase.SETUP
            sm.handle_message(MessageType.GAME_START, {})
            result = sm.handle_message(MessageType.GAME_START, {})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        # setup_complete violations
        if scenario == Scenario.SETUP_COMPLETE_DURING_LOBBY:
            result = sm.handle_message(MessageType.SETUP_COMPLETE, {"team_key": "r"})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.SETUP_COMPLETE_DURING_PLAYING:
            sm.phase = GamePhase.PLAYING
            result = sm.handle_message(MessageType.SETUP_COMPLETE, {"team_key": "r"})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.SETUP_COMPLETE_TWICE:
            sm.phase = GamePhase.SETUP
            sm.handle_message(MessageType.SETUP_COMPLETE, {"team_key": "r"})
            result = sm.handle_message(MessageType.SETUP_COMPLETE, {"team_key": "r"})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        # undo/resign violations
        if scenario == Scenario.UNDO_DURING_SETUP:
            sm.phase = GamePhase.SETUP
            result = sm.handle_message(MessageType.UNDO_REQUEST, {})
            passed = not result and len(sm.errors) > 0
            return ScenarioResult(scenario, passed,
                sm.errors[0] if sm.errors else "no error", sm.events)

        if scenario == Scenario.RESIGN_DURING_SETUP:
            sm.phase = GamePhase.SETUP
            result = sm.handle_message(MessageType.RESIGN, {})
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
            "kind": "state_machine_violation",
            "scenario": result.scenario.name,
            "message": result.message,
            "events": result.events,
        }
        return save_corpus(
            self._crashes_dir, "chess", "state_machine_fuzzer",
            TEAM_R_RGB, TEAM_L_RGB, [], failure, self._seed,
        )


def main() -> int:
    """Run state machine fuzzer."""
    import argparse

    parser = argparse.ArgumentParser(description="State Machine Fuzzer")
    parser.add_argument("--iterations", "-n", type=int, default=100)
    parser.add_argument("--seed", "-s", type=int, default=42)
    args = parser.parse_args()

    print(f"[INFO] State Machine Fuzzer: seed={args.seed}")

    fuzzer = StateMachineFuzzer(seed=args.seed)
    total, passed, failed = fuzzer.run_fuzzing(args.iterations)

    print(f"\nDone. {total} scenarios")
    print(f"  passed={passed}  failed={failed}")

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
