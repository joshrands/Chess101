"""
test_networked_runner.py — unit tests for NetworkedGameRunner logic.

Covers:
  - _on_hello: sends rejoin_sync (not game_setup) when phase is PLAYING
  - _on_hello: sends game_setup during pre-game phases
  - _on_rejoin_sync: restores team colours, board grid, counters, net_seq
  - _remote_last_move: set by _apply_remote_move, cleared by _next_turn on local move

Run with:
    .venv/bin/python -m pytest tests/test_networked_runner.py -v
"""
from __future__ import annotations

import os
import sys
import types

import pytest

# ── Headless pygame (must be set before pygame is imported) ───────────────────
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

# Replace conftest's MagicMock rgbmatrix with the real FakeRGBMatrix so that
# _init_board()'s FakeRGBMatrix() calls succeed.
import simulator.fake_rgbmatrix as _frm  # noqa: E402

_rmod = types.ModuleType("rgbmatrix")
_rmod.RGBMatrix        = _frm.FakeRGBMatrix
_rmod.RGBMatrixOptions = _frm.FakeRGBMatrixOptions
_rmod.FrameCanvas      = _frm.FakeFrameCanvas
sys.modules["rgbmatrix"]      = _rmod
sys.modules["rgbmatrix.core"] = _rmod

_smbus_mod = types.ModuleType("smbus")
class _SMBus:
    def __init__(self, *a, **kw) -> None: pass
    def read_byte(self, *a, **kw) -> int: return 0
    def write_byte(self, *a, **kw) -> None: pass
_smbus_mod.SMBus = _SMBus
sys.modules["smbus"] = _smbus_mod

import pygame  # noqa: E402

from network.protocol import encode_grid, decode_grid, MoveFlags  # noqa: E402
from simulator.app import Phase  # noqa: E402
from simulator.networked_runner import NetworkedGameRunner, NetworkRole  # noqa: E402


# ── Module-scoped pygame surface (created once for the whole file) ─────────────

@pytest.fixture(scope="module")
def _pygame():
    pygame.init()
    pygame.display.set_mode((1200, 960))
    yield
    pygame.quit()


# ── Runner factories ──────────────────────────────────────────────────────────

def _make_host(_pygame) -> NetworkedGameRunner:
    """HOST runner fully initialised and advanced to PLAYING."""
    runner = NetworkedGameRunner(
        role=NetworkRole.HOST, host_ip=None, port=65190, player_name="Host")
    runner._init_board()
    b = runner._board
    b.team_r.r, b.team_r.g, b.team_r.b = 65, 180, 232
    b.team_l.r, b.team_l.g, b.team_l.b = 255, 140, 0
    b.computer_player_r = False
    b.computer_player_l = False
    runner._start_game()
    return runner


def _make_guest(_pygame) -> NetworkedGameRunner:
    """GUEST runner with board initialised (pre-game, not yet PLAYING)."""
    runner = NetworkedGameRunner(
        role=NetworkRole.GUEST, host_ip="127.0.0.1", port=65190, player_name="Guest")
    runner._init_board()
    b = runner._board
    b.team_r.r, b.team_r.g, b.team_r.b = 65, 180, 232
    b.team_l.r, b.team_l.g, b.team_l.b = 255, 140, 0
    b.computer_player_r = False
    b.computer_player_l = False
    runner._start_game()
    return runner


# ── _on_hello rejoin detection ────────────────────────────────────────────────

class TestOnHelloRejoinDetection:

    def test_sends_rejoin_sync_not_game_setup_when_playing(self, _pygame):
        """HOST in PLAYING sends rejoin_sync when a guest reconnects."""
        runner = _make_host(_pygame)
        assert runner.phase == Phase.PLAYING

        sent = []
        runner._net_send = lambda msg: sent.append(msg)

        runner._dispatch({
            "type": "hello",
            "version": "1",
            "player_name": "Guest",
            "role": "guest",
        })

        types_sent = [m["type"] for m in sent]
        assert "rejoin_sync" in types_sent, \
            "HOST should send rejoin_sync when phase is PLAYING"
        assert "game_setup" not in types_sent, \
            "HOST must not send game_setup on a rejoin"

    def test_sends_game_setup_before_playing(self, _pygame):
        """HOST in COLOR_PICK sends game_setup for a fresh connection."""
        runner = NetworkedGameRunner(
            role=NetworkRole.HOST, host_ip=None, port=65191, player_name="Host")
        runner._init_board()
        runner.phase = Phase.COLOR_PICK  # override NAME_ENTRY default
        assert runner.phase == Phase.COLOR_PICK

        sent = []
        runner._net_send = lambda msg: sent.append(msg)

        runner._dispatch({
            "type": "hello",
            "version": "1",
            "player_name": "Guest",
            "role": "guest",
        })

        types_sent = [m["type"] for m in sent]
        assert "game_setup" in types_sent
        assert "rejoin_sync" not in types_sent

    def test_rejoin_resets_waiting_for_ack(self, _pygame):
        """HOST clears _waiting_for_ack on rejoin so the game doesn't stall."""
        runner = _make_host(_pygame)
        runner._waiting_for_ack = True

        runner._net_send = lambda msg: None
        runner._dispatch({
            "type": "hello",
            "version": "1",
            "player_name": "Guest",
            "role": "guest",
        })

        assert runner._waiting_for_ack is False


# ── _on_rejoin_sync state restoration ─────────────────────────────────────────

class TestOnRejoinSync:

    def _make_rejoin_msg(self, runner: NetworkedGameRunner, **overrides) -> dict:
        """Build a rejoin_sync message from the runner's current state."""
        b = runner._board
        msg = runner._build_rejoin_sync()
        msg.update(overrides)
        return msg

    def test_restores_team_colours(self, _pygame):
        guest = _make_guest(_pygame)
        b = guest._board

        msg = self._make_rejoin_msg(guest,
            team_r={"r": 190, "g": 25, "b": 255, "name": "Purple"},
            team_l={"r": 245, "g": 125, "b": 0,   "name": "Orange"},
        )
        guest._dispatch(msg)

        assert b.team_r.r == 190
        assert b.team_r.name == "Purple"
        assert b.team_l.r == 245
        assert b.team_l.name == "Orange"

    def test_restores_peace_time_and_move_count(self, _pygame):
        guest = _make_guest(_pygame)

        msg = self._make_rejoin_msg(guest, peace_time=17, move_count=42)
        guest._dispatch(msg)

        assert guest.peace_time == 17
        assert guest._move_count == 42

    def test_restores_computer_player_flags(self, _pygame):
        guest = _make_guest(_pygame)

        msg = self._make_rejoin_msg(guest,
            computer_player_r=True,
            computer_player_l=False,
        )
        guest._dispatch(msg)

        assert guest._board.computer_player_r is True
        assert guest._board.computer_player_l is False

    def test_resets_net_seq_to_zero(self, _pygame):
        guest = _make_guest(_pygame)
        guest._net_seq = 99

        msg = self._make_rejoin_msg(guest)
        guest._dispatch(msg)

        assert guest._net_seq == 0

    def test_advances_to_playing_phase(self, _pygame):
        guest = _make_guest(_pygame)
        guest.phase = Phase.COLOR_PICK  # simulate mid-reconnect state

        msg = self._make_rejoin_msg(guest)
        guest._dispatch(msg)

        assert guest.phase == Phase.PLAYING

    def test_restores_current_team(self, _pygame):
        guest = _make_guest(_pygame)
        b = guest._board

        msg = self._make_rejoin_msg(guest, current_team_key="l")
        guest._dispatch(msg)

        assert guest._current_team is not None
        assert guest._current_team.r == b.team_l.r

    def test_restores_board_grid_piece_types(self, _pygame):
        """Piece types and team ownership survive the encode/decode round-trip."""
        host = _make_host(_pygame)
        guest = _make_guest(_pygame)

        # Move a host pawn forward so the board is non-trivially different
        host._board.grid[2][0] = host._board.grid[1][0]
        host._board.grid[2][0].row = 2
        host._board.grid[1][0] = None

        msg = host._build_rejoin_sync()
        # Reuse guest's team objects (same colours) for decode compatibility
        msg["team_r"] = {
            "r": guest._board.team_r.r,
            "g": guest._board.team_r.g,
            "b": guest._board.team_r.b,
            "name": guest._board.team_r.name,
        }
        msg["team_l"] = {
            "r": guest._board.team_l.r,
            "g": guest._board.team_l.g,
            "b": guest._board.team_l.b,
            "name": guest._board.team_l.name,
        }

        guest._dispatch(msg)

        from pieces.pawn import Pawn
        assert guest._board.grid[2][0] is not None
        assert isinstance(guest._board.grid[2][0], Pawn)
        assert guest._board.grid[1][0] is None


# ── _remote_last_move set/clear logic ─────────────────────────────────────────

class TestRemoteLastMove:

    def test_initially_none_after_reset(self, _pygame):
        runner = _make_host(_pygame)
        assert runner._remote_last_move is None

    def test_cleared_by_next_turn_when_local_move_pending(self, _pygame):
        """_next_turn clears _remote_last_move when a local move is being sent."""
        runner = _make_host(_pygame)
        runner._remote_last_move = (6, 0, 5, 0)

        # Simulate a pending local move (set before calling _next_turn)
        runner._pending_send_move = {
            "fr": 1, "fc": 0, "tr": 2, "tc": 0,
            "piece": "Pawn",
            "captured": None,
            "flags": MoveFlags(),
        }

        # Patch _net_send and super()._next_turn so we only test the clear logic
        runner._net_send = lambda msg: None
        original_next = runner.__class__.__bases__[0]._next_turn
        runner.__class__.__bases__[0]._next_turn = lambda self: None
        try:
            runner._next_turn()
        finally:
            runner.__class__.__bases__[0]._next_turn = original_next

        assert runner._remote_last_move is None

    def test_not_cleared_by_next_turn_without_local_move(self, _pygame):
        """_next_turn leaves _remote_last_move intact when no local move is pending."""
        runner = _make_host(_pygame)
        runner._remote_last_move = (6, 0, 5, 0)
        runner._pending_send_move = None

        original_next = runner.__class__.__bases__[0]._next_turn
        runner.__class__.__bases__[0]._next_turn = lambda self: None
        try:
            runner._next_turn()
        finally:
            runner.__class__.__bases__[0]._next_turn = original_next

        assert runner._remote_last_move == (6, 0, 5, 0)


# ═════════════════════════════════════════════════════════════════════════════
# Bug-fix tests — online-play guards
# ═════════════════════════════════════════════════════════════════════════════

import time  # noqa: E402 (placed here to avoid reorder with top-level imports)

from simulator.app import _CELL_PX  # noqa: E402


class _FakeRelay:
    """Minimal relay-client stub — records sent messages."""
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, msg: dict) -> None:
        self.sent.append(msg)

    def color_chosen_msgs(self) -> list[dict]:
        return [m for m in self.sent if m.get("type") == "color_chosen"]

    def war_games_msgs(self) -> list[dict]:
        return [m for m in self.sent if m.get("type") == "war_games_choice"]


def _click(row: int, col: int) -> pygame.event.Event:
    """Synthesise a MOUSEBUTTONDOWN at the centre pixel of board cell (row, col)."""
    px = col * _CELL_PX + _CELL_PX // 2
    py = row * _CELL_PX + _CELL_PX // 2
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": (px, py), "button": 1})


def _make_online_runner(role: NetworkRole, _pygame_fixture) -> tuple[NetworkedGameRunner, _FakeRelay]:
    """Create a NetworkedGameRunner wired to a FakeRelay, ready for tests."""
    runner = NetworkedGameRunner(role=role)
    runner._init_board()
    relay = _FakeRelay()
    runner._relay_client = relay
    runner._peer_name = "Bob"           # simulate peer already introduced
    runner.phase = Phase.COLOR_PICK
    return runner, relay


# ── Bug 1 — Keepalive: _on_connected must reset _last_pong_s ─────────────────

class TestKeepaliveOnConnect:
    def test_peer_connected_resets_pong_clock(self, _pygame):
        runner = NetworkedGameRunner(role=NetworkRole.ONLINE_HOST)
        runner._init_board()
        relay = _FakeRelay()
        runner._relay_client = relay

        # Simulate a 40-second wait before peer joins
        runner._last_pong_s = time.time() - 40.0

        runner._on_connected()

        assert time.time() - runner._last_pong_s < 1.0, (
            "_on_connected() must reset _last_pong_s so a long wait before peer "
            "joins does not immediately trigger the 30s pong timeout"
        )

    def test_no_immediate_disconnect_after_connect(self, _pygame):
        runner = NetworkedGameRunner(role=NetworkRole.ONLINE_HOST)
        runner._init_board()
        relay = _FakeRelay()
        runner._relay_client = relay

        # Simulate a 40-second wait before peer joins
        runner._last_pong_s = time.time() - 40.0

        runner._on_connected()
        runner._check_keepalive()   # would have fired the timeout before the fix

        assert runner._peer_disconnected is False, (
            "Peer should not be marked disconnected immediately after connecting"
        )


# ── Bugs 2 & 3 — COLOR_PICK guards ───────────────────────────────────────────

class TestColorPickGuards:
    def test_color_pick_blocked_before_peer_joins(self, _pygame):
        """Clicks on row 2 must be ignored while _peer_name is None."""
        runner, relay = _make_online_runner(NetworkRole.ONLINE_HOST, _pygame)
        runner._peer_name = None        # peer has NOT joined yet

        runner._handle_color_pick(_click(2, 3))

        assert relay.color_chosen_msgs() == [], "No color_chosen should be sent before peer joins"
        assert runner._local_color_sent is False

    def test_color_pick_allowed_after_peer_joins(self, _pygame):
        """After peer sends hello, row 2 clicks should register."""
        runner, relay = _make_online_runner(NetworkRole.ONLINE_HOST, _pygame)
        # _peer_name already set by _make_online_runner

        runner._handle_color_pick(_click(2, 3))

        msgs = relay.color_chosen_msgs()
        assert len(msgs) == 1
        assert msgs[0]["color_idx"] == 3
        assert runner._local_color_sent is True

    def test_color_pick_idempotent(self, _pygame):
        """Clicking a second time must not send another color_chosen."""
        runner, relay = _make_online_runner(NetworkRole.ONLINE_HOST, _pygame)

        runner._handle_color_pick(_click(2, 0))   # first pick: col 0
        runner._handle_color_pick(_click(2, 5))   # attempted re-pick: col 5

        msgs = relay.color_chosen_msgs()
        assert len(msgs) == 1, "Only the first pick should be sent"
        assert msgs[0]["color_idx"] == 0, "First pick (col 0) should be the winner"
        assert runner._selected_r_idx == 0


# ── Bug 4 — WAR_GAMES guard ───────────────────────────────────────────────────

class TestWarGamesGuards:
    def test_war_games_idempotent(self, _pygame):
        """Clicking a second time in WAR_GAMES must not send another war_games_choice."""
        runner, relay = _make_online_runner(NetworkRole.ONLINE_HOST, _pygame)
        runner.phase = Phase.WAR_GAMES

        runner._handle_war_games(_click(3, 0))   # first pick: Human (col 0-3)
        runner._handle_war_games(_click(3, 5))   # attempted re-pick: AI (col 4-7)

        msgs = relay.war_games_msgs()
        assert len(msgs) == 1, "Only the first war-games choice should be sent"
        assert msgs[0]["is_ai"] is False, "First pick (Human) should be the winner"
        assert runner._b.computer_player_r is False


# ── Bug 5 — New game goes to COLOR_PICK (rematch), not LOBBY ─────────────────

class TestNewGameRematch:
    def test_new_game_stays_connected_host(self, _pygame):
        """HOST pressing N should land at COLOR_PICK with relay still wired."""
        runner, relay = _make_online_runner(NetworkRole.ONLINE_HOST, _pygame)
        runner.phase = Phase.GAME_OVER

        runner._new_game_local()

        assert runner.phase == Phase.COLOR_PICK, (
            "Online HOST should rematch at COLOR_PICK, not go back to LOBBY"
        )
        assert runner._relay_client is relay, "Relay should remain connected after rematch"
        assert runner._peer_disconnected is False

    def test_new_game_stays_connected_guest(self, _pygame):
        """GUEST receiving new_game should also land at COLOR_PICK."""
        runner, relay = _make_online_runner(NetworkRole.ONLINE_GUEST, _pygame)
        runner._local_team_key = "l"
        runner.phase = Phase.GAME_OVER

        runner._incoming.append({"type": "new_game"})
        runner._drain_incoming()

        assert runner.phase == Phase.COLOR_PICK, (
            "Online GUEST should rematch at COLOR_PICK after receiving new_game"
        )
        assert runner._peer_disconnected is False

    def test_new_game_resets_color_state(self, _pygame):
        """Color negotiation state must be cleared so the rematch can re-pick."""
        runner, relay = _make_online_runner(NetworkRole.ONLINE_HOST, _pygame)
        runner._local_color_sent = True
        runner._selected_r_idx = 3
        runner.phase = Phase.GAME_OVER

        runner._new_game_local()

        assert runner._local_color_sent is False
        assert runner._selected_r_idx is None


# ── relay_error handling ──────────────────────────────────────────────────────

class TestRelayErrorHandling:
    """relay_error(illegal_move) must unblock _waiting_for_ack and trigger sync."""

    def test_illegal_move_clears_waiting_for_ack(self, _pygame):
        runner, relay = _make_online_runner(NetworkRole.ONLINE_HOST, _pygame)
        runner._waiting_for_ack = True

        runner._dispatch({"type": "relay_error", "code": "illegal_move",
                          "from_row": 6, "from_col": 4, "to_row": 4, "to_col": 4})

        assert runner._waiting_for_ack is False, (
            "illegal_move relay_error must clear _waiting_for_ack "
            "so the game does not freeze"
        )

    def test_illegal_move_sends_board_sync_request(self, _pygame):
        runner, relay = _make_online_runner(NetworkRole.ONLINE_HOST, _pygame)
        runner._waiting_for_ack = True
        relay.sent.clear()

        runner._dispatch({"type": "relay_error", "code": "illegal_move",
                          "from_row": 6, "from_col": 4, "to_row": 4, "to_col": 4})

        types_sent = [m["type"] for m in relay.sent]
        assert "board_sync_request" in types_sent, (
            "illegal_move rejection must trigger board_sync_request "
            "to resync the board state with the peer"
        )

    def test_other_relay_error_does_not_clear_ack(self, _pygame):
        runner, relay = _make_online_runner(NetworkRole.ONLINE_HOST, _pygame)
        runner._waiting_for_ack = True

        runner._dispatch({"type": "relay_error", "code": "server_full"})

        assert runner._waiting_for_ack is True, (
            "Non-illegal_move relay errors must not touch _waiting_for_ack"
        )


# ── game_start includes team colors (enables relay anti-cheat) ─────────────

class TestGameStartColors:
    """HOST's game_start must include team_r and team_l so the relay can
    initialize the server-side RoomValidator (anti-cheat)."""

    def test_game_start_includes_team_r_and_team_l(self, _pygame):
        runner, relay = _make_online_runner(NetworkRole.ONLINE_HOST, _pygame)
        b = runner._b
        # Set distinct team colors we can verify
        b.team_r.r, b.team_r.g, b.team_r.b = 65, 180, 232
        b.team_l.r, b.team_l.g, b.team_l.b = 255, 140, 0
        b.computer_player_r = False
        b.computer_player_l = False
        relay.sent.clear()

        runner._check_war_complete()   # triggers game_start when both choices set

        game_start_msgs = [m for m in relay.sent if m.get("type") == "game_start"]
        assert len(game_start_msgs) == 1, "HOST should send exactly one game_start"
        msg = game_start_msgs[0]
        assert "team_r" in msg, "game_start must include team_r for relay anti-cheat"
        assert "team_l" in msg, "game_start must include team_l for relay anti-cheat"
        assert msg["team_r"] == {"r": 65, "g": 180, "b": 232}
        assert msg["team_l"] == {"r": 255, "g": 140, "b": 0}


# ── Relay reconnect: board-reset regression ────────────────────────────────────
#
# After a long relay disconnect the relay replays up to 50 buffered messages,
# which can include game_start and game_setup from when the game was first set up.
# Those handlers both call initialize_game_board(), which stamps starting pieces
# back onto rows 0-1 / 6-7 WITHOUT clearing the rest of the grid — so any piece
# that had moved to rows 2-5 stayed put while the original 32 pieces reappeared
# at their starting squares.  The fix adds early-return guards when
# phase == PLAYING, and makes the non-HOST side send a hello back on reconnect
# so HOST is prompted to send rejoin_sync and restore the full state cleanly.

class TestRelayReconnectGuards:

    def _make_playing_guest(self, _pygame) -> NetworkedGameRunner:
        """ONLINE_GUEST runner wired to a FakeRelay, advanced to PLAYING."""
        runner = NetworkedGameRunner(role=NetworkRole.ONLINE_GUEST)
        runner._init_board()
        b = runner._b
        b.team_r.r, b.team_r.g, b.team_r.b = 65, 180, 232
        b.team_l.r, b.team_l.g, b.team_l.b = 255, 140, 0
        b.computer_player_r = False
        b.computer_player_l = False
        relay = _FakeRelay()
        runner._relay_client = relay
        runner._peer_name = "Host"
        runner._peer_connected = True
        runner._start_game()   # phase → PLAYING, grid populated
        return runner

    def _move_pawn(self, runner: NetworkedGameRunner) -> None:
        """Advance the team_r pawn at (1,0) to (2,0) so the board is non-trivial."""
        b = runner._b
        b.grid[2][0] = b.grid[1][0]
        b.grid[1][0] = None

    # ── game_start guard ──────────────────────────────────────────────────────

    def test_game_start_ignored_when_playing(self, _pygame):
        """Replayed game_start must not call initialize_game_board on a live board."""
        runner = self._make_playing_guest(_pygame)
        self._move_pawn(runner)
        b = runner._b

        runner._dispatch({
            "type": "game_start",
            "team_r": {"r": b.team_r.r, "g": b.team_r.g, "b": b.team_r.b},
            "team_l": {"r": b.team_l.r, "g": b.team_l.g, "b": b.team_l.b},
        })

        assert b.grid[1][0] is None, (
            "Replayed game_start must not stamp a starting pawn back at (1,0) — "
            "that was the pre-fix board-reset bug"
        )
        assert b.grid[2][0] is not None, "Moved pawn at (2,0) must survive"
        assert runner.phase == Phase.PLAYING

    def test_game_start_accepted_before_playing(self, _pygame):
        """game_start must still work normally when phase is not yet PLAYING."""
        runner = NetworkedGameRunner(role=NetworkRole.ONLINE_GUEST)
        runner._init_board()
        b = runner._b
        b.team_r.r, b.team_r.g, b.team_r.b = 65, 180, 232
        b.team_l.r, b.team_l.g, b.team_l.b = 255, 140, 0
        b.computer_player_r = False
        b.computer_player_l = False
        runner._relay_client = _FakeRelay()
        runner._peer_name = "Host"
        runner.phase = Phase.WAR_GAMES

        runner._dispatch({
            "type": "game_start",
            "team_r": {"r": b.team_r.r, "g": b.team_r.g, "b": b.team_r.b},
            "team_l": {"r": b.team_l.r, "g": b.team_l.g, "b": b.team_l.b},
        })

        assert runner.phase == Phase.PLAYING, "game_start should advance to PLAYING normally"
        assert b.grid[1][0] is not None, "initialize_game_board must run for a fresh game_start"

    # ── game_setup guard ──────────────────────────────────────────────────────

    def test_game_setup_ignored_when_playing(self, _pygame):
        """Replayed game_setup must not call initialize_game_board."""
        runner = self._make_playing_guest(_pygame)
        self._move_pawn(runner)
        b = runner._b

        runner._dispatch({
            "type": "game_setup",
            "version": "1",
            "host_name": "Host",
            "guest_name": "Guest",
        })

        assert b.grid[1][0] is None, "game_setup replay must not repopulate (1,0)"
        assert b.grid[2][0] is not None, "Moved pawn must survive game_setup replay"
        assert runner.phase == Phase.PLAYING

    def test_game_setup_spectator_view_ignored_when_playing(self, _pygame):
        """Replayed spectator-view game_setup must also be suppressed."""
        runner = self._make_playing_guest(_pygame)
        self._move_pawn(runner)
        b = runner._b

        runner._dispatch({
            "type": "game_setup",
            "version": "1",
            "mode": "spectator_view",
            "host_name": "Host",
            "guest_name": "Guest",
        })

        assert b.grid[1][0] is None
        assert b.grid[2][0] is not None
        assert runner.phase == Phase.PLAYING

    # ── hello reconnect triggers rejoin_sync ──────────────────────────────────

    def test_guest_sends_hello_back_when_reconnecting(self, _pygame):
        """GUEST in PLAYING receiving hello must send hello back so HOST sends rejoin_sync."""
        runner = self._make_playing_guest(_pygame)
        sent: list[dict] = []
        runner._net_send = lambda msg: sent.append(msg)

        runner._dispatch({
            "type": "hello",
            "version": "1",
            "player_name": "Host",
            "role": "host",
        })

        hello_msgs = [m for m in sent if m.get("type") == "hello"]
        assert len(hello_msgs) == 1, (
            "GUEST must send hello back to HOST on reconnect — "
            "that hello causes HOST to send rejoin_sync and restore the board"
        )
        assert hello_msgs[0].get("role") == "guest"
        assert hello_msgs[0].get("version") == "1"

    def test_guest_hello_reconnect_clears_disconnect_flag(self, _pygame):
        """Receiving hello while PLAYING clears _peer_disconnected."""
        runner = self._make_playing_guest(_pygame)
        runner._peer_disconnected = True
        runner._net_send = lambda msg: None

        runner._dispatch({
            "type": "hello",
            "version": "1",
            "player_name": "Host",
            "role": "host",
        })

        assert runner._peer_disconnected is False

    def test_host_still_sends_rejoin_sync_on_guest_hello(self, _pygame):
        """HOST receiving GUEST's hello (sent by the reconnect fix) sends rejoin_sync."""
        host = _make_host(_pygame)
        assert host.phase == Phase.PLAYING

        sent: list[dict] = []
        host._net_send = lambda msg: sent.append(msg)

        host._dispatch({
            "type": "hello",
            "version": "1",
            "player_name": "Guest",
            "role": "guest",
        })

        types_sent = [m["type"] for m in sent]
        assert "rejoin_sync" in types_sent, (
            "HOST must respond to the reconnect hello with rejoin_sync"
        )
