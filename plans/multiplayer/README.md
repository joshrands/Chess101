# Chess101 Multiplayer — Master Plan

## Vision

Allow any combination of Chess101 clients to play each other: two simulator windows, a simulator against a physical board, or two physical boards. Start on a local network, extend to the internet. Also support a read-only spectator mode where a simulator watches a physical game in progress.

---

## Modes to Support

| Mode | Description | Phase |
|---|---|---|
| Sim vs Sim (LAN) | Two simulator windows, same or different machines | 1 |
| Sim vs Pi (LAN) | Simulator plays against a physical board | 2 |
| Pi vs Pi (LAN) | Two physical boards on the same network | 2 |
| Spectator (LAN) | Sim watches a physical or virtual game, read-only | 2 |
| Sim vs Sim (Internet) | Two simulators anywhere in the world | 3 |
| Sim vs Pi (Internet) | Simulator vs physical board, remotely | 3 |
| Pi vs Pi (Internet) | Two physical boards, anywhere | 3 |

---

## Phased Roadmap

### Phase 1 — LAN Sim vs Sim (2–3 weeks)
The foundation. Two simulator instances on a local network play a game. One is the **host** (starts a server, controls team setup), the other is the **guest** (connects, plays as team_l). All game logic still runs locally on each side; only moves are transmitted.

Deliverables:
- `network/` package with protocol, server, client modules
- `NetworkedGameRunner` subclass of `GameRunner`
- LAN discovery via UDP broadcast (no setup required)
- Updated simulator lobby screen (Host / Join / Local / Watch)
- Move message format v1
- Board hash verification after each move

### Phase 2 — LAN Physical Board Support (3–4 weeks)
Extend Phase 1 to physical boards. The Pi runs a headless network game manager that transmits moves when the sensor detects a completed lift-off/landing cycle. A sim connecting to a Pi can see the board state in real time (spectator or active opponent).

Deliverables:
- `NetworkedBoard` — headless Pi game manager with network hooks
- `network/discovery.py` — mDNS/Zeroconf LAN advertisement
- Spectator mode in `GameRunner` (receive-only, no input)
- Physical board setup flow over network (color pick driven from Pi display or from connecting sim)
- Pi CLI flags: `--host`, `--join <ip>`, `--spectate <ip>`

### Phase 3 — Internet Play (4–6 weeks)
A lightweight relay server brokers connections between players who are not on the same network. No peer-to-peer NAT traversal needed; both sides connect outward to the relay.

Deliverables:
- `network/relay_server.py` — standalone relay (deployable to any VPS)
- Relay protocol extension (room codes, reconnection tokens)
- Lobby UI: enter room code or generate one
- Reconnection on disconnect (game state can be resumed)
- Optional: web spectator page (read-only, rendered in a browser)

---

## Document Index

| File | Contents |
|---|---|
| `README.md` | This file — overview and roadmap |
| `protocol.md` | Wire protocol: message types, JSON schema, sequencing |
| `architecture.md` | Code structure: new files, changed files, class design |
| `ux.md` | UX flows: lobby, color pick, WAR_GAMES, spectator, all modes |
| `phase-1-lan-sim.md` | Phase 1 step-by-step implementation tasks |
| `phase-2-physical.md` | Phase 2 step-by-step implementation tasks |
| `phase-3-internet.md` | Phase 3 step-by-step implementation tasks |
| `phase-3-chessmatrix-hardware.md` | Phase 3 ChessMatrix hardware UX — status, implementation notes, test coverage |

---

## Key Design Decisions

### Transport: WebSockets over TCP
- Single library (`websockets`, pure Python, asyncio-based)
- Works for LAN and internet without protocol changes
- Framed messages (no delimiter parsing)
- Easy to add a web spectator later (browsers speak WebSocket natively)
- Graceful close and reconnect semantics built in

### Game logic stays local
Neither side trusts the other to run their game logic. Each client independently validates that the move it receives is legal before applying it. If a move is illegal on the receiver's board, it sends a `desync` message and requests a full board snapshot. This prevents one buggy client from corrupting the other.

### Moves are the only wire primitive
The board state is not streamed continuously. Only moves are sent. After each move, both sides independently apply the move to their local board and verify the resulting board hash matches. Full board sync is only triggered on desync.

### Host controls setup
The host's color and WAR_GAMES selections propagate to the guest. The guest can accept or negotiate. In Phase 1 the host picks both team colors and the game starts; in later phases the guest can choose their own color.

### Physical board is always the authority
When a Pi is involved, the Pi is always the source of truth for piece positions. The Pi's sensor reads are the canonical board; the simulator receiving moves from a Pi renders them but does not override them.

---

## Future Work — Phase 4: Host-Side Anti-Cheat

### Problem with the current relay validator

The relay server runs an independent copy of the chess engine (`network/validator.py`, `RoomValidator`) to validate moves before forwarding them. This creates a parallel chess brain that can silently diverge from the clients:

- Any engine bug must be fixed in two places — the game engine **and** the validator.
- Edge cases that the validator handles differently from the client cause false rejections (the `sky_fall`-on-King bug, where the validator incorrectly restricted a King's escape moves to the attacker's ray, is one example).
- The relay is now stateful and chess-aware, making it harder to reason about, test, and deploy independently.

### Proposed design — relay as a pure pass-through

Move all anti-cheat responsibility to the HOST, who already runs the authoritative game engine and knows every legal move at every point in the game.

**Relay changes (`network/relay.py`)**
- Remove `RoomValidator`, `_maybe_init_validator`, `_validate_move`, and the `room.validator` field from `Room`.
- The relay becomes a stateless message router: receive → record history → forward. No chess knowledge required.
- `network/validator.py` can be deleted once host-side validation is in place.

**Host changes (`simulator/networked_runner.py` and `game/networked_board.py`)**
- In `_apply_remote_move` (Sim) and `_wait_for_remote_move` (Pi), after parsing the incoming `move` message, verify it against the legal targets already computed by `_begin_turn` / `calc_targets`:
  1. Confirm it is the GUEST's turn (current team check).
  2. Look up the piece at `(from_row, from_col)` and confirm it belongs to the remote team.
  3. Check that `(to_row, to_col)` is in the piece's pre-computed `targets` list.
- If any check fails: log the violation, send a `board_sync_request` to force reconciliation, and optionally disconnect the peer.
- Because `_begin_turn` is always called before the remote move is processed, legal targets are already available — no extra computation required.

**Why this is better**
- Single source of truth: the rules engine used for validation is the exact same code that drives gameplay. Engine bugs are fixed once and take effect everywhere.
- The relay is stateless and trivially correct — any WebSocket proxy could replace it.
- Relay cold-starts and reconnects become simpler: no game state to rebuild on the server side.
