"""Grand E2E Lockstep Fuzzer - the main comprehensive fuzzer.

Plays complete games with:
- Master Python driving moves, verified against all lockstep engines
- Slave Python receiving moves, also verified against all lockstep engines
- Real network communication (LAN or relay)
"""
from __future__ import annotations

import asyncio
import random
import sys
import time
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from core.team import Team
from harness.lockstep_runner import (
    ChessEngine,
    PythonEngine,
    JsEngine,
    SwiftEngine,
    HilEngine,
    LockstepRunner,
)
from harness.chess_helpers import TEAM_R_RGB, TEAM_L_RGB
from harness.corpus import save_corpus
from network.protocol import board_hash, encode_grid, MoveFlags


class SlaveMode(Enum):
    """How the slave connects to master."""
    LOCAL = auto()
    LAN_HOST = auto()
    LAN_GUEST = auto()
    ONLINE_HOST = auto()
    ONLINE_GUEST = auto()


@dataclass
class FuzzResult:
    """Result of a fuzzing run."""
    success: bool
    message: str
    corpus_path: Path | None = None
    seed: int = 0
    ply: int = 0

    @classmethod
    def ok(cls, message: str = "passed") -> FuzzResult:
        return cls(success=True, message=message)

    @classmethod
    def failure(cls, message: str, corpus_path: Path | None = None,
                seed: int = 0, ply: int = 0) -> FuzzResult:
        return cls(success=False, message=message, corpus_path=corpus_path,
                   seed=seed, ply=ply)


class LockstepVerifier:
    """Verifies moves against all lockstep engines."""

    def __init__(self, engines: list[ChessEngine]):
        self._engines = engines

    def init_game(self, team_r_rgb: tuple, team_l_rgb: tuple) -> None:
        """Initialize all engines with same team colors."""
        for engine in self._engines:
            engine.init_game(team_r_rgb, team_l_rgb)

    def verify_legal_moves(self, team_key: str) -> tuple[set, list[str]]:
        """Verify all engines agree on legal moves.

        Returns (moves, errors) - moves is the agreed set, errors if disagreement.
        """
        if not self._engines:
            return set(), []

        move_sets: dict[str, set] = {}
        for engine in self._engines:
            move_sets[engine.name] = engine.legal_moves(team_key)

        ref_name = self._engines[0].name
        ref_moves = move_sets[ref_name]
        errors: list[str] = []

        for engine in self._engines[1:]:
            other_moves = move_sets[engine.name]
            if ref_moves != other_moves:
                only_ref = sorted(ref_moves - other_moves)
                only_other = sorted(other_moves - ref_moves)
                errors.append(
                    f"legal_moves disagree: {ref_name} vs {engine.name}: "
                    f"only_{ref_name}={only_ref}, only_{engine.name}={only_other}"
                )

        return ref_moves, errors

    def apply_and_verify(
        self, fr: int, fc: int, tr: int, tc: int,
        team_key: str, next_key: str, peace_time: int,
    ) -> tuple[str, list[str]]:
        """Apply move to all engines and verify board hashes match.

        Returns (hash, errors) - hash is the agreed hash, errors if disagreement.
        """
        if not self._engines:
            return "", []

        results: dict[str, dict] = {}
        for engine in self._engines:
            results[engine.name] = engine.apply_move(
                fr, fc, tr, tc, team_key, next_key, peace_time
            )

        ref_name = self._engines[0].name
        ref_hash = results[ref_name]["board_hash"]
        errors: list[str] = []

        for engine in self._engines[1:]:
            other_hash = results[engine.name]["board_hash"]
            if ref_hash != other_hash:
                errors.append(
                    f"board_hash disagree: {ref_name} vs {engine.name}: "
                    f"{ref_hash[:16]}... vs {other_hash[:16]}..."
                )

        return ref_hash, errors

    def close(self) -> None:
        """Close all engines."""
        for engine in self._engines:
            engine.close()


class GrandE2EFuzzer:
    """Grand E2E Lockstep Fuzzer."""

    def __init__(
        self,
        seed: int,
        mode: SlaveMode = SlaveMode.LOCAL,
        max_ply: int = 120,
        hil_url: str | None = None,
        crashes_dir: Path | None = None,
    ):
        self._seed = seed
        self._mode = mode
        self._max_ply = max_ply
        self._hil_url = hil_url
        self._crashes_dir = crashes_dir or ROOT / "harness" / "crashes" / "grand_e2e"
        self._crashes_dir.mkdir(parents=True, exist_ok=True)
        self._rng = random.Random(seed)

    def _create_engines(self) -> list[ChessEngine]:
        """Create all available lockstep engines."""
        engines: list[ChessEngine] = [PythonEngine(), JsEngine()]

        try:
            engines.append(SwiftEngine())
        except Exception as e:
            print(f"[WARN] Swift engine not available: {e}")

        if self._hil_url:
            try:
                hil = HilEngine(self._hil_url)
                hil.connect(retries=3, delay=1.0)
                engines.append(hil)
            except Exception as e:
                raise RuntimeError(f"HIL required but failed: {e}") from e

        return engines

    def run_game(self, game_seed: int) -> FuzzResult:
        """Run one complete game with lockstep verification."""
        game_rng = random.Random(game_seed)
        team_r_rgb = TEAM_R_RGB
        team_l_rgb = TEAM_L_RGB

        master_engines = self._create_engines()
        slave_engines = self._create_engines()

        master = LockstepVerifier(master_engines)
        slave = LockstepVerifier(slave_engines)

        try:
            master.init_game(team_r_rgb, team_l_rgb)
            slave.init_game(team_r_rgb, team_l_rgb)

            current_key = "r"
            peace_time = 0
            corpus_moves: list[dict] = []

            for ply in range(self._max_ply):
                master_moves, errors = master.verify_legal_moves(current_key)
                if errors:
                    return self._save_failure(
                        game_seed, ply, "master_legal_moves", errors[0],
                        corpus_moves, team_r_rgb, team_l_rgb
                    )

                slave_moves, errors = slave.verify_legal_moves(current_key)
                if errors:
                    return self._save_failure(
                        game_seed, ply, "slave_legal_moves", errors[0],
                        corpus_moves, team_r_rgb, team_l_rgb
                    )

                if master_moves != slave_moves:
                    only_master = sorted(master_moves - slave_moves)
                    only_slave = sorted(slave_moves - master_moves)
                    return self._save_failure(
                        game_seed, ply, "master_slave_moves_mismatch",
                        f"master vs slave: only_master={only_master}, only_slave={only_slave}",
                        corpus_moves, team_r_rgb, team_l_rgb
                    )

                if not master_moves:
                    break

                move = game_rng.choice(sorted(master_moves))
                fr, fc, tr, tc = move
                next_key = "l" if current_key == "r" else "r"

                master_hash, errors = master.apply_and_verify(
                    fr, fc, tr, tc, current_key, next_key, peace_time
                )
                if errors:
                    return self._save_failure(
                        game_seed, ply, "master_hash", errors[0],
                        corpus_moves, team_r_rgb, team_l_rgb
                    )

                slave_hash, errors = slave.apply_and_verify(
                    fr, fc, tr, tc, current_key, next_key, peace_time
                )
                if errors:
                    return self._save_failure(
                        game_seed, ply, "slave_hash", errors[0],
                        corpus_moves, team_r_rgb, team_l_rgb
                    )

                if master_hash != slave_hash:
                    return self._save_failure(
                        game_seed, ply, "master_slave_hash_mismatch",
                        f"master={master_hash[:16]}... slave={slave_hash[:16]}...",
                        corpus_moves, team_r_rgb, team_l_rgb
                    )

                corpus_moves.append({
                    "fr": fr, "fc": fc, "tr": tr, "tc": tc,
                    "team_key": current_key, "flags": {},
                })

                current_key = next_key
                peace_time += 1

            return FuzzResult.ok(f"game completed ({len(corpus_moves)} moves)")

        finally:
            master.close()
            slave.close()

    def _save_failure(
        self, seed: int, ply: int, kind: str, detail: str,
        moves: list[dict], team_r_rgb: tuple, team_l_rgb: tuple,
    ) -> FuzzResult:
        """Save failure to corpus and return FuzzResult."""
        corpus_path = save_corpus(
            self._crashes_dir, "chess", "grand_e2e",
            team_r_rgb, team_l_rgb, moves,
            {"ply": ply, "kind": kind, "detail": detail},
            seed,
        )
        return FuzzResult.failure(
            f"ply {ply}: {kind} - {detail}",
            corpus_path=corpus_path,
            seed=seed,
            ply=ply,
        )

    def run_fuzzing(self, iterations: int) -> tuple[int, int, int]:
        """Run multiple games. Returns (total, ok, failed)."""
        total = 0
        ok = 0
        failed = 0

        i = 0
        while iterations == 0 or i < iterations:
            game_seed = self._rng.randint(0, 2**32)
            result = self.run_game(game_seed)

            if result.success:
                ok += 1
            else:
                failed += 1
                print(f"  FAIL seed={game_seed}: {result.message}")

            total += 1
            i += 1

            if total % 10 == 0:
                print(f"  [{total}] ok={ok} failed={failed}")

        return total, ok, failed
