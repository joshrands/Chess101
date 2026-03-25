# Plan: Lockstep Test Harness + Fuzzing Framework

## Context

Several subsystems have independent Python and JavaScript implementations that are expected to be semantically equivalent but are only tested in isolation. Bugs caused by divergence between the two (e.g., one decodes a barcode that the other rejects, or one generates a legal move the other considers illegal) are invisible to the current test suite. This plan builds:

1. **A lockstep harness** — a driver that feeds identical inputs to both Python and JS implementations and asserts they agree on every output.
2. **A fuzzer** — a corpus-based input generator that exercises the lockstep harness at scale, looking for disagreements, crashes, and invariant violations.

---

## What to lockstep

### Surface A — ChessMatrix barcode decode (`network/chessmatrix.py` ↔ `web/chessmatrix-scanner.js`)

Both fully implement the same 15-stage decode pipeline. Both are already well-tested individually; the lockstep finds *disagreements*: cases where Python returns a code and JS returns null (or vice versa), or where both return different codes.

**Input domain:** synthetic RGBA frames at arbitrary rotation / perspective / noise / lighting.
**Oracle:** Python result == JS result (including null == null).

### Surface B — ChessMatrix encode (`network/chessmatrix.py::encode` ↔ JS encoder in `test_chessmatrix_js.js`)

The JS encoder is currently embedded in the test file (`encodeChessMatrix`). It should be extracted to `web/chessmatrix-encoder.js` so it can be called independently.

**Input domain:** random 6-char all-alpha room codes.
**Oracle:** encode → render → decode round-trip is identity on both sides, and Python-encoded image decodes correctly in JS (and vice versa).

### Surface C — Chess gameplay (`pieces/*.py` + `game/board.py` ↔ JS chess engine in `web/sim.html`)

`web/sim.html` contains a complete JS chess implementation with `calcTargets`, check/checkmate/stalemate, and alpha-beta AI. It is browser-only and cannot be tested from Node.js today.

**Prerequisite:** Extract the JS chess engine from `sim.html` into `web/chess-engine.js` (a Node-compatible CommonJS/ESM module). No logic changes — extraction and wrapping only.

**Input domain:** random legal move sequences from the starting position.
**Oracle at each step:**
- Set of legal moves agrees between Python and JS.
- Board state hash (same canonical string used by `network/protocol.py::board_hash`) agrees.
- Check / checkmate / stalemate status agrees.

### Surface D — Full networked game through the relay (all role combinations)

A complete game is simulated through the relay with every combination of Python and JS implementations filling the HOST, GUEST, and SPECTATOR roles. The fuzzer generates the move sequence; the harness checks that all participants agree after every move.

**Role implementations:**
- **Python HOST/GUEST** — `NetworkedGameRunner` / `NetworkedBoard` (existing)
- **JS HOST/GUEST** — extracted from `web/sim.html` via `web/chess-engine.js` + bridge (Phase 2 prerequisite)
- **Python SPECTATOR** — `NetworkedGameRunner` with `NetworkRole.SPECTATOR` (existing)
- **JS SPECTATOR** — `applyMove` + `applyGrid` + message handler extracted from `web/spectator.html` into `web/spectator-engine.js` + bridge

**Combination matrix (HOST × GUEST):**

| # | HOST | GUEST | Spectators |
|---|------|-------|------------|
| 1 | Python | Python | — |
| 2 | Python | Python | Python |
| 3 | Python | Python | JS |
| 4 | Python | Python | Python + JS |
| 5 | Python | JS | — |
| 6 | Python | JS | Python |
| 7 | Python | JS | JS |
| 8 | Python | JS | Python + JS |
| 9 | JS | Python | — |
| 10 | JS | Python | Python |
| 11 | JS | Python | JS |
| 12 | JS | Python | Python + JS |
| 13 | JS | JS | — |
| 14 | JS | JS | Python |
| 15 | JS | JS | JS |
| 16 | JS | JS | Python + JS |

All 16 combinations run through the full fuzzer. `test_online_flow.py` covers the Python×Python happy path only — it plays a fixed short sequence and checks the protocol handshake, not move-level correctness under adversarial inputs. The fuzzer adds what it lacks: random move sequences that exercise en passant, castling, promotion, and fifty-move edge cases; desync-recovery paths; and spectator state consistency. All 16 combinations are net-new from the fuzzer's perspective.

**Oracles applied after every move:**
- HOST board hash == GUEST board hash (existing desync detection)
- Every connected SPECTATOR's board hash == game's board hash
- `currentKey` and `move_count` match across all participants
- Checkmate / stalemate / fifty-move detected identically on all sides

**Spectator-specific scenarios to fuzz:**
- Spectator joins mid-game (receives `rejoin_sync`, then subsequent moves)
- Spectator reconnects after disconnect (should resync cleanly)
- Multiple spectators of different implementations connected simultaneously

**What `spectator.html` independently implements (the interesting oracle):**
`spectator.html` has its own `applyMove` that handles en passant (`flags.captured_at`), castling (`flags.rook_from/rook_to`), and promotion (`flags.promoted_to`). These are independent reimplementations of the move-application logic and could diverge from the Python/JS game engines. Any disagreement between a spectator's board state and the game's board state is a bug.

**New prerequisite for JS SPECTATOR:** extract `applyMove`, `applyGrid`, and the message-handling logic from `web/spectator.html` into `web/spectator-engine.js` (Node-compatible). Logic-only extraction; `spectator.html` keeps a `<script src>` include.

This is the highest-value surface and the last to implement — it depends on Surfaces A–C and the JS extractions.

---

## Architecture

### Bridge protocol

The harness is **Python-orchestrated**. A Node.js bridge process runs persistently alongside the Python test process, communicating over stdin/stdout with newline-delimited JSON.

```
Python orchestrator
   │
   ├─ calls Python functions directly (import)
   │
   └─ subprocess: node harness/js_bridge.js
         stdin  ← {"op": "decode_frame", "rgba_b64": "...", "w": 320, "h": 240}
         stdout → {"result": "ABCDEF"}   or   {"result": null}   or   {"error": "..."}
```

The bridge is thin: one `switch` on `op`, dispatch to the right JS function, serialize output. Startup cost is paid once per test session; per-call overhead is only JSON serialization (~microseconds).

**Files:**
- `harness/js_bridge.js` — Node.js bridge (stdin→JS→stdout)
- `harness/python_bridge.py` — Python wrapper class (`JsBridge`) with typed methods
- `tests/test_lockstep.py` — pytest suite using `JsBridge`

### Fuzzer design

A simple corpus-and-mutate fuzzer (no coverage instrumentation at first):

```
corpus/
  seeds/     ← known-good inputs committed to repo
  crashes/   ← inputs that caused a disagreement or crash (auto-saved)
  queue/     ← generated inputs pending run

FuzzRunner:
  1. Pick an input from corpus (seed or previously generated)
  2. Mutate it (surface-specific mutations)
  3. Run on Python side → result_py
  4. Run on JS side via JsBridge → result_js
  5. Compare; save to crashes/ if disagree or either crashes
  6. If result_py != null and result_js != null, add to corpus
```

Mutations by surface:
- **ChessMatrix images:** rotate ±5°, add Gaussian/salt-pepper noise, adjust brightness/contrast, apply mild perspective warp, crop slightly.
- **Move sequences:** append a random legal move, swap two adjacent moves, truncate.
- **Network messages:** flip a random bit in a serialized field, change a piece type, alter coordinates by ±1.

---

## Phase 1 — ChessMatrix lockstep + fuzzer

**Goal:** validate that Python and JS always agree on `decode_frame`.

### Steps

1. **`harness/js_bridge.js`** — implement `decode_frame` op:
   ```js
   case 'decode_frame': {
     const rgba = Buffer.from(msg.rgba_b64, 'base64');
     const result = decodeFrame(new Uint8Array(rgba), msg.w, msg.h);
     respond({ result });
   }
   ```

2. **`harness/python_bridge.py`** — `JsBridge.decode_frame(rgba, w, h) -> str | None`

3. **`tests/test_lockstep_chessmatrix.py`** — parametrized over a set of synthetic frames (all existing `_make_frame_*` variants × a sample of room codes), asserting `py_result == js_result`.

4. **`harness/fuzz_chessmatrix.py`** — standalone fuzzer script (not a pytest test):
   ```
   python harness/fuzz_chessmatrix.py --iterations 10000 --seed-dir harness/seeds/chessmatrix/
   ```
   Runs indefinitely, printing disagreements, saving to `harness/crashes/chessmatrix/`.

5. **Seeds:** copy a few synthetic PNGs from existing test fixtures.

---

## Phase 2 — Chess gameplay lockstep

**Goal:** validate that Python and JS chess engines agree on legal moves and board state.

### Steps

1. **Extract JS chess engine** from `web/sim.html` into `web/chess-engine.js`:
   - Extract all piece classes, board logic, check/checkmate/stalemate detection.
   - No logic changes; wrap with `module.exports = { Board, Piece, ... }`.
   - Update `sim.html` to `import` from the new module (or keep a script include).

2. **`harness/js_bridge.js`** — add ops:
   - `chess_legal_moves(grid_json, team_r_json, team_l_json, active_team_key)` → `[[fr,fc,tr,tc], ...]`
   - `chess_apply_move(grid_json, fr, fc, tr, tc, flags_json)` → `{grid, board_hash, status}`

3. **`harness/python_bridge.py`** — matching typed wrappers.

4. **`tests/test_lockstep_chess.py`** — play random games from the starting position, comparing legal move sets and board hashes at each step.

5. **`harness/fuzz_chess.py`** — move-sequence fuzzer:
   - Start from initial position.
   - At each ply, ask Python for legal moves, pick one at random, apply on both sides, compare.
   - Record the full PGN-style sequence on disagreement.

---

## Phase 3 — Full networked game fuzzing (all role combinations)

**Goal:** simulate complete games for every HOST×GUEST combination, with optional spectators of mixed implementation, and detect any divergence, crash, or protocol error.

### Steps

1. Reuse the in-process relay from `test_relay.py` / `test_online_flow.py`.
2. Build a `GameSession` harness class that accepts `host_impl`, `guest_impl`, and `spectator_impls` (`"python"` or `"js"`) and wires the right implementations together.
3. Fuzzer generates move sequences; `GameSession` feeds them to HOST and verifies all participants agree after each move.
4. Run the full combination matrix (16 combinations) as a parametrized pytest suite in `tests/test_lockstep_networked.py`.
5. Run the full matrix as `harness/fuzz_networked.py` for long-running adversarial campaigns with additional perturbations:
   - Drop packets (relay-level hook)
   - Replay a move message twice
   - Corrupt `board_hash` field to force desync-recovery paths
   - Send moves out of sequence
   - Spectator connects mid-game at a random ply (tests `rejoin_sync`)
   - Multiple spectators join and leave at different points

---

## Open questions / decisions before starting

| Question | Options | Recommendation |
|---|---|---|
| Bridge transport | stdio JSON (simple) vs WebSocket vs shared memory | stdio JSON — simplest for this scale |
| JS chess extraction | Extract to `web/chess-engine.js` vs keep in `sim.html` | Extract — needed for Node.js testability |
| Fuzzer persistence | In-memory only vs corpus-on-disk | Disk corpus — lets you replay crashes and grow corpus over time |
| Coverage guidance | None vs V8 inspector / Python coverage | None to start; add if random generation misses important cases |
| Harness location | `tests/` vs new top-level `harness/` | New `harness/` dir — keeps fuzzing tools separate from pytest suite |

---

## Critical files (new)

- `harness/js_bridge.js` — Node.js stdio bridge
- `harness/python_bridge.py` — Python `JsBridge` wrapper class
- `harness/fuzz_chessmatrix.py` — ChessMatrix fuzzer entry point
- `harness/fuzz_chess.py` — chess gameplay fuzzer entry point
- `harness/fuzz_networked.py` — full networked game fuzzer (all 16 combinations)
- `harness/seeds/chessmatrix/` — seed corpus for barcode fuzzer
- `tests/test_lockstep_chessmatrix.py` — pytest lockstep suite (Surface A)
- `tests/test_lockstep_chess.py` — pytest lockstep suite (Surface C)
- `tests/test_lockstep_networked.py` — pytest lockstep suite (Surface D, all 16 combinations)
- `web/chess-engine.js` — extracted JS chess engine (Phase 2 prerequisite)
- `web/spectator-engine.js` — extracted JS spectator logic: `applyMove`, `applyGrid`, message handler (Phase 3 prerequisite)

## Existing files modified

- `web/sim.html` — import chess logic from `chess-engine.js` instead of inline
- `web/spectator.html` — import message-handling logic from `spectator-engine.js` instead of inline
- `web/chessmatrix-scanner.js` — no changes (bridge calls `decodeFrame` already exported)
