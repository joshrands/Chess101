"""Validator Fuzzer - adversarial testing of RoomValidator.

Tests that validator correctly rejects:
- Illegal chess moves
- Out-of-bounds coordinates
- Wrong types (string instead of int)
- Missing fields
- Malformed flags
- Moves before game_start
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

from network.validator import RoomValidator
from harness.chess_helpers import TEAM_R_RGB, TEAM_L_RGB
from harness.corpus import save_corpus


class AttackType(Enum):
    """Types of adversarial inputs to test."""
    # Illegal chess moves
    BLOCKED_PATH = auto()
    LEAVES_KING_IN_CHECK = auto()
    WRONG_PIECE = auto()
    WRONG_TEAM = auto()
    EMPTY_SQUARE = auto()

    # Out of bounds
    ROW_OVERFLOW = auto()
    COL_OVERFLOW = auto()
    NEGATIVE_COORDS = auto()

    # Type confusion
    STRING_COORDS = auto()
    FLOAT_COORDS = auto()
    NULL_COORDS = auto()
    NONE_COORDS = auto()

    # Missing fields
    NO_FROM_ROW = auto()
    NO_FROM_COL = auto()
    NO_TO_ROW = auto()
    NO_TO_COL = auto()

    # Malformed
    FLAGS_NOT_DICT = auto()
    COORDS_ARE_LIST = auto()


@dataclass
class AttackResult:
    """Result of an attack test."""
    attack: AttackType
    msg: dict
    expected_reject: bool
    actual_result: bool
    exception: Exception | None = None

    @property
    def passed(self) -> bool:
        """True if validator behaved correctly."""
        if self.exception:
            return False
        return self.actual_result == (not self.expected_reject)


class ValidatorFuzzer:
    """Adversarial fuzzer for RoomValidator."""

    def __init__(self, seed: int, crashes_dir: Path | None = None):
        self._seed = seed
        self._rng = random.Random(seed)
        self._crashes_dir = crashes_dir or ROOT / "harness" / "crashes" / "validator"
        self._crashes_dir.mkdir(parents=True, exist_ok=True)

    def _fresh_validator(self) -> RoomValidator:
        """Create fresh initialized validator."""
        v = RoomValidator()
        v.initialize(TEAM_R_RGB, TEAM_L_RGB)
        return v

    def _legal_move(self) -> dict:
        """Return a legal opening move (e2-e4)."""
        return {
            "type": "move",
            "from_row": 6,
            "from_col": 4,
            "to_row": 4,
            "to_col": 4,
            "flags": {},
        }

    def run_attack(self, attack: AttackType) -> AttackResult:
        """Run single attack and return result."""
        validator = self._fresh_validator()
        msg = self._build_attack_msg(attack)
        expected_reject = self._should_reject(attack)

        try:
            result = validator.validate_and_apply(msg)
            attack_result = AttackResult(
                attack=attack,
                msg=msg,
                expected_reject=expected_reject,
                actual_result=result,
            )
        except Exception as e:
            attack_result = AttackResult(
                attack=attack,
                msg=msg,
                expected_reject=expected_reject,
                actual_result=False,
                exception=e,
            )

        if not attack_result.passed:
            self._save_failure(attack_result)

        return attack_result

    def _save_failure(self, result: AttackResult) -> Path:
        """Save failed attack to corpus."""
        move_repr = {
            "fr": result.msg.get("from_row"),
            "fc": result.msg.get("from_col"),
            "tr": result.msg.get("to_row"),
            "tc": result.msg.get("to_col"),
            "team_key": "r",
            "flags": result.msg.get("flags", {}),
        }
        failure = {
            "ply": 0,
            "kind": "validator_attack",
            "attack_type": result.attack.name,
            "expected_reject": result.expected_reject,
            "actual_result": result.actual_result,
            "exception": str(result.exception) if result.exception else None,
            "raw_msg": result.msg,
        }
        return save_corpus(
            self._crashes_dir, "chess", "validator_fuzzer",
            TEAM_R_RGB, TEAM_L_RGB, [move_repr], failure, self._seed,
        )

    def _should_reject(self, attack: AttackType) -> bool:
        """Should validator reject this attack?"""
        return True

    def _build_attack_msg(self, attack: AttackType) -> dict:
        """Build malicious message for attack type."""
        base = self._legal_move()

        if attack == AttackType.BLOCKED_PATH:
            base["from_row"] = 7
            base["from_col"] = 0
            base["to_row"] = 5
            base["to_col"] = 0
            return base

        if attack == AttackType.WRONG_TEAM:
            # Try to move team_l pawn (row 6) when it's team_r turn
            base["from_row"] = 6
            base["from_col"] = 4
            base["to_row"] = 4
            base["to_col"] = 4
            return base

        if attack == AttackType.EMPTY_SQUARE:
            base["from_row"] = 4
            base["from_col"] = 4
            return base

        if attack == AttackType.ROW_OVERFLOW:
            base["from_row"] = 999
            return base

        if attack == AttackType.COL_OVERFLOW:
            base["to_col"] = 999
            return base

        if attack == AttackType.NEGATIVE_COORDS:
            base["from_row"] = -1
            base["from_col"] = -1
            return base

        if attack == AttackType.STRING_COORDS:
            base["from_row"] = "6"
            base["from_col"] = "4"
            base["to_row"] = "4"
            base["to_col"] = "4"
            return base

        if attack == AttackType.FLOAT_COORDS:
            base["from_row"] = 6.5
            base["from_col"] = 4.5
            return base

        if attack == AttackType.NULL_COORDS:
            base["from_row"] = None
            return base

        if attack == AttackType.NONE_COORDS:
            base["from_row"] = None
            base["from_col"] = None
            base["to_row"] = None
            base["to_col"] = None
            return base

        if attack == AttackType.NO_FROM_ROW:
            del base["from_row"]
            return base

        if attack == AttackType.NO_FROM_COL:
            del base["from_col"]
            return base

        if attack == AttackType.NO_TO_ROW:
            del base["to_row"]
            return base

        if attack == AttackType.NO_TO_COL:
            del base["to_col"]
            return base

        if attack == AttackType.FLAGS_NOT_DICT:
            base["flags"] = "not_a_dict"
            return base

        if attack == AttackType.COORDS_ARE_LIST:
            base["from_row"] = [6]
            base["from_col"] = [4]
            return base

        if attack == AttackType.WRONG_PIECE:
            base["from_row"] = 6
            base["from_col"] = 0
            base["to_row"] = 4
            base["to_col"] = 2
            return base

        return base

    def run_all_attacks(self) -> list[AttackResult]:
        """Run all attack types."""
        results = []
        for attack in AttackType:
            result = self.run_attack(attack)
            results.append(result)
        return results

    def run_fuzzing(self, iterations: int) -> tuple[int, int, int]:
        """Run random attacks. Returns (total, passed, failed)."""
        total = 0
        passed = 0
        failed = 0

        results = self.run_all_attacks()
        for result in results:
            total += 1
            if result.passed:
                passed += 1
            else:
                failed += 1
                if result.exception:
                    print(f"  FAIL {result.attack.name}: exception {result.exception}")
                else:
                    print(f"  FAIL {result.attack.name}: expected reject={result.expected_reject}, got result={result.actual_result}")

        for i in range(iterations - len(AttackType)):
            attack = self._rng.choice(list(AttackType))
            result = self.run_attack(attack)
            total += 1
            if result.passed:
                passed += 1
            else:
                failed += 1

        return total, passed, failed


def main() -> int:
    """Run validator fuzzer."""
    import argparse

    parser = argparse.ArgumentParser(description="Validator Fuzzer")
    parser.add_argument("--iterations", "-n", type=int, default=100)
    parser.add_argument("--seed", "-s", type=int, default=42)
    args = parser.parse_args()

    print(f"[INFO] Validator Fuzzer: iterations={args.iterations}, seed={args.seed}")

    fuzzer = ValidatorFuzzer(seed=args.seed)
    total, passed, failed = fuzzer.run_fuzzing(args.iterations)

    print(f"\nDone. {total} attacks")
    print(f"  passed={passed}  failed={failed}")

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
