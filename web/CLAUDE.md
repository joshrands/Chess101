# Web / JavaScript

Browser-based simulator and spectator UI, plus the JS chess engine that must stay in sync with the Python and Swift engines.

## Three-Platform Sync

`web/chess-engine.js` is one of three chess engines that must stay in sync. See the root `CLAUDE.md` "Three-Platform Rule" section. Verify parity with:

```bash
bazel run //harness:fuzz_chess -- --iterations 100
bazel run //harness:fuzz_networked -- --iterations 100
node tests/test_chessmatrix_js.js
node tests/test_sim_js.js
```

## Running JS tests

```bash
# Via Bazel:
bazel test //tests:test_chessmatrix_js
bazel test //tests:test_sim_js

# Directly (no npm install needed):
node tests/test_chessmatrix_js.js
node tests/test_chessmatrix_js.js --verbose
node tests/test_sim_js.js
node tests/test_sim_js.js --verbose
```

When a lockstep fuzzer finds a disagreement, **assume the bug is in the JS** — the Python engine is canonical and the JS is more recently touched.

## Files

```
web/
├── chess-engine.js         # JS chess engine — must stay in sync with Python + Swift
├── spectator-engine.js     # JS spectator move logic
├── chessmatrix-scanner.js  # ChessMatrix decoder (browser + Node.js, no dependencies)
├── sim.html                # Browser simulator — connects to relay, plays chess
├── spectator.html          # Spectator view
├── hil_visualizer.html     # Visual display for the HIL container (ws://localhost:8766)
├── index.html              # Landing page
└── pieces/                 # SVG/PNG piece assets
```

## HIL visualizer

`web/hil_visualizer.html` connects to the HIL control server at `ws://localhost:8766` and renders the 32×32 LED frame live. Open it in a browser while running `python -m hil.run_hil` or the Docker HIL container.

## ChessMatrix scanner

`web/chessmatrix-scanner.js` is the JS decoder for the ChessMatrix barcode. It runs in both browser and Node.js (no dependencies). The decoding pipeline must match `network/chessmatrix.py` exactly — use the lockstep tests to verify:

```bash
bazel test //tests:test_lockstep_chessmatrix
```

Debug tool: open `tools/pipeline_debug.html` in a browser for an interactive step-by-step view of the JS decoding pipeline.
