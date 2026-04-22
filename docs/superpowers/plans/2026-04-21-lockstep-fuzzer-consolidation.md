# Lockstep Fuzzer Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate `fuzz_chess.py` and `fuzz_lockstep_swift.py` into a single modular `fuzz_lockstep.py` with a pluggable engine architecture.

**Architecture:** Create `lockstep_runner.py` with a `ChessEngine` ABC and four implementations (Python, JS, Swift, HIL). The `LockstepRunner` class runs games through all engines in parallel, comparing results at each ply. The thin CLI wrapper `fuzz_lockstep.py` instantiates engines and calls the runner.

**Tech Stack:** Python 3.9+, Bazel, existing `JsBridge`, `SwiftBridge`, `HilBridge`

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `harness/lockstep_runner.py` | CREATE | Engine protocol + 4 implementations + LockstepRunner |
| `harness/fuzz_lockstep.py` | CREATE | CLI entry point |
| `tests/test_lockstep_runner.py` | CREATE | Unit tests for runner |
| `harness/BUILD.bazel` | MODIFY | Add new targets, remove old |
| `harness/fuzz_chess.py` | DELETE | After migration verified |
| `harness/fuzz_lockstep_swift.py` | DELETE | After migration verified |
| `CLAUDE.md` | MODIFY | Update fuzzer docs |
| `tests/README.md` | MODIFY | Update fuzzer docs |

---

### Task 1: Create ChessEngine ABC and PythonEngine

**Files:**
- Create: `harness/lockstep_runner.py`
- Test: `tests/test_lockstep_runner.py`

- [ ] **Step 1: Write the failing test for PythonEngine**

```python
# tests/test_lockstep_runner.py
"""Unit tests for lockstep_runner module."""
from __future__ import annotations

import pytest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.lockstep_runner import PythonEngine


class TestPythonEngine:
    def test_name(self):
        engine = PythonEngine()
        assert engine.name == "python"

    def test_init_game(self):
        engine = PythonEngine()
        engine.init_game((64, 180, 232), (255, 140, 0))
        # Should not raise

    def test_legal_moves_initial_position(self):
        engine = PythonEngine()
        engine.init_game((64, 180, 232), (255, 140, 0))
        moves = engine.legal_moves("r")
        # 20 legal moves for white in starting position
        assert len(moves) == 20
        # Check a known pawn move exists
        assert (1, 0, 2, 0) in moves  # a2-a3
        assert (1, 0, 3, 0) in moves  # a2-a4

    def test_apply_move(self):
        engine = PythonEngine()
        engine.init_game((64, 180, 232), (255, 140, 0))
        result = engine.apply_move(1, 4, 3, 4, "r", "l", 0)  # e2-e4
        assert "grid" in result
        assert "board_hash" in result
        assert isinstance(result["board_hash"], str)
        assert len(result["board_hash"]) == 64  # SHA-256 hex
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_lockstep_runner.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'harness.lockstep_runner'"

- [ ] **Step 3: Create lockstep_runner.py with ChessEngine ABC and PythonEngine**

```python
# harness/lockstep_runner.py
"""Modular lockstep chess engine testing framework.

Provides a pluggable architecture for testing multiple chess engine
implementations in lockstep. Each engine implements the ChessEngine
protocol; the LockstepRunner plays games through all engines and
detects disagreements.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Set, Tuple

from core.team import Team
from pieces.pawn import Pawn
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
        if self._grid is None or self._team_r is None:
            raise RuntimeError("Game not initialized")
        py_apply_move(self._grid, fr, fc, tr, tc)
        grid_json = py_grid_to_json(self._grid, self._team_r)
        hash_val = board_hash(self._grid, peace_time, next_key, self._team_r)
        return {"grid": grid_json, "board_hash": hash_val}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_lockstep_runner.py::TestPythonEngine -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add harness/lockstep_runner.py tests/test_lockstep_runner.py
git commit -m "feat: add ChessEngine ABC and PythonEngine"
```

---

### Task 2: Add JsEngine

**Files:**
- Modify: `harness/lockstep_runner.py`
- Modify: `tests/test_lockstep_runner.py`

- [ ] **Step 1: Write the failing test for JsEngine**

Add to `tests/test_lockstep_runner.py`:

```python
from harness.lockstep_runner import JsEngine


class TestJsEngine:
    def test_name(self):
        engine = JsEngine()
        try:
            assert engine.name == "js"
        finally:
            engine.close()

    def test_init_and_legal_moves(self):
        engine = JsEngine()
        try:
            engine.init_game((64, 180, 232), (255, 140, 0))
            moves = engine.legal_moves("r")
            assert len(moves) == 20
        finally:
            engine.close()

    def test_apply_move(self):
        engine = JsEngine()
        try:
            engine.init_game((64, 180, 232), (255, 140, 0))
            result = engine.apply_move(1, 4, 3, 4, "r", "l", 0)
            assert "board_hash" in result
        finally:
            engine.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_lockstep_runner.py::TestJsEngine -v`
Expected: FAIL with "ImportError: cannot import name 'JsEngine'"

- [ ] **Step 3: Add JsEngine to lockstep_runner.py**

Add after `PythonEngine` class:

```python
from harness.python_bridge import JsBridge


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_lockstep_runner.py::TestJsEngine -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add harness/lockstep_runner.py tests/test_lockstep_runner.py
git commit -m "feat: add JsEngine to lockstep runner"
```

---

### Task 3: Add SwiftEngine

**Files:**
- Modify: `harness/lockstep_runner.py`
- Modify: `tests/test_lockstep_runner.py`

- [ ] **Step 1: Write the failing test for SwiftEngine**

Add to `tests/test_lockstep_runner.py`:

```python
from harness.lockstep_runner import SwiftEngine


class TestSwiftEngine:
    def test_name(self):
        engine = SwiftEngine()
        try:
            assert engine.name == "swift"
        finally:
            engine.close()

    def test_init_and_legal_moves(self):
        engine = SwiftEngine()
        try:
            engine.init_game((64, 180, 232), (255, 140, 0))
            moves = engine.legal_moves("r")
            assert len(moves) == 20
        finally:
            engine.close()

    def test_apply_move(self):
        engine = SwiftEngine()
        try:
            engine.init_game((64, 180, 232), (255, 140, 0))
            result = engine.apply_move(1, 4, 3, 4, "r", "l", 0)
            assert "board_hash" in result
        finally:
            engine.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_lockstep_runner.py::TestSwiftEngine -v`
Expected: FAIL with "ImportError: cannot import name 'SwiftEngine'"

- [ ] **Step 3: Add SwiftEngine to lockstep_runner.py**

Add after `JsEngine` class:

```python
from harness.swift_bridge import SwiftBridge


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_lockstep_runner.py::TestSwiftEngine -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add harness/lockstep_runner.py tests/test_lockstep_runner.py
git commit -m "feat: add SwiftEngine to lockstep runner"
```

---

### Task 4: Add HilEngine

**Files:**
- Modify: `harness/lockstep_runner.py`
- Modify: `tests/test_lockstep_runner.py`

- [ ] **Step 1: Write the failing test for HilEngine**

Add to `tests/test_lockstep_runner.py`:

```python
import pytest
from harness.lockstep_runner import HilEngine


class TestHilEngine:
    def test_name(self):
        engine = HilEngine("ws://localhost:8766")
        assert engine.name == "hil"

    @pytest.mark.skip(reason="Requires running HIL container")
    def test_connect_and_legal_moves(self):
        engine = HilEngine("ws://localhost:8766")
        try:
            engine.connect()
            engine.init_game((64, 180, 232), (255, 140, 0))
            moves = engine.legal_moves("r")
            assert len(moves) == 20
        finally:
            engine.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_lockstep_runner.py::TestHilEngine::test_name -v`
Expected: FAIL with "ImportError: cannot import name 'HilEngine'"

- [ ] **Step 3: Add HilEngine to lockstep_runner.py**

Add after `SwiftEngine` class:

```python
try:
    from hil.client import HilBridge
    _HAS_HIL = True
except ImportError:
    HilBridge = None  # type: ignore
    _HAS_HIL = False


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_lockstep_runner.py::TestHilEngine::test_name -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add harness/lockstep_runner.py tests/test_lockstep_runner.py
git commit -m "feat: add HilEngine to lockstep runner"
```

---

### Task 5: Add LockstepRunner class

**Files:**
- Modify: `harness/lockstep_runner.py`
- Modify: `tests/test_lockstep_runner.py`

- [ ] **Step 1: Write the failing test for LockstepRunner**

Add to `tests/test_lockstep_runner.py`:

```python
from harness.lockstep_runner import LockstepRunner, PythonEngine, JsEngine


class TestLockstepRunner:
    def test_run_game_both_agree(self):
        """Two engines that agree should return True."""
        py = PythonEngine()
        js = JsEngine()
        try:
            runner = LockstepRunner(
                engines=[py, js],
                crashes_dir=Path("/tmp/test_crashes"),
                seed=42,
                max_ply=10,
            )
            ok = runner.run_game(12345)
            assert ok is True
        finally:
            js.close()

    def test_run_fuzzing_returns_stats(self):
        """run_fuzzing should return (total, ok, disagree)."""
        py = PythonEngine()
        js = JsEngine()
        try:
            runner = LockstepRunner(
                engines=[py, js],
                crashes_dir=Path("/tmp/test_crashes"),
                seed=42,
                max_ply=20,
            )
            total, ok, disagree = runner.run_fuzzing(3)
            assert total == 3
            assert ok == 3
            assert disagree == 0
        finally:
            js.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_lockstep_runner.py::TestLockstepRunner -v`
Expected: FAIL with "ImportError: cannot import name 'LockstepRunner'"

- [ ] **Step 3: Add LockstepRunner to lockstep_runner.py**

Add at end of file:

```python
import json
import random
import time
from pathlib import Path

from harness.corpus import save_corpus


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
            # Get legal moves from all engines
            move_sets: dict[str, set] = {}
            for engine in self._engines:
                move_sets[engine.name] = engine.legal_moves(current_key)

            # Compare all against first engine
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
                break  # Game over

            # Pick and apply move
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

            # Compare hashes
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
            peace_time += 1  # Simplified; real impl tracks captures/pawns

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_lockstep_runner.py::TestLockstepRunner -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add harness/lockstep_runner.py tests/test_lockstep_runner.py
git commit -m "feat: add LockstepRunner class"
```

---

### Task 6: Create fuzz_lockstep.py CLI

**Files:**
- Create: `harness/fuzz_lockstep.py`

- [ ] **Step 1: Create the CLI entry point**

```python
#!/usr/bin/env python3
"""Unified lockstep chess fuzzer.

Tests Python, JS, Swift, and HIL chess engines in lockstep, comparing
legal moves and board hashes at each ply. Disagreements are saved as
crash files for replay.

Usage::

    bazel run //harness:fuzz_lockstep -- --iterations 100
    .venv/bin/python harness/fuzz_lockstep.py --iterations 100
    .venv/bin/python harness/fuzz_lockstep.py --engines python,js,swift
    .venv/bin/python harness/fuzz_lockstep.py --hil-url ws://localhost:8766
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.lockstep_runner import (
    PythonEngine,
    JsEngine,
    SwiftEngine,
    HilEngine,
    LockstepRunner,
)


AVAILABLE_ENGINES = {
    "python": PythonEngine,
    "js": JsEngine,
    "swift": SwiftEngine,
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Unified lockstep chess fuzzer"
    )
    parser.add_argument(
        "--iterations", type=int, default=100,
        help="Number of games (0 = infinite)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="RNG seed for reproducibility",
    )
    parser.add_argument(
        "--max-ply", type=int, default=120,
        help="Max half-moves per game",
    )
    parser.add_argument(
        "--engines", type=str, default="python,js,swift",
        help="Comma-separated engine names (default: python,js,swift)",
    )
    parser.add_argument(
        "--hil-url", type=str, default=None,
        help="HIL container WebSocket URL (adds HIL engine)",
    )
    args = parser.parse_args()

    crashes_dir = ROOT / "harness" / "crashes" / "lockstep"

    # Build engine list
    engine_names = [e.strip() for e in args.engines.split(",")]
    engines = []

    for name in engine_names:
        if name not in AVAILABLE_ENGINES:
            print(f"[ERROR] Unknown engine: {name}")
            print(f"Available: {', '.join(AVAILABLE_ENGINES.keys())}")
            return 1
        engines.append(AVAILABLE_ENGINES[name]())

    # Add HIL if URL provided
    hil = None
    if args.hil_url:
        try:
            hil = HilEngine(args.hil_url)
            hil.connect(retries=3, delay=1.0)
            engines.append(hil)
            print(f"[INFO] HIL connected at {args.hil_url}")
        except Exception as e:
            print(f"[WARN] HIL connection failed ({e}), continuing without HIL")

    if len(engines) < 2:
        print("[ERROR] Need at least 2 engines for lockstep testing")
        return 1

    engine_list = ", ".join(e.name for e in engines)
    print(f"[INFO] Engines: {engine_list}")
    print(f"[INFO] Starting lockstep fuzz: iterations={args.iterations}, "
          f"seed={args.seed}, max_ply={args.max_ply}")

    runner = LockstepRunner(
        engines=engines,
        crashes_dir=crashes_dir,
        seed=args.seed,
        max_ply=args.max_ply,
    )

    t0 = time.time()
    try:
        total, ok, disagree = runner.run_fuzzing(args.iterations)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        total, ok, disagree = 0, 0, 0
    finally:
        for e in engines:
            e.close()

    elapsed = time.time() - t0
    print(f"\nDone. {total} games in {elapsed:.1f}s")
    print(f"  ok={ok}  disagree={disagree}")
    if disagree > 0:
        print(f"  Crash files in {crashes_dir}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Test CLI runs**

Run: `.venv/bin/python harness/fuzz_lockstep.py --iterations 5 --engines python,js`
Expected: Output showing 5 games completed with ok=5

- [ ] **Step 3: Commit**

```bash
git add harness/fuzz_lockstep.py
git commit -m "feat: add fuzz_lockstep.py CLI"
```

---

### Task 7: Update BUILD.bazel

**Files:**
- Modify: `harness/BUILD.bazel`

- [ ] **Step 1: Add new targets and remove old ones**

Replace `fuzz_chess` and `fuzz_lockstep_swift` targets with:

```python
py_library(
    name = "lockstep_runner",
    srcs = ["lockstep_runner.py"],
    visibility = ["//:__subpackages__"],
    deps = [
        ":chess_helpers",
        ":corpus",
        ":python_bridge",
        ":swift_bridge",
        "//core",
        "//hil:client",
        "//network",
        "//pieces",
    ],
)

py_binary(
    name = "fuzz_lockstep",
    srcs = ["fuzz_lockstep.py"],
    data = [
        "js_bridge.js",
        "//web:chess_engine_js",
        "//web:chessmatrix_scanner_js",
    ],
    deps = [
        ":lockstep_runner",
    ],
)
```

Delete these targets:
- `fuzz_chess`
- `fuzz_lockstep_swift`

- [ ] **Step 2: Run Bazel build to verify**

Run: `bazel build //harness:fuzz_lockstep`
Expected: Build succeeds

- [ ] **Step 3: Test via Bazel**

Run: `bazel run //harness:fuzz_lockstep -- --iterations 5 --engines python,js`
Expected: 5 games, ok=5

- [ ] **Step 4: Commit**

```bash
git add harness/BUILD.bazel
git commit -m "build: add fuzz_lockstep target, remove old fuzz_chess/fuzz_lockstep_swift"
```

---

### Task 8: Verify backward compatibility with existing corpus

**Files:**
- None created, verification only

- [ ] **Step 1: List existing corpus files**

Run: `find harness/crashes -name "*.corpus.json" | head -5`
Expected: Shows existing corpus files

- [ ] **Step 2: Run lockstep fuzzer and verify no crashes on startup**

Run: `.venv/bin/python harness/fuzz_lockstep.py --iterations 10 --engines python,js,swift`
Expected: All 10 games pass (assuming engines are in sync)

- [ ] **Step 3: Document verification**

No commit needed - verification step only.

---

### Task 9: Delete old fuzzer files

**Files:**
- Delete: `harness/fuzz_chess.py`
- Delete: `harness/fuzz_lockstep_swift.py`

- [ ] **Step 1: Delete old files**

```bash
rm harness/fuzz_chess.py
rm harness/fuzz_lockstep_swift.py
```

- [ ] **Step 2: Run Gazelle to update BUILD files**

Run: `bazel run //:gazelle`
Review output - revert any incorrect changes to pre-seeded BUILD files.

- [ ] **Step 3: Verify Bazel still works**

Run: `bazel build //harness/...`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add -A harness/
git commit -m "chore: delete fuzz_chess.py and fuzz_lockstep_swift.py"
```

---

### Task 10: Update documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `tests/README.md`

- [ ] **Step 1: Update CLAUDE.md lockstep fuzzer section**

Find and replace references to `fuzz_chess` and `fuzz_lockstep_swift` with `fuzz_lockstep`:

```markdown
**Lockstep fuzzers** (save disagreements to `harness/crashes/`):
```bash
bazel run //harness:fuzz_lockstep -- --iterations 100
bazel run //harness:fuzz_lockstep -- --iterations 100 --engines python,js
bazel run //harness:fuzz_lockstep -- --hil-url ws://localhost:8766
.venv/bin/python harness/fuzz_lockstep.py --iterations 100   # Python+JS+Swift
```
```

- [ ] **Step 2: Update tests/README.md**

Update fuzzer documentation to reference the new unified fuzzer.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md tests/README.md
git commit -m "docs: update fuzzer documentation for fuzz_lockstep"
```

---

### Task 11: Final verification

- [ ] **Step 1: Run full test suite**

Run: `bazel test //tests/... //harness:fuzz_lockstep`
Expected: All tests pass

- [ ] **Step 2: Run lockstep fuzzer with all engines**

Run: `.venv/bin/python harness/fuzz_lockstep.py --iterations 20 --engines python,js,swift`
Expected: ok=20, disagree=0

- [ ] **Step 3: Test HIL integration (if container available)**

Run:
```bash
docker-compose -f docker-compose.hil.yml up -d
.venv/bin/python harness/fuzz_lockstep.py --iterations 10 --hil-url ws://localhost:8766
docker-compose -f docker-compose.hil.yml down
```
Expected: ok=10 with HIL engine included

---

## Summary

Total tasks: 11
Files created: 3 (`lockstep_runner.py`, `fuzz_lockstep.py`, `test_lockstep_runner.py`)
Files deleted: 2 (`fuzz_chess.py`, `fuzz_lockstep_swift.py`)
Files modified: 3 (`BUILD.bazel`, `CLAUDE.md`, `tests/README.md`)
