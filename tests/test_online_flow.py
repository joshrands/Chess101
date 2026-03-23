"""
test_online_flow.py — E2E integration tests for the online relay game flow.

Two real NetworkedGameRunner instances connect through the in-process relay
(conftest.py relay_url fixture) and exercise the full handshake, color-pick,
war-games, and playing phases of the protocol.

These tests catch the class of bugs that unit tests with manually injected
state (_peer_name = "Bob") cannot detect — in particular, anything that
depends on the hello exchange actually happening (phase-gating, peer-name
guards, relay-history replay).

Run with:
    .venv/bin/python -m pytest tests/test_online_flow.py -v
"""
from __future__ import annotations

import os
import sys
import time
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

from simulator.app import Phase, _CELL_PX  # noqa: E402
from simulator.networked_runner import NetworkedGameRunner, NetworkRole  # noqa: E402


# ── Module-scoped pygame surface (one window for all tests in this file) ──────

@pytest.fixture(scope="module")
def _pygame():
    pygame.init()
    pygame.display.set_mode((1200, 960))
    yield
    pygame.quit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pump_until(condition, runners, timeout: float = 8.0) -> bool:
    """Drain all runners until condition() returns True or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for r in runners:
            r._drain_incoming()
        if condition():
            return True
        time.sleep(0.05)
    return False


def _make_runner(
    role: NetworkRole,
    relay_url: str,
    name: str,
    room_code: str | None = None,
) -> NetworkedGameRunner:
    """Create a runner initialised with a headless board."""
    runner = NetworkedGameRunner(
        role=role,
        player_name=name,
        relay_url=relay_url,
        room_code=room_code,
    )
    runner._init_board()
    return runner


def _connect_pair(
    relay_url: str,
    host_name: str = "Alice",
    guest_name: str = "Bob",
) -> tuple[NetworkedGameRunner, NetworkedGameRunner]:
    """Connect HOST and GUEST through the in-process relay.

    Blocks until both sides have exchanged hellos and are in COLOR_PICK.
    Callers must call _stop_network() on both runners when done.
    """
    host = _make_runner(NetworkRole.ONLINE_HOST, relay_url, host_name)
    host.phase = Phase.COLOR_PICK
    host._start_network()

    ok = _pump_until(lambda: host._room_code is not None, [host], timeout=10.0)
    assert ok, "HOST failed to obtain a room code from the relay"

    guest = _make_runner(
        NetworkRole.ONLINE_GUEST, relay_url, guest_name,
        room_code=host._room_code,
    )
    guest.phase = Phase.COLOR_PICK
    guest._start_network()

    ok = _pump_until(
        lambda: (
            host._peer_name is not None
            and guest._peer_name is not None
            and guest.phase == Phase.COLOR_PICK
        ),
        [host, guest],
        timeout=10.0,
    )
    assert ok, (
        f"Handshake timed out: host._peer_name={host._peer_name!r} "
        f"guest._peer_name={guest._peer_name!r} "
        f"guest.phase={guest.phase!r}"
    )
    return host, guest


def _advance_to_war_games(
    relay_url: str,
) -> tuple[NetworkedGameRunner, NetworkedGameRunner]:
    """Connect pair and pick colors so both runners are in WAR_GAMES."""
    host, guest = _connect_pair(relay_url)
    host._handle_color_pick(_click(2, 0))
    guest._handle_color_pick(_click(5, 5))
    ok = _pump_until(
        lambda: host.phase == Phase.WAR_GAMES and guest.phase == Phase.WAR_GAMES,
        [host, guest],
    )
    assert ok, (
        f"Failed to advance to WAR_GAMES: "
        f"host.phase={host.phase!r}, guest.phase={guest.phase!r}"
    )
    return host, guest


def _advance_to_playing(
    relay_url: str,
) -> tuple[NetworkedGameRunner, NetworkedGameRunner]:
    """Connect pair through all setup phases until both are in PLAYING."""
    host, guest = _advance_to_war_games(relay_url)
    host._handle_war_games(_click(3, 0))   # HOST: Human (col 0-3)
    guest._handle_war_games(_click(4, 7))  # GUEST: Human (col 4-7, row-4 inverted)
    ok = _pump_until(
        lambda: host.phase == Phase.PLAYING and guest.phase == Phase.PLAYING,
        [host, guest],
        timeout=10.0,
    )
    assert ok, (
        f"Failed to advance to PLAYING: "
        f"host.phase={host.phase!r}, guest.phase={guest.phase!r}"
    )
    return host, guest


def _click(row: int, col: int) -> pygame.event.Event:
    """Synthesize a MOUSEBUTTONDOWN at the centre pixel of board cell (row, col)."""
    px = col * _CELL_PX + _CELL_PX // 2
    py = row * _CELL_PX + _CELL_PX // 2
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": (px, py), "button": 1})


# ═════════════════════════════════════════════════════════════════════════════
# TestOnlineHandshake — hello exchange over a live relay
# ═════════════════════════════════════════════════════════════════════════════

class TestOnlineHandshake:
    """After connecting through the relay, both sides exchange hello messages
    and advance to COLOR_PICK."""

    def test_host_knows_guest_name(self, _pygame, relay_url):
        host, guest = _connect_pair(relay_url)
        try:
            assert host._peer_name == "Bob", (
                "HOST should know GUEST's name after the hello exchange"
            )
        finally:
            host._stop_network()
            guest._stop_network()

    def test_guest_knows_host_name(self, _pygame, relay_url):
        host, guest = _connect_pair(relay_url)
        try:
            assert guest._peer_name == "Alice", (
                "GUEST should know HOST's name after the hello exchange"
            )
        finally:
            host._stop_network()
            guest._stop_network()

    def test_both_in_color_pick_after_handshake(self, _pygame, relay_url):
        host, guest = _connect_pair(relay_url)
        try:
            assert host.phase == Phase.COLOR_PICK, (
                "HOST should be in COLOR_PICK after sending game_setup"
            )
            assert guest.phase == Phase.COLOR_PICK, (
                "GUEST should be in COLOR_PICK after receiving game_setup"
            )
        finally:
            host._stop_network()
            guest._stop_network()

    def test_host_gets_room_code(self, _pygame, relay_url):
        host, guest = _connect_pair(relay_url)
        try:
            assert host._room_code is not None
            assert len(host._room_code) == 6
        finally:
            host._stop_network()
            guest._stop_network()


# ═════════════════════════════════════════════════════════════════════════════
# TestOnlineColorPick — color selection propagates over a live relay
# ═════════════════════════════════════════════════════════════════════════════

class TestOnlineColorPick:
    """Regression: HOST was blocked from picking a color because _peer_name was
    None (the hello was never sent back).  After the fix, both sides should be
    able to pick immediately once the handshake completes."""

    def test_host_can_pick_color(self, _pygame, relay_url):
        """HOST picks on row 2; _local_color_sent and _selected_r_idx must be set."""
        host, guest = _connect_pair(relay_url)
        try:
            host._handle_color_pick(_click(2, 3))

            assert host._local_color_sent, (
                "HOST should have sent color_chosen after clicking row 2 — "
                "_peer_name guard was not blocking"
            )
            assert host._selected_r_idx == 3
        finally:
            host._stop_network()
            guest._stop_network()

    def test_guest_can_pick_color(self, _pygame, relay_url):
        """GUEST picks on row 5; _local_color_sent and _selected_l_idx must be set."""
        host, guest = _connect_pair(relay_url)
        try:
            guest._handle_color_pick(_click(5, 6))

            assert guest._local_color_sent
            assert guest._selected_l_idx == 6
        finally:
            host._stop_network()
            guest._stop_network()

    def test_host_color_propagates_to_guest(self, _pygame, relay_url):
        """color_chosen from HOST arrives at GUEST and sets _selected_r_idx."""
        host, guest = _connect_pair(relay_url)
        try:
            host._handle_color_pick(_click(2, 4))

            ok = _pump_until(
                lambda: guest._selected_r_idx is not None,
                [host, guest],
            )
            assert ok, "GUEST never received HOST's color_chosen"
            assert guest._selected_r_idx == 4
        finally:
            host._stop_network()
            guest._stop_network()

    def test_guest_color_propagates_to_host(self, _pygame, relay_url):
        """color_chosen from GUEST arrives at HOST and sets _selected_l_idx."""
        host, guest = _connect_pair(relay_url)
        try:
            guest._handle_color_pick(_click(5, 1))

            ok = _pump_until(
                lambda: host._selected_l_idx is not None,
                [host, guest],
            )
            assert ok, "HOST never received GUEST's color_chosen"
            assert host._selected_l_idx == 1
        finally:
            host._stop_network()
            guest._stop_network()

    def test_both_advance_to_war_games_after_both_picks(self, _pygame, relay_url):
        """Once both sides have picked, both advance to WAR_GAMES."""
        host, guest = _connect_pair(relay_url)
        try:
            host._handle_color_pick(_click(2, 2))
            guest._handle_color_pick(_click(5, 7))

            ok = _pump_until(
                lambda: (
                    host.phase == Phase.WAR_GAMES
                    and guest.phase == Phase.WAR_GAMES
                ),
                [host, guest],
            )
            assert ok, (
                f"Both sides should advance to WAR_GAMES after picking colors; "
                f"host.phase={host.phase!r}, guest.phase={guest.phase!r}"
            )
        finally:
            host._stop_network()
            guest._stop_network()


# ═════════════════════════════════════════════════════════════════════════════
# TestOnlineWarGames — war-games choices propagate over a live relay
# ═════════════════════════════════════════════════════════════════════════════

class TestOnlineWarGames:

    def test_host_war_games_choice_propagates_to_guest(self, _pygame, relay_url):
        """HOST's war_games_choice (team_r) arrives at GUEST."""
        host, guest = _advance_to_war_games(relay_url)
        try:
            host._handle_war_games(_click(3, 0))   # col 0-3 = Human

            ok = _pump_until(
                lambda: guest._board.computer_player_r is not None,
                [host, guest],
            )
            assert ok, "GUEST never received HOST's war_games_choice"
            assert guest._board.computer_player_r is False
        finally:
            host._stop_network()
            guest._stop_network()

    def test_guest_war_games_choice_propagates_to_host(self, _pygame, relay_url):
        """GUEST's war_games_choice (team_l) arrives at HOST."""
        host, guest = _advance_to_war_games(relay_url)
        try:
            guest._handle_war_games(_click(4, 7))  # row-4: col 4-7 = Human

            ok = _pump_until(
                lambda: host._board.computer_player_l is not None,
                [host, guest],
            )
            assert ok, "HOST never received GUEST's war_games_choice"
            assert host._board.computer_player_l is False
        finally:
            host._stop_network()
            guest._stop_network()

    def test_both_advance_to_playing_after_war_games(self, _pygame, relay_url):
        """After both sides pick, HOST sends game_start and both enter PLAYING."""
        host, guest = _advance_to_war_games(relay_url)
        try:
            host._handle_war_games(_click(3, 0))
            guest._handle_war_games(_click(4, 7))

            ok = _pump_until(
                lambda: (
                    host.phase == Phase.PLAYING
                    and guest.phase == Phase.PLAYING
                ),
                [host, guest],
                timeout=10.0,
            )
            assert ok, (
                f"Both sides should enter PLAYING after war_games; "
                f"host.phase={host.phase!r}, guest.phase={guest.phase!r}"
            )
        finally:
            host._stop_network()
            guest._stop_network()


# ═════════════════════════════════════════════════════════════════════════════
# TestOnlineReconnectGuards — relay history replay must not corrupt the board
# ═════════════════════════════════════════════════════════════════════════════

class TestOnlineReconnectGuards:
    """Regression: when a relay reconnect replays history (game_start,
    game_setup), those messages must be silently ignored while in PLAYING."""

    def test_game_start_ignored_when_replayed_during_playing(self, _pygame, relay_url):
        """A replayed game_start must not call _start_game() on a live board."""
        host, guest = _advance_to_playing(relay_url)
        try:
            b = guest._board
            # Move a pawn so the board differs from the starting position.
            b.grid[2][0] = b.grid[1][0]
            b.grid[1][0] = None
            moved_piece = b.grid[2][0]

            # Inject a replayed game_start as relay history would deliver.
            guest._dispatch({"type": "game_start"})

            assert b.grid[2][0] is moved_piece, (
                "game_start replayed during PLAYING must not reset the board"
            )
            assert b.grid[1][0] is None, (
                "Original square should still be empty after game_start replay"
            )
        finally:
            host._stop_network()
            guest._stop_network()

    def test_game_setup_ignored_when_replayed_during_playing(self, _pygame, relay_url):
        """A replayed game_setup must not change phase or reinitialize the board."""
        host, guest = _advance_to_playing(relay_url)
        try:
            b = guest._board
            b.grid[2][0] = b.grid[1][0]
            b.grid[1][0] = None

            guest._dispatch({
                "type": "game_setup",
                "version": "1",
                "host_name": "Alice",
                "guest_name": "Bob",
            })

            assert guest.phase == Phase.PLAYING, (
                "game_setup replayed during PLAYING must not change phase"
            )
            assert b.grid[2][0] is not None, (
                "game_setup replayed during PLAYING must not reinitialize the board"
            )
        finally:
            host._stop_network()
            guest._stop_network()

    def test_phase_stays_playing_after_both_replays(self, _pygame, relay_url):
        """Replaying both game_setup and game_start leaves the game in PLAYING."""
        host, guest = _advance_to_playing(relay_url)
        try:
            guest._dispatch({
                "type": "game_setup",
                "version": "1",
                "host_name": "Alice",
                "guest_name": "Bob",
            })
            guest._dispatch({"type": "game_start"})

            assert guest.phase == Phase.PLAYING
        finally:
            host._stop_network()
            guest._stop_network()
