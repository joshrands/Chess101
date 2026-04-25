# harness/lockstep_runner.py
"""Modular lockstep chess engine testing framework.

Provides a pluggable architecture for testing multiple chess engine
implementations in lockstep. Each engine implements the ChessEngine
protocol; the LockstepRunner plays games through all engines and
detects disagreements.
"""
from __future__ import annotations

import json
import random
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Set, Tuple

from core.team import Team
from network.protocol import board_hash
from harness.chess_helpers import (
    TEAM_R_RGB,
    TEAM_L_RGB,
    py_init_board,
    py_grid_to_json,
    py_legal_moves,
    py_apply_move,
    clear_en_passant,
)
from harness.corpus import save_corpus, load_corpus
from harness.python_bridge import JsBridge
from harness.swift_bridge import SwiftBridge

try:
    from hil.client import HilBridge
    _HAS_HIL = True
except ImportError:
    HilBridge = None  # type: ignore
    _HAS_HIL = False


class ChessEngine(ABC):
    """Protocol for lockstep-testable chess engines."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable engine name for error reporting."""
        ...

    @abstractmethod
    def init_game(
        self,
        team_r_rgb: tuple[int, int, int],
        team_l_rgb: tuple[int, int, int],
    ) -> None:
        """Initialize a new game with the given team colors."""
        ...

    @abstractmethod
    def legal_moves(self, team_key: str) -> Set[Tuple[int, int, int, int]]:
        """Return set of (fr, fc, tr, tc) legal moves for the team."""
        ...

    @abstractmethod
    def apply_move(
        self,
        fr: int, fc: int, tr: int, tc: int,
        team_key: str, next_key: str, peace_time: int,
    ) -> dict:
        """Apply move and return {'grid': ..., 'board_hash': ...}."""
        ...

    def close(self) -> None:
        """Clean up resources (optional)."""
        pass


class PythonEngine(ChessEngine):
    """Python chess engine using chess_helpers directly."""

    def __init__(self) -> None:
        self._grid: list | None = None
        self._team_r: Team | None = None
        self._team_l: Team | None = None

    @property
    def name(self) -> str:
        return "python"

    def init_game(
        self,
        team_r_rgb: tuple[int, int, int],
        team_l_rgb: tuple[int, int, int],
    ) -> None:
        self._team_r = Team(*team_r_rgb)
        self._team_l = Team(*team_l_rgb)
        self._grid = py_init_board(self._team_r, self._team_l)

    def legal_moves(self, team_key: str) -> Set[Tuple[int, int, int, int]]:
        if self._grid is None or self._team_r is None or self._team_l is None:
            raise RuntimeError("Game not initialized")
        team = self._team_r if team_key == "r" else self._team_l
        clear_en_passant(self._grid, team)
        return py_legal_moves(self._grid, team)

    def apply_move(
        self,
        fr: int, fc: int, tr: int, tc: int,
        team_key: str, next_key: str, peace_time: int,
    ) -> dict:
        if self._grid is None or self._team_r is None or self._team_l is None:
            raise RuntimeError("Game not initialized")
        # Clear en_passant for the team that just moved (window expired)
        moving_team = self._team_r if team_key == "r" else self._team_l
        clear_en_passant(self._grid, moving_team)
        py_apply_move(self._grid, fr, fc, tr, tc)
        grid_json = py_grid_to_json(self._grid, self._team_r)
        hash_val = board_hash(self._grid, peace_time, next_key, self._team_r)
        return {"grid": grid_json, "board_hash": hash_val}


class JsEngine(ChessEngine):
    """JavaScript chess engine via JsBridge subprocess."""

    def __init__(self) -> None:
        self._bridge = JsBridge()
        self._grid: list | None = None
        self._team_r_rgb: tuple[int, int, int] = TEAM_R_RGB
        self._team_l_rgb: tuple[int, int, int] = TEAM_L_RGB

    @property
    def name(self) -> str:
        return "js"

    def init_game(
        self,
        team_r_rgb: tuple[int, int, int],
        team_l_rgb: tuple[int, int, int],
    ) -> None:
        self._team_r_rgb = team_r_rgb
        self._team_l_rgb = team_l_rgb
        self._grid = self._bridge.chess_init(team_r_rgb, team_l_rgb)

    def legal_moves(self, team_key: str) -> Set[Tuple[int, int, int, int]]:
        if self._grid is None:
            raise RuntimeError("Game not initialized")
        raw = self._bridge.chess_legal_moves(
            self._grid, self._team_r_rgb, self._team_l_rgb, team_key
        )
        return {tuple(m) for m in raw}

    def apply_move(
        self,
        fr: int, fc: int, tr: int, tc: int,
        team_key: str, next_key: str, peace_time: int,
    ) -> dict:
        if self._grid is None:
            raise RuntimeError("Game not initialized")
        result = self._bridge.chess_apply_move(
            self._grid, self._team_r_rgb, self._team_l_rgb,
            fr, fc, tr, tc, team_key, next_key, peace_time,
        )
        self._grid = result["grid"]
        return result

    def close(self) -> None:
        self._bridge.close()


class SwiftEngine(ChessEngine):
    """Swift chess engine via SwiftBridge subprocess."""

    def __init__(self) -> None:
        self._bridge = SwiftBridge()
        self._grid: list | None = None
        self._team_r_rgb: tuple[int, int, int] = TEAM_R_RGB
        self._team_l_rgb: tuple[int, int, int] = TEAM_L_RGB

    @property
    def name(self) -> str:
        return "swift"

    def init_game(
        self,
        team_r_rgb: tuple[int, int, int],
        team_l_rgb: tuple[int, int, int],
    ) -> None:
        self._team_r_rgb = team_r_rgb
        self._team_l_rgb = team_l_rgb
        self._grid = self._bridge.chess_init(team_r_rgb, team_l_rgb)

    def legal_moves(self, team_key: str) -> Set[Tuple[int, int, int, int]]:
        if self._grid is None:
            raise RuntimeError("Game not initialized")
        raw = self._bridge.chess_legal_moves(
            self._grid, self._team_r_rgb, self._team_l_rgb, team_key
        )
        return {tuple(m) for m in raw}

    def apply_move(
        self,
        fr: int, fc: int, tr: int, tc: int,
        team_key: str, next_key: str, peace_time: int,
    ) -> dict:
        if self._grid is None:
            raise RuntimeError("Game not initialized")
        result = self._bridge.chess_apply_move(
            self._grid, self._team_r_rgb, self._team_l_rgb,
            fr, fc, tr, tc, team_key, next_key, peace_time,
        )
        self._grid = result["grid"]
        return result

    def close(self) -> None:
        self._bridge.close()


class HilEngine(ChessEngine):
    """HIL Docker container chess engine via WebSocket."""

    def __init__(self, url: str = "ws://localhost:8766") -> None:
        if not _HAS_HIL:
            raise ImportError("hil.client not available")
        self._url = url
        self._bridge: HilBridge | None = None

    @property
    def name(self) -> str:
        return "hil"

    def connect(self, retries: int = 3, delay: float = 1.0) -> None:
        """Connect to HIL container. Call before init_game."""
        self._bridge = HilBridge(url=self._url, timeout=10.0)
        self._bridge.connect(retries=retries, delay=delay)
        if not self._bridge.ping():
            raise ConnectionError(f"HIL at {self._url} not responding")

    def init_game(
        self,
        team_r_rgb: tuple[int, int, int],
        team_l_rgb: tuple[int, int, int],
    ) -> None:
        if self._bridge is None:
            raise RuntimeError("Not connected - call connect() first")
        self._bridge.chess_init(team_r_rgb, team_l_rgb)

    def legal_moves(self, team_key: str) -> Set[Tuple[int, int, int, int]]:
        if self._bridge is None:
            raise RuntimeError("Not connected")
        raw = self._bridge.chess_legal_moves(team_key)
        return {tuple(m) for m in raw}

    def apply_move(
        self,
        fr: int, fc: int, tr: int, tc: int,
        team_key: str, next_key: str, peace_time: int,
    ) -> dict:
        if self._bridge is None:
            raise RuntimeError("Not connected")
        return self._bridge.chess_apply_move(
            fr, fc, tr, tc, team_key, next_key, peace_time
        )

    def close(self) -> None:
        if self._bridge:
            self._bridge.close()
            self._bridge = None


class LockstepRunner:
    """Runs games through multiple engines, comparing at each ply."""

    def __init__(
        self,
        engines: list[ChessEngine],
        crashes_dir: Path,
        seed: int,
        max_ply: int = 120,
    ) -> None:
        if len(engines) < 2:
            raise ValueError("Need at least 2 engines for lockstep testing")
        self._engines = engines
        self._crashes_dir = crashes_dir
        self._seed = seed
        self._max_ply = max_ply
        self._rng = random.Random(seed)
        self._crashes_dir.mkdir(parents=True, exist_ok=True)

    def run_game(self, game_seed: int) -> bool:
        """Run one game through all engines. Returns True if all agreed."""
        game_rng = random.Random(game_seed)
        team_r_rgb = TEAM_R_RGB
        team_l_rgb = TEAM_L_RGB

        for engine in self._engines:
            engine.init_game(team_r_rgb, team_l_rgb)

        current_key = "r"
        peace_time = 0
        corpus_moves: list[dict] = []

        for ply in range(self._max_ply):
            move_sets: dict[str, set] = {}
            for engine in self._engines:
                move_sets[engine.name] = engine.legal_moves(current_key)

            ref_name = self._engines[0].name
            ref_moves = move_sets[ref_name]

            for engine in self._engines[1:]:
                other_moves = move_sets[engine.name]
                if ref_moves != other_moves:
                    self._save_moves_crash(
                        game_seed, ply, ref_name, engine.name,
                        ref_moves, other_moves, corpus_moves,
                    )
                    return False

            if not ref_moves:
                break

            move = game_rng.choice(sorted(ref_moves))
            fr, fc, tr, tc = move
            next_key = "l" if current_key == "r" else "r"

            results: dict[str, dict] = {}
            for engine in self._engines:
                results[engine.name] = engine.apply_move(
                    fr, fc, tr, tc, current_key, next_key, peace_time
                )

            corpus_moves.append({
                "fr": fr, "fc": fc, "tr": tr, "tc": tc,
                "team_key": current_key, "flags": {},
            })

            ref_hash = results[ref_name]["board_hash"]
            for engine in self._engines[1:]:
                other_hash = results[engine.name]["board_hash"]
                if ref_hash != other_hash:
                    self._save_hash_crash(
                        game_seed, ply, move, ref_name, engine.name,
                        ref_hash, other_hash, corpus_moves,
                    )
                    return False

            current_key = next_key
            peace_time += 1

        return True

    def run_fuzzing(self, iterations: int) -> tuple[int, int, int]:
        """Run multiple games. Returns (total, ok, disagree)."""
        total = 0
        ok = 0
        disagree = 0

        i = 0
        while iterations == 0 or i < iterations:
            game_seed = self._rng.randint(0, 2**32)
            if self.run_game(game_seed):
                ok += 1
            else:
                disagree += 1
            total += 1
            i += 1

        return total, ok, disagree

    def _save_moves_crash(
        self, game_seed: int, ply: int,
        engine_a: str, engine_b: str,
        moves_a: set, moves_b: set,
        corpus_moves: list[dict],
    ) -> None:
        tag = f"{engine_a}_vs_{engine_b}"
        fname = f"moves_ply{ply}_{tag}.json"
        crash = {
            "seed": game_seed, "ply": ply, "tag": tag,
            "move_history": corpus_moves,
            f"only_{engine_a}": sorted(moves_a - moves_b),
            f"only_{engine_b}": sorted(moves_b - moves_a),
        }
        (self._crashes_dir / fname).write_text(json.dumps(crash, indent=2))
        save_corpus(
            self._crashes_dir, "chess", "fuzz_lockstep",
            TEAM_R_RGB, TEAM_L_RGB, corpus_moves,
            {"ply": ply, "kind": "legal_moves", "detail": tag},
            game_seed,
        )

    def _save_hash_crash(
        self, game_seed: int, ply: int, move: tuple,
        engine_a: str, engine_b: str,
        hash_a: str, hash_b: str,
        corpus_moves: list[dict],
    ) -> None:
        tag = f"{engine_a}_vs_{engine_b}"
        fname = f"hash_ply{ply}_{tag}.json"
        crash = {
            "seed": game_seed, "ply": ply, "tag": tag,
            "move": list(move), "move_history": corpus_moves,
            f"{engine_a}_hash": hash_a, f"{engine_b}_hash": hash_b,
        }
        (self._crashes_dir / fname).write_text(json.dumps(crash, indent=2))
        save_corpus(
            self._crashes_dir, "chess", "fuzz_lockstep",
            TEAM_R_RGB, TEAM_L_RGB, corpus_moves,
            {"ply": ply, "kind": "board_hash", "detail": tag,
             f"{engine_a}_hash": hash_a[:16], f"{engine_b}_hash": hash_b[:16]},
            game_seed,
        )

    def replay_corpus(self, corpus_path: Path) -> tuple[bool, str]:
        """Replay corpus file through all engines. Returns (passed, message).

        Tests that all engines now agree on the recorded move sequence.
        If engines disagree, the corpus represents an unfixed bug.
        """
        corpus = load_corpus(corpus_path)
        moves = corpus["moves"]
        team_r_rgb = tuple(corpus["team_r_rgb"])
        team_l_rgb = tuple(corpus["team_l_rgb"])

        for engine in self._engines:
            engine.init_game(team_r_rgb, team_l_rgb)

        current_key = "r"
        peace_time = 0

        for ply, move_data in enumerate(moves):
            move_sets: dict[str, set] = {}
            for engine in self._engines:
                move_sets[engine.name] = engine.legal_moves(current_key)

            ref_name = self._engines[0].name
            ref_moves = move_sets[ref_name]

            for engine in self._engines[1:]:
                other_moves = move_sets[engine.name]
                if ref_moves != other_moves:
                    only_ref = ref_moves - other_moves
                    only_other = other_moves - ref_moves
                    return False, (
                        f"ply {ply}: legal moves disagree "
                        f"({ref_name} vs {engine.name}): "
                        f"only_{ref_name}={sorted(only_ref)}, "
                        f"only_{engine.name}={sorted(only_other)}"
                    )

            fr = move_data["fr"]
            fc = move_data["fc"]
            tr = move_data["tr"]
            tc = move_data["tc"]
            next_key = "l" if current_key == "r" else "r"

            results: dict[str, dict] = {}
            for engine in self._engines:
                results[engine.name] = engine.apply_move(
                    fr, fc, tr, tc, current_key, next_key, peace_time
                )

            ref_hash = results[ref_name]["board_hash"]
            for engine in self._engines[1:]:
                other_hash = results[engine.name]["board_hash"]
                if ref_hash != other_hash:
                    return False, (
                        f"ply {ply}: board hash disagree "
                        f"({ref_name} vs {engine.name}): "
                        f"{ref_hash[:16]}... vs {other_hash[:16]}..."
                    )

            current_key = next_key
            peace_time += 1

        return True, f"passed ({len(moves)} moves)"
