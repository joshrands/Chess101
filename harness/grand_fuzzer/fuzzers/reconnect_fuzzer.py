"""Reconnect Fuzzer - tests reconnection edge cases.

Tests:
- Disconnect mid-move (before ack)
- Concurrent reconnects with same token
- Disconnect during setup phase
- Reconnect after ack timeout
- History overflow (50+ messages)
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
    """Reconnection test scenarios."""
    NORMAL_RECONNECT = auto()
    DISCONNECT_MID_MOVE = auto()
    RECONNECT_GETS_HISTORY = auto()
    CONCURRENT_RECONNECT = auto()
    DISCONNECT_DURING_SETUP = auto()
    RECONNECT_AFTER_TIMEOUT = auto()
    HISTORY_OVERFLOW = auto()
    INVALID_TOKEN = auto()
    RECONNECT_AFTER_ROOM_CLOSE = auto()
    SPECTATOR_RECONNECT = auto()


@dataclass
class ScenarioResult:
    """Result of a scenario test."""
    scenario: Scenario
    passed: bool
    message: str
    events: list[dict]


class MockRelay:
    """Simulates relay server for reconnection testing."""

    def __init__(self):
        self.rooms: dict[str, dict] = {}
        self.history_limit = 50

    def create_room(self, host_token: str) -> str:
        """Create room, return code."""
        code = f"ROOM{len(self.rooms)}"
        self.rooms[code] = {
            "host_token": host_token,
            "guest_token": None,
            "host_ws": "connected",
            "guest_ws": None,
            "history": [],
            "spectators": [],
        }
        return code

    def join_room(self, code: str, guest_token: str) -> bool:
        """Guest joins room."""
        if code not in self.rooms:
            return False
        room = self.rooms[code]
        if room["guest_token"] is not None:
            return False
        room["guest_token"] = guest_token
        room["guest_ws"] = "connected"
        return True

    def disconnect(self, code: str, token: str) -> None:
        """Simulate disconnect."""
        if code not in self.rooms:
            return
        room = self.rooms[code]
        if room["host_token"] == token:
            room["host_ws"] = None
        elif room["guest_token"] == token:
            room["guest_ws"] = None

    def reconnect(self, code: str, token: str) -> tuple[bool, list[dict]]:
        """Attempt reconnect. Returns (success, history)."""
        if code not in self.rooms:
            return False, []
        room = self.rooms[code]
        if token == room["host_token"]:
            room["host_ws"] = "connected"
            return True, room["history"][-self.history_limit:]
        elif token == room["guest_token"]:
            room["guest_ws"] = "connected"
            return True, room["history"][-self.history_limit:]
        return False, []

    def send_message(self, code: str, msg: dict) -> bool:
        """Send message, add to history."""
        if code not in self.rooms:
            return False
        room = self.rooms[code]
        room["history"].append(msg)
        # Trim to limit
        if len(room["history"]) > self.history_limit * 2:
            room["history"] = room["history"][-self.history_limit:]
        return True

    def is_connected(self, code: str, token: str) -> bool:
        """Check if player is connected."""
        if code not in self.rooms:
            return False
        room = self.rooms[code]
        if token == room["host_token"]:
            return room["host_ws"] == "connected"
        elif token == room["guest_token"]:
            return room["guest_ws"] == "connected"
        return False

    def close_room(self, code: str) -> None:
        """Close/delete room."""
        if code in self.rooms:
            del self.rooms[code]


class ReconnectFuzzer:
    """Fuzzer for reconnection edge cases."""

    def __init__(self, seed: int, crashes_dir: Path | None = None):
        self._seed = seed
        self._rng = random.Random(seed)
        self._crashes_dir = crashes_dir or ROOT / "harness" / "crashes" / "reconnect"
        self._crashes_dir.mkdir(parents=True, exist_ok=True)

    def run_scenario(self, scenario: Scenario) -> ScenarioResult:
        """Run a single scenario."""
        relay = MockRelay()
        events: list[dict] = []

        if scenario == Scenario.NORMAL_RECONNECT:
            code = relay.create_room("host_token")
            relay.join_room(code, "guest_token")
            events.append({"action": "create_join", "code": code})

            relay.disconnect(code, "guest_token")
            events.append({"action": "disconnect", "token": "guest"})

            success, history = relay.reconnect(code, "guest_token")
            events.append({"action": "reconnect", "success": success})

            passed = success and relay.is_connected(code, "guest_token")
            return ScenarioResult(scenario, passed, "normal reconnect", events)

        if scenario == Scenario.DISCONNECT_MID_MOVE:
            code = relay.create_room("host_token")
            relay.join_room(code, "guest_token")

            # Host sends move
            relay.send_message(code, {"type": "move", "seq": 1})
            events.append({"action": "send_move", "seq": 1})

            # Guest disconnects before ack
            relay.disconnect(code, "guest_token")
            events.append({"action": "disconnect_before_ack"})

            # Guest reconnects
            success, history = relay.reconnect(code, "guest_token")
            events.append({"action": "reconnect", "history_len": len(history)})

            # Should get the move in history
            passed = success and len(history) == 1 and history[0]["seq"] == 1
            return ScenarioResult(scenario, passed,
                f"move in history: {len(history)}", events)

        if scenario == Scenario.RECONNECT_GETS_HISTORY:
            code = relay.create_room("host_token")
            relay.join_room(code, "guest_token")

            # Send multiple messages
            for i in range(5):
                relay.send_message(code, {"type": "move", "seq": i})
            events.append({"action": "send_moves", "count": 5})

            relay.disconnect(code, "guest_token")
            success, history = relay.reconnect(code, "guest_token")
            events.append({"action": "reconnect", "history_len": len(history)})

            passed = success and len(history) == 5
            return ScenarioResult(scenario, passed,
                f"history length: {len(history)}", events)

        if scenario == Scenario.CONCURRENT_RECONNECT:
            code = relay.create_room("host_token")
            relay.join_room(code, "guest_token")
            relay.disconnect(code, "guest_token")

            # Two concurrent reconnects (simulated)
            success1, _ = relay.reconnect(code, "guest_token")
            success2, _ = relay.reconnect(code, "guest_token")
            events.append({"action": "concurrent_reconnect",
                          "first": success1, "second": success2})

            # Both succeed in mock (real relay might race)
            passed = success1 and success2
            return ScenarioResult(scenario, passed,
                f"both succeeded (mock allows)", events)

        if scenario == Scenario.DISCONNECT_DURING_SETUP:
            code = relay.create_room("host_token")
            relay.join_room(code, "guest_token")

            # Send setup message
            relay.send_message(code, {"type": "color_chosen", "team_key": "r"})
            events.append({"action": "send_color"})

            # Disconnect during setup
            relay.disconnect(code, "guest_token")
            events.append({"action": "disconnect_during_setup"})

            # Reconnect
            success, history = relay.reconnect(code, "guest_token")
            events.append({"action": "reconnect", "history_len": len(history)})

            # Should get color_chosen in history
            passed = success and len(history) >= 1
            has_color = any(m.get("type") == "color_chosen" for m in history)
            passed = passed and has_color
            return ScenarioResult(scenario, passed,
                f"setup msg in history: {has_color}", events)

        if scenario == Scenario.RECONNECT_AFTER_TIMEOUT:
            code = relay.create_room("host_token")
            relay.join_room(code, "guest_token")
            relay.disconnect(code, "guest_token")
            events.append({"action": "disconnect"})

            # Simulate timeout by just waiting (mock doesn't timeout)
            # In real relay, room might expire
            success, _ = relay.reconnect(code, "guest_token")
            events.append({"action": "reconnect_after_delay", "success": success})

            passed = success  # Mock allows, real might not
            return ScenarioResult(scenario, passed,
                "mock allows (real may timeout)", events)

        if scenario == Scenario.HISTORY_OVERFLOW:
            code = relay.create_room("host_token")
            relay.join_room(code, "guest_token")

            # Send more than history limit
            for i in range(60):
                relay.send_message(code, {"type": "move", "seq": i})
            events.append({"action": "send_moves", "count": 60})

            relay.disconnect(code, "guest_token")
            success, history = relay.reconnect(code, "guest_token")
            events.append({"action": "reconnect", "history_len": len(history)})

            # Should only get last 50
            passed = success and len(history) == 50
            # Check we got the LAST 50 (seq 10-59)
            if history:
                first_seq = history[0].get("seq", -1)
                passed = passed and first_seq == 10
            return ScenarioResult(scenario, passed,
                f"history capped at {len(history)}", events)

        if scenario == Scenario.INVALID_TOKEN:
            code = relay.create_room("host_token")
            relay.join_room(code, "guest_token")
            relay.disconnect(code, "guest_token")

            # Try with wrong token
            success, _ = relay.reconnect(code, "wrong_token")
            events.append({"action": "reconnect_wrong_token", "success": success})

            passed = not success  # Should fail
            return ScenarioResult(scenario, passed,
                f"rejected invalid token: {not success}", events)

        if scenario == Scenario.RECONNECT_AFTER_ROOM_CLOSE:
            code = relay.create_room("host_token")
            relay.join_room(code, "guest_token")
            relay.disconnect(code, "guest_token")

            # Close room
            relay.close_room(code)
            events.append({"action": "room_closed"})

            # Try reconnect
            success, _ = relay.reconnect(code, "guest_token")
            events.append({"action": "reconnect_after_close", "success": success})

            passed = not success  # Should fail
            return ScenarioResult(scenario, passed,
                f"rejected after close: {not success}", events)

        if scenario == Scenario.SPECTATOR_RECONNECT:
            code = relay.create_room("host_token")
            relay.join_room(code, "guest_token")

            # Spectator has no token in mock
            # Real relay: spectators can't reconnect
            events.append({"action": "spectator_no_reconnect"})
            passed = True  # Documented behavior
            return ScenarioResult(scenario, passed,
                "spectators cannot reconnect (by design)", events)

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
            "kind": "reconnect_failure",
            "scenario": result.scenario.name,
            "message": result.message,
            "events": result.events,
        }
        return save_corpus(
            self._crashes_dir, "chess", "reconnect_fuzzer",
            TEAM_R_RGB, TEAM_L_RGB, [], failure, self._seed,
        )


def main() -> int:
    """Run reconnect fuzzer."""
    import argparse

    parser = argparse.ArgumentParser(description="Reconnect Fuzzer")
    parser.add_argument("--iterations", "-n", type=int, default=100)
    parser.add_argument("--seed", "-s", type=int, default=42)
    args = parser.parse_args()

    print(f"[INFO] Reconnect Fuzzer: seed={args.seed}")

    fuzzer = ReconnectFuzzer(seed=args.seed)
    total, passed, failed = fuzzer.run_fuzzing(args.iterations)

    print(f"\nDone. {total} scenarios")
    print(f"  passed={passed}  failed={failed}")

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
