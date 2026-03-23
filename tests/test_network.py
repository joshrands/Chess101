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


# ── NetworkedBoard (Phase 2) ──────────────────────────────────────────────────


class _FakeNet:
    """Minimal stand-in for GameServer / GameClient used in NetworkedBoard tests."""

    def __init__(self):
        self.sent: list[dict] = []
        self._handler = None

    def send(self, msg: dict) -> None:
        self.sent.append(msg)

    def set_message_handler(self, cb) -> None:
        self._handler = cb

    def inject(self, msg: dict) -> None:
        """Simulate an incoming message arriving from the peer."""
        if self._handler:
            self._handler(msg)


def _make_networked_board(local_team_key: str = "r") -> "NetworkedBoard":
    """Instantiate a NetworkedBoard with a fake transport (no real sockets)."""
    from game.networked_board import NetworkedBoard
    net = _FakeNet()
    board = NetworkedBoard(net=net, local_team_key=local_team_key)
    board.initialize_game_board()
    return board


class TestNetworkedBoardOnLocalMove:
    """_on_local_move hook: builds flags, sends a move msg, waits for ack."""

    def _simulate_local_move(self, board, fr, fc, tr, tc, pre_capture=None):
        """Replicate the grid state that exists when _on_local_move fires."""
        board.grid[tr][tc] = board.grid[fr][fc]
        board.grid[fr][fc] = None
        return pre_capture

    def test_sends_move_message_on_pawn_advance(self, teams):
        """After a local pawn move, a move message is queued for the peer."""
        board = _make_networked_board("r")
        net = board._net

        # Pre-inject ack so _on_local_move's polling loop exits immediately.
        net.inject({"type": "move_ack", "seq": 1, "status": "ok"})

        # Replicate do_turn grid state: piece moved to (2,0), (1,0) cleared
        self._simulate_local_move(board, 1, 0, 2, 0)
        board._on_local_move(1, 0, 2, 0, None)

        assert any(m["type"] == "move" for m in net.sent), \
            "Expected a move message to be sent"
        move_msg = next(m for m in net.sent if m["type"] == "move")
        assert move_msg["from_row"] == 1
        assert move_msg["from_col"] == 0
        assert move_msg["to_row"]   == 2
        assert move_msg["to_col"]   == 0
        assert move_msg["piece"]    == "Pawn"

    def test_move_flags_capture(self, teams):
        """is_capture is set when pre_capture is not None."""
        board = _make_networked_board("r")
        net = board._net
        net.inject({"type": "move_ack", "seq": 1, "status": "ok"})

        team_r, team_l = teams
        captured_pawn = Pawn(3, 4, team_l)
        board.grid[2][4] = Pawn(2, 4, board.team_r)
        self._simulate_local_move(board, 2, 4, 3, 4)
        board._on_local_move(2, 4, 3, 4, captured_pawn)

        move_msg = next(m for m in net.sent if m["type"] == "move")
        assert move_msg["flags"]["is_capture"] is True

    def test_move_ack_timeout_sets_game_over(self, teams):
        """If no move_ack arrives within timeout, game_over is set."""
        import threading
        board = _make_networked_board("r")
        self._simulate_local_move(board, 1, 0, 2, 0)

        finished = threading.Event()

        def _call_hook():
            import game.networked_board as _nb
            orig = _nb._ACK_TIMEOUT_S
            _nb._ACK_TIMEOUT_S = 0.1
            try:
                board._on_local_move(1, 0, 2, 0, None)
            finally:
                _nb._ACK_TIMEOUT_S = orig
            finished.set()

        t = threading.Thread(target=_call_hook, daemon=True)
        t.start()
        finished.wait(timeout=2.0)
        assert board.game_over is True


class TestNetworkedBoardApplyRemoteMove:
    """_apply_remote_move correctly updates the grid and sends move_ack."""

    def test_applies_move_to_grid(self, teams):
        """Remote move updates grid[tr][tc] and clears grid[fr][fc]."""
        board = _make_networked_board("r")
        net = board._net
        team_r, team_l = teams

        # team_l pawn at (6,0) → (5,0) (standard pawn push)
        piece_before = board.grid[6][0]
        assert piece_before is not None

        msg = build_move_msg(1, 6, 0, 5, 0, "Pawn",
                             MoveFlags(), board_hash(board.grid, 0, "l", board.team_r))
        board._apply_remote_move(msg)

        assert board.grid[5][0] is not None, "Piece should be at (5,0)"
        assert board.grid[6][0] is None,     "Source square should be empty"

    def test_sends_move_ack(self, teams):
        """After applying a remote move, a move_ack is sent back."""
        board = _make_networked_board("r")
        net = board._net

        h = board_hash(board.grid, 0, "l", board.team_r)
        msg = build_move_msg(1, 6, 0, 5, 0, "Pawn", MoveFlags(), h)
        board._apply_remote_move(msg)

        assert any(m["type"] == "move_ack" for m in net.sent)

    def test_desync_sends_board_sync_request(self, teams):
        """Hash mismatch after remote move → board_sync_request sent."""
        board = _make_networked_board("r")
        net = board._net

        # Deliberately wrong hash
        msg = build_move_msg(1, 6, 0, 5, 0, "Pawn", MoveFlags(), "wrong" * 13)
        board._apply_remote_move(msg)

        types = [m["type"] for m in net.sent]
        assert "move_ack" in types
        ack = next(m for m in net.sent if m["type"] == "move_ack")
        assert ack["status"] == "desync"
        assert "board_sync_request" in types


class TestNetworkedBoardOnGameOver:
    """_on_game_over sends a game_event message to the peer."""

    def test_sends_checkmate_event(self, teams):
        board = _make_networked_board("r")
        net = board._net
        board._on_game_over("checkmate", board.team_l)
        assert any(
            m["type"] == "game_event" and m["event"] == "checkmate"
            for m in net.sent
        )

    def test_sends_stalemate_event(self, teams):
        board = _make_networked_board("r")
        net = board._net
        board._on_game_over("stalemate", board.team_r)
        assert any(
            m["type"] == "game_event" and m["event"] == "stalemate"
            for m in net.sent
        )


class TestNetworkedBoardRemoteGameEvent:
    """Receiving game_event sets game_over."""

    def test_checkmate_sets_game_over(self, teams):
        board = _make_networked_board("r")
        net = board._net
        net.inject({"type": "game_event", "event": "checkmate", "losing_team_key": "r"})
        board._drain_incoming()
        assert board.game_over is True

    def test_stalemate_sets_game_over(self, teams):
        board = _make_networked_board("r")
        net = board._net
        net.inject({"type": "game_event", "event": "stalemate", "losing_team_key": "l"})
        board._drain_incoming()
        assert board.game_over is True


class TestNetworkedBoardWaitForRemoteMove:
    """_wait_for_remote_move sets game_over on timeout."""

    def test_timeout_sets_game_over(self):
        import game.networked_board as _nb
        board = _make_networked_board("r")
        orig = _nb._REMOTE_TIMEOUT_S
        _nb._REMOTE_TIMEOUT_S = 0.1
        try:
            board._wait_for_remote_move(timeout=0.1)
        finally:
            _nb._REMOTE_TIMEOUT_S = orig
        assert board.game_over is True

    def test_applies_move_when_available(self):
        """If a move is already queued, _wait_for_remote_move applies it immediately."""
        board = _make_networked_board("r")
        h = board_hash(board.grid, 0, "l", board.team_r)
        board._pending_remote_move = build_move_msg(1, 6, 0, 5, 0, "Pawn", MoveFlags(), h)
        board._wait_for_remote_move()
        # Move was applied — source should be empty
        assert board.grid[6][0] is None


class TestMdns:
    """Smoke tests for mDNS advertiser and listener (zeroconf may not be installed)."""

    def test_advertiser_start_stop_no_crash(self):
        """MdnsAdvertiser.start/stop should not raise even if zeroconf missing."""
        from network.mdns import MdnsAdvertiser
        adv = MdnsAdvertiser(host_name="TestHost", port=65198)
        adv.start()   # no-op if zeroconf not installed
        adv.stop()

    def test_listener_start_stop_no_crash(self):
        """MdnsListener.start/stop should not raise even if zeroconf missing."""
        from network.mdns import MdnsListener
        listener = MdnsListener()
        listener.start()
        listener.stop()

    def test_discovered_game_fields(self):
        """DiscoveredMdnsGame has the expected fields."""
        from network.mdns import DiscoveredMdnsGame
        g = DiscoveredMdnsGame(name="Alice", host_ip="10.0.0.1", port=65101)
        assert g.name    == "Alice"
        assert g.host_ip == "10.0.0.1"
        assert g.port    == 65101
        assert g.state   == "lobby"


# ── TestChessMatrix ─────────────────────────────────────────────────────────────


class TestChessMatrix:
    """Tests for network.chessmatrix encode/decode helpers."""

    def test_round_trip_basic(self):
        from network.chessmatrix import room_code_to_bytes, bytes_to_room_code
        for code in ("AAAAAA", "ZZZZZZ", "ABCDEF", "XKCDQR"):
            data = room_code_to_bytes(code)
            assert len(data) == 4
            assert bytes_to_room_code(data) == code

    def test_boundary_values(self):
        from network.chessmatrix import room_code_to_bytes, bytes_to_room_code
        # Minimum: AAAAAA → 0
        assert room_code_to_bytes("AAAAAA") == b"\x00\x00\x00\x00"
        assert bytes_to_room_code(b"\x00\x00\x00\x00") == "AAAAAA"
        # Maximum: ZZZZZZ → 26^6 - 1 = 308 915 775 = 0x126_7B08F
        import struct
        max_val = 26 ** 6 - 1
        max_bytes = struct.pack(">I", max_val)
        assert room_code_to_bytes("ZZZZZZ") == max_bytes
        assert bytes_to_room_code(max_bytes) == "ZZZZZZ"

    def test_invalid_inputs(self):
        import pytest
        from network.chessmatrix import room_code_to_bytes, bytes_to_room_code
        with pytest.raises(ValueError):
            room_code_to_bytes("ABC")          # too short
        with pytest.raises(ValueError):
            room_code_to_bytes("ABC123")       # contains digits (all-alpha required)
        with pytest.raises(ValueError):
            bytes_to_room_code(b"\xff\xff\xff\xff")   # value out of range

    def test_no_digits_allowed(self):
        import pytest
        from network.chessmatrix import room_code_to_bytes
        for bad in ("A1BCDE", "123456", "ABCDE1"):
            with pytest.raises(ValueError):
                room_code_to_bytes(bad)

    # ── encode() tests (mock the chessmatrix library) ──────────────────────

    def _make_raw(self, mapping: dict) -> list:
        """Build an 8×8 nested list (raw[row][col]) with given (row, col) → value."""
        raw = [[0] * 8 for _ in range(8)]
        for (row, col), val in mapping.items():
            raw[row][col] = val
        return raw

    def test_unknown_color_index_renders_as_white(self):
        """Color values outside 0-3 (structural / border cells) render as white."""
        from unittest.mock import patch
        import importlib
        # All cells return value 4 (not a data color — simulates white border cells)
        raw = [[4] * 8 for _ in range(8)]
        with patch.dict("sys.modules", {"chessmatrix": type("cm", (), {"encode": staticmethod(lambda d: raw)})()} ):
            import network.chessmatrix as cm_mod
            importlib.reload(cm_mod)
            grid = cm_mod.encode("AAAAAA")
        assert all(
            grid[r][c] == (255, 255, 255)
            for r in range(8) for c in range(8)
        ), "All unknown-index cells should render as white"

    def test_data_colors_map_correctly(self):
        """0=black, 1=red, 2=green, 3=blue in the encode output."""
        from unittest.mock import patch
        import importlib
        # raw[row][col]: put each color at a distinct (row=0, col) position
        raw = self._make_raw({(0, 0): 0, (0, 1): 1, (0, 2): 2, (0, 3): 3})
        with patch.dict("sys.modules", {"chessmatrix": type("cm", (), {"encode": staticmethod(lambda d: raw)})()} ):
            import network.chessmatrix as cm_mod
            importlib.reload(cm_mod)
            grid = cm_mod.encode("AAAAAA")
        # Library is row-major: raw[row][col] → grid[row][col] directly
        assert grid[0][0] == (0,   0,   0),   "BLACK at grid[0][0]"
        assert grid[0][1] == (220, 0,   0),   "RED at grid[0][1]"
        assert grid[0][2] == (0,   180, 0),   "GREEN at grid[0][2]"
        assert grid[0][3] == (0,   0,   220), "BLUE at grid[0][3]"

    def test_encode_preserves_row_major_layout(self):
        """Library raw[row][col] passes through directly to grid[row][col].

        Places a sentinel RED cell at raw[row=5][col=2].  encode() must
        preserve this: grid[row=5][col=2] = RED, not grid[row=2][col=5].
        """
        from unittest.mock import patch
        import importlib
        raw = self._make_raw({(5, 2): 1})   # raw[row=5][col=2] = RED
        with patch.dict("sys.modules", {"chessmatrix": type("cm", (), {"encode": staticmethod(lambda d: raw)})()} ):
            import network.chessmatrix as cm_mod
            importlib.reload(cm_mod)
            grid = cm_mod.encode("AAAAAA")
        assert grid[5][2] == (220, 0, 0), "Sentinel RED must appear at grid[row=5][col=2]"
        assert grid[2][5] == (0, 0, 0),   "Transposed position grid[row=2][col=5] must be black"
