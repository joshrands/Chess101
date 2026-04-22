"""Seed-controlled fault injection for fuzzing."""
from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class FaultType(Enum):
    """Types of faults that can be injected."""
    DISCONNECT = auto()
    DELAY = auto()
    CORRUPT_TYPE = auto()
    CORRUPT_COORDS = auto()
    MISSING_FIELD = auto()
    WRONG_TYPE = auto()
    OUT_OF_BOUNDS = auto()
    WRONG_TEAM = auto()
    DUPLICATE = auto()


@dataclass
class FaultEvent:
    """Records a fault injection event."""
    fault_type: FaultType
    original_msg: dict
    modified_msg: dict | None
    description: str


class FaultInjector:
    """Seed-controlled fault injection."""

    def __init__(self, seed: int, fault_probability: float = 0.0):
        self._rng = random.Random(seed)
        self._prob = fault_probability
        self._fault_log: list[FaultEvent] = []
        self._enabled = fault_probability > 0.0

    @property
    def fault_log(self) -> list[FaultEvent]:
        """Get the log of all injected faults."""
        return self._fault_log

    def enable(self, probability: float = 0.1) -> None:
        """Enable fault injection with given probability."""
        self._prob = probability
        self._enabled = True

    def disable(self) -> None:
        """Disable fault injection."""
        self._enabled = False

    def maybe_inject(self, msg: dict) -> tuple[dict | None, FaultType | None]:
        """Possibly inject a fault into a message.

        Returns:
            (modified_msg, fault_type) - modified_msg is None for DISCONNECT
        """
        if not self._enabled or self._rng.random() > self._prob:
            return msg, None

        fault = self._rng.choice(list(FaultType))
        modified = self._apply_fault(msg.copy(), fault)

        event = FaultEvent(
            fault_type=fault,
            original_msg=msg,
            modified_msg=modified,
            description=f"Injected {fault.name} into {msg.get('type', 'unknown')}",
        )
        self._fault_log.append(event)

        return modified, fault

    def _apply_fault(self, msg: dict, fault: FaultType) -> dict | None:
        """Apply a specific fault to a message."""
        if fault == FaultType.DISCONNECT:
            return None

        if fault == FaultType.DELAY:
            return msg

        if fault == FaultType.CORRUPT_TYPE:
            msg["type"] = "invalid_" + msg.get("type", "unknown")
            return msg

        if fault == FaultType.CORRUPT_COORDS:
            for key in ("from_row", "from_col", "to_row", "to_col"):
                if key in msg:
                    msg[key] = self._rng.randint(-10, 10)
            return msg

        if fault == FaultType.MISSING_FIELD:
            removable = [k for k in msg.keys() if k != "type"]
            if removable:
                del msg[self._rng.choice(removable)]
            return msg

        if fault == FaultType.WRONG_TYPE:
            for key in ("from_row", "from_col", "to_row", "to_col"):
                if key in msg:
                    msg[key] = str(msg[key])
            return msg

        if fault == FaultType.OUT_OF_BOUNDS:
            for key in ("from_row", "from_col", "to_row", "to_col"):
                if key in msg:
                    msg[key] = self._rng.choice([999, -1, 100, 256])
            return msg

        if fault == FaultType.WRONG_TEAM:
            if "team_key" in msg:
                msg["team_key"] = "l" if msg["team_key"] == "r" else "r"
            return msg

        if fault == FaultType.DUPLICATE:
            return msg

        return msg

    def should_duplicate(self) -> bool:
        """Check if last fault was DUPLICATE (caller should send twice)."""
        if self._fault_log and self._fault_log[-1].fault_type == FaultType.DUPLICATE:
            return True
        return False
