# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Chess101 is a physical chess board running on a Raspberry Pi. An 8x8 RGB LED matrix displays the board, eight Arduinos connected via I2C detect piece positions using reed switches (one Arduino per row), and Python implements chess logic with an optional AI opponent.

## Running the Game

The game must be run with `sudo` on the Raspberry Pi (the LED matrix requires root privileges):

```bash
sudo python3 GameManager.py
```

Common LED matrix flags (passed through `samplebase.py`):
```bash
sudo python3 GameManager.py --led-rows=32 --led-cols=32 --led-chain=4
sudo python3 GameManager.py --led-gpio-mapping=adafruit-hat
```

## Architecture

### Entry Point & Game Loop
- **`GameManager.py`** — Entry point. Creates a `Board` instance and calls `board.process()` in an infinite loop.
- **`Board.py`** — Central game controller. Extends `SampleBase` for LED matrix access. Manages the full game lifecycle: color selection, interactive piece setup via `interactiveSetup()`, turn processing via `doTurn()` or `computerMove()`, and mismatch detection between the physical board and software state.

### Hardware Interface
- **`Master.py`** — Communicates with 8 Arduinos over I2C (via `smbus`), one per board row at addresses `0x04`–`0x0b`. `readData()` polls all rows; `getCellState(row, col)` returns 0 (piece present) or 1 (empty). I2C errors are retried automatically.
- **`samplebase.py`** — Base class for all LED matrix programs. Initializes `RGBMatrix` and parses command-line LED configuration flags. All classes that render to the LED matrix inherit from this.
- **`rgbmatrix/`** — Compiled Cython bindings to the C++ `rpi-rgb-led-matrix` library. Must be built for the target Pi (see `python_from_the_pi_sorry_messy/README.md`).

### Chess Logic
- **`Piece.py`** — Abstract base. Each piece has `row`, `col`, `team`, `targets`, `touched`, `critical`, and `criticalTargets`. Key abstract methods: `calcTargets(checkerTown)` and `getValue(board)`. The `Kingsman()` method is a shared ray-casting helper for sliding pieces. `skyFall()` and `criticalMan()` filter valid moves when the king is in check or a piece is pinned.
- **`King.py`** — Most complex piece. `calcTargets()` simulates each candidate move to detect self-check. `amIGonnaDie()` scans all 8 directions and knight positions to detect checks. When in check, `godSaveTheKing` holds the cells that would resolve the check; all other pieces call `skyFall()` to restrict their moves to only those cells.
- **Pawn, Bishop, Rook, Knight, Queen** — Each implements `calcTargets()` and `getValue()`. Pawn handles en passant (`enPassantable` flag) and promotion (auto-promotes to Queen at back rank).
- **`Team.py`** — Identifies a team by its RGB color (used for ownership comparisons throughout piece logic).
- **`Cell.py`** — Simple `(row, col)` struct used for target squares.

### AI
- **`AI.py`** — Alpha-beta minimax. Takes a `Tree` root node and runs `alpha_beta_search()` to find the best move.
- **`Tree.py`** — Game tree node. Holds `boardState` (8x8 grid snapshot), `oldCell`/`newCell` (the move), and `children`. `getUtility()` computes material balance: sums `getValue()` for each piece, returning the difference (positive favors `teamR`).

### Board Coordinate System
The grid is `checkerTown[row][col]`, an 8x8 list of `Piece | None`. Row 0 is `teamR`'s back rank; row 7 is `teamL`'s. Each cell maps to an 8x8 pixel block on the LED matrix.

## Hardware Dependencies (Pi Only)
- `smbus` — I2C communication with Arduinos
- `rgbmatrix` — Compiled Cython library (must be built on the Pi)
- `RPi.GPIO` — GPIO access (used in `PiControl/ReedSwitchTest.py`)
- `numpy`, `PIL` — Used in Board rendering

## Other Files
- **`grid.py`** — Standalone test script for LED matrix grid rendering.
- **`soundtest.py`** — Standalone sound test.
- **`PiControl/ReedSwitchTest.py`** — Standalone test for reed switch GPIO input.
- **`include (trash)/`** — Old versions of Board and Game; not used.
- **`python_from_the_pi_sorry_messy/`** — Original messy copy from the Pi, kept for reference. The active code is in the root directory.
