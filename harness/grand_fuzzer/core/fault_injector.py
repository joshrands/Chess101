"""Fault injection for network fuzzing.

Provides seed-controlled fault injection: disconnects, delays,
message corruption, duplicates, and drops.
"""
from __future__ import annotations

import copy
import random
from enum import Enum, auto
from dataclasses import dataclass
from typing import Callable


class FaultType(Enum):
    """Types of faults that can be injected."""
    DISCONNECT = auto()       # Close WebSocket connection
    DELAY = auto()            # Add latency to message
    CORRUPT_COORDS = auto()   # Change move coordinates
    CORRUPT_TYPE = auto()     # Change message type field
    MISSING_FIELD = auto()    # Remove a required field
    WRONG_TYPE = auto()       # String instead of int, etc.
    DUPLICATE = auto()        # Send message twice
    DROP = auto()             # Don't send message at all
    REORDER = auto()          # Send messages out of order


@dataclass
class FaultConfig:
    """Configuration for fault injection."""
    fault_type: FaultType
    probability: float = 0.1  # Chance of fault occurring
    params: dict = None       # Type-specific parameters

    def __post_init__(self):
        if self.params is None:
            self.params = {}


class FaultInjector:
    """Injects faults into network messages based on seed."""

    def __init__(self, seed: int, faults: list[FaultConfig] | None = None):
        self._rng = random.Random(seed)
        self._faults = faults or []
        self._pending_reorder: list[dict] = []
        self._disconnect_requested = False

    def add_fault(self, fault: FaultConfig) -> None:
        """Add a fault configuration."""
        self._faults.append(fault)

    def should_disconnect(self) -> bool:
        """Check if disconnect was triggered and reset flag."""
        if self._disconnect_requested:
            self._disconnect_requested = False
            return True
        return False

    def process_message(self, msg: dict) -> list[dict]:
        """Process a message, potentially injecting faults.

        Returns list of messages to send (may be empty, single, or duplicated).
        """
        result = [copy.deepcopy(msg)]

        for fault in self._faults:
            if self._rng.random() > fault.probability:
                continue

            if fault.fault_type == FaultType.DISCONNECT:
                self._disconnect_requested = True
                return []

            elif fault.fault_type == FaultType.DROP:
                return []

            elif fault.fault_type == FaultType.DUPLICATE:
                result.append(copy.deepcopy(msg))

            elif fault.fault_type == FaultType.CORRUPT_COORDS:
                result = [self._corrupt_coords(m) for m in result]

            elif fault.fault_type == FaultType.CORRUPT_TYPE:
                result = [self._corrupt_type(m) for m in result]

            elif fault.fault_type == FaultType.MISSING_FIELD:
                field = fault.params.get("field", "from_row")
                result = [self._remove_field(m, field) for m in result]

            elif fault.fault_type == FaultType.WRONG_TYPE:
                field = fault.params.get("field", "from_row")
                result = [self._wrong_type(m, field) for m in result]

            elif fault.fault_type == FaultType.REORDER:
                self._pending_reorder.extend(result)
                if len(self._pending_reorder) >= 2:
                    self._rng.shuffle(self._pending_reorder)
                    result = self._pending_reorder
                    self._pending_reorder = []
                else:
                    return []

        return result

    def _corrupt_coords(self, msg: dict) -> dict:
        """Corrupt coordinate fields in a move message."""
        if msg.get("type") != "move":
            return msg
        field = self._rng.choice(["from_row", "from_col", "to_row", "to_col"])
        corruption = self._rng.choice([999, -1, "6", None, [6]])
        msg[field] = corruption
        return msg

    def _corrupt_type(self, msg: dict) -> dict:
        """Corrupt the message type field."""
        msg["type"] = self._rng.choice(["invalid_type", "MOVE", "", None, 123])
        return msg

    def _remove_field(self, msg: dict, field: str) -> dict:
        """Remove a field from the message."""
        msg.pop(field, None)
        return msg

    def _wrong_type(self, msg: dict, field: str) -> dict:
        """Change field to wrong type."""
        if field not in msg:
            return msg
        original = msg[field]
        if isinstance(original, int):
            msg[field] = str(original)
        elif isinstance(original, str):
            msg[field] = 123
        elif isinstance(original, bool):
            msg[field] = "true"
        elif isinstance(original, dict):
            msg[field] = list(original.items())
        return msg

    def flush_reorder(self) -> list[dict]:
        """Get any pending reordered messages."""
        msgs = self._pending_reorder
        self._pending_reorder = []
        return msgs


def standard_fault_suite(probability: float = 0.05) -> list[FaultConfig]:
    """Return a standard set of fault configurations for fuzzing."""
    return [
        FaultConfig(FaultType.CORRUPT_COORDS, probability),
        FaultConfig(FaultType.MISSING_FIELD, probability, {"field": "from_row"}),
        FaultConfig(FaultType.MISSING_FIELD, probability, {"field": "to_col"}),
        FaultConfig(FaultType.WRONG_TYPE, probability, {"field": "from_row"}),
        FaultConfig(FaultType.DUPLICATE, probability * 0.5),
        FaultConfig(FaultType.DROP, probability * 0.2),
    ]


def aggressive_fault_suite() -> list[FaultConfig]:
    """High-probability faults for stress testing."""
    return [
        FaultConfig(FaultType.CORRUPT_COORDS, 0.2),
        FaultConfig(FaultType.CORRUPT_TYPE, 0.1),
        FaultConfig(FaultType.MISSING_FIELD, 0.15, {"field": "from_row"}),
        FaultConfig(FaultType.WRONG_TYPE, 0.15, {"field": "to_row"}),
        FaultConfig(FaultType.DUPLICATE, 0.1),
        FaultConfig(FaultType.DROP, 0.05),
        FaultConfig(FaultType.DISCONNECT, 0.02),
        FaultConfig(FaultType.REORDER, 0.05),
    ]
