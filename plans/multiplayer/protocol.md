# Chess101 Multiplayer — Wire Protocol

## Transport

**WebSocket** over TCP, port `65101` (default, configurable).

All messages are UTF-8 JSON objects, one per WebSocket frame. Every message has a `type` field and a `seq` (sequence number, monotonically increasing per sender).

```json
{ "type": "<message_type>", "seq": 42, ... }
```

---

## Connection Lifecycle

```
Guest                           Host
  |                               |
  |------- WebSocket connect ---->|
  |<------ hello (host) ----------|
  |------- hello (guest) -------->|
  |<------ game_setup ------------|   (host sends current setup state)
  |------- setup_ack ------------>|
  |                               |
  |       [COLOR_PICK phase]      |
  |<------ color_chosen ----------|   (host picks team_r color)
  |------- color_chosen --------->|   (guest picks team_l color)
  |<------ war_games_choice ------|   (host: human or AI)
  |------- war_games_choice ----->|   (guest: human or AI)
  |<------ game_start ------------|   (host signals both sides ready)
  |                               |
  |       [PLAYING phase]         |
  |------- move ----------------->|   (guest makes a move)
  |<------ move_ack --------------|   (host confirms + board hash)
  |<------ move ------------------|   (host makes a move)
  |------- move_ack ------------->|   (guest confirms + board hash)
  |                               |
  |       [GAME_OVER]             |
  |<------ game_over -------------|
  |------- game_over_ack -------->|
  |<------ new_game_offer --------|   (optional: host offers rematch)
  |------- new_game_response ---->|
```

---

## Message Types

### `hello`
Sent immediately after connection by both sides.

```json
{
  "type": "hello",
  "seq": 0,
  "version": "1",
  "client_type": "sim" | "pi",
  "player_name": "Seth"
}
```

**Fields:**
- `version` — protocol version string; both sides must match or connection is rejected
- `client_type` — `"sim"` for the Mac simulator, `"pi"` for a physical board
- `player_name` — display name shown in the panel (future: configurable)

---

### `game_setup`
Host → Guest. Sent after both `hello` messages are exchanged. Communicates the current setup state so the guest can render the same lobby view.

```json
{
  "type": "game_setup",
  "seq": 1,
  "host_is": "team_r",
  "guest_is": "team_l",
  "team_r_color_idx": null,
  "team_l_color_idx": null,
  "team_r_is_ai": null,
  "team_l_is_ai": null
}
```

- `host_is` — which team the host controls; always `"team_r"` in Phase 1
- `*_color_idx` — index into `Board.team_array` (0–7), null until chosen
- `*_is_ai` — null until chosen in WAR_GAMES

---

### `color_chosen`
Either side → other. Sent when a player picks their color.

```json
{
  "type": "color_chosen",
  "seq": 2,
  "team": "team_r" | "team_l",
  "color_idx": 3
}
```

---

### `war_games_choice`
Either side → other. Sent when a player decides human or AI.

```json
{
  "type": "war_games_choice",
  "seq": 3,
  "team": "team_r" | "team_l",
  "is_ai": false
}
```

---

### `game_start`
Host → Guest. Signals that both sides have completed setup and the game should begin. Both sides call `initialize_game_board()` locally.

```json
{
  "type": "game_start",
  "seq": 4,
  "team_r": { "r": 65, "g": 180, "b": 232, "name": "Blue" },
  "team_l": { "r": 255, "g": 140, "b": 0,   "name": "Orange" },
  "first_to_move": "team_r"
}
```

---

### `move`
Mover → opponent. Describes a completed move.

```json
{
  "type": "move",
  "seq": 10,
  "from_row": 1,
  "from_col": 4,
  "to_row": 3,
  "to_col": 4,
  "piece": "Pawn",
  "flags": {
    "is_capture": false,
    "captured_piece": null,
    "captured_at": null,
    "is_en_passant": false,
    "is_castling": false,
    "rook_from": null,
    "rook_to": null,
    "is_promotion": false,
    "promotion_to": null
  },
  "board_hash": "a3f8c..."
}
```

**Fields:**
- `from_row`, `from_col`, `to_row`, `to_col` — source and destination squares
- `piece` — piece type name (for display and validation)
- `flags.is_capture` — true if a piece was removed
- `flags.captured_piece` — type name of captured piece (for material tracking)
- `flags.captured_at` — `[row, col]` of the captured piece (differs from `to` for en passant)
- `flags.is_en_passant` — true if the capture was en passant
- `flags.is_castling` — true if King moved 2 squares
- `flags.rook_from` / `rook_to` — `[row, col]` of the rook's start and end (castling only)
- `flags.is_promotion` — true if a pawn reached the back rank
- `flags.promotion_to` — always `"Queen"` for now (underpromotion is Phase 3+)
- `board_hash` — SHA-256 of the canonical board state string after this move (see hashing section)

---

### `move_ack`
Receiver → mover. Confirms the move was received, validated, and applied.

```json
{
  "type": "move_ack",
  "seq": 11,
  "ack_seq": 10,
  "board_hash": "a3f8c...",
  "status": "ok" | "desync"
}
```

- `status: "desync"` triggers a `board_sync_request` from the receiver

---

### `board_sync_request`
Either side → other. Requests a full board snapshot. Triggered when hashes don't match.

```json
{
  "type": "board_sync_request",
  "seq": 12,
  "after_seq": 10
}
```

---

### `board_sync`
Either side → other. Full board state snapshot.

```json
{
  "type": "board_sync",
  "seq": 13,
  "after_seq": 10,
  "peace_time": 4,
  "current_team": "team_r",
  "grid": [
    [
      { "piece": "Rook",   "team": "r", "touched": false } | null,
      { "piece": "Knight", "team": "r", "touched": false } | null,
      ...
    ],
    ...
  ]
}
```

**Grid encoding:** 8 rows × 8 columns. Each cell is either `null` (empty) or an object with:
- `piece` — type name: `"Pawn"`, `"Rook"`, `"Knight"`, `"Bishop"`, `"Queen"`, `"King"`
- `team` — `"r"` or `"l"` (shorthand for team_r / team_l)
- `touched` — bool, whether the piece has moved (used for castling eligibility)
- `en_passantable` — bool, Pawn only (true for exactly one turn after 2-square advance)

---

### `game_event`
Host → Guest (and optionally Guest → Host). Broadcasts a significant game event.

```json
{
  "type": "game_event",
  "seq": 20,
  "event": "check" | "checkmate" | "stalemate" | "fifty_move_draw" | "threefold_draw",
  "team": "team_r" | "team_l" | null,
  "winner": "team_r" | "team_l" | null
}
```

- `team` — the team the event applies to (e.g. the team in check; the team that lost)
- `winner` — non-null on `checkmate`

---

### `game_over_ack`
Guest → Host. Acknowledges the game_over event.

```json
{
  "type": "game_over_ack",
  "seq": 21,
  "ack_seq": 20
}
```

---

### `new_game_offer`
Either side → other. Proposes a rematch.

```json
{
  "type": "new_game_offer",
  "seq": 22,
  "swap_sides": false
}
```

---

### `new_game_response`
Either side → other.

```json
{
  "type": "new_game_response",
  "seq": 23,
  "accepted": true
}
```

---

### `ping` / `pong`
Keepalive. Either side may send `ping` at any time; the other replies with `pong` using the same `seq`.

```json
{ "type": "ping", "seq": 99 }
{ "type": "pong", "seq": 99 }
```

---

### `error`
Either side. Sent when a protocol violation or unrecoverable error occurs. Connection should be closed after sending.

```json
{
  "type": "error",
  "seq": 50,
  "code": "version_mismatch" | "illegal_move" | "wrong_turn" | "unknown_message",
  "detail": "human-readable explanation"
}
```

---

## Board Hashing

After each move both sides compute and exchange a hash of the board state for consistency checking.

**Canonical board string format:**
```
<row0_col0_piece_team>,<row0_col1_piece_team>,...,<row7_col7_piece_team>|<peace_time>|<current_team>
```

Where each cell is either `"."` (empty) or `"<TypeInitial><team>"` e.g. `"Pr"` (Pawn, team_r), `"Kl"` (King, team_l), `"Ql"` (Queen, team_l).

Type initials: P=Pawn, R=Rook, N=Knight, B=Bishop, Q=Queen, K=King.

SHA-256 of this string (hex, lowercase). Both sides must produce the same hash after independently applying the same move.

---

## LAN Discovery (Phase 1)

Before a WebSocket connection is established, the host broadcasts its presence over UDP so guests on the same subnet can find it without typing an IP address.

**Broadcast address:** 255.255.255.255, **port** 65102

**Beacon message** (JSON, sent every 2 seconds):
```json
{
  "type": "chess101_beacon",
  "host_name": "Seth's Mac",
  "host_ip": "192.168.1.42",
  "ws_port": 65101,
  "game_state": "lobby" | "playing",
  "spectators_allowed": true
}
```

Guests listen on port 65102 and populate the "Join Game" list. Clicking a discovered game attempts a WebSocket connection to `ws://<host_ip>:<ws_port>`.

---

## Phase 3 Extension — Relay Protocol

A relay server acts as a message broker. Clients connect to `wss://relay.chess101.example.com/` and are assigned to a room.

Additional message types for relay:

### `relay_create`
Client → Relay. Create a new room.
```json
{ "type": "relay_create", "seq": 0, "player_name": "Seth" }
```
Relay responds with:
```json
{ "type": "relay_created", "seq": 0, "room_code": "XKCD42", "token": "<reconnect_token>" }
```

### `relay_join`
Client → Relay. Join an existing room.
```json
{ "type": "relay_join", "seq": 0, "room_code": "XKCD42", "player_name": "Alex" }
```

### `relay_spectate`
Client → Relay. Join as read-only observer.
```json
{ "type": "relay_spectate", "seq": 0, "room_code": "XKCD42" }
```

After joining, all subsequent messages use the same formats as Phase 1 — the relay is transparent. The relay simply forwards messages between the two players (and broadcasts to spectators).

**Reconnection:** On disconnect, a client reconnects using its `token`. The relay holds the last 50 messages per room so the reconnecting client can replay missed state.
