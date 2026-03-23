"""test_relay.py — Relay server protocol, forwarding, reconnect, and anti-cheat tests.

Run modes
---------
    # Default: in-process relay, fast, no Docker needed
    .venv/bin/python -m pytest tests/test_relay.py -v

    # Docker: builds chess101-relay image, runs it for the session
    .venv/bin/python -m pytest tests/test_relay.py -v --relay-docker

    # External relay (pre-built Docker or live):
    docker run -d -p 8765:8765 -e RELAY_PORT=8765 chess101-relay
    RELAY_URL=ws://127.0.0.1:8765 .venv/bin/python -m pytest tests/test_relay.py -v

    # Live smoke test:
    RELAY_URL=wss://relay.chess101.net .venv/bin/python -m pytest tests/test_relay.py -v
"""
from __future__ import annotations

import json
import os
import socket
import string
import threading
import time
import urllib.request
from typing import Optional, Tuple

import pytest
from websockets.sync.client import connect as _ws_connect

from network.relay_client import RelayClient


# ── Low-level WS helpers ───────────────────────────────────────────────────────


def _open(url: str):
    """Open a synchronous WebSocket connection."""
    return _ws_connect(url, open_timeout=5.0)


def _send(ws, msg: dict) -> None:
    ws.send(json.dumps(msg))


def _recv(ws, timeout: float = 2.0) -> Optional[dict]:
    """Receive one message. Returns None on timeout or closed connection."""
    try:
        raw = ws.recv(timeout=timeout)
        return json.loads(raw)
    except Exception:
        return None


def _drain(ws, count: int, timeout: float = 2.0) -> list[dict]:
    """Receive exactly *count* messages, returning them in order."""
    return [m for _ in range(count) if (m := _recv(ws, timeout)) is not None]


# ── Higher-level protocol helpers ──────────────────────────────────────────────


def _do_host(url: str, name: str = "Host") -> Tuple[object, str, str]:
    """Open WS, send relay_create. Returns (ws, room_code, token)."""
    ws = _open(url)
    _send(ws, {"type": "relay_create", "player_name": name, "version": "1"})
    msg = _recv(ws)
    assert msg is not None and msg["type"] == "relay_created", (
        f"Expected relay_created, got {msg}"
    )
    return ws, msg["room_code"], msg["token"]


def _do_guest(url: str, code: str, name: str = "Guest") -> Tuple[object, str]:
    """Open WS, send relay_join. Returns (ws, token)."""
    ws = _open(url)
    _send(ws, {"type": "relay_join", "room_code": code, "player_name": name, "version": "1"})
    msg = _recv(ws)
    assert msg is not None and msg["type"] == "relay_created", (
        f"Expected relay_created for join, got {msg}"
    )
    return ws, msg["token"]


def _do_spectate(url: str, code: str):
    """Open WS, send relay_spectate. Returns ws."""
    ws = _open(url)
    _send(ws, {"type": "relay_spectate", "room_code": code})
    msg = _recv(ws)
    assert msg is not None and msg["type"] == "relay_spectating", (
        f"Expected relay_spectating, got {msg}"
    )
    return ws


def _do_reconnect(url: str, code: str, token: str) -> Tuple[object, dict]:
    """Open WS, send relay_reconnect. Returns (ws, first_response_msg)."""
    ws = _open(url)
    _send(ws, {"type": "relay_reconnect", "room_code": code, "token": token})
    msg = _recv(ws)
    assert msg is not None, "No response to relay_reconnect"
    return ws, msg


def _game(seq: int = 0, origin: str = "test") -> dict:
    """Make a simple game-protocol message (never relay_* prefixed)."""
    return {"type": "game_msg", "seq": seq, "origin": origin}


def _is_external(request) -> bool:
    """True when tests run against an external relay (Docker or live URL)."""
    return bool(os.environ.get("RELAY_URL")) or request.config.getoption(
        "--relay-docker", default=False
    )


# ── TestRoomLifecycle ──────────────────────────────────────────────────────────


class TestRoomLifecycle:

    def test_create_gets_code_and_token(self, relay_url):
        ws, code, token = _do_host(relay_url)
        ws.close()
        alphanum = set(string.ascii_uppercase + string.digits)
        assert len(code) == 6
        assert all(c in alphanum for c in code)
        assert len(token) > 0

    def test_guest_join_notifies_host(self, relay_url):
        h_ws, code, _ = _do_host(relay_url, "HostPlayer")
        g_ws, _ = _do_guest(relay_url, code, "GuestPlayer")
        notif = _recv(h_ws)
        try:
            assert notif is not None
            assert notif["type"] == "relay_peer_connected"
            assert notif["peer_name"] == "GuestPlayer"
        finally:
            h_ws.close(); g_ws.close()

    def test_join_nonexistent_room(self, relay_url):
        ws = _open(relay_url)
        _send(ws, {"type": "relay_join", "room_code": "ZZZZZZ", "player_name": "X", "version": "1"})
        msg = _recv(ws)
        ws.close()
        assert msg is not None
        assert msg["type"] == "relay_error"
        assert msg["code"] == "room_not_found"

    def test_room_full_third_client(self, relay_url):
        h_ws, code, _ = _do_host(relay_url)
        g_ws, _ = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected
        ws3 = _open(relay_url)
        _send(ws3, {"type": "relay_join", "room_code": code, "player_name": "Z", "version": "1"})
        msg = _recv(ws3)
        try:
            assert msg is not None
            assert msg["type"] == "relay_error"
            assert msg["code"] == "room_not_found"
        finally:
            h_ws.close(); g_ws.close(); ws3.close()

    def test_spectate_live_room(self, relay_url):
        h_ws, code, _ = _do_host(relay_url)
        s_ws = _do_spectate(relay_url, code)   # asserts relay_spectating internally
        h_ws.close(); s_ws.close()

    def test_spectate_nonexistent_room(self, relay_url):
        ws = _open(relay_url)
        _send(ws, {"type": "relay_spectate", "room_code": "XXXX00"})
        msg = _recv(ws)
        ws.close()
        assert msg is not None
        assert msg["type"] == "relay_error"
        assert msg["code"] == "room_not_found"


# ── TestMessageForwarding ──────────────────────────────────────────────────────


class TestMessageForwarding:

    def test_host_to_guest(self, relay_url):
        h_ws, code, _ = _do_host(relay_url)
        g_ws, _ = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected
        payload = _game(seq=1, origin="host")
        _send(h_ws, payload)
        received = _recv(g_ws)
        try:
            assert received == payload
        finally:
            h_ws.close(); g_ws.close()

    def test_guest_to_host(self, relay_url):
        h_ws, code, _ = _do_host(relay_url)
        g_ws, _ = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected
        payload = _game(seq=2, origin="guest")
        _send(g_ws, payload)
        received = _recv(h_ws)
        try:
            assert received == payload
        finally:
            h_ws.close(); g_ws.close()

    def test_spectator_receives_all(self, relay_url):
        h_ws, code, _ = _do_host(relay_url)
        g_ws, _ = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected
        s_ws = _do_spectate(relay_url, code)

        for i in range(3):
            _send(h_ws, _game(seq=i, origin="host"))
        for i in range(3):
            _send(g_ws, _game(seq=i, origin="guest"))

        # Spectator should receive all 6 messages
        received = [m for _ in range(6) if (m := _recv(s_ws, timeout=3.0)) is not None]
        try:
            assert len(received) == 6, f"Expected 6, got {len(received)}: {received}"
        finally:
            h_ws.close(); g_ws.close(); s_ws.close()

    def test_sender_does_not_receive_own_message(self, relay_url):
        """The relay forwards to the OTHER player only, not the sender."""
        h_ws, code, _ = _do_host(relay_url)
        g_ws, _ = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected
        _send(h_ws, _game(seq=1))
        assert _recv(g_ws) is not None           # guest receives it
        echo = _recv(h_ws, timeout=0.3)          # host should NOT get it back
        try:
            assert echo is None, f"Host received its own message back: {echo}"
        finally:
            h_ws.close(); g_ws.close()


# ── TestHistoryReplay ──────────────────────────────────────────────────────────


class TestHistoryReplay:

    def test_history_replayed_on_join(self, relay_url):
        h_ws, code, _ = _do_host(relay_url)
        for i in range(5):
            _send(h_ws, _game(seq=i))
        time.sleep(0.1)  # let relay flush messages into history
        g_ws, _ = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected
        replayed = _drain(g_ws, 5, timeout=3.0)
        extra = _recv(g_ws, timeout=0.3)
        try:
            assert len(replayed) == 5, f"Expected 5 history msgs, got {len(replayed)}"
            assert extra is None, f"Unexpected extra message after history: {extra}"
        finally:
            h_ws.close(); g_ws.close()

    def test_history_replayed_in_order(self, relay_url):
        h_ws, code, _ = _do_host(relay_url)
        for i in range(5):
            _send(h_ws, _game(seq=i))
        time.sleep(0.1)
        g_ws, _ = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected
        replayed = _drain(g_ws, 5, timeout=3.0)
        try:
            seqs = [m["seq"] for m in replayed]
            assert seqs == list(range(5)), f"Out-of-order history: {seqs}"
        finally:
            h_ws.close(); g_ws.close()

    def test_history_cap_at_50(self, relay_url):
        h_ws, code, _ = _do_host(relay_url)
        for i in range(55):
            _send(h_ws, _game(seq=i))
        time.sleep(0.15)
        g_ws, _ = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected
        replayed = []
        while True:
            m = _recv(g_ws, timeout=0.5)
            if m is None:
                break
            replayed.append(m)
        try:
            assert len(replayed) == 50, f"Expected 50 history msgs, got {len(replayed)}"
            # The 5 oldest messages should have been dropped (seqs 0-4)
            seqs = [m["seq"] for m in replayed]
            assert seqs[0] == 5, f"Expected first replayed seq=5, got {seqs[0]}"
        finally:
            h_ws.close(); g_ws.close()

    def test_history_replayed_on_reconnect(self, relay_url):
        h_ws, code, _ = _do_host(relay_url)
        g_ws, g_token = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected
        for i in range(3):
            _send(h_ws, _game(seq=i))
        time.sleep(0.05)
        g_ws.close()
        time.sleep(0.05)
        _recv(h_ws)  # drain peer_disconnected

        new_g_ws, resp = _do_reconnect(relay_url, code, g_token)
        _recv(h_ws)  # drain peer_connected (reconnect notification)
        assert resp["type"] == "relay_reconnected"
        replayed = _drain(new_g_ws, 3, timeout=3.0)
        try:
            assert len(replayed) == 3, f"Expected 3 replayed msgs, got {len(replayed)}"
        finally:
            h_ws.close(); new_g_ws.close()

    def test_spectator_gets_history(self, relay_url):
        h_ws, code, _ = _do_host(relay_url)
        g_ws, _ = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected
        for i in range(3):
            _send(h_ws, _game(seq=i))
        time.sleep(0.05)
        s_ws = _do_spectate(relay_url, code)
        replayed = _drain(s_ws, 3, timeout=3.0)
        extra = _recv(s_ws, timeout=0.3)
        try:
            assert len(replayed) == 3, f"Expected 3 history msgs for spectator, got {len(replayed)}"
            assert extra is None
        finally:
            h_ws.close(); g_ws.close(); s_ws.close()


# ── TestReconnectionStandard ───────────────────────────────────────────────────


class TestReconnectionStandard:

    def test_reconnect_valid_token(self, relay_url):
        h_ws, code, _ = _do_host(relay_url)
        g_ws, g_token = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected
        g_ws.close()
        time.sleep(0.05)
        new_g_ws, resp = _do_reconnect(relay_url, code, g_token)
        try:
            assert resp["type"] == "relay_reconnected"
            assert resp.get("room_code") == code
        finally:
            h_ws.close(); new_g_ws.close()

    def test_reconnect_bad_token(self, relay_url):
        h_ws, code, _ = _do_host(relay_url)
        g_ws, _ = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected
        h_ws.close(); g_ws.close()
        ws, resp = _do_reconnect(relay_url, code, "deadbeef" * 8)
        ws.close()
        assert resp["type"] == "relay_error"
        assert resp["code"] == "bad_token"

    def test_reconnect_wrong_room(self, relay_url):
        ws, resp = _do_reconnect(relay_url, "BADRM0", "sometoken" * 4)
        ws.close()
        assert resp["type"] == "relay_error"
        assert resp["code"] in ("room_not_found", "bad_token")

    def test_reconnect_notifies_peer(self, relay_url):
        h_ws, code, _ = _do_host(relay_url)
        g_ws, g_token = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected
        g_ws.close()
        time.sleep(0.05)
        _recv(h_ws)  # drain peer_disconnected
        new_g_ws, _ = _do_reconnect(relay_url, code, g_token)
        notif = _recv(h_ws, timeout=3.0)
        try:
            assert notif is not None
            assert notif["type"] == "relay_peer_connected"
        finally:
            h_ws.close(); new_g_ws.close()

    def test_reconnect_after_room_expired(self, relay_url, request, monkeypatch):
        """Simulate relay restart by clearing _rooms — reconnect returns room_not_found."""
        if _is_external(request):
            pytest.skip("Cannot simulate room expiry on external relay")
        import network.relay as relay_mod
        h_ws, code, h_token = _do_host(relay_url)
        g_ws, g_token = _do_guest(relay_url, code)
        _recv(h_ws)
        h_ws.close(); g_ws.close()
        relay_mod._rooms.clear()
        ws, resp = _do_reconnect(relay_url, code, g_token)
        ws.close()
        assert resp["type"] == "relay_error"


# ── TestReconnectionEdgeCases ─────────────────────────────────────────────────


class TestReconnectionEdgeCases:

    def test_new_guest_blocked_after_first_guest_disconnects(self, relay_url):
        """Room slot stays locked for the original token even after disconnect.

        Documents current behavior: once two players have been assigned to a
        room, the room is permanently "full" from the relay's perspective.
        A third party cannot fill the vacated slot; only the original token
        can reconnect.
        """
        h_ws, code, _ = _do_host(relay_url)
        g_ws, _ = _do_guest(relay_url, code, "Original")
        _recv(h_ws)  # drain peer_connected
        g_ws.close()
        time.sleep(0.05)
        _recv(h_ws)  # drain peer_disconnected

        ws2 = _open(relay_url)
        _send(ws2, {"type": "relay_join", "room_code": code, "player_name": "Intruder", "version": "1"})
        msg = _recv(ws2)
        try:
            assert msg is not None
            assert msg["type"] == "relay_error"
            # is_full=True because the disconnected guest's token is still in players
            assert msg["code"] == "room_not_found"
        finally:
            h_ws.close(); ws2.close()

    def test_both_disconnect_then_both_reconnect(self, relay_url):
        """Both players disconnect then reconnect; second reconnect notifies the first."""
        h_ws, code, h_token = _do_host(relay_url)
        g_ws, g_token = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected

        h_ws.close()
        g_ws.close()
        time.sleep(0.1)

        # Host reconnects first
        new_h_ws, h_resp = _do_reconnect(relay_url, code, h_token)
        assert h_resp["type"] == "relay_reconnected"

        # Guest reconnects second → host gets relay_peer_connected
        new_g_ws, g_resp = _do_reconnect(relay_url, code, g_token)
        assert g_resp["type"] == "relay_reconnected"

        notif = _recv(new_h_ws, timeout=3.0)
        try:
            assert notif is not None
            assert notif["type"] == "relay_peer_connected"
        finally:
            new_h_ws.close(); new_g_ws.close()

    def test_rapid_reconnect_same_player(self, relay_url):
        """Guest reconnects 3× in quick succession; no WS-pointer corruption."""
        h_ws, code, _ = _do_host(relay_url)
        g_ws, g_token = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected

        for i in range(3):
            g_ws.close()
            time.sleep(0.05)
            _recv(h_ws)  # drain peer_disconnected
            g_ws, resp = _do_reconnect(relay_url, code, g_token)
            assert resp["type"] == "relay_reconnected", f"Reconnect #{i + 1} failed: {resp}"
            _recv(h_ws)  # drain peer_connected

        # After 3 reconnects, forwarding still works
        _send(g_ws, _game(seq=99))
        received = _recv(h_ws, timeout=2.0)
        try:
            assert received is not None
            assert received["seq"] == 99
        finally:
            h_ws.close(); g_ws.close()

    def test_host_reconnects_guest_already_waiting(self, relay_url):
        """Host drops mid-game; guest stays; host reconnects; forwarding resumes."""
        h_ws, code, h_token = _do_host(relay_url)
        g_ws, _ = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected

        h_ws.close()
        time.sleep(0.05)
        _recv(g_ws)  # drain peer_disconnected

        new_h_ws, resp = _do_reconnect(relay_url, code, h_token)
        assert resp["type"] == "relay_reconnected"
        _recv(g_ws)  # drain peer_connected

        _send(g_ws, _game(seq=1, origin="guest"))
        msg_at_host = _recv(new_h_ws, timeout=2.0)
        try:
            assert msg_at_host is not None
            assert msg_at_host["origin"] == "guest"
        finally:
            new_h_ws.close(); g_ws.close()

    def test_host_joins_own_room_as_guest(self, relay_url):
        """Documents edge-case: host can relay_join their own open room.

        A second connection from the same host process creates a second player
        slot, making the room self-looped.  This documents (and locks in) that
        behavior so future changes break this test explicitly.
        """
        h_ws, code, _ = _do_host(relay_url, "Solo")
        ws2 = _open(relay_url)
        _send(ws2, {"type": "relay_join", "room_code": code, "player_name": "Solo2", "version": "1"})
        join_resp = _recv(ws2)
        peer_notif = _recv(h_ws)
        try:
            # Join succeeds because room had only 1 player
            assert join_resp is not None
            assert join_resp["type"] == "relay_created"
            # Original host is notified of the "new peer"
            assert peer_notif is not None
            assert peer_notif["type"] == "relay_peer_connected"
            # Messages from ws2 are forwarded to h_ws
            _send(ws2, _game(seq=42))
            fwd = _recv(h_ws, timeout=2.0)
            assert fwd is not None and fwd["seq"] == 42
        finally:
            h_ws.close(); ws2.close()

    def test_dead_spectator_removed_on_forward(self, relay_url):
        """Relay removes a dead spectator and continues forwarding without crashing."""
        h_ws, code, _ = _do_host(relay_url)
        g_ws, _ = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected
        s_ws = _do_spectate(relay_url, code)

        s_ws.close()  # spectator drops abruptly
        time.sleep(0.05)

        # Players can still exchange messages
        _send(h_ws, _game(seq=1))
        received = _recv(g_ws, timeout=2.0)
        try:
            assert received is not None
            assert received["seq"] == 1
        finally:
            h_ws.close(); g_ws.close()


# ── TestDisconnect ─────────────────────────────────────────────────────────────


class TestDisconnect:

    def test_peer_disconnect_notification(self, relay_url):
        h_ws, code, _ = _do_host(relay_url)
        g_ws, _ = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected
        g_ws.close()
        notif = _recv(h_ws, timeout=3.0)
        h_ws.close()
        assert notif is not None
        assert notif["type"] == "relay_peer_disconnected"

    def test_silent_both_disconnect(self, relay_url):
        """Both players drop simultaneously; relay stays operational."""
        h_ws, code, _ = _do_host(relay_url)
        g_ws, _ = _do_guest(relay_url, code)
        _recv(h_ws)
        h_ws.close()
        g_ws.close()
        time.sleep(0.1)

        # Relay should still accept new connections
        new_ws, new_code, _ = _do_host(relay_url)
        new_ws.close()
        assert len(new_code) == 6


# ── TestHealthCheck ────────────────────────────────────────────────────────────


class TestHealthCheck:

    def test_health_check_returns_200(self, relay_url):
        """HTTP GET /health returns 200 OK (used by Render.com health probes)."""
        http_url = relay_url.replace("ws://", "http://").replace("wss://", "https://")
        resp = urllib.request.urlopen(f"{http_url}/health", timeout=5)
        assert resp.status == 200


# ── TestServerLimits ───────────────────────────────────────────────────────────


class TestServerLimits:

    def test_server_full(self, relay_url, request, monkeypatch):
        """relay_create fails with server_full when room limit is reached."""
        if _is_external(request):
            pytest.skip("Cannot control MAX_ROOMS on external relay")
        import network.relay as relay_mod
        monkeypatch.setattr(relay_mod, "_MAX_ROOMS", 1)

        ws1, _, _ = _do_host(relay_url, "Host1")
        ws2 = _open(relay_url)
        _send(ws2, {"type": "relay_create", "player_name": "Host2", "version": "1"})
        msg = _recv(ws2)
        try:
            assert msg is not None
            assert msg["type"] == "relay_error"
            assert msg["code"] == "server_full"
        finally:
            ws1.close(); ws2.close()

    def test_room_code_uniqueness(self, relay_url):
        """Ten rooms all get distinct 6-character uppercase-alphanumeric codes."""
        alphanum = set(string.ascii_uppercase + string.digits)
        codes = []
        connections = []
        try:
            for _ in range(10):
                ws, code, _ = _do_host(relay_url)
                connections.append(ws)
                codes.append(code)
        finally:
            for ws in connections:
                ws.close()
        assert len(set(codes)) == 10, f"Duplicate room codes generated: {codes}"
        for code in codes:
            assert len(code) == 6
            assert all(c in alphanum for c in code)


# ── TestRelayClientIntegration ─────────────────────────────────────────────────


class TestRelayClientIntegration:

    def test_client_create_room(self, relay_url):
        rc = RelayClient(relay_url=relay_url, role="host", player_name="TestHost")
        rc.set_message_handler(lambda msg: None)
        code = rc.create_room(timeout=10.0)
        rc.stop()
        assert code is not None
        assert len(code) == 6

    def test_client_join_room(self, relay_url):
        h_ws, code, _ = _do_host(relay_url)
        rc = RelayClient(relay_url=relay_url, role="guest", player_name="TestGuest")
        rc.set_message_handler(lambda msg: None)
        ok = rc.join_room(code, timeout=10.0)
        rc.stop()
        h_ws.close()
        assert ok is True

    def test_client_reconnect_returns_false_on_error(self, relay_url):
        """reconnect() must return False when the relay rejects the token.

        Regression test: an earlier version returned True even on relay_error
        because the _room_ready event was set on both success and error paths.
        """
        rc = RelayClient(relay_url=relay_url, role="host", player_name="Tester")
        rc.set_message_handler(lambda msg: None)
        code = rc.create_room(timeout=10.0)
        assert code is not None, "create_room failed — is the relay running?"
        # Inject a bad token to force relay_error bad_token on reconnect
        rc._token = "baaaaadtoken" * 4
        result = rc.reconnect(timeout=5.0)
        rc.stop()
        assert result is False, (
            "reconnect() returned True despite relay_error — regression!"
        )

    def test_client_relay_messages_not_delivered_to_handler(self, relay_url):
        """relay_* control messages are intercepted; the game handler never sees them."""
        rc = RelayClient(relay_url=relay_url, role="host", player_name="Filter")
        delivered: list = []
        rc.set_message_handler(delivered.append)
        code = rc.create_room(timeout=10.0)
        assert code is not None

        # Trigger relay_peer_connected by having a guest join
        g_ws, _ = _do_guest(relay_url, code)
        rc.wait_for_peer(timeout=5.0)
        time.sleep(0.1)

        rc.stop()
        g_ws.close()

        relay_ctrl = [m for m in delivered if str(m.get("type", "")).startswith("relay_")]
        assert relay_ctrl == [], (
            f"relay_* messages leaked into game handler: {relay_ctrl}"
        )

    def test_client_retry_on_unavailable_then_available(self, monkeypatch):
        """RelayClient retries when the relay is initially unavailable.

        The relay starts 1 second after the client begins connecting.
        RelayClient's first attempt fails immediately (ConnectionRefused),
        then waits 3 s before retrying — by which point the relay is up.
        """
        import asyncio
        import network.relay as relay_mod
        import websockets

        monkeypatch.setattr(relay_mod, "_rooms", {})

        sock = socket.socket()
        sock.bind(("", 0))
        port = sock.getsockname()[1]
        sock.close()
        url = f"ws://127.0.0.1:{port}"

        # Start RelayClient immediately (relay not listening yet)
        rc = RelayClient(relay_url=url, role="host", player_name="Retry")
        rc.set_message_handler(lambda msg: None)
        result_box: list = []

        def _try():
            result_box.append(rc.create_room(timeout=20.0))

        t = threading.Thread(target=_try, daemon=True)
        t.start()

        # Wait 1 s, then start the in-process relay (first retry fires at ~3 s)
        time.sleep(1.0)

        loop = asyncio.new_event_loop()
        ready = threading.Event()
        stop_holder: list = []

        async def _serve() -> None:
            stop_event = asyncio.Event()
            stop_holder.append(stop_event)
            async with websockets.serve(
                relay_mod._handle, "127.0.0.1", port,
                process_request=relay_mod._process_request,
            ):
                ready.set()
                await stop_event.wait()

        threading.Thread(
            target=lambda: loop.run_until_complete(_serve()), daemon=True
        ).start()
        assert ready.wait(timeout=5.0), "Delayed relay failed to start"

        t.join(timeout=20.0)
        rc.stop()
        if stop_holder:
            loop.call_soon_threadsafe(stop_holder[0].set)

        assert result_box, "create_room never returned (client thread hung)"
        assert result_box[0] is not None, (
            "create_room returned None — client gave up before relay started"
        )


# ── TestAntiCheat ──────────────────────────────────────────────────────────────


class TestAntiCheat:
    """Exercises server-side RoomValidator through the relay message path.

    The validator initialises when ``game_start`` is received, then validates
    every subsequent ``move`` message before forwarding it.
    """

    # Colors that match the validator's Team comparison (r channel used for identity)
    _GAME_START = {
        "type": "game_start",
        "team_r": {"r": 64,  "g": 180, "b": 232},
        "team_l": {"r": 255, "g": 140, "b": 0},
    }
    # Legal opening move: e-pawn two squares (row 1 col 4 → row 3 col 4, team_r)
    _LEGAL_MOVE = {
        "type": "move",
        "seq": 1,
        "from_row": 1, "from_col": 4,
        "to_row":   3, "to_col":   4,
        "piece": "Pawn",
        "flags": {},
        "board_hash": "",
    }
    # Illegal move: king teleports five ranks forward
    _ILLEGAL_MOVE = {
        "type": "move",
        "seq": 1,
        "from_row": 0, "from_col": 4,
        "to_row":   5, "to_col":   4,
        "piece": "King",
        "flags": {},
        "board_hash": "",
    }

    @staticmethod
    def _anticheat_available() -> bool:
        import network.relay as relay_mod
        return getattr(relay_mod, "_ANTICHEAT_AVAILABLE", False)

    def test_legal_move_forwarded(self, relay_url):
        if not self._anticheat_available():
            pytest.skip("RoomValidator not available — anti-cheat disabled")
        h_ws, code, _ = _do_host(relay_url)
        g_ws, _ = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected
        _send(h_ws, self._GAME_START)
        _recv(g_ws)  # guest receives game_start (forwarded)
        _send(h_ws, self._LEGAL_MOVE)
        received = _recv(g_ws, timeout=3.0)
        try:
            assert received is not None, "Legal move was NOT forwarded to guest"
            assert received["type"] == "move"
        finally:
            h_ws.close(); g_ws.close()

    def test_illegal_move_rejected(self, relay_url):
        if not self._anticheat_available():
            pytest.skip("RoomValidator not available — anti-cheat disabled")
        h_ws, code, _ = _do_host(relay_url)
        g_ws, _ = _do_guest(relay_url, code)
        _recv(h_ws)  # drain peer_connected
        _send(h_ws, self._GAME_START)
        _recv(g_ws)  # guest receives game_start
        _send(h_ws, self._ILLEGAL_MOVE)
        error_msg = _recv(h_ws, timeout=3.0)
        nothing   = _recv(g_ws, timeout=0.5)
        try:
            assert error_msg is not None, "Expected relay_error illegal_move from relay"
            assert error_msg["type"] == "relay_error"
            assert error_msg["code"] == "illegal_move"
            assert nothing is None, f"Guest received the illegal move: {nothing}"
        finally:
            h_ws.close(); g_ws.close()


# ── TestGameProtocolForwarding ─────────────────────────────────────────────────


class TestGameProtocolForwarding:
    """Verify that every actual game-protocol message type passes through the
    relay unchanged — guaranteeing identical behaviour with and without relay.

    Each test sends a real game message from one side and asserts the other
    side receives an identical copy.  The relay must NOT modify, drop, or
    reorder game-layer messages.
    """

    def _pair(self, relay_url):
        """Return (h_ws, g_ws) with both connected and relay_peer_connected drained."""
        h_ws, code, _ = _do_host(relay_url)
        g_ws, _       = _do_guest(relay_url, code)
        _recv(h_ws)    # drain relay_peer_connected on host side
        return h_ws, g_ws

    # ── Negotiation messages (host → guest) ──────────────────────────────────

    def test_hello_forwarded(self, relay_url):
        h_ws, g_ws = self._pair(relay_url)
        msg = {"type": "hello", "version": "1", "player_name": "Alice", "role": "host"}
        _send(h_ws, msg)
        received = _recv(g_ws)
        try:
            assert received == msg, f"hello not forwarded intact: {received}"
        finally:
            h_ws.close(); g_ws.close()

    def test_game_setup_forwarded(self, relay_url):
        h_ws, g_ws = self._pair(relay_url)
        msg = {"type": "game_setup", "version": "1",
               "host_name": "Alice", "guest_name": "Bob"}
        _send(h_ws, msg)
        received = _recv(g_ws)
        try:
            assert received == msg
        finally:
            h_ws.close(); g_ws.close()

    def test_color_chosen_forwarded(self, relay_url):
        h_ws, g_ws = self._pair(relay_url)
        msg = {"type": "color_chosen", "team_key": "r", "color_idx": 3}
        _send(h_ws, msg)
        received = _recv(g_ws)
        try:
            assert received == msg
        finally:
            h_ws.close(); g_ws.close()

    def test_war_games_choice_forwarded(self, relay_url):
        h_ws, g_ws = self._pair(relay_url)
        msg = {"type": "war_games_choice", "team_key": "r", "is_ai": False}
        _send(h_ws, msg)
        received = _recv(g_ws)
        try:
            assert received == msg
        finally:
            h_ws.close(); g_ws.close()

    def test_game_start_forwarded(self, relay_url):
        """game_start (with team colors) reaches guest and is not consumed by relay."""
        h_ws, g_ws = self._pair(relay_url)
        msg = {
            "type": "game_start",
            "team_r": {"r": 65,  "g": 180, "b": 232},
            "team_l": {"r": 255, "g": 140, "b": 0},
        }
        _send(h_ws, msg)
        received = _recv(g_ws)
        try:
            assert received == msg, (
                "game_start must be forwarded to guest unchanged; "
                "relay should not strip or modify it"
            )
        finally:
            h_ws.close(); g_ws.close()

    # ── Move round-trip (both directions) ────────────────────────────────────

    def test_move_forwarded_host_to_guest(self, relay_url):
        h_ws, g_ws = self._pair(relay_url)
        msg = {
            "type": "move", "seq": 1,
            "from_row": 1, "from_col": 4, "to_row": 3, "to_col": 4,
            "piece": "Pawn", "flags": {}, "board_hash": "abc123",
        }
        _send(h_ws, msg)
        received = _recv(g_ws)
        try:
            assert received == msg
        finally:
            h_ws.close(); g_ws.close()

    def test_move_ack_forwarded_guest_to_host(self, relay_url):
        h_ws, g_ws = self._pair(relay_url)
        msg = {"type": "move_ack", "seq": 1, "status": "ok", "board_hash": "abc123"}
        _send(g_ws, msg)
        received = _recv(h_ws)
        try:
            assert received == msg
        finally:
            h_ws.close(); g_ws.close()

    # ── Keepalive (ping → pong round-trip through relay) ─────────────────────

    def test_ping_forwarded(self, relay_url):
        h_ws, g_ws = self._pair(relay_url)
        msg = {"type": "ping", "seq": 42}
        _send(h_ws, msg)
        received = _recv(g_ws)
        try:
            assert received == msg, "ping must pass through relay unchanged"
        finally:
            h_ws.close(); g_ws.close()

    def test_pong_forwarded(self, relay_url):
        h_ws, g_ws = self._pair(relay_url)
        msg = {"type": "pong", "seq": 42}
        _send(g_ws, msg)
        received = _recv(h_ws)
        try:
            assert received == msg, "pong must pass through relay unchanged"
        finally:
            h_ws.close(); g_ws.close()

    # ── Post-game reset ───────────────────────────────────────────────────────

    def test_new_game_forwarded(self, relay_url):
        h_ws, g_ws = self._pair(relay_url)
        msg = {"type": "new_game"}
        _send(h_ws, msg)
        received = _recv(g_ws)
        try:
            assert received == msg
        finally:
            h_ws.close(); g_ws.close()

    # ── Desync recovery ───────────────────────────────────────────────────────

    def test_board_sync_request_forwarded(self, relay_url):
        h_ws, g_ws = self._pair(relay_url)
        msg = {"type": "board_sync_request"}
        _send(h_ws, msg)
        received = _recv(g_ws)
        try:
            assert received == msg
        finally:
            h_ws.close(); g_ws.close()

    def test_board_sync_forwarded(self, relay_url):
        h_ws, g_ws = self._pair(relay_url)
        msg = {"type": "board_sync", "grid": [], "peace_time": 0,
               "current_team_key": "r", "move_count": 5}
        _send(g_ws, msg)
        received = _recv(h_ws)
        try:
            assert received == msg
        finally:
            h_ws.close(); g_ws.close()
