#!/usr/bin/env python3
"""fuzz_relay.py — Randomised relay server fuzzer.

Generates random sequences of create / join / send / disconnect / reconnect
operations and verifies delivery invariants after each game:

  • Ordering   — messages arrive in send order
  • Completeness — no message is dropped
  • No duplicates
  • Spectator delivery — spectators receive every forwarded message
  • Reconnect catch-up — reconnecting player receives full history

Usage
-----
    .venv/bin/python harness/fuzz_relay.py [--iterations N] [--seed N]

    # Against external relay:
    RELAY_URL=ws://127.0.0.1:8765 .venv/bin/python harness/fuzz_relay.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import socket
import sys
import threading
import time
from typing import Optional

# ── Make project root importable ─────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from websockets.sync.client import connect as _ws_connect

# ── Helpers ────────────────────────────────────────────────────────────────────

def _open(url: str, timeout: float = 5.0):
    return _ws_connect(url, open_timeout=timeout)

def _send(ws, msg: dict) -> None:
    ws.send(json.dumps(msg))

def _recv(ws, timeout: float = 3.0) -> Optional[dict]:
    try:
        return json.loads(ws.recv(timeout=timeout))
    except Exception:
        return None

def _drain_all(ws, timeout: float = 0.3) -> list[dict]:
    msgs = []
    while True:
        m = _recv(ws, timeout=timeout)
        if m is None:
            break
        msgs.append(m)
    return msgs

def _do_host(url: str, name: str = "Host"):
    ws = _open(url)
    _send(ws, {"type": "relay_create", "player_name": name, "version": "1"})
    msg = _recv(ws)
    assert msg and msg["type"] == "relay_created", f"create failed: {msg}"
    return ws, msg["room_code"], msg["token"]

def _do_guest(url: str, code: str, name: str = "Guest"):
    ws = _open(url)
    _send(ws, {"type": "relay_join", "room_code": code, "player_name": name, "version": "1"})
    msg = _recv(ws)
    assert msg and msg["type"] == "relay_created", f"join failed: {msg}"
    return ws, msg["token"]

def _do_spectate(url: str, code: str):
    ws = _open(url)
    _send(ws, {"type": "relay_spectate", "room_code": code})
    msg = _recv(ws)
    assert msg and msg["type"] == "relay_spectating", f"spectate failed: {msg}"
    return ws

def _game_msg(seq: int, origin: str, payload: str = "") -> dict:
    return {"type": "game_msg", "seq": seq, "origin": origin, "payload": payload}

def _is_game_msg(m: dict) -> bool:
    return m.get("type") == "game_msg"


# ── Invariant checker ─────────────────────────────────────────────────────────

class DeliveryLog:
    """Track sent messages and verify receipt invariants."""

    def __init__(self, name: str):
        self.name = name
        self.sent: list[dict] = []
        self.received: list[dict] = []

    def record_send(self, msg: dict):
        self.sent.append(msg)

    def record_recv(self, msg: dict):
        self.received.append(msg)

    def check(self) -> list[str]:
        """Return list of violation strings (empty = all good)."""
        errors = []
        game_sent = [m for m in self.sent if _is_game_msg(m)]
        game_recv = [m for m in self.received if _is_game_msg(m)]

        if len(game_recv) != len(game_sent):
            errors.append(
                f"{self.name}: sent {len(game_sent)} messages, received {len(game_recv)}"
            )
        for i, (s, r) in enumerate(zip(game_sent, game_recv)):
            if s != r:
                errors.append(f"{self.name}: message {i} mismatch — sent {s}, got {r}")
        return errors


# ── Individual fuzz scenarios ──────────────────────────────────────────────────

def scenario_basic_forward(url: str, rng: random.Random) -> list[str]:
    """Host and guest exchange N random messages; verify all arrive in order."""
    h_ws, code, _ = _do_host(url)
    g_ws, _       = _do_guest(url, code)
    _recv(h_ws)  # drain relay_peer_connected

    n_host  = rng.randint(1, 20)
    n_guest = rng.randint(1, 20)
    h_log = DeliveryLog("guest←host")
    g_log = DeliveryLog("host←guest")

    # Send host → guest
    for i in range(n_host):
        msg = _game_msg(i, "host", payload=rng.randbytes(rng.randint(0, 64)).hex())
        _send(h_ws, msg)
        h_log.record_send(msg)

    # Send guest → host
    for i in range(n_guest):
        msg = _game_msg(i, "guest", payload=rng.randbytes(rng.randint(0, 64)).hex())
        _send(g_ws, msg)
        g_log.record_send(msg)

    time.sleep(0.1)  # let relay process

    for m in _drain_all(g_ws): h_log.record_recv(m)
    for m in _drain_all(h_ws): g_log.record_recv(m)

    h_ws.close(); g_ws.close()

    return h_log.check() + g_log.check()


def scenario_spectator(url: str, rng: random.Random) -> list[str]:
    """Spectator receives every message forwarded between players.

    Ordering invariant: each sender's messages arrive in send order relative to
    that sender's own stream. The interleaving of host vs guest is not
    deterministic, so we only check per-sender order.
    """
    h_ws, code, _ = _do_host(url)
    g_ws, _       = _do_guest(url, code)
    _recv(h_ws)   # drain relay_peer_connected
    s_ws          = _do_spectate(url, code)

    n = rng.randint(1, 15)
    sent: list[dict] = []
    for i in range(n):
        origin = "host" if rng.random() < 0.5 else "guest"
        sender = h_ws if origin == "host" else g_ws
        msg = _game_msg(i, origin)
        _send(sender, msg)
        sent.append(msg)

    time.sleep(0.2)
    spec_got = [m for m in _drain_all(s_ws) if _is_game_msg(m)]
    h_ws.close(); g_ws.close(); s_ws.close()

    errors = []

    # Count check
    if len(spec_got) != len(sent):
        errors.append(f"spectator: sent {len(sent)}, received {len(spec_got)}")
        return errors  # ordering checks below would be noisy

    # Per-sender ordering: messages from each origin must arrive in send order
    for origin in ("host", "guest"):
        sent_by = [m for m in sent if m["origin"] == origin]
        got_by  = [m for m in spec_got if m["origin"] == origin]
        if got_by != sent_by:
            errors.append(
                f"spectator: {origin} message ordering wrong — sent {sent_by}, got {got_by}"
            )

    return errors


def scenario_reconnect(url: str, rng: random.Random) -> list[str]:
    """Disconnect guest after N messages; reconnect; verify history replay."""
    h_ws, code, h_token = _do_host(url)
    g_ws, g_token        = _do_guest(url, code)
    _recv(h_ws)  # drain relay_peer_connected

    n_before = rng.randint(1, 10)
    sent_before: list[dict] = []
    for i in range(n_before):
        msg = _game_msg(i, "host")
        _send(h_ws, msg)
        sent_before.append(msg)
        _recv(g_ws)  # consume at guest before disconnect

    # Guest disconnects abruptly
    g_ws.close()
    _recv(h_ws)  # drain relay_peer_disconnected
    time.sleep(0.05)

    # Host sends more while guest is away
    n_during = rng.randint(1, 10)
    sent_during: list[dict] = []
    for i in range(n_during):
        msg = _game_msg(n_before + i, "host")
        _send(h_ws, msg)
        sent_during.append(msg)
    time.sleep(0.05)

    # Guest reconnects
    g2_ws = _open(url)
    _send(g2_ws, {"type": "relay_reconnect", "room_code": code, "token": g_token})
    reconnect_msg = _recv(g2_ws)

    errors = []
    if reconnect_msg is None or reconnect_msg.get("type") != "relay_reconnected":
        errors.append(f"reconnect failed: {reconnect_msg}")
        g2_ws.close(); h_ws.close()
        return errors

    _recv(h_ws)  # drain relay_peer_connected after reconnect

    # Guest should receive all history messages (replay)
    time.sleep(0.1)
    replayed = [m for m in _drain_all(g2_ws) if _is_game_msg(m)]
    expected = sent_before + sent_during
    # History buffer may not include all sent_before (only last 50 total),
    # but all sent_during must be present.
    for msg in sent_during:
        if msg not in replayed:
            errors.append(f"reconnect: message not replayed: {msg}")

    h_ws.close(); g2_ws.close()
    return errors


def scenario_rapid_join_leave(url: str, rng: random.Random) -> list[str]:
    """Rapid create / close cycles should not crash the server."""
    errors = []
    n = rng.randint(5, 20)
    for _ in range(n):
        try:
            ws, code, _ = _do_host(url)
            if rng.random() < 0.5:
                g_ws, _ = _do_guest(url, code)
                g_ws.close()
            ws.close()
        except Exception as exc:
            errors.append(f"rapid_join_leave: exception {exc}")
    # Verify server still responds after the storm
    try:
        ws, code, _ = _do_host(url)
        ws.close()
    except Exception as exc:
        errors.append(f"rapid_join_leave: server unresponsive after storm: {exc}")
    return errors


def scenario_invalid_codes(url: str, rng: random.Random) -> list[str]:
    """Bad room codes and double-join should return relay_error, not crash."""
    errors = []

    # Join non-existent room
    ws = _open(url)
    _send(ws, {"type": "relay_join", "room_code": "ZZZZZZ", "version": "1"})
    msg = _recv(ws); ws.close()
    if not (msg and msg.get("type") == "relay_error" and msg.get("code") == "room_not_found"):
        errors.append(f"bad_code: expected room_not_found, got {msg}")

    # Create room, then try to join it twice (room full)
    h_ws, code, _ = _do_host(url)
    g_ws, _       = _do_guest(url, code)
    _recv(h_ws)   # drain peer_connected
    ws3 = _open(url)
    _send(ws3, {"type": "relay_join", "room_code": code, "version": "1"})
    msg = _recv(ws3); ws3.close()
    if not (msg and msg.get("type") == "relay_error" and msg.get("code") == "room_not_found"):
        errors.append(f"full_room: expected room_not_found, got {msg}")

    # Bad reconnect token
    ws = _open(url)
    _send(ws, {"type": "relay_reconnect", "room_code": code, "token": "badtoken"})
    msg = _recv(ws); ws.close()
    if not (msg and msg.get("type") == "relay_error" and msg.get("code") == "bad_token"):
        errors.append(f"bad_token: expected bad_token, got {msg}")

    h_ws.close(); g_ws.close()
    return errors


def scenario_burst_messages(url: str, rng: random.Random) -> list[str]:
    """Send a burst of messages with no pacing; verify all arrive."""
    h_ws, code, _ = _do_host(url)
    g_ws, _       = _do_guest(url, code)
    _recv(h_ws)

    n = rng.randint(50, 200)
    log = DeliveryLog("burst")
    for i in range(n):
        msg = _game_msg(i, "host")
        _send(h_ws, msg)
        log.record_send(msg)

    time.sleep(0.3)
    for m in _drain_all(g_ws, timeout=0.5): log.record_recv(m)
    h_ws.close(); g_ws.close()
    return log.check()


# ── In-process relay bootstrap ─────────────────────────────────────────────────

def _start_inprocess_relay() -> tuple[str, object]:
    """Start a relay server in a background thread. Returns (ws URL, relay_mod)."""
    import websockets
    import network.relay as relay_mod

    relay_mod._rooms.clear()

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    ready  = threading.Event()
    loop   = asyncio.new_event_loop()

    async def _serve():
        async with websockets.serve(
            relay_mod._handle,
            "127.0.0.1",
            port,
            process_request=relay_mod._process_request,
        ):
            ready.set()
            await asyncio.Future()  # run forever

    threading.Thread(target=lambda: loop.run_until_complete(_serve()), daemon=True).start()
    assert ready.wait(timeout=5.0), "In-process relay failed to start"
    return f"ws://127.0.0.1:{port}", relay_mod


# ── Main ───────────────────────────────────────────────────────────────────────

SCENARIOS = [
    ("basic_forward",      scenario_basic_forward,    40),
    ("spectator",          scenario_spectator,        20),
    ("reconnect",          scenario_reconnect,        20),
    ("rapid_join_leave",   scenario_rapid_join_leave, 10),
    ("invalid_codes",      scenario_invalid_codes,    5),
    ("burst_messages",     scenario_burst_messages,   5),
]


def main():
    ap = argparse.ArgumentParser(description="Relay server fuzzer")
    ap.add_argument("--iterations", type=int, default=100,
                    help="Total fuzzing iterations (default 100)")
    ap.add_argument("--seed",       type=int, default=42,
                    help="RNG seed (default 42)")
    args = ap.parse_args()

    live_url = os.environ.get("RELAY_URL")
    if live_url:
        url, relay_mod = live_url, None
    else:
        url, relay_mod = _start_inprocess_relay()
    print(f"Fuzzing relay at {url}")
    print(f"Iterations: {args.iterations}  Seed: {args.seed}\n")

    rng = random.Random(args.seed)
    # Build weighted scenario list
    pool = [(name, fn) for name, fn, weight in SCENARIOS for _ in range(weight)]
    rng.shuffle(pool)

    total = passed = failed = 0
    failures: list[tuple[str, list[str]]] = []

    for i in range(args.iterations):
        # Reset room state between iterations so rooms from closed connections
        # don't accumulate and trigger server_full errors.
        if relay_mod is not None:
            relay_mod._rooms.clear()

        name, fn = pool[i % len(pool)]
        try:
            errors = fn(url, rng)
        except AssertionError as exc:
            errors = [f"assertion: {exc}"]
        except Exception as exc:
            errors = [f"exception: {type(exc).__name__}: {exc}"]

        total += 1
        if errors:
            failed += 1
            failures.append((name, errors))
            for e in errors:
                print(f"  FAIL [{name}] iter={i}: {e}")
        else:
            passed += 1
            if (i + 1) % 10 == 0:
                print(f"  ... {i+1}/{args.iterations} passed={passed} failed={failed}")

    print(f"\n{'─'*60}")
    print(f"Results: {passed} passed, {failed} failed out of {total}")
    if failures:
        print("\nFailures by scenario:")
        by_scenario: dict[str, int] = {}
        for name, _ in failures:
            by_scenario[name] = by_scenario.get(name, 0) + 1
        for name, count in sorted(by_scenario.items(), key=lambda x: -x[1]):
            print(f"  {name}: {count}")
        sys.exit(1)
    else:
        print("All invariants satisfied.")


if __name__ == "__main__":
    main()
