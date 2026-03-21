# Chess101 Multiplayer — Code Architecture

## New Package: `network/`

```
network/
├── __init__.py
├── protocol.py       # Message dataclasses, serialization, board hashing
├── server.py         # WebSocket server (host side)
├── client.py         # WebSocket client (guest side)
├── discovery.py      # UDP beacon broadcast + listener (LAN discovery)
└── relay.py          # Relay server entry point (Phase 3)
```

---

## `network/protocol.py`

Central definitions for all wire messages and board serialization. No I/O — pure data.

```python
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Optional
from pieces.piece import Piece
from pieces.pawn import Pawn

# ── Message base ──────────────────────────────────────────────────────────────

@dataclass
class Message:
    type: str
    seq: int

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(raw: str) -> dict:
        return json.loads(raw)

# ── Move flags ────────────────────────────────────────────────────────────────

@dataclass
class MoveFlags:
    is_capture: bool = False
    captured_piece: Optional[str] = None
    captured_at: Optional[list[int]] = None   # [row, col]
    is_en_passant: bool = False
    is_castling: bool = False
    rook_from: Optional[list[int]] = None     # [row, col]
    rook_to: Optional[list[int]] = None       # [row, col]
    is_promotion: bool = False
    promotion_to: Optional[str] = None        # "Queen"

# ── Cell encoding ─────────────────────────────────────────────────────────────

_PIECE_INITIAL = {
    "Pawn": "P", "Rook": "R", "Knight": "N",
    "Bishop": "B", "Queen": "Q", "King": "K",
}

def encode_grid(grid: list, team_r_r: int) -> list[list[Optional[dict]]]:
    """Serialize an 8×8 grid to a JSON-safe list of lists."""
    result = []
    for row in grid:
        encoded_row = []
        for cell in row:
            if cell is None:
                encoded_row.append(None)
            else:
                team = "r" if cell.team.r == team_r_r else "l"
                entry: dict = {
                    "piece": type(cell).__name__,
                    "team": team,
                    "touched": cell.touched,
                }
                if isinstance(cell, Pawn):
                    entry["en_passantable"] = cell.en_passantable
                encoded_row.append(entry)
        result.append(encoded_row)
    return result

def board_hash(grid: list, peace_time: int, current_team: str) -> str:
    """Compute a SHA-256 hash of the board state for sync verification."""
    parts = []
    for row in grid:
        for cell in row:
            if cell is None:
                parts.append(".")
            else:
                initial = _PIECE_INITIAL.get(type(cell).__name__, "?")
                team = "r" if hasattr(cell, "team") else "l"
                parts.append(f"{initial}{team}")
    canonical = ",".join(parts) + f"|{peace_time}|{current_team}"
    return hashlib.sha256(canonical.encode()).hexdigest()
```

---

## `network/server.py`

Runs on the host. Accepts one game connection and any number of spectator connections. Uses `asyncio` + `websockets`.

```python
import asyncio
import websockets
from network.protocol import Message

class GameServer:
    """WebSocket server for the hosting player."""

    def __init__(self, port: int = 65101):
        self.port = port
        self._game_conn = None        # the one opponent WebSocket
        self._spectators: list = []   # read-only spectator connections
        self._on_message = None       # callback: (msg: dict) -> None
        self._send_queue: asyncio.Queue = asyncio.Queue()

    def set_message_handler(self, callback) -> None:
        self._on_message = callback

    async def send(self, msg: dict) -> None:
        """Queue a message to the opponent."""
        await self._send_queue.put(msg)

    async def broadcast(self, msg: dict) -> None:
        """Send to opponent + all spectators."""
        await self.send(msg)
        for ws in self._spectators:
            try:
                await ws.send(json.dumps(msg))
            except Exception:
                pass

    async def _handle_opponent(self, ws) -> None:
        self._game_conn = ws
        async for raw in ws:
            msg = json.loads(raw)
            if self._on_message:
                self._on_message(msg)

    async def _sender_loop(self) -> None:
        while True:
            msg = await self._send_queue.get()
            if self._game_conn:
                await self._game_conn.send(json.dumps(msg))

    async def start(self) -> None:
        async with websockets.serve(self._route, "0.0.0.0", self.port):
            await self._sender_loop()

    async def _route(self, ws) -> None:
        # First message determines role
        raw = await ws.recv()
        msg = json.loads(raw)
        if msg.get("type") == "relay_spectate":
            self._spectators.append(ws)
            await ws.wait_closed()
            self._spectators.remove(ws)
        else:
            await self._handle_opponent(ws)
            self._game_conn = None
```

---

## `network/client.py`

Runs on the guest. Connects to the host's WebSocket server.

```python
import asyncio
import json
import websockets

class GameClient:
    """WebSocket client for the joining player."""

    def __init__(self, host_ip: str, port: int = 65101):
        self.uri = f"ws://{host_ip}:{port}"
        self._ws = None
        self._on_message = None
        self._send_queue: asyncio.Queue = asyncio.Queue()

    def set_message_handler(self, callback) -> None:
        self._on_message = callback

    async def connect(self) -> None:
        self._ws = await websockets.connect(self.uri)

    async def send(self, msg: dict) -> None:
        await self._send_queue.put(msg)

    async def run(self) -> None:
        await self.connect()
        recv_task = asyncio.create_task(self._recv_loop())
        send_task = asyncio.create_task(self._send_loop())
        await asyncio.gather(recv_task, send_task)

    async def _recv_loop(self) -> None:
        async for raw in self._ws:
            msg = json.loads(raw)
            if self._on_message:
                self._on_message(msg)

    async def _send_loop(self) -> None:
        while True:
            msg = await self._send_queue.get()
            await self._ws.send(json.dumps(msg))
```

---

## `network/discovery.py`

UDP beacon for LAN game discovery. Runs alongside the WebSocket server.

```python
import asyncio
import json
import socket
import threading
from dataclasses import dataclass

BEACON_PORT = 65102
BEACON_INTERVAL = 2.0  # seconds

@dataclass
class DiscoveredGame:
    host_name: str
    host_ip: str
    ws_port: int
    game_state: str        # "lobby" or "playing"
    spectators_allowed: bool

class BeaconBroadcaster:
    """Broadcasts game presence on the LAN via UDP."""

    def __init__(self, host_name: str, ws_port: int = 65101):
        self.host_name = host_name
        self.ws_port = ws_port
        self.game_state = "lobby"
        self._running = False

    def start(self) -> None:
        self._running = True
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while self._running:
            payload = json.dumps({
                "type": "chess101_beacon",
                "host_name": self.host_name,
                "ws_port": self.ws_port,
                "game_state": self.game_state,
                "spectators_allowed": True,
            }).encode()
            sock.sendto(payload, ("255.255.255.255", BEACON_PORT))
            import time; time.sleep(BEACON_INTERVAL)

class BeaconListener:
    """Listens for game beacons and maintains a list of discovered games."""

    def __init__(self):
        self.games: dict[str, DiscoveredGame] = {}  # ip → game
        self._running = False

    def start(self) -> None:
        self._running = True
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", BEACON_PORT))
        sock.settimeout(1.0)
        while self._running:
            try:
                data, (ip, _) = sock.recvfrom(1024)
                msg = json.loads(data)
                if msg.get("type") == "chess101_beacon":
                    self.games[ip] = DiscoveredGame(
                        host_name=msg["host_name"],
                        host_ip=ip,
                        ws_port=msg["ws_port"],
                        game_state=msg["game_state"],
                        spectators_allowed=msg.get("spectators_allowed", False),
                    )
            except (socket.timeout, json.JSONDecodeError):
                pass
```

---

## `simulator/networked_runner.py`

Subclass of `GameRunner` that hooks the network layer into the game loop.

```python
import asyncio
import threading
from simulator.app import GameRunner, Phase
from network.server import GameServer
from network.client import GameClient
from network.discovery import BeaconBroadcaster, BeaconListener
from network.protocol import encode_grid, board_hash, MoveFlags

class NetworkRole:
    HOST = "host"
    GUEST = "guest"
    SPECTATOR = "spectator"

class NetworkedGameRunner(GameRunner):
    """GameRunner with a network opponent instead of a local second player."""

    def __init__(self, role: str, host_ip: str = None, port: int = 65101):
        super().__init__()
        self.role = role
        self._net_seq = 0
        self._pending_remote_move: dict | None = None  # set by network thread
        self._net_lock = threading.Lock()
        self._local_team_key = "team_r" if role == NetworkRole.HOST else "team_l"

        if role == NetworkRole.HOST:
            self._net = GameServer(port=port)
            self._beacon = BeaconBroadcaster("Chess101 Game", ws_port=port)
        else:
            self._net = GameClient(host_ip=host_ip, port=port)
            self._beacon = None

        self._net.set_message_handler(self._on_network_message)

    # ── Network thread ────────────────────────────────────────────────────────

    def _start_network(self) -> None:
        """Start the async network loop in a background thread."""
        def run():
            asyncio.run(self._net.start() if self.role == NetworkRole.HOST
                        else self._net.run())
        threading.Thread(target=run, daemon=True).start()
        if self._beacon:
            self._beacon.start()

    def _on_network_message(self, msg: dict) -> None:
        """Called from the network thread; store pending moves for the game loop."""
        t = msg.get("type")
        if t == "move":
            with self._net_lock:
                self._pending_remote_move = msg
        elif t == "color_chosen":
            self._apply_remote_color(msg)
        elif t == "war_games_choice":
            self._apply_remote_war_games(msg)
        elif t == "game_start":
            self._apply_game_start(msg)
        elif t == "board_sync":
            self._apply_board_sync(msg)

    # ── Game loop integration ─────────────────────────────────────────────────

    def _update(self) -> None:
        """Override: also check for pending remote moves."""
        super()._update()
        if self.phase == Phase.PLAYING:
            self._check_remote_move()

    def _check_remote_move(self) -> None:
        """Apply a queued remote move if it's the opponent's turn."""
        b = self._b
        is_local_turn = (
            (self._local_team_key == "team_r") == (self._current_team is b.team_r)
        )
        if is_local_turn:
            return  # wait for local player input

        with self._net_lock:
            msg = self._pending_remote_move
            self._pending_remote_move = None

        if msg is None:
            return

        # Validate and apply the remote move
        fr, fc = msg["from_row"], msg["from_col"]
        tr, tc = msg["to_row"],   msg["to_col"]
        piece = b.grid[fr][fc]
        if piece is None:
            self._send_error("illegal_move", "No piece at source square")
            return

        b.grid[tr][tc] = piece
        self._apply_move(fr, fc, tr, tc)
        self._move_count += 1

        # Verify hash
        expected = msg.get("board_hash")
        actual = board_hash(
            b.grid, self.peace_time,
            "team_r" if self._current_team is b.team_r else "team_l"
        )
        status = "ok" if actual == expected else "desync"
        self._net_send({"type": "move_ack", "ack_seq": msg["seq"], "board_hash": actual, "status": status})

        if status == "desync":
            self._net_send({"type": "board_sync_request", "after_seq": msg["seq"]})
        else:
            self._next_turn()

    # ── Local move hook ───────────────────────────────────────────────────────

    def _next_turn(self) -> None:
        """Override: after a local move, send it to the opponent before flipping."""
        # _last_move is set by _handle_playing before calling _next_turn
        if hasattr(self, "_last_move") and self._last_move:
            self._net_send_move(*self._last_move)
            self._last_move = None
        super()._next_turn()

    def _net_send_move(self, fr, fc, tr, tc, flags: MoveFlags = None) -> None:
        b = self._b
        if flags is None:
            flags = MoveFlags()
        self._net_send({
            "type": "move",
            "from_row": fr, "from_col": fc,
            "to_row":   tr, "to_col":   tc,
            "piece": type(b.grid[tr][tc]).__name__,
            "flags": flags.__dict__,
            "board_hash": board_hash(
                b.grid, self.peace_time,
                "team_r" if self._current_team is b.team_r else "team_l"
            ),
        })

    # ── Utility ───────────────────────────────────────────────────────────────

    def _net_send(self, msg: dict) -> None:
        self._net_seq += 1
        msg["seq"] = self._net_seq
        asyncio.run_coroutine_threadsafe(self._net.send(msg), self._net_loop)

    def _send_error(self, code: str, detail: str) -> None:
        self._net_send({"type": "error", "code": code, "detail": detail})
```

---

## Changes to `simulator/app.py`

The existing `GameRunner` needs two small additions to support `NetworkedGameRunner`:

1. **`_last_move` attribute** — set in `_handle_playing` after a move is applied, before `_next_turn()` is called:
   ```python
   # In _handle_playing, after applying the move:
   self._last_move = (old_r, old_c, row, col)
   self._next_turn()
   ```

2. **`_next_turn` made overridable** — already a method, no change needed.

3. **Lobby phase (Phase.LOBBY)** — new phase inserted before COLOR_PICK for networked mode. Shows "Host / Join / Local / Watch" options. Only added to `NetworkedGameRunner`, not the base class.

---

## Changes to `GameManager.py` (Phase 2)

Add CLI flags for network mode:

```python
parser.add_argument("--host", action="store_true", help="Host a networked game")
parser.add_argument("--join", metavar="IP", help="Join a networked game at IP")
parser.add_argument("--spectate", metavar="IP", help="Spectate a game at IP")
parser.add_argument("--port", type=int, default=65101, help="Network port")
```

When `--host` or `--join` is provided, `Board` uses a `NetworkedBoard` variant that sends moves over the network after each detected lift-off/landing cycle.

---

## File Summary

### New files

| File | Purpose |
|---|---|
| `network/__init__.py` | Package marker |
| `network/protocol.py` | Message dataclasses, grid encoding, board hashing |
| `network/server.py` | WebSocket host server |
| `network/client.py` | WebSocket guest client |
| `network/discovery.py` | UDP LAN beacon broadcast + listener |
| `network/relay.py` | Phase 3 relay server |
| `simulator/networked_runner.py` | `NetworkedGameRunner(GameRunner)` |
| `simulator/lobby.py` | Lobby screen rendering (Host/Join/Local/Watch) |

### Modified files

| File | Change |
|---|---|
| `simulator/app.py` | `_last_move` tracking; `Phase.LOBBY` enum member |
| `simulator/run_simulator.py` | CLI flags `--host`, `--join`, `--spectate`, `--port` |
| `GameManager.py` | CLI flags for Pi network mode |
| `game/board.py` | Extract `_apply_move` into a shared helper; add move event callback hook |
| `requirements.txt` | Add `websockets>=12` |
| `requirements-dev.txt` | No change |

---

## Dependency

```
websockets>=12.0
```

Pure Python, no compiled extensions. Asyncio-based, plays nicely with the existing threading model (the network loop runs in its own thread with `asyncio.run()`; Pygame loop stays on the main thread; messages cross over via a thread-safe queue).
