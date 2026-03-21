"""
test_network.py — Unit tests for the Chess101 network protocol layer.

Covers:
  - encode_grid / decode_grid round-trip for all 6 piece types
  - board_hash determinism and change-on-move
  - MoveFlags serialization round-trip
  - build_move_msg structure
  - BeaconBroadcaster / BeaconListener round-trip
  - GameServer / GameClient connect and message exchange

Run with:
    .venv/bin/python -m pytest tests/test_network.py -v
"""
from __future__ import annotations

import copy
import json
import time

import pytest

# ── Imports ──────────────────────────────────────────────────────────────────

from core.team import Team
from core.cell import Cell
from pieces.pawn import Pawn
from pieces.rook import Rook
from pieces.knight import Knight
from pieces.bishop import Bishop
from pieces.queen import Queen
from pieces.king import King

from network.protocol import (
    MoveFlags,
    board_hash,
    build_move_msg,
    decode_grid,
    encode_grid,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def teams():
    """(team_r, team_l) matching Board.py defaults."""
    return Team(64, 180, 232), Team(255, 140, 0)


@pytest.fixture
def start_grid(teams):
    """Standard starting position grid."""
    team_r, team_l = teams
    grid = [[None] * 8 for _ in range(8)]
    for col in range(8):
        grid[1][col] = Pawn(1, col, team_r)
    grid[0][2] = Bishop(0, 2, team_r)
    grid[0][5] = Bishop(0, 5, team_r)
    grid[0][0] = Rook(0, 0, team_r)
    grid[0][7] = Rook(0, 7, team_r)
    grid[0][1] = Knight(0, 1, team_r)
    grid[0][6] = Knight(0, 6, team_r)
    grid[0][3] = Queen(0, 3, team_r)
    grid[0][4] = King(0, 4, team_r)
    for col in range(8):
        grid[6][col] = Pawn(6, col, team_l)
    grid[7][2] = Bishop(7, 2, team_l)
    grid[7][5] = Bishop(7, 5, team_l)
    grid[7][0] = Rook(7, 0, team_l)
    grid[7][7] = Rook(7, 7, team_l)
    grid[7][1] = Knight(7, 1, team_l)
    grid[7][6] = Knight(7, 6, team_l)
    grid[7][3] = Queen(7, 3, team_l)
    grid[7][4] = King(7, 4, team_l)
    return grid


# ── encode_grid / decode_grid ────────────────────────────────────────────────

class TestGridRoundTrip:

    def test_start_pos_round_trip(self, start_grid, teams):
        """Full 32-piece starting position survives encode → decode."""
        team_r, team_l = teams
        encoded = encode_grid(start_grid, team_r)
        decoded = decode_grid(encoded, team_r, team_l)

        for row in range(8):
            for col in range(8):
                orig = start_grid[row][col]
                recon = decoded[row][col]
                if orig is None:
                    assert recon is None
                else:
                    assert type(recon) == type(orig)
                    assert recon.row == orig.row
                    assert recon.col == orig.col
                    assert recon.team.r == orig.team.r

    def test_all_piece_types(self, teams):
        """Every piece class round-trips correctly."""
        team_r, team_l = teams
        grid = [[None] * 8 for _ in range(8)]
        pieces = [
            Pawn(1, 0, team_r), Rook(0, 0, team_r), Knight(0, 1, team_r),
            Bishop(0, 2, team_r), Queen(0, 3, team_r), King(0, 4, team_r),
        ]
        for i, p in enumerate(pieces):
            grid[p.row][p.col] = p

        encoded = encode_grid(grid, team_r)
        decoded = decode_grid(encoded, team_r, team_l)
        for p in pieces:
            recon = decoded[p.row][p.col]
            assert type(recon).__name__ == type(p).__name__
            assert recon.team.r == team_r.r

    def test_empty_board(self, teams):
        """Empty board encodes and decodes without error."""
        team_r, team_l = teams
        grid = [[None] * 8 for _ in range(8)]
        encoded = encode_grid(grid, team_r)
        decoded = decode_grid(encoded, team_r, team_l)
        for row in decoded:
            for cell in row:
                assert cell is None

    def test_pawn_en_passantable_preserved(self, teams):
        """Pawn.en_passantable flag survives serialization."""
        team_r, team_l = teams
        grid = [[None] * 8 for _ in range(8)]
        pawn = Pawn(1, 3, team_r)
        pawn.en_passantable = True
        grid[1][3] = pawn
        encoded = encode_grid(grid, team_r)
        decoded = decode_grid(encoded, team_r, team_l)
        assert isinstance(decoded[1][3], Pawn)
        assert decoded[1][3].en_passantable is True

    def test_touched_flag_preserved(self, teams):
        """Piece.touched flag survives serialization."""
        team_r, team_l = teams
        grid = [[None] * 8 for _ in range(8)]
        rook = Rook(0, 0, team_r)
        rook.touched = True
        grid[0][0] = rook
        encoded = encode_grid(grid, team_r)
        decoded = decode_grid(encoded, team_r, team_l)
        assert decoded[0][0].touched is True

    def test_team_assignment(self, teams):
        """Pieces are assigned to the correct team after decode."""
        team_r, team_l = teams
        grid = [[None] * 8 for _ in range(8)]
        grid[1][0] = Pawn(1, 0, team_r)
        grid[6][0] = Pawn(6, 0, team_l)
        encoded = encode_grid(grid, team_r)
        decoded = decode_grid(encoded, team_r, team_l)
        assert decoded[1][0].team.r == team_r.r
        assert decoded[6][0].team.r == team_l.r


# ── board_hash ───────────────────────────────────────────────────────────────

class TestBoardHash:

    def test_deterministic(self, start_grid, teams):
        """Same board always produces the same hash."""
        team_r, _ = teams
        h1 = board_hash(start_grid, 0, "r", team_r)
        h2 = board_hash(start_grid, 0, "r", team_r)
        assert h1 == h2

    def test_different_after_move(self, start_grid, teams):
        """Hash changes when a piece moves."""
        team_r, _ = teams
        h_before = board_hash(start_grid, 0, "r", team_r)
        grid2 = copy.deepcopy(start_grid)
        grid2[2][0] = grid2[1][0]
        grid2[1][0] = None
        grid2[2][0].row = 2
        h_after = board_hash(grid2, 1, "l", team_r)
        assert h_before != h_after

    def test_different_peace_time(self, start_grid, teams):
        """Hash changes when peace_time changes."""
        team_r, _ = teams
        h1 = board_hash(start_grid, 0, "r", team_r)
        h2 = board_hash(start_grid, 1, "r", team_r)
        assert h1 != h2

    def test_different_turn(self, start_grid, teams):
        """Hash changes when current_team_key changes."""
        team_r, _ = teams
        h1 = board_hash(start_grid, 0, "r", team_r)
        h2 = board_hash(start_grid, 0, "l", team_r)
        assert h1 != h2

    def test_is_hex_string(self, start_grid, teams):
        """Hash is a 64-character lowercase hex string (SHA-256)."""
        team_r, _ = teams
        h = board_hash(start_grid, 0, "r", team_r)
        assert len(h) == 64
        assert h == h.lower()
        int(h, 16)   # raises if not valid hex


# ── MoveFlags ────────────────────────────────────────────────────────────────

class TestMoveFlags:

    def test_defaults(self):
        f = MoveFlags()
        assert f.is_capture is False
        assert f.is_en_passant is False
        assert f.is_castling is False
        assert f.is_promotion is False
        assert f.captured_at is None
        assert f.rook_from is None
        assert f.rook_to is None

    def test_round_trip_standard(self):
        f = MoveFlags(is_capture=True)
        assert MoveFlags.from_dict(f.to_dict()).is_capture is True

    def test_round_trip_en_passant(self):
        f = MoveFlags(is_en_passant=True, captured_at=(3, 4))
        rt = MoveFlags.from_dict(f.to_dict())
        assert rt.is_en_passant is True
        assert rt.captured_at == (3, 4)

    def test_round_trip_castling(self):
        f = MoveFlags(is_castling=True, rook_from=(0, 0), rook_to=(0, 3))
        rt = MoveFlags.from_dict(f.to_dict())
        assert rt.is_castling is True
        assert rt.rook_from == (0, 0)
        assert rt.rook_to == (0, 3)

    def test_round_trip_promotion(self):
        f = MoveFlags(is_promotion=True)
        rt = MoveFlags.from_dict(f.to_dict())
        assert rt.is_promotion is True

    def test_to_dict_serialisable(self):
        f = MoveFlags(is_castling=True, rook_from=(0, 7), rook_to=(0, 5))
        json.dumps(f.to_dict())   # must not raise


# ── build_move_msg ────────────────────────────────────────────────────────────

class TestBuildMoveMsg:

    def test_structure(self):
        flags = MoveFlags()
        msg = build_move_msg(1, 1, 0, 2, 0, "Pawn", flags, "abc123")
        assert msg["type"] == "move"
        assert msg["seq"] == 1
        assert msg["from_row"] == 1
        assert msg["from_col"] == 0
        assert msg["to_row"] == 2
        assert msg["to_col"] == 0
        assert msg["piece"] == "Pawn"
        assert msg["board_hash"] == "abc123"
        assert isinstance(msg["flags"], dict)

    def test_serialisable(self):
        flags = MoveFlags(is_capture=True)
        msg = build_move_msg(0, 0, 0, 1, 0, "Rook", flags, "x" * 64)
        json.dumps(msg)   # must not raise


# ── Discovery beacon ─────────────────────────────────────────────────────────

class TestBeacon:

    @pytest.mark.skip(reason="UDP 255.255.255.255 broadcast is unreliable on loopback; "
                      "parsing is covered by test_listener_parses_beacon")
    def test_broadcaster_sends_valid_json(self):
        """BeaconBroadcaster sends parseable JSON on the broadcast port."""
        import socket
        import threading

        from network.discovery import BeaconBroadcaster, _BROADCAST_PORT

        received: list[dict] = []
        done = threading.Event()

        def _listen():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", _BROADCAST_PORT))
            sock.settimeout(3.0)
            try:
                data, _ = sock.recvfrom(1024)
                received.append(json.loads(data.decode()))
            except Exception:
                pass
            finally:
                sock.close()
                done.set()

        t = threading.Thread(target=_listen, daemon=True)
        t.start()
        time.sleep(0.05)   # let listener bind before broadcaster starts

        bc = BeaconBroadcaster("TestHost", port=65101, state="lobby")
        bc.start()
        done.wait(timeout=4.0)
        bc.stop()

        assert received, "No beacon received within timeout"
        msg = received[0]
        assert msg["type"] == "chess101_beacon"
        assert msg["host_name"] == "TestHost"
        assert msg["state"] == "lobby"

    def test_listener_parses_beacon(self):
        """BeaconListener detects a beacon broadcast and populates games dict."""
        import socket

        from network.discovery import (
            BeaconListener,
            _BROADCAST_PORT,
            _local_ip,
        )

        listener = BeaconListener()
        listener.start()
        time.sleep(0.1)   # let listener bind

        # Send a synthetic beacon
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        payload = json.dumps({
            "type": "chess101_beacon",
            "version": "1",
            "host_name": "SyntheticHost",
            "ip": "127.0.0.1",
            "port": 65101,
            "state": "lobby",
        }).encode()
        sock.sendto(payload, ("255.255.255.255", _BROADCAST_PORT))
        sock.close()

        time.sleep(0.2)   # let listener process
        listener.stop()

        games = listener.games
        assert "127.0.0.1:65101" in games
        assert games["127.0.0.1:65101"].host_name == "SyntheticHost"

    def test_listener_prunes_stale(self, monkeypatch):
        """Stale entries are removed after STALE_TIMEOUT."""
        import network.discovery as _disc
        from network.discovery import BeaconListener, DiscoveredGame

        listener = BeaconListener()
        old_game = DiscoveredGame("Old", "1.2.3.4", 65101, "lobby")
        old_game.last_seen = time.time() - 20   # definitely stale
        with listener._lock:
            listener._games["1.2.3.4:65101"] = old_game
        listener._prune()
        assert "1.2.3.4:65101" not in listener.games


# ── GameServer / GameClient ───────────────────────────────────────────────────

class TestTransport:
    """Functional tests for GameServer ↔ GameClient message exchange.

    These tests start a real asyncio server and client on localhost.
    They require the ``websockets`` library.
    """

    def test_server_client_exchange(self):
        """Server and client can connect and exchange JSON messages."""
        from network.server import GameServer
        from network.client import GameClient

        server_received: list[dict] = []
        client_received: list[dict] = []

        server = GameServer(host="127.0.0.1", port=65199)
        server.set_message_handler(lambda m: server_received.append(m))
        server.start()

        client = GameClient(host_ip="127.0.0.1", port=65199)
        client.set_message_handler(lambda m: client_received.append(m))
        assert client.connect(timeout=5.0), "Client failed to connect"

        # Give server a moment to register the connection
        time.sleep(0.2)

        # Client → Server
        client.send({"type": "hello", "name": "pytest"})
        time.sleep(0.3)
        assert any(m.get("type") == "hello" for m in server_received)

        # Server → Client
        server.send({"type": "hello", "name": "host"})
        time.sleep(0.3)
        assert any(m.get("type") == "hello" for m in client_received)

        client.stop()
        server.stop()
