# Fuzz Testing Bug Report

Bugs discovered by the lockstep fuzzing harness comparing the Python chess
engine, the JS chess engine (`web/chess-engine.js`), and the JS spectator
engine (`web/spectator-engine.js`).

All JS code was added recently; when the two implementations disagree, the
bug is almost certainly in the JS side — the Python engine is the long-standing
reference implementation.

---

## Phase 1 — ChessMatrix barcode parity (Python ↔ JS scanner)

**Status:** 190+ disagreements found by `fuzz_chessmatrix.py`.

These are boundary-robustness differences, not logic bugs: the Python and JS
decode pipelines use slightly different Hough/threshold parameters, so one
succeeds on marginal frames where the other fails.  Both return the *same*
room code when they both succeed — no wrong-decode bugs have been found.

**Impact:** Low.  The scanner is designed to retry every frame; a single missed
frame is invisible to the user.  No action required unless a wrong-decode (both
return a code, but different codes) is found.

---

## Phase 2 — Chess engine parity (Python ↔ JS engine)

### FUZZ-01: JS engine computes extra legal moves

**Severity:** High
**Found by:** `fuzz_chess.py`, `harness/crashes/chess/moves_game000034_ply59.json`
**Pattern:** `only_python=[], only_js=[[6,4,5,5]]`
**Root cause (suspected):** The JS engine's pin detection (`criticalMan`) or
check filtering (`skyFall`) is less restrictive than Python's — it allows
moves that should be blocked because the piece is pinned to the king or the
move doesn't resolve check.

**Reproduction:** seed 1629748727, ply 59 — JS finds move (6,4)→(5,5) as
legal while Python does not.  At this point JS has 1 extra legal move.

### FUZZ-02: Python and JS disagree on which diagonal a piece can move

**Severity:** High
**Found by:** `fuzz_chess.py`, `harness/crashes/chess/moves_game000000_ply115.json`
**Pattern:** `only_python=[[4,4,3,3]], only_js=[[4,4,5,3]]`
**Root cause (suspected):** A piece at (4,4) can move to (3,3) in Python but
(5,3) in JS (or vice versa).  This suggests a directional bug in the JS
engine's target calculation — likely a sign error in the diagonal ray-casting
or an incorrect `criticalMan` pin-ray direction.

**Reproduction:** seed 2746317213, ply 115.

### FUZZ-03: Legal move set divergence is systematic

**Severity:** High
**Found by:** `fuzz_chess.py` (42/50 default-run games disagree)
**Pattern:** In the majority of random games, the engines eventually disagree
on the legal move set, typically between plies 40–120.  The disagreement is
almost always `js_extra > 0` — JS allows moves that Python forbids.

**Root cause (suspected):** The JS engine's `criticalMan()` (pin detection)
and/or `skyFall()` (check-response filtering) implementations diverge from
the Python equivalents.  These are the most complex parts of the move-legality
logic and the most likely place for a translation error.

**Next step:** Isolate the specific piece + board state at the first
disagreement ply, compare `calcTargets` output cell-by-cell between Python
and JS to find the exact divergence point.

---

## Phase 3 — Networked parity (Python engine ↔ JS engine ↔ JS spectator)

### FUZZ-04: JS engine does not clear en-passant-captured pawn from grid

**Severity:** High
**Found by:** `fuzz_networked.py`, `harness/crashes/networked/game000019_ply53.json`
**Pattern:** After an en passant capture, the JS engine keeps the captured
pawn on the board at `captured_at`.  The Python engine and JS spectator
correctly remove it.

**Details:** Move (3,4)→(2,5) with flags `is_en_passant=true, captured_at=[3,5]`.
After the move:
- Python grid at (3,5): `None` (correct — captured pawn removed)
- Spectator grid at (3,5): `None` (correct — flags.captured_at handled)
- JS engine grid at (3,5): `{type:"Pawn", team_r:true}` (BUG — pawn not removed)

**Root cause:** In `chess-engine.js` `applyMove()`, the en passant capture
path calls `piece.move(tr, tc, grid)` which returns the enemy cell, and the
enemy is removed from the grid.  However, the `flags.captured_at` is then
*overwritten* by the regular capture check (`if (captured) flags.captured_at
= [tr, tc]`).  The actual grid mutation to remove the en-passant pawn may be
happening in `Pawn.move()` but the JS bridge's `applyMove` function at
line 122 (`if (captured) flags.captured_at = [tr, tc]`) overwrites the
en-passant-specific `captured_at` with the destination cell.

More critically, looking at `js_bridge.js:applyMove()` line 122:
```js
if (captured) flags.captured_at = [tr, tc];
```
When `captured` is the pre-existing piece at the destination (which is `null`
for en passant, since the captured pawn is *beside* the landing square), this
line should be harmless.  But the real issue is likely that `Pawn.move()` in
the JS engine does not correctly return the enemy cell or does not trigger the
grid removal, causing the captured pawn to remain.

**Reproduction:** seed 3466589567, ply 53.

**Next step:** Add a targeted unit test in `test_sim_js.js` that sets up an
en passant position and verifies the captured pawn is removed from the grid
after `applyMove`.

---

## Summary

| ID | Phase | Severity | Summary | Likely location |
|----|-------|----------|---------|-----------------|
| FUZZ-01 | 2 | High | JS allows moves Python forbids (pin/check) | `chess-engine.js` `criticalMan`/`skyFall` |
| FUZZ-02 | 2 | High | Diagonal move direction disagreement | `chess-engine.js` ray-casting or pin logic |
| FUZZ-03 | 2 | High | Systematic legal-move divergence (42/50 games) | `chess-engine.js` move legality |
| FUZZ-04 | 3 | High | En passant captured pawn not cleared from JS grid | `chess-engine.js` `applyMove` / `Pawn.move` |

All bugs point to `web/chess-engine.js` — the recently-added JS chess engine
translation.  The Python engine and JS spectator engine agree in all tested
cases, confirming the Python implementation as the correct reference.
