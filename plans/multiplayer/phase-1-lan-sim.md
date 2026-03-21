# Phase 1 — LAN Sim vs Sim: Implementation Plan

## Goal

Two simulator instances on the same local network play a game of chess. One is the host, one is the guest. Moves are transmitted over WebSocket. Board state is verified by hash after every move.

## Scope

- Sim vs Sim only (no Pi)
- Local network only (no relay)
- Human players only (no remote AI — each side can independently use local AI for their own team)
- Color pick and WAR_GAMES negotiated between both clients
- LAN discovery via UDP beacon (no manual IP entry needed on the same subnet)
- Reconnection within 60 seconds

## Out of Scope (deferred to Phase 2+)

- Physical board support
- Internet play
- Spectator mode (infrastructure exists, but no UI)
- In-game chat
- Move history export
- Move timer / clock

---

## Work Estimate

**Total: ~2–3 weeks solo, ~1 week with two people**

| Task | Effort |
|---|---|
| `network/protocol.py` — message dataclasses + board hash | 0.5 day |
| `network/server.py` — async WebSocket server | 1 day |
| `network/client.py` — async WebSocket client | 0.5 day |
| `network/discovery.py` — UDP beacon | 0.5 day |
| `simulator/app.py` — `_last_move` tracking + `Phase.LOBBY` | 0.5 day |
| `simulator/lobby.py` — Lobby screen render | 1 day |
| `simulator/networked_runner.py` — `NetworkedGameRunner` | 3 days |
| COLOR_PICK negotiation (propagate both choices) | 1 day |
| WAR_GAMES negotiation | 0.5 day |
| Move send/receive/ack loop | 2 days |
| Desync detection + board_sync recovery | 1 day |
| Disconnection handling + reconnect | 1 day |
| Side panel updates (mode, peer, signal strength) | 0.5 day |
| Ping/pong keepalive | 0.25 day |
| `run_simulator.py` CLI flags | 0.25 day |
| Integration testing (two windows on one machine) | 1 day |
| Bug fixes | 1–2 days |

---

## Step-by-Step Implementation

### Step 1: Protocol foundation

Create `network/__init__.py` (empty) and `network/protocol.py`:

- [ ] `MoveFlags` dataclass (all move special-case flags)
- [ ] `encode_grid(grid, team_r_r)` — serialize 8×8 to JSON-safe list
- [ ] `decode_grid(encoded, team_r, team_l)` — deserialize back to Piece objects
- [ ] `board_hash(grid, peace_time, current_team_key)` — SHA-256 consistency check
- [ ] `build_move_msg(seq, fr, fc, tr, tc, piece, flags, hash)` — produce a move dict

Tests:
- Round-trip `encode_grid → decode_grid` produces equal grid
- `board_hash` is deterministic (same board = same hash)
- `board_hash` changes on any piece move

### Step 2: WebSocket transport

Create `network/server.py` and `network/client.py`:

- [ ] `GameServer` — `asyncio` + `websockets.serve`
  - [ ] Accepts exactly one opponent connection
  - [ ] Routes `hello` to role detection
  - [ ] `send(msg: dict)` — queues outbound message
  - [ ] `set_message_handler(callback)` — wire up to game loop
- [ ] `GameClient` — `websockets.connect`
  - [ ] `connect()`, `run()`, `send()`
  - [ ] Same `set_message_handler` interface

Tests (headless, no Pygame):
- Server accepts a client connection
- Client sends a message, server receives it via handler
- Server sends, client receives
- Client disconnect is detected by server

### Step 3: LAN discovery

Create `network/discovery.py`:

- [ ] `BeaconBroadcaster` — UDP broadcast every 2s on 255.255.255.255:65102
- [ ] `BeaconListener` — listens on port 65102, populates `games` dict
- [ ] Stale game cleanup — remove entries not seen in 10s

Tests:
- Broadcaster sends valid JSON beacons
- Listener parses beacons and populates the game list
- Stale entries are removed after timeout

### Step 4: Lobby screen

Add `Phase.LOBBY` to `simulator/app.py` and create `simulator/lobby.py`:

- [ ] 4 options: Play Locally / Host a Game / Join a Game / Watch a Game
- [ ] Click or arrow keys to navigate, Enter/click to confirm
- [ ] `_render_lobby()` — draws 4 colored rows on the board
- [ ] `_handle_lobby(event)` — handles selection
- [ ] Side panel lobby section — shows discovered games list
- [ ] `BeaconListener` runs on a background thread, updates panel list each frame
- [ ] `--local` flag skips Lobby and goes straight to COLOR_PICK

### Step 5: `NetworkedGameRunner` scaffold

Create `simulator/networked_runner.py`:

- [ ] `NetworkRole` enum: HOST, GUEST, SPECTATOR
- [ ] `NetworkedGameRunner(GameRunner)` constructor
  - [ ] Creates `GameServer` or `GameClient` based on role
  - [ ] Creates `BeaconBroadcaster` if host
  - [ ] Starts network thread (asyncio loop in daemon thread)
- [ ] Override `run()` to start network before Pygame loop
- [ ] Override `_update()` to call `_check_remote_move()`
- [ ] `_on_network_message(msg)` dispatches to specific handlers
- [ ] Thread-safe `_pending_remote_move` (protected by `threading.Lock`)

### Step 6: Handshake and COLOR_PICK negotiation

- [ ] `_send_hello()` — sends `hello` on connect
- [ ] `_on_hello(msg)` — validates version, stores peer name
- [ ] Host sends `game_setup` after both hellos exchanged
- [ ] `_handle_color_pick` override:
  - Host: pick color → send `color_chosen` → wait for guest's `color_chosen` → advance
  - Guest: wait for host's color first (grey out that column) → pick own → send → advance
- [ ] `_on_color_chosen(msg)` — applies remote color selection to board

### Step 7: WAR_GAMES negotiation

- [ ] `_handle_war_games` override:
  - Both sides make their own choice independently
  - Each sends `war_games_choice`
  - Once both received, host sends `game_start`
- [ ] `_on_war_games_choice(msg)` — applies remote choice
- [ ] `_on_game_start(msg)` — both sides call `_start_game()` from this handler

### Step 8: Move send/receive loop

The most critical part.

**Sending a local move:**
- [ ] In `_handle_playing`, after the player's move is applied, set `self._last_move = (fr, fc, tr, tc, flags)`
- [ ] In `_next_turn` override, if `_last_move` is set:
  - Compute `board_hash` of the resulting position
  - Build and send `move` message
  - Wait for `move_ack` before considering the turn complete (or proceed optimistically)
- [ ] Build `MoveFlags` from the move:
  - Check if capture (grid[tr][tc] was not None before move)
  - Check if en passant (pawn diagonal move, destination was empty)
  - Check if castling (king moved 2 squares)
  - Check if promotion (pawn reached back rank)

**Receiving a remote move:**
- [ ] `_check_remote_move()` — called each frame in `_update()` during opponent's turn
- [ ] Validate that it's the opponent's turn before applying
- [ ] Apply the move: `grid[tr][tc] = grid[fr][fc]`, `grid[fr][fc] = None`
- [ ] Call `_apply_move(fr, fc, tr, tc)` — handles special piece logic
- [ ] Handle special flags:
  - `is_en_passant`: remove `grid[captured_at[0]][captured_at[1]]`
  - `is_castling`: move rook using `rook_from`/`rook_to`
  - `is_promotion`: grid cell is now a Queen (piece already promoted on sender's side; `decode` restores Queen)
- [ ] Compute local board hash, compare to `msg["board_hash"]`
- [ ] Send `move_ack` with `status: "ok"` or `"desync"`
- [ ] On `"ok"`: call `_next_turn()`
- [ ] On `"desync"`: send `board_sync_request`, wait for `board_sync`

### Step 9: Desync recovery

- [ ] `_on_board_sync_request(msg)` — send full board state via `board_sync`
- [ ] `_on_board_sync(msg)` — call `_apply_board_sync()`:
  - Decode grid from message
  - Replace `board.grid` in place (clear and repopulate)
  - Set `peace_time`, `_current_team`
  - Call `_begin_turn()` to recalculate legal moves
- [ ] After recovery, log: `"Board sync applied after desync at seq {n}"`

### Step 10: Disconnection handling

- [ ] WebSocket close → set `_peer_disconnected = True`
- [ ] In `_render()`, if `_peer_disconnected`: render dim overlay on board
- [ ] Side panel: countdown timer (60s), then "Resign / Return to Lobby" options
- [ ] On reconnect within timeout: client sends `hello` again, server sends `game_setup` with current state, `board_sync` with full position, game resumes
- [ ] Keepalive: `ping` sent every 10s, if no `pong` in 30s → treat as disconnect

### Step 11: CLI wiring

Update `run_simulator.py`:

```python
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--local",    action="store_true")
parser.add_argument("--host",     action="store_true")
parser.add_argument("--join",     metavar="IP")
parser.add_argument("--spectate", metavar="IP")
parser.add_argument("--port",     type=int, default=65101)
args = parser.parse_args()

if args.local:
    GameRunner().run()
elif args.host:
    NetworkedGameRunner(role=NetworkRole.HOST, port=args.port).run()
elif args.join:
    NetworkedGameRunner(role=NetworkRole.GUEST, host_ip=args.join, port=args.port).run()
elif args.spectate:
    NetworkedGameRunner(role=NetworkRole.SPECTATOR, host_ip=args.spectate, port=args.port).run()
else:
    NetworkedGameRunner(role=None).run()  # shows Lobby
```

---

## Testing Plan

### Unit tests (`tests/test_network.py`)

- [ ] Protocol: `encode_grid` / `decode_grid` round-trip for all 6 piece types
- [ ] Protocol: `board_hash` determinism
- [ ] Protocol: `board_hash` changes after each move type (capture, castle, promotion)
- [ ] Discovery: beacon parse
- [ ] Server: connects and receives hello
- [ ] Client: connects and sends hello
- [ ] Move serialization: standard move, capture, en passant, castling, promotion

### Integration tests (`tests/test_multiplayer.py`)

- [ ] Full game: two `NetworkedGameRunner` instances, headless Pygame, 5-move game
- [ ] Desync simulation: corrupt hash, verify `board_sync` recovery
- [ ] Disconnect + reconnect within timeout
- [ ] COLOR_PICK: host picks color, guest receives it, guest picks color, both advance
- [ ] GAME_OVER: checkmate is detected, `game_event` sent, both sides show correct winner

### Manual test checklist

- [ ] Two terminal windows on the same Mac: one `--host`, one `--join 127.0.0.1`
- [ ] Two Macs on the same WiFi: discover via beacon, join, play to checkmate
- [ ] Disconnect mid-game (kill the host), reconnect within 60s, game resumes
- [ ] Both sides pick same color (should be blocked)
- [ ] AI vs AI: both sides select AI in WAR_GAMES — game plays to completion automatically

---

## Dependencies to Add

```
websockets>=12.0
```

Add to `requirements.txt` (not just dev). Both Pi and Mac will need it.

---

## Notes

- The asyncio event loop runs in a dedicated daemon thread. The Pygame loop stays on the main thread. Messages cross via `asyncio.run_coroutine_threadsafe` (outbound) and `threading.Lock`-protected queues (inbound). This avoids any Pygame/asyncio interaction issues.
- The `board_hash` function must produce identical output on both machines. Python's `copy.deepcopy` and `dict` ordering are both deterministic within a session, but the canonical string format must be explicitly defined (see `protocol.md`) to guarantee cross-machine agreement.
- Promotion always produces a Queen in Phase 1. When a `board_sync` is received containing a Queen where a Pawn was, it is reconstructed correctly because the grid is decoded from type names, not piece objects.
