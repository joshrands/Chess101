"""Chaos layer for E2E fuzzing.

Provides chaos profiles, scenario scheduling, and integration
with FaultInjector for deterministic chaos injection.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Any

from .fault_injector import FaultInjector, FaultConfig, FaultType, standard_fault_suite, aggressive_fault_suite


class ChaosProfile(Enum):
    """Chaos intensity profiles."""
    GENTLE = auto()      # 5% message faults, 1 scenario/game
    STANDARD = auto()    # 10% message faults, 3 scenarios/game
    AGGRESSIVE = auto()  # 20% message faults, 5 scenarios/game, disconnects
    ADVERSARIAL = auto() # 30% message faults, all scenarios enabled


@dataclass
class ChaosConfig:
    """Configuration derived from a chaos profile."""
    profile: ChaosProfile
    message_fault_probability: float
    scenarios_per_game: int
    enable_disconnects: bool
    enable_reconnects: bool
    enable_spectator_chaos: bool
    fault_configs: list[FaultConfig] = field(default_factory=list)
    enabled_scenarios: set[str] | None = None  # None = all enabled

    @classmethod
    def from_profile(cls, profile: ChaosProfile) -> "ChaosConfig":
        """Create config from a profile."""
        if profile == ChaosProfile.GENTLE:
            return cls(
                profile=profile,
                message_fault_probability=0.05,
                scenarios_per_game=1,
                enable_disconnects=False,
                enable_reconnects=False,
                enable_spectator_chaos=False,
                fault_configs=_gentle_fault_suite(),
            )
        elif profile == ChaosProfile.STANDARD:
            return cls(
                profile=profile,
                message_fault_probability=0.10,
                scenarios_per_game=3,
                enable_disconnects=True,
                enable_reconnects=True,
                enable_spectator_chaos=False,
                fault_configs=standard_fault_suite(0.10),
            )
        elif profile == ChaosProfile.AGGRESSIVE:
            return cls(
                profile=profile,
                message_fault_probability=0.20,
                scenarios_per_game=5,
                enable_disconnects=True,
                enable_reconnects=True,
                enable_spectator_chaos=True,
                fault_configs=aggressive_fault_suite(),
            )
        else:  # ADVERSARIAL
            return cls(
                profile=profile,
                message_fault_probability=0.30,
                scenarios_per_game=10,
                enable_disconnects=True,
                enable_reconnects=True,
                enable_spectator_chaos=True,
                fault_configs=_adversarial_fault_suite(),
            )


def _gentle_fault_suite() -> list[FaultConfig]:
    """Low-probability faults for gentle testing."""
    return [
        FaultConfig(FaultType.DUPLICATE, 0.02),
        FaultConfig(FaultType.DELAY, 0.05, {"min_ms": 10, "max_ms": 100}),
    ]


def _adversarial_fault_suite() -> list[FaultConfig]:
    """High-probability faults for adversarial testing."""
    return [
        FaultConfig(FaultType.CORRUPT_COORDS, 0.25),
        FaultConfig(FaultType.CORRUPT_TYPE, 0.15),
        FaultConfig(FaultType.MISSING_FIELD, 0.20, {"field": "from_row"}),
        FaultConfig(FaultType.MISSING_FIELD, 0.20, {"field": "to_col"}),
        FaultConfig(FaultType.WRONG_TYPE, 0.20, {"field": "from_row"}),
        FaultConfig(FaultType.WRONG_TYPE, 0.20, {"field": "team_key"}),
        FaultConfig(FaultType.DUPLICATE, 0.15),
        FaultConfig(FaultType.DROP, 0.10),
        FaultConfig(FaultType.DISCONNECT, 0.05),
        FaultConfig(FaultType.REORDER, 0.10),
    ]


class TurnScenario(Enum):
    """Scenarios that can be injected at turn boundaries."""
    DISCONNECT_BEFORE_ACK = auto()
    DISCONNECT_AFTER_ACK = auto()
    DUPLICATE_MOVE = auto()
    WRONG_TURN_MOVE = auto()
    STALE_SEQ = auto()


class GameScenario(Enum):
    """Scenarios that can be injected at game level."""
    # Connection chaos
    RECONNECT_MID_SETUP = auto()
    RECONNECT_MID_GAME = auto()
    RECONNECT_AT_GAME_OVER = auto()

    # Spectator chaos
    SPECTATOR_JOIN_MID_GAME = auto()
    SPECTATOR_LEAVE_MID_GAME = auto()
    SPECTATOR_RAPID_JOIN_LEAVE = auto()

    # Late join
    LATE_JOIN_COLOR_PICK = auto()
    LATE_JOIN_PLAYING = auto()

    # Post-game
    NEW_GAME_IMMEDIATE = auto()
    NEW_GAME_DURING_ANIMATION = auto()

    # Race conditions
    CONCURRENT_MOVES = auto()
    CONCURRENT_RECONNECTS = auto()

    # Protocol edge cases
    SEQ_WRAPAROUND = auto()
    HISTORY_OVERFLOW = auto()


class StateCondition(Enum):
    """Board state conditions for conditional scenarios."""
    PAWN_ON_7TH = auto()
    KING_IN_CHECK = auto()
    EN_PASSANT_AVAILABLE = auto()
    CASTLING_AVAILABLE = auto()
    LOW_MATERIAL = auto()
    FIFTY_MOVE_NEAR = auto()


@dataclass
class ScheduledScenario:
    """A scenario scheduled to trigger at a specific point."""
    scenario: GameScenario | TurnScenario
    trigger_ply: int | None = None  # None = trigger when condition met
    condition: StateCondition | None = None
    triggered: bool = False


class ScenarioScheduler:
    """Schedules and tracks scenario injection.

    Uses seeded RNG for deterministic scenario selection and timing.
    """

    def __init__(self, seed: int, config: ChaosConfig):
        self._rng = random.Random(seed)
        self._config = config
        self._scheduled: list[ScheduledScenario] = []
        self._triggered_scenarios: list[tuple[int, str]] = []  # (ply, name)

    def plan_scenarios(self, max_ply: int) -> None:
        """Plan scenarios for a game. Call before game starts."""
        self._scheduled.clear()
        self._triggered_scenarios.clear()

        # Select scenarios based on profile
        available_game_scenarios = list(GameScenario)
        available_turn_scenarios = list(TurnScenario)

        # Filter by enabled_scenarios if specified
        if self._config.enabled_scenarios is not None:
            available_game_scenarios = [
                s for s in available_game_scenarios
                if s.name in self._config.enabled_scenarios
            ]
            available_turn_scenarios = [
                s for s in available_turn_scenarios
                if s.name in self._config.enabled_scenarios
            ]

        if not self._config.enable_disconnects:
            available_turn_scenarios = [
                s for s in available_turn_scenarios
                if "DISCONNECT" not in s.name
            ]
            available_game_scenarios = [
                s for s in available_game_scenarios
                if "RECONNECT" not in s.name
            ]

        if not self._config.enable_spectator_chaos:
            available_game_scenarios = [
                s for s in available_game_scenarios
                if "SPECTATOR" not in s.name
            ]

        # Schedule game-level scenarios
        num_game = min(self._config.scenarios_per_game, len(available_game_scenarios))
        selected_game = self._rng.sample(available_game_scenarios, num_game)

        for scenario in selected_game:
            trigger_ply = self._rng.randint(1, max(1, max_ply - 5))
            self._scheduled.append(ScheduledScenario(
                scenario=scenario,
                trigger_ply=trigger_ply,
            ))

        # Schedule turn-level scenarios (1 per ~20 plies)
        num_turn = max_ply // 20
        if num_turn > 0 and available_turn_scenarios:
            for _ in range(num_turn):
                scenario = self._rng.choice(available_turn_scenarios)
                trigger_ply = self._rng.randint(1, max_ply)
                self._scheduled.append(ScheduledScenario(
                    scenario=scenario,
                    trigger_ply=trigger_ply,
                ))

    def get_scenarios_for_ply(self, ply: int) -> list[GameScenario | TurnScenario]:
        """Get scenarios that should trigger at this ply."""
        result = []
        for sched in self._scheduled:
            if sched.triggered:
                continue
            if sched.trigger_ply == ply:
                sched.triggered = True
                result.append(sched.scenario)
                self._triggered_scenarios.append((ply, sched.scenario.name))
        return result

    def check_condition_scenarios(
        self, ply: int, condition_checker: Callable[[StateCondition], bool]
    ) -> list[GameScenario | TurnScenario]:
        """Check and trigger condition-based scenarios."""
        result = []
        for sched in self._scheduled:
            if sched.triggered:
                continue
            if sched.condition is not None and condition_checker(sched.condition):
                sched.triggered = True
                result.append(sched.scenario)
                self._triggered_scenarios.append((ply, sched.scenario.name))
        return result

    @property
    def triggered_scenarios(self) -> list[tuple[int, str]]:
        """Get list of (ply, scenario_name) for triggered scenarios."""
        return self._triggered_scenarios[:]


class ChaosPeer:
    """Wraps a network peer with chaos injection.

    Intercepts send/recv and applies FaultInjector transformations.
    Records all events to timeline.
    """

    def __init__(
        self,
        impl: Any,  # NetworkPeer or similar
        name: str,
        fault_injector: FaultInjector,
        timeline_recorder: Any,  # TimelineRecorder from corpus
    ):
        self._impl = impl
        self._name = name
        self._fault_injector = fault_injector
        self._timeline = timeline_recorder
        self._connected = True
        self._last_failure: str | None = None  # "disconnect", "drop", or None
        self._fault_injected_this_turn = False

    def send(self, msg: dict) -> bool:
        """Send message with fault injection.

        Returns False if message was dropped or connection closed.
        Sets fault_injected=True if failure was due to injected fault.
        """
        self._last_failure = None
        self._fault_injected_this_turn = False

        if not self._connected:
            self._last_failure = "already_disconnected"
            return False

        # Check for disconnect fault — simulate disconnect, don't actually close
        if self._fault_injector.should_disconnect():
            self._timeline.record_fault("DISCONNECT", self._name)
            self._timeline.record_disconnect(self._name, "fault_injected")
            self._connected = False
            self._last_failure = "disconnect"
            self._fault_injected_this_turn = True
            # Note: Don't close underlying peer — fuzzer reuses it across games.
            # Real disconnect testing is in integration_e2e.py.
            return False

        # Process message through fault injector
        original = msg.copy()
        messages = self._fault_injector.process_message(msg)

        if not messages:
            # Message dropped
            self._timeline.record_fault("DROP", self._name, before=original)
            self._last_failure = "drop"
            self._fault_injected_this_turn = True
            return False

        for i, m in enumerate(messages):
            if m != original:
                self._timeline.record_fault(
                    "CORRUPT" if i == 0 else "DUPLICATE",
                    self._name,
                    before=original,
                    after=m,
                )
            self._timeline.record_send(self._name, m)
            self._impl.send(m)

        return True

    def recv(self, timeout: float = 5.0) -> dict | None:
        """Receive message and record to timeline."""
        if not self._connected:
            return None

        msg = self._impl.recv(timeout=timeout)
        if msg is not None:
            self._timeline.record_recv(self._name, msg)
        return msg

    def clear(self) -> None:
        """Clear receive buffer."""
        if hasattr(self._impl, "clear"):
            self._impl.clear()

    def close(self) -> None:
        """Close connection."""
        self._connected = False
        if hasattr(self._impl, "close"):
            self._impl.close()

    def reconnect(self) -> bool:
        """Attempt reconnection."""
        if hasattr(self._impl, "reconnect"):
            success = self._impl.reconnect()
            self._timeline.record_reconnect(self._name, success)
            self._connected = success
            return success
        return False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def impl(self) -> Any:
        return self._impl

    @property
    def last_failure(self) -> str | None:
        """Return the reason for the last send() failure, or None if it succeeded."""
        return self._last_failure

    @property
    def fault_injected(self) -> bool:
        """True if the last send() failed due to an injected fault (DROP/DISCONNECT)."""
        return self._fault_injected_this_turn
