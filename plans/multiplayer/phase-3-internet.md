# Phase 3 — Internet Play

## Goal

Allow players on different networks, anywhere in the world, to play against each other. No peer-to-peer NAT traversal — both sides connect outward to a lightweight relay server that brokers the game.

## Prerequisite

Phase 1 and Phase 2 must be complete. The Phase 3 relay is protocol-transparent: the same message types from Phase 1 are used unchanged. The relay just routes them between clients.

---

## Work Estimate

**Total: ~4–6 weeks additional**

| Task | Effort |
|---|---|
| `network/relay.py` — relay server | 3 days |
| Room code generation + management | 1 day |
| Reconnection token system | 1 day |
| TLS (wss://) setup | 0.5 day |
| Lobby UI: room code entry + sharing | 1.5 days |
| Relay deployment (Docker + VPS) | 1 day |
| Latency compensation (move animation delay) | 1.5 days |
| Anti-cheat: server-side move validation | 3 days |
| Web spectator page (optional) | 3 days |
| Load testing + reliability | 2 days |
| Bug fixes | 2 days |

---

## Relay Server (`network/relay.py`)

A standalone Python process (not part of the simulator or GameManager). Runs on a VPS. Has no chess logic — it is a pure message broker.

### Responsibilities

- Accept WebSocket connections from players and spectators
- Assign clients to rooms (identified by 6-character room codes)
- Forward all messages from one player to the other
- Broadcast to spectators
- Buffer the last 50 messages per room for reconnection replay
- Generate reconnection tokens (random UUIDs stored per room)
- Clean up rooms after 10 minutes of inactivity

### Room lifecycle

```
Client A connects → relay_create → room code "XKCD42" issued
Client B connects → relay_join "XKCD42" → joined
Both clients send relay_join_ack → relay signals both: relay_peer_connected
Game messages flow: relay forwards transparently
Client A disconnects → relay sends relay_peer_disconnected to B
Client A reconnects with token → relay_reconnect "XKCD42" token "abc..." → replayed last 50 msgs
Game over → room stays open 5min then deleted
```

### Relay-specific message types (extension to Phase 1 protocol)

```json
// Client → Relay: create room
{ "type": "relay_create", "seq": 0, "player_name": "Seth", "version": "1" }

// Relay → Client: room created
{ "type": "relay_created", "room_code": "XKCD42", "token": "uuid-abc..." }

// Client → Relay: join existing room
{ "type": "relay_join", "room_code": "XKCD42", "player_name": "Alex", "version": "1" }

// Client → Relay: spectate
{ "type": "relay_spectate", "room_code": "XKCD42" }

// Client → Relay: reconnect after disconnect
{ "type": "relay_reconnect", "room_code": "XKCD42", "token": "uuid-abc..." }

// Relay → Client: peer connected / disconnected
{ "type": "relay_peer_connected",    "peer_name": "Alex" }
{ "type": "relay_peer_disconnected", "peer_name": "Alex" }

// Relay → Client: error
{ "type": "relay_error", "code": "room_not_found" | "room_full" | "bad_token" | "version_mismatch" }
```

After the join handshake, the relay is transparent. All `hello`, `color_chosen`, `move`, `move_ack`, etc. messages pass through unmodified.

### Relay server implementation sketch

```python
import asyncio
import json
import secrets
import time
import websockets
from dataclasses import dataclass, field

@dataclass
class Room:
    code: str
    players: dict = field(default_factory=dict)  # token → ws
    spectators: list = field(default_factory=list)
    history: list = field(default_factory=list)   # last 50 messages
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

_rooms: dict[str, Room] = {}

async def handle_connection(ws):
    raw = await ws.recv()
    msg = json.loads(raw)
    t = msg["type"]

    if t == "relay_create":
        code = _generate_code()
        token = secrets.token_hex(16)
        room = Room(code=code)
        room.players[token] = ws
        _rooms[code] = room
        await ws.send(json.dumps({"type": "relay_created", "room_code": code, "token": token}))
        await _player_loop(ws, room, token)

    elif t == "relay_join":
        code = msg["room_code"]
        if code not in _rooms or len(_rooms[code].players) >= 2:
            await ws.send(json.dumps({"type": "relay_error", "code": "room_not_found"}))
            return
        room = _rooms[code]
        token = secrets.token_hex(16)
        room.players[token] = ws
        # Notify existing player
        for other_token, other_ws in room.players.items():
            if other_token != token:
                await other_ws.send(json.dumps({"type": "relay_peer_connected", "peer_name": msg["player_name"]}))
        await ws.send(json.dumps({"type": "relay_created", "room_code": code, "token": token}))
        # Replay history for the joining player
        for hist_msg in room.history[-50:]:
            await ws.send(hist_msg)
        await _player_loop(ws, room, token)

    elif t == "relay_spectate":
        code = msg["room_code"]
        if code not in _rooms:
            await ws.send(json.dumps({"type": "relay_error", "code": "room_not_found"}))
            return
        room = _rooms[code]
        room.spectators.append(ws)
        for hist_msg in room.history[-50:]:
            await ws.send(hist_msg)
        await ws.wait_closed()
        room.spectators.remove(ws)

    elif t == "relay_reconnect":
        code = msg["room_code"]
        token = msg["token"]
        if code not in _rooms or token not in _rooms[code].players:
            await ws.send(json.dumps({"type": "relay_error", "code": "bad_token"}))
            return
        room = _rooms[code]
        room.players[token] = ws  # replace old (closed) ws
        for hist_msg in room.history[-50:]:
            await ws.send(hist_msg)
        await _player_loop(ws, room, token)

async def _player_loop(ws, room: Room, token: str):
    try:
        async for raw in ws:
            room.history.append(raw)
            room.last_activity = time.time()
            # Forward to other player
            for other_token, other_ws in room.players.items():
                if other_token != token:
                    await other_ws.send(raw)
            # Broadcast to spectators
            for spec_ws in room.spectators:
                try:
                    await spec_ws.send(raw)
                except Exception:
                    pass
    finally:
        # Notify peer of disconnect
        for other_token, other_ws in room.players.items():
            if other_token != token:
                try:
                    await other_ws.send(json.dumps({"type": "relay_peer_disconnected"}))
                except Exception:
                    pass

def _generate_code() -> str:
    import random, string
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

async def cleanup_loop():
    while True:
        await asyncio.sleep(60)
        now = time.time()
        stale = [code for code, room in _rooms.items()
                 if now - room.last_activity > 600]  # 10 min
        for code in stale:
            del _rooms[code]

async def main():
    asyncio.create_task(cleanup_loop())
    async with websockets.serve(handle_connection, "0.0.0.0", 65101, ssl=_load_ssl()):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
```

### Deployment

Runs on any VPS (1 CPU, 512MB RAM is sufficient for dozens of simultaneous games).

**Docker:**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY network/relay.py network/relay.py
RUN pip install websockets
CMD ["python", "-m", "network.relay"]
```

**TLS:** Put Nginx in front as a reverse proxy with a Let's Encrypt certificate. The relay itself handles plain WebSocket (`ws://`); Nginx terminates TLS and forwards to `ws://localhost:65101`.

**Environment variables:**
- `RELAY_PORT` — port to listen on (default 65101)
- `RELAY_MAX_ROOMS` — max concurrent rooms (default 100)
- `RELAY_ROOM_TIMEOUT` — seconds before idle room cleanup (default 600)

---

## Lobby UI: Internet Play

When the user selects "Host a Game" or "Join a Game" and no LAN games are discovered within 3 seconds, a "Play Online" option appears.

### Hosting online

1. Simulator connects to relay server (address baked into the build or configurable via env var)
2. Relay returns a 6-character room code: `XKCD42`
3. Board area shows the room code in large LED-cell characters (each character as an 8×8 LED block pattern)
4. Side panel shows: `"Share this code with your opponent: XKCD42"`
5. When the opponent joins, the game proceeds exactly as Phase 1

### Joining online

1. A text input appears in the Lobby (keyboard input captured by Pygame)
2. Player types the 6-character room code
3. Simulator connects to relay, sends `relay_join`
4. Game proceeds

### Room code display on the board

The 8×8 LED grid can display 6 characters using a 4×5 pixel font (or 2 characters per quadrant using 8×8). Simplest approach: display 3 characters at a time, alternating every 2 seconds.

---

## Latency Compensation

Over the internet, round-trip time might be 50–200ms. The existing optimistic move application (apply locally, then send, then wait for ack) already handles this well. The only visible latency is the opponent's move arriving: pieces appear to "jump" to their destination.

**Improvement (optional, Phase 3b):** Animate piece movement on the LED grid. When a remote move arrives, blink the source square for 300ms, then move the piece. This makes the animation feel intentional rather than laggy.

---

## Anti-Cheat Consideration

In Phase 1 and 2, both sides run the full chess engine and validate incoming moves independently. An intentionally buggy client could send an illegal move that the receiver rejects (desync recovery kicks in) — but the receiver can't force the sender to make a legal move.

**For Phase 3 (internet play):** The relay server can optionally run the chess engine server-side to validate all moves before forwarding. This requires embedding the chess logic into the relay, which is a significant addition. Recommended approach: run validation as an optional plugin and only enforce it in public-facing relay deployments.

---

## Optional: Web Spectator

A browser-based spectator view using the relay's WebSocket connection.

A simple HTML + Canvas page connects to the relay as a spectator:
```javascript
const ws = new WebSocket("wss://relay.chess101.example.com/");
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.type === "board_sync") renderBoard(msg.grid);
  if (msg.type === "move")       applyMove(msg);
};
```

The board can be rendered as an 8×8 HTML canvas with the same color scheme as the simulator. This is an attractive feature for sharing games with friends who don't have the app installed.

**Effort:** ~3 days for a functional spectator page. Not required for core Phase 3.
