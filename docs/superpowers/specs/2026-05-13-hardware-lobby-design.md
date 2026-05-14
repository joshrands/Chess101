# Hardware Board Lobby Design

Date: 2026-05-13

## Overview

A reed-switch-driven lobby menu for the physical Chess101 board. Two-level binary decision tree: **Local vs Network**, then (if Network) **Host vs Join**. All communication is through LED animations — no text, no prior knowledge required.

## Constraints

- **8×8 effective display**: 32×32 LED matrix, but each cell is 4×4 LEDs viewed as one color. Visual design targets 8×8 resolution.
- **Home-row avoidance**: Rows 0-1 and 6-7 may have pieces left from a previous game. These rows are display-only (ambient visuals) — never interactive, never blinking.
- **Interactive area**: Rows 2-5 (4 rows × 8 cols). All menu inputs happen here via reed switches.
- **Flashing convention**: A blinking cell means "interact here" — place or remove a piece.
- **Development target**: HIL container (docker mode) first, hardware second.

## Decision Tree

```
Level 1: Local vs Network
  ├── Local (amber side)  → color_picker (2-player) → war_games (2-player) → play
  └── Network (rain side) → Level 2: Host vs Join
        ├── Host (2,0) → start relay + LAN beacons → show ChessMatrix → wait → color_picker (1-player) → war_games (1-player) → play
        └── Join (5,0) → scan LAN beacons + ChessMatrix entry → connect → color_picker (1-player) → war_games (1-player) → play
```

## Level 1 — Local vs Network

### Idle State

The board is split down the center:

- **Left half (cols 0-3)**: Amber checkertown. Static warm color on checker squares, dark on non-checker squares. Represents physical, in-person play.
- **Right half (cols 4-7)**: Green checkertown base with matrix rain. Bright green cells cascade downward column by column at staggered offsets, each cell changing as a whole (bright head → medium trail → fade to base). Represents network/digital play.
- **Home rows (0-1, 6-7)**: Show ambient versions of both patterns under existing pieces. Non-interactive.

### Interaction

Place a piece **anywhere** on rows 2-5 on either half. No specific blinking targets — the visual split is the entire communication.

- Cols 0-3 → Local
- Cols 4-7 → Network

### Confirmation — Spread Takeover

When a piece is placed, a 3-second countdown begins. The chosen side's pattern spreads column by column from the center divide toward the opposite edge:

- **Network chosen**: Rain/green spreads leftward — col 3, then 2, then 1, then 0. Each column cross-fades from amber to green and picks up the rain animation.
- **Local chosen**: Amber spreads rightward — col 4, then 5, then 6, then 7. Each column cross-fades from green to amber. Rain fades out per column.

**Cancellation**: Pick up the piece at any point during the 3 seconds → snap back to split view.

### Post-Confirmation

- **Local**: Piece blinks until removed. Board is in forward-transition state (removal = proceed, not restart). → Proceed to `color_picker` (2-player mode).
- **Network**: Piece **stays on the board**. It becomes the visual representation of the remote opponent in Level 2. Rain stops; board settles to static green checkertown. → Proceed to Level 2.

## Level 2 — Host vs Join

### Prerequisite

The rain piece from Level 1 remains on the board at whatever position the user chose (rows 2-5, cols 4-7). It now glows green — the "opponent."

### Idle State

- **Base**: Static green checkertown (full board, no rain).
- **Opponent piece**: The cell at the Level 1 piece position is lit steady bright green (the cell itself, not an overlay). The physical piece is still there on the reed switch.
- **Choice cells**: (2,0) and (5,0) — the two corners of the left edge of the interactable area. Blink white in opposite phase (alternating).
- **Signals**: White signals alternate between the two choices. Each signal travels on a **monotonic random path** — every step moves closer to the target in either row or column (randomly chosen), so all paths have exactly `|Δrow| + |Δcol|` steps. Signal speed: ~100ms per cell, 3-cell trail.
  - Host signal: opponent → (2,0). "They come to you."
  - Join signal: (5,0) → opponent. "You go to them."
  - Signals alternate — one host, one join, repeat. Each on a fresh random path.
- **Signal path rule**: Always includes the opponent/rain piece cell. Always excludes the choice cell.

### Interaction

Place a piece on (2,0) for Host or (5,0) for Join.

### Post-Choice

- Only the chosen direction's signals repeat (each on a new random path).
- Subtle white concentric rings appear (post-choice only, not in idle):
  - **Host**: Single ring contracting inward toward (2,0), with distance falloff. Low intensity (~0.25).
  - **Join**: Single ring expanding outward from (5,0), with distance falloff. Low intensity (~0.25).
- **Cancellation**: Pick up the Host/Join piece → back to Level 2 idle.

### Confirmation

Same countdown mechanic (3 seconds). Since the board is already uniform green, the confirmation uses a fade rather than a spread — the board slowly dims over 3 seconds. Exact fade curve to be tuned in HIL.

After confirmation: **both pieces blink** (the rain/opponent piece and the Host/Join piece). User removes both. Board is in forward-transition state — removal means proceed.

## Navigation

Back navigation is implicit through piece removal:

| State | Action | Result |
|-------|--------|--------|
| L1 countdown | Pick up piece | Cancel → L1 idle |
| L2 idle | Pick up rain piece | Back → L1 idle |
| L2 countdown | Pick up Host/Join piece | Cancel → L2 idle |
| Blink-and-remove transition | Remove pieces | Proceed to next phase (NOT restart) |

The state machine distinguishes "waiting for a choice" (where empty board = idle) from "transitioning forward" (where empty board = proceed).

## Post-Lobby Flows

### Local

→ `color_picker` (2-player, rows 2 and 5) → `war_games` (2-player, rows 3 and 4) → `interactive_setup` → play.

No changes to existing flow except the lobby precedes it.

### Host

1. Establish relay connection → get room code.
2. Start LAN beacon broadcasting.
3. Display ChessMatrix barcode encoding the room code.
4. Wait for opponent to connect (via relay or LAN).
5. → `color_picker` (1-player, single row) → `war_games` (1-player, single row) → play.

### Join

1. Start scanning for LAN beacons.
2. Show ChessMatrix entry UX (CODE_SCAN_BOARD).
3. If LAN host discovered → **auto-connect** (skip ChessMatrix entry).
4. If user enters ChessMatrix code → connect via relay.
5. If connected game is already in progress → spectate.
6. → `color_picker` (1-player, single row) → `war_games` (1-player, single row) → play.

### Unified Networking

Host broadcasts LAN beacons **and** connects to relay simultaneously. The transport (LAN vs relay) is an implementation detail — the user never chooses between them. Join scans for LAN beacons **and** accepts ChessMatrix codes — whichever connects first wins.

## Implementation Changes

### New Code

- `Board.lobby()` method: Implements the two-level decision tree. Returns `"local"`, `"host"`, or `"join"`.
- Lobby animation helpers: rain renderer, spread takeover, signal path generator, monotonic random path builder.

### Modified Code

- `Board.run()`: Call `self.lobby()` before `color_picker()`. Use return value to determine networking mode and menu variants.
- `Board.color_picker()`: Add `single_player` parameter. When True, show only one row. Which row depends on team assignment: row 2 if local player is team_r (Host), row 5 if team_l (Join).
- `Board.war_games()`: Add `single_player` parameter. When True, show only one row. Row 3 for team_r, row 4 for team_l.
- `GameManager.py`: Lobby replaces `--host`/`--join`/`--host-online`/`--join-online` flags for the Pi path. CLI flags remain available for testing and for the simulator.
- Networking wiring: After lobby returns `"host"` or `"join"`, `Board.run()` instantiates the appropriate `RelayClient`/`GameServer`/`GameClient` and wires up `NetworkedBoard` behavior.

### Three-Platform Rule

The lobby is Pi/HIL only for now. The simulator keeps its existing keyboard/mouse lobby. JS and Swift engines will need equivalent lobby logic when those platforms gain lobby support — but that's out of scope for this iteration.

## Out of Scope

- Shutdown/reboot secret combo — needs a new home, separate design.
- Simulator lobby replacement.
- iOS/web lobby parity.
- Spectator auto-detection details (networking layer, not lobby UX).
