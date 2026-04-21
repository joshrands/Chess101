# Lockstep Fuzzer Consolidation

**Date:** 2026-04-21  
**Status:** Approved  
**Author:** Rocky (Claude)

## Summary

Consolidate chess lockstep testing into a single modular fuzzer that tests all four engines (Python, JS, Swift, HIL) together. Rename `fuzz_lockstep_swift.py` to `fuzz_lockstep.py` and delete the old file.

## Goals

1. Test all four chess engine implementations in lockstep: Python, JavaScript, Swift, and HIL (Docker)
2. Improve fuzzer naming to reflect actual functionality
3. Maintain backward compatibility with existing crash corpus files
4. Create modular architecture for future extensibility

## Non-Goals

- Changing the actual chess engine logic in any platform
- Modifying the HIL control server's lockstep methods
- Adding new fuzzing strategies (random moves remain)

## Background

Current state:
- `fuzz_chess.py` - Tests Python, JS, and optionally HIL via `--hil-url`
- `fuzz_lockstep_swift.py` - Tests Python, JS, Swift (no HIL)
- `fuzz_hil.py` - Tests HIL with random piece movements (not chess engine lockstep)

Problem: Swift is only in `fuzz_lockstep_swift.py`, HIL is only in `fuzz_chess.py`, and the naming is confusing.

## Design

### File Structure

```
harness/
├── lockstep_runner.py     # NEW: Engine protocol + runner loop
├── fuzz_lockstep.py       # NEW: Consolidates fuzz_chess + fuzz_lockstep_swift
├── fuzz_chess.py          # DELETE after migration
├── fuzz_lockstep_swift.py # DELETE after migration
├── python_bridge.py       # Existing JS bridge
├── swift_bridge.py        # Existing Swift bridge
└── ...
```

### Engine Protocol

```python
from abc import ABC, abstractmethod
from typing import Set, Tuple

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
```

### Engine Implementations

1. **PythonEngine** - Uses `chess_helpers` directly, no subprocess
2. **JsEngine** - Wraps existing `JsBridge`
3. **SwiftEngine** - Wraps existing `SwiftBridge`
4. **HilEngine** - Wraps existing `HilBridge`, connects to Docker container

### Lockstep Runner

```python
class LockstepRunner:
    """Runs games through multiple engines, comparing at each ply."""
    
    def __init__(
        self,
        engines: list[ChessEngine],
        crashes_dir: Path,
        seed: int,
        max_ply: int = 120,
    ):
        ...
    
    def run_game(self, game_seed: int) -> bool:
        """Run one game, return True if all engines agreed."""
        ...
    
    def run_fuzzing(self, iterations: int) -> tuple[int, int, int]:
        """Run multiple games, return (total, ok, disagree)."""
        ...
```

### CLI Interface

```bash
# Full lockstep (all engines):
bazel run //harness:fuzz_lockstep -- --iterations 100

# Subset of engines:
bazel run //harness:fuzz_lockstep -- --iterations 100 --engines python,js,swift

# With HIL container:
bazel run //harness:fuzz_lockstep -- --iterations 100 --hil-url ws://localhost:8766

# Default (Python + JS + Swift, HIL if --hil-url provided):
.venv/bin/python harness/fuzz_lockstep.py --iterations 100
```

Flags:
- `--iterations N` - Number of games (0 = infinite)
- `--seed N` - RNG seed for reproducibility
- `--max-ply N` - Maximum half-moves per game
- `--engines LIST` - Comma-separated engine names (default: python,js,swift)
- `--hil-url URL` - HIL container WebSocket URL (adds HIL engine if provided)

### Bazel Changes

```python
# harness/BUILD.bazel

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
    deps = [":lockstep_runner"],
)

# DELETE: fuzz_chess, fuzz_lockstep_swift targets
```

### Backward Compatibility

Existing corpus files have a `source` field (e.g., `"fuzz_chess"`, `"fuzz_lockstep_swift"`). The new fuzzer will:

1. Accept any `source` value when replaying corpus files
2. Write new corpus files with `source: "fuzz_lockstep"`
3. Use the same corpus format (version 1)

### Error Reporting

When engines disagree, report:
- Which engines differ (e.g., "python vs swift")
- The specific disagreement (legal moves or board hash)
- Full move history for reproduction
- Save corpus file for regression testing

## Testing Strategy

1. **Unit tests for lockstep_runner.py:**
   - Test engine protocol with mock engines
   - Test disagreement detection
   - Test corpus file generation

2. **Regression test with existing corpus:**
   - New Bazel test that replays all `*.corpus.json` files through new fuzzer
   - Verifies backward compatibility

3. **Integration test:**
   - `bazel test //harness:fuzz_lockstep_test` runs 10 iterations with Python+JS+Swift
   - CI runs this on every PR

4. **Manual HIL test:**
   - Start HIL container: `docker-compose -f docker-compose.hil.yml up -d`
   - Run: `.venv/bin/python harness/fuzz_lockstep.py --iterations 50 --hil-url ws://localhost:8766`

## Documentation Updates

1. **CLAUDE.md** - Update "Running Tests" section with new fuzzer name
2. **tests/README.md** - Update fuzzer documentation
3. **harness/BUILD.bazel comments** - Update inline docs

## Migration Steps

1. Create `lockstep_runner.py` with engine protocol and runner
2. Create engine implementations (Python, JS, Swift, HIL)
3. Create `fuzz_lockstep.py` using the runner
4. Update `BUILD.bazel` with new targets
5. Verify existing corpus files replay correctly
6. Delete `fuzz_chess.py` and `fuzz_lockstep_swift.py`
7. Update documentation

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Breaking existing corpus replay | Test all existing corpus files before deleting old fuzzers |
| HIL connection failures breaking tests | HIL is opt-in via --hil-url; default runs without HIL |
| Increased complexity | Clean protocol abstraction keeps each engine simple |
