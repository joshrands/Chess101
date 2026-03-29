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

### FUZZ-01: JS engine computes extra legal moves ✅ FIXED

**Severity:** High
**Found by:** `fuzz_chess.py`, `harness/crashes/chess/moves_game000034_ply59.json`
**Pattern:** `only_python=[], only_js=[[6,4,5,5]]`
**Root cause:** King `direction` was not serialized in the bridge or protocol.
When a king moved from its starting row, the JS engine reconstructed it with
`direction` based on the new row (via the `King` constructor: `row===7?-1:1`),
not the original row.  This caused `amIGonnaDie`'s pawn-attack check
(`(er-this.row)===this.direction`) to use the wrong direction, missing enemy
pawn attacks and allowing the king to move to attacked squares.
**Fixed in:** `25d8133` — King `direction` is now serialized/deserialized in
`js_bridge.js`, `network/protocol.py`, `chess-engine.js`, and `sim.html`.

### FUZZ-02: Python and JS disagree on which diagonal a piece can move ✅ FIXED

**Severity:** High
**Found by:** `fuzz_chess.py`, `harness/crashes/chess/moves_game000000_ply115.json`
**Pattern:** `only_python=[[4,4,3,3]], only_js=[[4,4,5,3]]`
**Root cause:** Same as FUZZ-01 — stale king direction caused incorrect pin-ray
detection.  The pinned piece's `criticalTargets` were computed against the wrong
direction, allowing movement along the wrong diagonal.
**Fixed in:** `25d8133`

### FUZZ-03: Legal move set divergence is systematic ✅ FIXED

**Severity:** High
**Found by:** `fuzz_chess.py` (42/50 default-run games disagree)
**Pattern:** JS allows moves that Python forbids, almost always `js_extra > 0`.
**Root cause:** Combination of FUZZ-01/02 (king direction serialization) and
BUG-07 (double check not handled — see below).
**Fixed in:** `25d8133` + `a57f974`

**Post-fix verification:** 200 games, 0 disagreements (seed 9999, 23,363 plies).

---

## Phase 3 — Networked parity (Python engine ↔ JS engine ↔ JS spectator)

### FUZZ-04: JS engine does not clear en-passant-captured pawn from grid ✅ FIXED

**Severity:** High
**Found by:** `fuzz_networked.py`, `harness/crashes/networked/game000019_ply53.json`
**Pattern:** After an en passant capture, the JS engine keeps the captured
pawn on the board.
**Root cause:** The bridge's `applyMove` relied on `Pawn.enPassantLoc` being
set by `calcTargets`, but `calcTargets` is not called during move application.
The `enPassantLoc` was stale or null from JSON deserialization, so `Pawn.move()`
didn't detect the en passant capture and the captured pawn remained on the board.
**Fixed in:** `a57f974` — `js_bridge.js:applyMove` now sets `enPassantLoc`
when the move is structurally en passant (pawn moves diagonally to empty square)
and clears it otherwise, before calling `piece.move()`.

**Post-fix verification:** 200 games, 0 disagreements (seed 9999, 23,363 plies).

---

## BUG-07 fix — Double check handling ✅ FIXED

**Severity:** High (from `bug_report.md`)
**Found by:** Fuzz testing exposed the practical impact.
**Root cause:** Both Python and JS `amIGonnaDie` only tracked the last attacker
found, so in double-check positions the `godSaveTheKing` escape squares only
reflected one attacker.  Non-king pieces could then "resolve" check by blocking
or capturing one attacker while the other still gave check.
**Fixed in:** `a57f974` — Both Python (`pieces/king.py`) and JS
(`web/chess-engine.js`) now count attackers.  When `attackerCount > 1`,
`godSaveTheKing` is cleared so `skyFall` filters out all non-king moves.

---

## Summary

| ID | Phase | Severity | Summary | Status |
|----|-------|----------|---------|--------|
| FUZZ-01 | 2 | High | JS allows moves Python forbids (king direction) | ✅ Fixed (`25d8133`) |
| FUZZ-02 | 2 | High | Diagonal move direction disagreement (king direction) | ✅ Fixed (`25d8133`) |
| FUZZ-03 | 2 | High | Systematic legal-move divergence (42/50 games) | ✅ Fixed (`25d8133` + `a57f974`) |
| FUZZ-04 | 3 | High | En passant captured pawn not cleared from JS grid | ✅ Fixed (`a57f974`) |
| BUG-07 | 2+3 | High | Double check only tracks one attacker | ✅ Fixed (`a57f974`) |

All bugs fixed and verified clean across 400+ fuzzed games (46,726 total plies).
