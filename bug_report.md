# Chess101 Bug Report

All bugs listed here are **locked in** — real defects in the original Pi code that are intentionally preserved. Regression tests pin the exact behaviour so any accidental fix is caught immediately.

Severity scale: **Critical** (breaks every game) · **High** (breaks meaningful chess positions) · **Medium** (breaks specific but real positions) · **Low** (no real gameplay impact)

---

## BUG-01 — Pawn direction is set by starting row, not by team

**Severity: Medium**
In standard play pawns always init at rows 1 or 6 so the proxy works and this never fires. However, the AI tree expands moves by calling `calc_targets` on the existing piece objects (direction already set), so AI search is unaffected too. The bug only surfaces if a pawn is programmatically constructed at a non-standard row — for example in a custom test setup or a future board-editor feature. At that point a `team_l` pawn silently moves the wrong direction with no error.

**File:** `pieces/pawn.py` — `Pawn.__init__`

**Symptom:** `direction` is `−1` if `row == 6`, `+1` otherwise. Team identity has no effect. A `team_l` pawn created at any row other than 6 will move toward `team_l`'s own back rank.

**Root cause:** Row number used as a proxy for team identity.

**Locked-in test:** `tests/test_gameplay.py::TestPawnCapture::test_direction_set_by_row_not_team`

---

## BUG-02 — `team_r` red channel incremented by 1 after colour selection

**Severity: Low**
The `+1` is applied once and consistently. Every downstream comparison reads from the team object, so the off-by-one is universally present and never creates a mismatch. The only way this would cause a problem is if someone hardcoded the raw palette value (e.g. `64`) and compared it directly against `team_r.r` (which is `65`). No existing code does this.

**File:** `simulator/app.py` — `GameRunner._handle_color_pick` / `game/board.py` — `Board.color_picker`

**Symptom:** After colour selection, `team_r.r` is one higher than the chosen palette entry. Picking Blue (`r=64`) stores `r=65`.

**Root cause:** Deliberate "lock-in signal" in the original Pi `color_picker` logic; carried over into the simulator.

**Locked-in test:** `tests/test_simulator.py::TestPhaseTransitions::test_team_r_r_incremented_bug_lock_in`

---

## BUG-03 — Team identity compared by red channel only

**Severity: Low**
The eight palette colours have red values `0, 25, 28, 64, 190, 245, 250, 254` — all distinct. After BUG-02 applies `+1` to `team_r`, that set becomes `1, 26, 29, 65, 191, 246, 251, 255` — still all distinct and no overlap with the unmodified values. So no colour collision is possible with the current palette. The bug becomes real only if a new palette entry reuses a red value that already appears, which would silently merge two teams' pieces.

**Files:** `game/board.py` — `Board.get_team_pieces` / `simulator/app.py` — `GameRunner._get_team_pieces`

**Symptom:** `piece.team.r == team.r` is the sole ownership test. Green/blue channels are ignored.

**Root cause:** Shared single-channel convention used throughout the original codebase.

**Locked-in tests:** `tests/test_board.py::TestGetTeamPieces::test_red_channel_only_comparison_bug`, `tests/test_ai_tree.py::TestTreeUtility::test_utility_uses_only_red_channel_for_team_id`

---

## BUG-04 — Fifty-move rule triggers at 50 half-moves, not 100

**Severity: High**
Standard chess defines a "move" as one move by each player (two half-moves / plies). The rule should fire after 50 *full* moves = 100 half-moves. This implementation fires at 50 half-moves — exactly half the correct threshold. Technical endgames regularly exceed 25 full moves of quiet play: KBN vs K requires up to 33 full moves; K+R vs K up to 16. Those games will be incorrectly declared draws before they can be won or stalemated legitimately.

**File:** `game/rules.py` — `check_fifty_move_rule`

**Symptom:** `board.peace_time >= 50` triggers a draw. `peace_time` increments once per half-move (one player's turn).

**Root cause:** Off-by-factor-of-two error in the threshold.

**Locked-in test:** `tests/test_board.py::TestFiftyMoveRule::test_triggers_at_50_half_moves`

---

## BUG-05 — Threefold repetition compares piece *type*, not team identity

**Severity: Low**
For a false draw to be declared, two stored board snapshots would need to match the current position with the same piece types on the same squares but belonging to opposite teams. In a legal game, pieces never change ownership, so a square occupied by a `team_r` Pawn in snapshot A and a `team_l` Pawn in snapshot B at the same coordinates would require one team to have moved its pawn there and the other to have moved theirs there in an alternating pattern — essentially impossible without captures vacating the square in between. In practice this bug never fires incorrectly.

**File:** `game/rules.py` — `check_threefold_repetition`

**Symptom:** Position equality is `type(state[r][c]) is type(tron[r][c])` — a `team_r` Pawn and a `team_l` Pawn on the same square count as identical.

**Root cause:** Team identity never added to the comparison.

**Locked-in test:** `tests/test_board.py::TestThreefoldRepetition::test_uses_type_not_team_for_comparison`

---

## BUG-06 — `determine_direction_from_enemy_towards_king` returns float components

**Severity: Low**
Python's `==` comparison treats `0 == 0.0` as `True`, so the direction values are used correctly in all downstream comparisons (`if dir == 0`, `while row + dir < 8`, etc.). The float type is semantically wrong but produces no incorrect behaviour with the current code. It would only matter if a caller used strict type checking (`isinstance(dir, int)`) or stored the direction in a context that serialises types.

**File:** `pieces/king.py` — `determine_direction_from_enemy_towards_king`

**Symptom:** When enemy and king share a row or column, the zero component is `0.0` (float) rather than `0` (int). E.g. enemy at `(4,7)`, king at `(4,4)` → returns `(0, −1.0)`.

**Root cause:** Python 3 true division (`/`) used instead of integer coercion.

**Locked-in test:** `tests/test_king.py::TestDetermineDirection::test_same_row_col_component_is_float`

---

## BUG-07 — Double check only tracks the first attacker; second is silently discarded

**Severity: High**
Double check is a real tactic that occurs in actual games (discovered attack combined with a direct attack). The correct and only legal response to double check is a king move — no interposition or capture of one attacker is valid because the second attacker still gives check. This code populates `god_save_the_king` with squares that block only the first attacker found. Non-king pieces are then allowed to move to those squares, which does not resolve the double check and constitutes an illegal move being accepted by the engine.

**File:** `pieces/king.py` — `find_attacker` / `am_i_gonna_die`

**Symptom:** The attacker-finding loop returns on the first match. In a double-check position, one attacker's blocking squares are offered to non-king pieces as legal moves.

**Root cause:** Loop exits on first match rather than collecting all attackers.

**Locked-in test:** `tests/test_king.py::TestFindAttacker::test_returns_only_first_attacker_in_double_check`

---

## BUG-08 — `King.get_value()` always returns 0 due to a truthy empty-result tuple

**Severity: Low**
The king's point value is never used in a material exchange because kings are never captured — checkmate ends the game first. The AI's utility function (`Tree.get_utility`) sums piece values to determine which side is ahead in material; the king contributing 0 rather than some in-check penalty has no effect on move selection because check is handled separately through `am_i_gonna_die` and `god_save_the_king` before the utility is ever evaluated.

**File:** `pieces/king.py` — `get_value`

**Symptom:** `find_attacker()` always returns a tuple (e.g. `(-1, -1)` when safe). A non-empty tuple is always truthy, so `if self.find_attacker(board):` is always `True` and `value` is always set to `0`.

**Root cause:** Intended check was `!= (-1, -1)` (attacker found) but the sentinel tuple itself is truthy.

**Locked-in test:** `tests/test_king.py::TestKingGetValue::test_get_value_always_zero_due_to_truthy_tuple`

---

## BUG-09 — `Pawn.sky_fall()` unconditionally re-appends en passant target (**FIXED**)

**Severity: Medium** — **Fixed in `pieces/pawn.py`**

Two failure modes in the original code:

1. **Pin bypass**: `critical_man()` (inside `calc_targets()`) correctly removed `en_passant_loc` from targets when the pawn was pinned. `sky_fall()` then added it back unconditionally, letting a pinned pawn make an illegal en passant capture that exposed the king to the pinning piece.

2. **Check-resolution mismatch**: En passant captures the pawn at `(en_passant_loc.row - direction, en_passant_loc.col)`, not at `en_passant_loc` itself. So `en_passant_loc` is never in `god_save_the_king` (which contains the checking piece's square). The original workaround was to append `en_passant_loc` unconditionally — but this was too broad.

**Root cause:** `Pawn.sky_fall()` appended `en_passant_loc` with no check that (a) it survived pin filtering, or (b) the captured pawn's square resolves the check.

**Fix:** Only allow en passant during check when the move survived `critical_man()` (present in `self.targets` before sky_fall filtering) AND the captured pawn's square (`loc.row - self.direction`, `loc.col`) is in `god_save_the_king`.

**Locked-in test:** `tests/test_pieces.py::TestPawnMoveFiltering::test_skyfall_preserves_en_passant_loc`

---

## BUG-10 — `Tree.get_utility()` uses red channel only for team identity

**Severity: Low**
Same palette analysis as BUG-03 — all eight colours have distinct red values, and BUG-02's `+1` keeps them distinct. No material misattribution is possible with the current colour set. If a new palette colour sharing a red value were added, the AI would silently count enemy pieces as friendly material (or vice versa), causing completely wrong move selection with no error.

**File:** `ai/tree.py` — `Tree.get_utility`

**Symptom:** `piece.team.r == self.team_r.r` is the sole team check inside material evaluation.

**Root cause:** Same single-channel convention as BUG-03, applied in the AI layer.

**Locked-in test:** `tests/test_ai_tree.py::TestTreeUtility::test_utility_uses_only_red_channel_for_team_id`

---

## BUG-11 — `Tree` stores the board reference without deep-copying it

**Severity: Low**
All callers that build tree nodes (`Board.add_nodes`, `GameRunner._add_nodes`) pass `copy.deepcopy(board)` before constructing the `Tree`, so the stored reference is always an isolated snapshot in practice. The bug is a design fragility: the `Tree` class provides no protection against a caller forgetting to copy, and if that happened the AI would evaluate a board that continues to mutate as moves are applied, producing silently wrong utility values.

**File:** `ai/tree.py` — `Tree.__init__`

**Symptom:** `self.board_state = board_state` — no copy. Mutating the original after construction also mutates the node.

**Root cause:** Performance trade-off; deep-copy responsibility delegated to callers.

**Locked-in tests:** `tests/test_ai_tree.py::TestTreeBoardState::test_board_state_is_same_reference`, `test_board_state_is_same_reference`

---

## BUG-12 — `en_passantable` only set when advancing from `starting_row`

**Severity: Low**
In a real game, a pawn can only make its two-square advance from its starting row (it hasn't moved yet, so it must be there). The condition `old_row == self.starting_row` is therefore always satisfied when a double advance occurs in normal play, making this bug unreachable. It would only fire if a piece were teleported or if `starting_row` were set incorrectly, neither of which happens in the current codebase.

**File:** `pieces/pawn.py` — `Pawn.move`

**Symptom:** The en passant eligibility flag is gated on `old_row == self.starting_row` in addition to the two-square distance check.

**Root cause:** Starting-row check used as proxy for "first move"; a `has_moved` flag would be more robust.

**Locked-in test:** `tests/test_pieces.py::TestPawnMove::test_move_no_en_passant_from_non_starting_row`

---

## BUG-13 — Pawn promotion formula uses `(starting_row + 6) % 12`

**Severity: Low**
For the two standard starting rows the formula is correct: row 1 → promotes at row 7; row 6 → promotes at row 0. The `% 12` makes it work symmetrically. It is opaque and would give wrong results for any `starting_row` outside `{1, 6}`, but those values never appear in a standard game.

**File:** `pieces/pawn.py` — `Pawn.move`

**Symptom:** Promotion triggers when `row == (self.starting_row + 6) % 12`.

**Root cause:** Clever but non-obvious encoding of "6 rows forward from starting position."

**Locked-in test:** `tests/test_pieces.py::TestPawnPromotion::test_promotion_dir1_at_row7`

---

## BUG-14 — Pawn promotion mutates the board array in place

**Severity: Low**
All call sites that pass a board into `Pawn.move()` for AI speculation already use `copy.deepcopy`, so the mutation hits the copy rather than the live board. For the live-game path, mutating the live board is actually the intended effect (the pawn is replaced by a Queen on the real board). The bug is that `move()` has a hidden side effect with no return value or signal — a caller who passes a live board for read-only inspection would silently corrupt it.

**File:** `pieces/pawn.py` — `Pawn.move`

**Symptom:** At promotion, `board[row][col] = Queen(...)` is executed directly inside `move()` rather than returned for the caller to apply.

**Root cause:** Promotion written to operate on the live board; no separation of concerns.

**Locked-in test:** `tests/test_pieces.py::TestPawnPromotion::test_promotion_modifies_board_array_directly`

---

## BUG-15 — Default `Team.name` is hardcoded "Wendy"

**Severity: Low**
Purely cosmetic. On the Pi, team names appear only in display strings. In the simulator the name is overwritten during the colour-pick phase (`team.name = _COLOR_NAMES[col]`), so players never see "Wendy" during normal use. Any programmatically constructed `Team` that skips `set_name()` will carry the default, which could produce confusing log output in tests or debug sessions.

**File:** `core/team.py` — `Team.__init__`

**Symptom:** `Team(0, 0, 0).name == "Wendy"` for all newly created teams.

**Root cause:** Hardcoded default value; no logic to derive a name from colour at construction.

**Locked-in test:** `tests/test_primitives.py::TestTeam::test_default_name_is_wendy`

---

## Network Chaos Bugs (Grand Fuzzer)

Discovered by `harness/grand_fuzzer` chaos testing on 2026-04-22. Total: **637 corpus files** across 7 failure categories. These are network resilience bugs — the system fails to handle connection drops, timeouts, and reconnection under adversarial conditions.

| Category | Count | Sample Error |
|---|---|---|
| `chaos_disconnect` | 291 | master disconnected by fault injection |
| `phase_setup` | 177 | slave didn't receive color_r: None |
| `network_timeout` | 83 | slave did not receive move (or dropped by fault) |
| `send_failed_already_disconnected` | 38 | master send failed: already_disconnected |
| `chaos_drop` | 30 | master drop by fault injection |
| `recovery_failed_drop` | 12 | Production failed to recover from drop |
| `chaos_already_disconnected` | 6 | master already_disconnected by fault injection |

**Corpus location:** `harness/crashes/grand_e2e/`

**Suspected files:** `game/networked_board.py`, `network/server.py`, `network/relay_client.py`, `simulator/networked_runner.py`

### BUG-16 — Phase setup fails under network chaos

**Severity: High**

Color pick phase does not reliably complete when network faults occur during handshake. Slave client receives `None` instead of `color_r` value after retry.

**Root cause:** Retry logic in phase setup doesn't handle mid-handshake disconnection gracefully.

### BUG-17 — Send fails on already-disconnected connection

**Severity: Medium**

Code attempts to send messages on connections that have already been disconnected, raising `already_disconnected` errors instead of checking connection state first.

**Root cause:** Missing connection state check before send operations.

### BUG-18 — Recovery fails after network drop

**Severity: High**

After fault injection drops a connection, the reconnection/recovery logic fails to restore game state. 12 corpus files show "Production failed to recover from drop".

**Root cause:** Reconnection logic does not properly replay or resync game state.

---

## Open issues

Design debts not locked in by tests but worth tracking.

| ID | Summary |
|---|---|
| OPEN-01 | Two players can pick the same colour — `_get_team_pieces` would merge both teams |
| OPEN-02 | Vestigial `days_*_since_injury` / `double_*_jeopardy` attrs in `Board.__init__` — dead code |
| OPEN-03 | En passant capture depends on `move()` return value; silent failure if `None` returned unexpectedly |
| OPEN-05 | No draw warning when approaching fifty-move or threefold limits |
| OPEN-07 | State leak between networked game sessions — legal move in a new online game rejected as illegal after completing a previous game. Likely stale board state, piece flags, turn tracking, or sequence numbers carried from the prior session. Suspected: `simulator/networked_runner.py`, `game/networked_board.py`, relay room state. |
| OPEN-08 | Chaos fuzzer corpus not deterministically replayable — seeds control RNG decisions but not network timing/thread scheduling. Same seeds can produce different outcomes. Need mock-based replay or timeline event injection for true determinism. Suspected: `harness/grand_fuzzer/`, `harness/chaos_replay.py`. |
| OPEN-09 | Grand E2E fuzzer bypasses game code — uses custom `NetworkPeer` classes instead of `NetworkedGameRunner`/`NetworkedBoard`. ACK/retry fixes in game code don't get tested. Fix: use headless pygame (`SDL_VIDEODRIVER=dummy`), create actual `NetworkedGameRunner` instances, wrap `GameServer`/`GameClient` with chaos injection, run real game phases. Suspected: `harness/grand_fuzzer/fuzzers/grand_e2e.py`. |
