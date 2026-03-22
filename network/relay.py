"""Chess101 WebSocket relay server.

Brokers games between players on different networks without peer-to-peer NAT
traversal.  Both players connect outward to this server; it forwards messages
between them transparently after the room handshake is complete.

Features
--------
- 6-character room codes (uppercase alphanumeric)
- UUID reconnection tokens — clients can resume a dropped session
- Last-50-message replay buffer per room for reconnect catch-up
- Spectator support (receive-only connections)
- Server-side move validation via RoomValidator (anti-cheat)
- Idle room cleanup every 60 s (default TTL 10 min)

Configuration (environment variables)
--------------------------------------
RELAY_PORT          TCP port to listen on (default 8765)
RELAY_MAX_ROOMS     Maximum concurrent rooms (default 100)
RELAY_ROOM_TIMEOUT  Seconds before an idle room is deleted (default 600)

Deployment
----------
  python -m network.relay                          # plain ws://
  RELAY_PORT=8765 python -m network.relay

Run behind Nginx for wss:// (TLS) — see deploy/nginx.conf.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import websockets
    import websockets.exceptions
    import websockets.server
except ImportError:
    websockets = None  # type: ignore[assignment]

# ── Configuration ─────────────────────────────────────────────────────────────
_PORT         = int(os.environ.get("RELAY_PORT",         "8765"))
_MAX_ROOMS    = int(os.environ.get("RELAY_MAX_ROOMS",    "100"))
_ROOM_TIMEOUT = int(os.environ.get("RELAY_ROOM_TIMEOUT", "600"))
_HISTORY_LEN  = 50    # messages buffered per room for reconnect replay
_CODE_LEN     = 6

# ── Anti-cheat integration ────────────────────────────────────────────────────
try:
    from network.validator import RoomValidator
    _ANTICHEAT_AVAILABLE = True
except Exception:
    _ANTICHEAT_AVAILABLE = False
    logger.warning("RoomValidator unavailable — anti-cheat disabled")


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class _Player:
    ws: Any                          # websocket connection
    token: str
    name: str = "Player"
    team_key: Optional[str] = None   # "r" or "l", assigned after game_setup


@dataclass
class Room:
    code: str
    players:    dict[str, _Player]  = field(default_factory=dict)  # token → _Player
    spectators: list                = field(default_factory=list)
    history:    list[str]           = field(default_factory=list)  # raw JSON strings
    created_at: float               = field(default_factory=time.time)
    last_activity: float            = field(default_factory=time.time)
    validator:  Optional[Any]       = None   # RoomValidator once game_start received

    @property
    def is_full(self) -> bool:
        return len(self.players) >= 2

    def other_player(self, token: str) -> Optional[_Player]:
        for t, p in self.players.items():
            if t != token:
                return p
        return None

    def record(self, raw: str) -> None:
        """Append raw JSON to the history buffer, capping at _HISTORY_LEN."""
        self.history.append(raw)
        if len(self.history) > _HISTORY_LEN:
            self.history.pop(0)
        self.last_activity = time.time()


# ── Room registry ─────────────────────────────────────────────────────────────

_rooms: dict[str, Room] = {}


def _generate_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(random.choices(alphabet, k=_CODE_LEN))
        if code not in _rooms:
            return code


def _make_token() -> str:
    return secrets.token_hex(16)


# ── Message helpers ────────────────────────────────────────────────────────────

def _j(obj: dict) -> str:
    return json.dumps(obj)


async def _send(ws, obj: dict) -> None:
    try:
        await ws.send(_j(obj))
    except Exception:
        pass


async def _replay(ws, history: list[str]) -> None:
    for raw in history:
        try:
            await ws.send(raw)
        except Exception:
            break


# ── Anti-cheat helpers ────────────────────────────────────────────────────────

def _maybe_init_validator(room: Room, msg: dict) -> None:
    """Initialize RoomValidator when game_start is received."""
    if not _ANTICHEAT_AVAILABLE or room.validator is not None:
        return
    if msg.get("type") != "game_start":
        return
    team_r = msg.get("team_r")
    team_l = msg.get("team_l")
    if team_r and team_l:
        try:
            v = RoomValidator()
            v.initialize(
                (team_r["r"], team_r["g"], team_r["b"]),
                (team_l["r"], team_l["g"], team_l["b"]),
            )
            room.validator = v
            logger.info("[%s] Anti-cheat validator initialised", room.code)
        except Exception as exc:
            logger.warning("[%s] Validator init failed: %s", room.code, exc)


def _validate_move(room: Room, msg: dict) -> bool:
    """Return False if the move is illegal (relay should reject it)."""
    if msg.get("type") != "move":
        return True
    if room.validator is None:
        return True
    try:
        ok = room.validator.validate_and_apply(msg)
        if not ok:
            logger.warning(
                "[%s] ILLEGAL MOVE rejected: %s→%s",
                room.code, (msg.get("from_row"), msg.get("from_col")),
                (msg.get("to_row"), msg.get("to_col")),
            )
        return ok
    except Exception as exc:
        logger.error("[%s] Validator exception: %s — allowing move", room.code, exc)
        return True


# ── Connection handler ────────────────────────────────────────────────────────

async def _handle(ws) -> None:
    """Dispatch the initial relay handshake message."""
    try:
        raw = await ws.recv()
        msg = json.loads(raw)
    except Exception:
        return

    t = msg.get("type", "")

    if t == "relay_create":
        await _handle_create(ws, msg)
    elif t == "relay_join":
        await _handle_join(ws, msg)
    elif t == "relay_spectate":
        await _handle_spectate(ws, msg)
    elif t == "relay_reconnect":
        await _handle_reconnect(ws, msg)
    else:
        await _send(ws, {"type": "relay_error", "code": "bad_handshake"})


async def _handle_create(ws, msg: dict) -> None:
    if len(_rooms) >= _MAX_ROOMS:
        await _send(ws, {"type": "relay_error", "code": "server_full"})
        return

    code  = _generate_code()
    token = _make_token()
    name  = msg.get("player_name", "Player")

    room = Room(code=code)
    player = _Player(ws=ws, token=token, name=name)
    room.players[token] = player
    _rooms[code] = room

    await _send(ws, {"type": "relay_created", "room_code": code, "token": token})
    logger.info("[%s] Room created by %r", code, name)

    await _player_loop(ws, room, token)


async def _handle_join(ws, msg: dict) -> None:
    code = msg.get("room_code", "").upper()
    room = _rooms.get(code)

    if room is None or room.is_full:
        await _send(ws, {"type": "relay_error", "code": "room_not_found"})
        return

    token = _make_token()
    name  = msg.get("player_name", "Player")
    player = _Player(ws=ws, token=token, name=name)
    room.players[token] = player

    # Notify existing player that a peer has arrived.
    other = room.other_player(token)
    if other is not None:
        await _send(other.ws, {"type": "relay_peer_connected", "peer_name": name})

    await _send(ws, {"type": "relay_created", "room_code": code, "token": token})

    # Replay message history so the joining player catches up.
    await _replay(ws, room.history)

    logger.info("[%s] %r joined", code, name)
    await _player_loop(ws, room, token)


async def _handle_spectate(ws, msg: dict) -> None:
    code = msg.get("room_code", "").upper()
    room = _rooms.get(code)

    if room is None:
        await _send(ws, {"type": "relay_error", "code": "room_not_found"})
        return

    room.spectators.append(ws)
    await _send(ws, {"type": "relay_spectating", "room_code": code})
    await _replay(ws, room.history)

    logger.info("[%s] Spectator joined", code)
    try:
        await ws.wait_closed()
    except Exception:
        pass
    finally:
        try:
            room.spectators.remove(ws)
        except ValueError:
            pass


async def _handle_reconnect(ws, msg: dict) -> None:
    code  = msg.get("room_code", "").upper()
    token = msg.get("token", "")
    room  = _rooms.get(code)

    if room is None or token not in room.players:
        await _send(ws, {"type": "relay_error", "code": "bad_token"})
        return

    # Replace the stale websocket with the new connection.
    room.players[token].ws = ws

    # Notify peer that the player is back.
    other = room.other_player(token)
    if other is not None:
        await _send(other.ws, {
            "type": "relay_peer_connected",
            "peer_name": room.players[token].name,
        })

    await _send(ws, {"type": "relay_reconnected", "room_code": code})
    await _replay(ws, room.history)

    logger.info("[%s] %r reconnected", code, room.players[token].name)
    await _player_loop(ws, room, token)


# ── Per-player message loop ────────────────────────────────────────────────────

async def _player_loop(ws, room: Room, token: str) -> None:
    """Forward messages between the two players and to spectators."""
    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            # Initialise validator when game_start is seen.
            _maybe_init_validator(room, msg)

            # Anti-cheat: validate move messages before forwarding.
            if not _validate_move(room, msg):
                player = room.players.get(token)
                await _send(ws, {
                    "type": "relay_error",
                    "code": "illegal_move",
                    "from_row": msg.get("from_row"),
                    "from_col": msg.get("from_col"),
                    "to_row":   msg.get("to_row"),
                    "to_col":   msg.get("to_col"),
                })
                continue

            # Record in history buffer.
            room.record(raw)

            # Forward to the other player.
            other = room.other_player(token)
            if other is not None:
                try:
                    await other.ws.send(raw)
                except Exception:
                    pass

            # Broadcast to all spectators.
            dead_specs: list = []
            for spec_ws in room.spectators:
                try:
                    await spec_ws.send(raw)
                except Exception:
                    dead_specs.append(spec_ws)
            for spec_ws in dead_specs:
                try:
                    room.spectators.remove(spec_ws)
                except ValueError:
                    pass

    except Exception:
        pass
    finally:
        # Notify peer that this player disconnected.
        other = room.other_player(token)
        if other is not None:
            player_name = room.players[token].name if token in room.players else "Opponent"
            await _send(other.ws, {
                "type": "relay_peer_disconnected",
                "peer_name": player_name,
            })
        logger.info("[%s] Player %r loop ended", room.code, token[:8])


# ── Cleanup task ──────────────────────────────────────────────────────────────

async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(60)
        now   = time.time()
        stale = [
            code for code, room in list(_rooms.items())
            if now - room.last_activity > _ROOM_TIMEOUT
        ]
        for code in stale:
            del _rooms[code]
            logger.info("Room %s expired and removed", code)


# ── Server entry point ────────────────────────────────────────────────────────

async def _main() -> None:
    if websockets is None:
        raise RuntimeError(
            "websockets library not installed — run: pip install 'websockets>=12.0'"
        )

    asyncio.create_task(_cleanup_loop())

    async with websockets.serve(_handle, "0.0.0.0", _PORT):
        logger.info("Chess101 relay listening on ws://0.0.0.0:%d", _PORT)
        await asyncio.Future()   # run forever


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_main())
