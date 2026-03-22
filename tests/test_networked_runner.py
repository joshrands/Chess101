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
