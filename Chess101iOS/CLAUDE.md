# Chess101iOS

Native iOS app connecting to `wss://relay.chess101.net` for internet games. Scans ChessMatrix room codes via camera, plays in 2D or 3D.

## Three-Platform Sync

The Swift chess engine (`Sources/Chess101Engine/`) must stay in sync with the Python engine (`pieces/`, `game/`) and the JS engine (`web/chess-engine.js`). Any legal-move or board-hash change must be made in all three. Verify with:

```bash
.venv/bin/python harness/fuzz_lockstep_swift.py --iterations 100
```

## Setup

```bash
# Install XcodeGen (once):
brew install xcodegen

# Regenerate Xcode project after editing project.yml:
cd Chess101iOS && xcodegen generate && cd ..
```

`project.yml` is the source of truth for build settings. **Never edit `.xcodeproj` directly.**

## Running Tests

```bash
# Via Bazel (preferred — matches CI):
bazel test //Chess101iOS:Chess101IOSTests

# Via Swift directly:
cd Chess101iOS && swift test && cd ..
```

Test files:
- `Tests/Chess101IOSTests/EngineTests.swift` — Board init, legal moves, check, castling, en passant, promotion, alpha-beta
- `Tests/Chess101IOSTests/RSCodecTests.swift` — Reed-Solomon codec (ChessMatrix ECC)

## SwiftBridge (lockstep fuzzing)

`Sources/SwiftBridge/` is a macOS CLI target that wraps `Chess101Engine` for the Python lockstep fuzzer. It reads JSON move commands from stdin and writes results to stdout — the same stdio protocol as `harness/js_bridge.js`.

```bash
# Build the bridge binary (needed by fuzz_lockstep_swift.py):
cd Chess101iOS && swift build -c release && cd ..

# Run the three-way lockstep fuzzer:
.venv/bin/python harness/fuzz_lockstep_swift.py --iterations 100
```

## Package Structure

```
Chess101iOS/
├── Package.swift                    # Swift package: Chess101Engine + Chess101iOS + SwiftBridge targets
├── project.yml                      # XcodeGen spec (source of truth)
├── BUILD.bazel                      # Bazel sh_test wrapper for swift test
├── run_swift_test.sh                # Invoked by Bazel; finds Package.swift in runfiles
│
├── Sources/
│   ├── Chess101Engine/              # Pure Swift chess logic — NO UIKit
│   │   ├── Board.swift             # Board state, grid, piece placement
│   │   ├── Piece.swift, Pawn.swift, Rook.swift, Bishop.swift, Knight.swift, Queen.swift, King.swift
│   │   ├── Team.swift, Cell.swift, MoveFlags.swift, Rules.swift
│   │   ├── Protocol.swift          # encode_grid, decode_grid, board_hash (matches Python/JS)
│   │   └── AI/AIPlayer.swift       # Alpha-beta minimax
│   │
│   ├── SwiftBridge/
│   │   └── main.swift              # macOS CLI stdio bridge for fuzz_lockstep_swift.py
│   │
│   └── Chess101iOS/                 # SwiftUI app
│       ├── Chess101App.swift        # @main — splash gate → ContentView
│       ├── Game/
│       │   ├── GameSession.swift    # ObservableObject: board state, turn, relay integration
│       │   ├── GamePhase.swift      # Phase enum
│       │   └── MoveAnimation.swift
│       ├── Network/
│       │   ├── RelayClient.swift    # URLSessionWebSocketTask relay client
│       │   └── ChessMatrix/        # ChessMatrix Swift decoder (camera frames)
│       └── UI/
│           ├── ContentView.swift, LobbyView.swift, ColorPickView.swift, WarGamesView.swift
│           ├── BoardView.swift      # 2D board (LED-style squares, tap to move)
│           ├── Board3DView.swift    # SceneKit 3D board (OBJ pieces, arc animations)
│           ├── GameOverView.swift, PanelView.swift
│           ├── ScannerView.swift    # AVFoundation camera for ChessMatrix scanning
│           ├── BoardTheme.swift
│           └── Components/
│
└── Tests/Chess101IOSTests/
    ├── EngineTests.swift
    └── RSCodecTests.swift
```

## Key architecture notes

**`RelayClient`**: `URLSessionWebSocketTask`-based. Uses `waiters: [CheckedContinuation]` for race-free one-shot handshake responses. `connectAndWait()` must complete before any `send()`.

**`Board3DView`**: SceneKit with `CADisplayLink` at 60fps. All squares use `.constant` lighting (pure emitters). Piece OBJ files in `Sources/Chess101iOS/Models/` — regenerate with `tools/stl_to_obj.py` if STL files change.

**`ScannerView`**: `AVCaptureSession` — `startRunning()` must be called on a background thread.

**`Chess101App`**: renders `SplashView` (8×8 tile assembly animation) then cross-fades to `ContentView` at 1.8s.

## Info.plist keys (via project.yml)

| Key | Value |
|---|---|
| `NSCameraUsageDescription` | Camera used to scan ChessMatrix room codes |
| `UILaunchScreen_BackgroundColorName` | `LaunchBackground` (dark navy) |

## Regenerating OBJ models

```bash
.venv/bin/python tools/stl_to_obj.py
# Then: cd Chess101iOS && xcodegen generate && cd ..
```
