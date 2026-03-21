# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Chess101 is a physical chess board running on a Raspberry Pi. An 8×8 RGB LED matrix displays the board, eight Arduinos connected via I2C detect piece positions using reed switches (one Arduino per row), and Python implements chess logic with an optional alpha-beta AI opponent.

A Mac simulator (`run_simulator.py`) lets you develop and test without any Pi hardware by substituting a Pygame window for the LED matrix and click events for reed-switch reads.

## Setup (Mac / development)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # pygame, numpy
.venv/bin/python run_simulator.py           # launch the simulator
```

## Running the Game

**Simulator (Mac):**
```bash
.venv/bin/python run_simulator.py
```

**Raspberry Pi (requires sudo for LED matrix access):**
```bash
sudo python3 GameManager.py
sudo python3 GameManager.py --led-rows=32 --led-cols=32 --led-chain=4
sudo python3 GameManager.py --led-gpio-mapping=adafruit-hat
```

## Running Tests

```bash
.venv/bin/python -m pytest tests/ -q          # all tests
.venv/bin/python -m pytest tests/ -v          # verbose
.venv/bin/python -m pytest tests/test_gameplay.py -v   # chess logic only
.venv/bin/python -m pytest tests/test_simulator.py -v  # simulator only
.venv/bin/python -m pytest tests/test_board.py -v      # Board-level tests
```

`conftest.py` stubs out `rgbmatrix` and `smbus` so all test files run on Mac without Pi hardware.

## Package Structure

```
Chess101/
├── GameManager.py          # Pi entry point — game loop over Board instances
├── run_simulator.py        # Mac entry point — injects fakes, launches GameRunner
├── samplebase.py           # Base class: parses LED flags, creates RGBMatrix
│
├── game/
│   ├── board.py            # Central controller: color-pick, setup, turns, rendering
│   └── rules.py            # Fifty-move rule, threefold repetition (duck-typed onto Board)
│
├── pieces/
│   ├── piece.py            # Abstract base: targets, pin/check filtering (sky_fall, critical_man)
│   ├── pawn.py             # En passant, promotion (auto-Queen), direction quirk (see BUG-01)
│   ├── rook.py             # Ray-casting; castling side effect inside King
│   ├── bishop.py
│   ├── knight.py
│   ├── queen.py
│   └── king.py             # Check detection (am_i_gonna_die), castling, god_save_the_king
│
├── core/
│   ├── cell.py             # (row, col) coordinate struct
│   ├── team.py             # RGB colour identity; comparison is .r-only (see BUG-03)
│   └── constants.py        # PieceValue, CellOccupancy enums
│
├── ai/
│   ├── ai.py               # Alpha-beta minimax (alpha_beta_search, max_value, min_value)
│   └── tree.py             # Game-tree node: board snapshot, move, children, get_utility
│
├── hardware/
│   ├── master.py           # I2C polling of 8 Arduinos (addresses 0x04–0x0b)
│   ├── sensor.py           # BoardSensor ABC: get_cell_state, read_data
│   └── led_matrix.py       # LEDDisplay ABC: set_pixel, clear, swap
│
├── ui/
│   └── renderer.py         # light_cell() — paints one 8×8 LED block per board cell
│
├── simulator/
│   ├── app.py              # GameRunner: Pygame event loop, phase state machine
│   ├── fake_rgbmatrix.py   # FakeFrameCanvas / FakeRGBMatrix backed by pygame.Surface
│   └── sensor.py           # SimSensor(BoardSensor) — click-driven, no I2C
│
└── tests/
    ├── conftest.py          # Stubs rgbmatrix and smbus for all non-Pi tests
    ├── test_gameplay.py     # Pure chess logic + GameRunner integration (headless)
    ├── test_simulator.py    # Simulator-specific bug regression tests
    └── test_board.py        # Board-level tests (runs on Mac via conftest stubs)
```

## Architecture

### Entry Points

- **`GameManager.py`** — Pi entry point. Loops `Board().process()` indefinitely. Catches SIGINT/SIGTERM for graceful shutdown after the current game.
- **`run_simulator.py`** — Mac entry point. Injects `FakeRGBMatrix` and a stub `smbus` into `sys.modules` before importing game code, then calls `GameRunner().run()`.

### Game Controller (`game/board.py`)

`Board(SampleBase)` owns the full Pi game lifecycle:

1. `color_picker()` — players choose team colours from an 8-option palette
2. `war_games()` — players choose Human or AI for each team
3. `create_players()` — assigns team display names
4. `interactive_setup(team)` — waits for all 16 pieces to be physically placed
5. `do_turn(team)` / `computer_move(team)` — human turn (lift/land detection) or AI turn
6. `declare_victory()` / `declare_stalemate()` — end-game LED animations

### Mac Simulator (`simulator/app.py`)

`GameRunner` reimplements the same logical flow without blocking calls. It runs a 60-fps Pygame loop through four phases:

```
COLOR_PICK → WAR_GAMES → PLAYING → GAME_OVER
                                        ↑
                              N key resets to COLOR_PICK
```

Each phase has a `_handle_*` method (click/key events) and a `_render_*` method (draws to the LED canvas). `_render()` calls `blit_to_screen()` then `_render_panel()` then a single `pygame.display.flip()`.

**Side panel** (`_render_panel`): shows current phase, active team with colour swatch, move count, peace-time bar, check/AI alerts, and a scrolling log feed capturing all Python `logging` records via `_PanelLogHandler`.

**AI threading**: `_execute_ai_move` launches the alpha-beta search in a `daemon` thread. The Pygame loop stays responsive. Mouse input is blocked during AI thinking. `_add_nodes` updates `_ai_display_board` under a lock so the board animates through candidate positions while the AI thinks.

### Hardware Interface

- **`hardware/master.py`** (`Master`) — polls all 8 Arduinos each turn; `get_cell_state(row, col)` returns `CellOccupancy.PIECE` (0) or `CellOccupancy.EMPTY` (1).
- **`samplebase.py`** (`SampleBase`) — parses CLI LED flags and constructs `RGBMatrix`. All rendering classes inherit from it on the Pi.
- **`rgbmatrix/`** — compiled Cython bindings for `rpi-rgb-led-matrix`. Must be built on the target Pi.

### Chess Logic

- **`pieces/piece.py`** — Abstract base. `calc_targets(board)` populates `self.targets`. `sky_fall()` restricts moves when the king is in check; `critical_man()` restricts moves when the piece is pinned.
- **`pieces/king.py`** — `am_i_gonna_die()` scans all 8 directions + knight offsets for attackers. `god_save_the_king` holds the set of cells that would resolve a check.
- **`pieces/pawn.py`** — Direction determined by constructor row (`row == 6` → `-1`, else `+1`), not by team — see **BUG-01**.
- **`ai/ai.py`** — `alpha_beta_search()` picks the best child of the root node. `max_value` / `min_value` implement standard alpha-beta pruning.
- **`ai/tree.py`** — `get_utility()` returns material balance (positive = favours `team_r`).

### Board Coordinate System

`board.grid[row][col]` — 8×8 list of `Piece | None`. Row 0 is `team_r`'s back rank; row 7 is `team_l`'s. Each cell maps to a 4×4 pixel block on the 32×32 LED matrix, rendered as a 120×120 px square in the simulator (`SCALE = 30`).

Mouse click → board cell:
```
col = px // (4 * 30)   # 120 px per cell
row = py // (4 * 30)
```

## Known Bugs

See `bug_report.md` for the full list. Key items:

| ID | Severity | Summary |
|---|---|---|
| BUG-01 | Medium | Pawn direction set by row number, not team |
| BUG-02 | Low | `team_r.r += 1` after colour selection — consistent, no mismatch |
| BUG-03 | Low | Team identity by red channel only — palette reds are all unique |
| BUG-04 | High | Fifty-move rule fires at 50 half-moves instead of 100 |
| BUG-05 | Low | Threefold repetition compares piece type, not team — false match impossible in legal play |
| BUG-06 | Low | `determine_direction` returns `0.0` float — `==` comparison still works |
| BUG-07 | High | Double check only tracks first attacker; second allows illegal blocking moves |
| BUG-08 | Low | `King.get_value()` always 0 — kings are never traded so value is irrelevant |
| BUG-09 | Medium | `filter_to_king_escape` re-appends en passant target even when it doesn't resolve check |
| BUG-10 | Low | `Tree.get_utility()` uses red channel only — same palette safety as BUG-03 |
| BUG-11 | Low | `Tree` stores board reference without deep copy — callers always copy first |
| BUG-12 | Low | `en_passantable` only set from `starting_row` — unreachable in legal play |
| BUG-13 | Low | Promotion formula `(starting_row + 6) % 12` — opaque but correct for rows 1 and 6 |
| BUG-14 | Low | Promotion mutates board in place — callers deep-copy for AI evaluation |
| BUG-15 | Low | Default `Team.name` is "Wendy" — cosmetic, overwritten at colour-pick time |

## Hardware Dependencies (Pi Only)

- `smbus` — I2C communication with Arduinos
- `rgbmatrix` — Compiled Cython library (build on the Pi)
- `RPi.GPIO` — GPIO access

## Other Files

- **`grid.py`** — Standalone LED matrix grid render test
- **`soundtest.py`** — Standalone sound test
- **`PiControl/ReedSwitchTest.py`** — Standalone reed-switch GPIO test
- **`include (trash)/`** — Old versions of Board; not used
- **`python_from_the_pi_sorry_messy/`** — Original Pi copy kept for reference
