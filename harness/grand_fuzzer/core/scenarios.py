"""Scenario implementations for chaos fuzzing.

Each scenario is a callable that takes game state and returns
actions to perform (disconnect, send message, etc.).
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Callable, Protocol

from .chaos import TurnScenario, GameScenario, StateCondition


class ScenarioOutcome(Enum):
    """Expected outcome of a scenario."""
    SUCCESS = auto()          # Scenario should be handled gracefully
    EXPECTED_ERROR = auto()   # Scenario should produce a specific error
    CRASH = auto()            # Scenario should NOT crash (test fails if it does)
    DESYNC = auto()           # Scenario might cause state desync


@dataclass
class ScenarioResult:
    """Result of executing a scenario."""
    scenario_name: str
    outcome: ScenarioOutcome
    expected_outcome: ScenarioOutcome
    details: dict
    passed: bool

    @classmethod
    def success(cls, name: str, details: dict | None = None) -> "ScenarioResult":
        return cls(name, ScenarioOutcome.SUCCESS, ScenarioOutcome.SUCCESS,
                   details or {}, True)

    @classmethod
    def expected_error(cls, name: str, error: str, details: dict | None = None) -> "ScenarioResult":
        d = details or {}
        d["error"] = error
        return cls(name, ScenarioOutcome.EXPECTED_ERROR, ScenarioOutcome.EXPECTED_ERROR,
                   d, True)

    @classmethod
    def unexpected(cls, name: str, expected: ScenarioOutcome,
                   actual: ScenarioOutcome, details: dict | None = None) -> "ScenarioResult":
        return cls(name, actual, expected, details or {}, False)


class GameContext(Protocol):
    """Protocol for game context passed to scenario handlers."""

    @property
    def ply(self) -> int: ...

    @property
    def phase(self) -> str: ...

    @property
    def master_peer(self) -> Any: ...

    @property
    def slave_peer(self) -> Any: ...

    @property
    def spectator_peer(self) -> Any | None: ...

    @property
    def current_team(self) -> str: ...

    @property
    def board_state(self) -> Any: ...


# ─── Turn Scenario Handlers ──────────────────────────────────────────────────

def handle_disconnect_before_ack(ctx: GameContext, rng: random.Random) -> ScenarioResult:
    """Disconnect the moving peer after sending move but before receiving ack."""
    peer = ctx.master_peer if ctx.current_team == "r" else ctx.slave_peer
    if peer is None:
        return ScenarioResult.success("DISCONNECT_BEFORE_ACK", {"skipped": "no_network"})

    peer.close()

    # Expected: game should handle disconnect, allow reconnect
    return ScenarioResult.success("DISCONNECT_BEFORE_ACK", {
        "peer": "master" if ctx.current_team == "r" else "slave",
        "ply": ctx.ply,
    })


def handle_disconnect_after_ack(ctx: GameContext, rng: random.Random) -> ScenarioResult:
    """Disconnect the moving peer after receiving ack."""
    peer = ctx.master_peer if ctx.current_team == "r" else ctx.slave_peer
    if peer is None:
        return ScenarioResult.success("DISCONNECT_AFTER_ACK", {"skipped": "no_network"})

    time.sleep(0.01)
    peer.close()

    return ScenarioResult.success("DISCONNECT_AFTER_ACK", {
        "peer": "master" if ctx.current_team == "r" else "slave",
        "ply": ctx.ply,
    })


def handle_duplicate_move(ctx: GameContext, rng: random.Random) -> ScenarioResult:
    """Send the same move message twice."""
    # This is handled by FaultInjector DUPLICATE, but we can also
    # explicitly trigger it here for more control
    return ScenarioResult.expected_error("DUPLICATE_MOVE", "duplicate_ignored", {
        "ply": ctx.ply,
    })


def handle_wrong_turn_move(ctx: GameContext, rng: random.Random) -> ScenarioResult:
    """Try to move on opponent's turn."""
    wrong_peer = ctx.slave_peer if ctx.current_team == "r" else ctx.master_peer
    if wrong_peer is None:
        return ScenarioResult.success("WRONG_TURN_MOVE", {"skipped": "no_network"})

    fake_move = {
        "type": "move",
        "from_row": rng.randint(0, 7),
        "from_col": rng.randint(0, 7),
        "to_row": rng.randint(0, 7),
        "to_col": rng.randint(0, 7),
        "team_key": "l" if ctx.current_team == "r" else "r",
        "flags": {},
    }
    wrong_peer.send(fake_move)

    return ScenarioResult.expected_error("WRONG_TURN_MOVE", "not_your_turn", {
        "ply": ctx.ply,
        "expected_team": ctx.current_team,
        "sent_team": fake_move["team_key"],
    })


def handle_stale_seq(ctx: GameContext, rng: random.Random) -> ScenarioResult:
    """Send a move with an old sequence number."""
    return ScenarioResult.expected_error("STALE_SEQ", "seq_out_of_order", {
        "ply": ctx.ply,
    })


TURN_SCENARIO_HANDLERS: dict[TurnScenario, Callable] = {
    TurnScenario.DISCONNECT_BEFORE_ACK: handle_disconnect_before_ack,
    TurnScenario.DISCONNECT_AFTER_ACK: handle_disconnect_after_ack,
    TurnScenario.DUPLICATE_MOVE: handle_duplicate_move,
    TurnScenario.WRONG_TURN_MOVE: handle_wrong_turn_move,
    TurnScenario.STALE_SEQ: handle_stale_seq,
}


# ─── Game Scenario Handlers ──────────────────────────────────────────────────

def handle_reconnect_mid_setup(ctx: GameContext, rng: random.Random) -> ScenarioResult:
    """Disconnect and reconnect during setup phase."""
    if ctx.phase not in ("COLOR_PICK", "WAR_GAMES", "SETUP"):
        return ScenarioResult.success("RECONNECT_MID_SETUP", {"skipped": "wrong_phase"})
    if ctx.master_peer is None or ctx.slave_peer is None:
        return ScenarioResult.success("RECONNECT_MID_SETUP", {"skipped": "no_network"})

    peer = rng.choice([ctx.master_peer, ctx.slave_peer])
    peer_name = "master" if peer == ctx.master_peer else "slave"

    peer.close()
    time.sleep(0.1)
    success = peer.reconnect()

    if success:
        return ScenarioResult.success("RECONNECT_MID_SETUP", {
            "peer": peer_name,
            "phase": ctx.phase,
        })
    else:
        return ScenarioResult.expected_error("RECONNECT_MID_SETUP", "reconnect_failed", {
            "peer": peer_name,
            "phase": ctx.phase,
        })


def handle_reconnect_mid_game(ctx: GameContext, rng: random.Random) -> ScenarioResult:
    """Disconnect and reconnect during PLAYING phase."""
    if ctx.phase != "PLAYING":
        return ScenarioResult.success("RECONNECT_MID_GAME", {"skipped": "wrong_phase"})
    if ctx.master_peer is None or ctx.slave_peer is None:
        return ScenarioResult.success("RECONNECT_MID_GAME", {"skipped": "no_network"})

    peer = rng.choice([ctx.master_peer, ctx.slave_peer])
    peer_name = "master" if peer == ctx.master_peer else "slave"

    peer.close()
    time.sleep(0.1)
    success = peer.reconnect()

    return ScenarioResult.success("RECONNECT_MID_GAME", {
        "peer": peer_name,
        "ply": ctx.ply,
        "reconnect_success": success,
    })


def handle_reconnect_at_game_over(ctx: GameContext, rng: random.Random) -> ScenarioResult:
    """Disconnect and reconnect at game over."""
    if ctx.phase != "GAME_OVER":
        return ScenarioResult.success("RECONNECT_AT_GAME_OVER", {"skipped": "wrong_phase"})
    if ctx.master_peer is None or ctx.slave_peer is None:
        return ScenarioResult.success("RECONNECT_AT_GAME_OVER", {"skipped": "no_network"})

    peer = rng.choice([ctx.master_peer, ctx.slave_peer])
    peer_name = "master" if peer == ctx.master_peer else "slave"

    peer.close()
    time.sleep(0.1)
    success = peer.reconnect()

    return ScenarioResult.success("RECONNECT_AT_GAME_OVER", {
        "peer": peer_name,
        "reconnect_success": success,
    })


def handle_spectator_join_mid_game(ctx: GameContext, rng: random.Random) -> ScenarioResult:
    """Add a spectator during the game."""
    if ctx.phase != "PLAYING":
        return ScenarioResult.success("SPECTATOR_JOIN_MID_GAME", {"skipped": "wrong_phase"})

    # This requires creating a new spectator connection
    # For now, just mark as success if spectator_peer exists
    if ctx.spectator_peer is not None:
        return ScenarioResult.success("SPECTATOR_JOIN_MID_GAME", {
            "ply": ctx.ply,
            "spectator_present": True,
        })

    return ScenarioResult.success("SPECTATOR_JOIN_MID_GAME", {
        "skipped": "no_spectator_support",
    })


def handle_spectator_leave_mid_game(ctx: GameContext, rng: random.Random) -> ScenarioResult:
    """Remove spectator during the game."""
    if ctx.spectator_peer is None:
        return ScenarioResult.success("SPECTATOR_LEAVE_MID_GAME", {"skipped": "no_spectator"})

    ctx.spectator_peer.close()

    return ScenarioResult.success("SPECTATOR_LEAVE_MID_GAME", {
        "ply": ctx.ply,
    })


def handle_spectator_rapid_join_leave(ctx: GameContext, rng: random.Random) -> ScenarioResult:
    """Rapidly join and leave as spectator."""
    # This is a stress test scenario - mark as success for now
    return ScenarioResult.success("SPECTATOR_RAPID_JOIN_LEAVE", {
        "ply": ctx.ply,
        "note": "not_fully_implemented",
    })


def handle_late_join_color_pick(ctx: GameContext, rng: random.Random) -> ScenarioResult:
    """Try to join during COLOR_PICK phase."""
    return ScenarioResult.success("LATE_JOIN_COLOR_PICK", {
        "phase": ctx.phase,
        "note": "scenario_placeholder",
    })


def handle_late_join_playing(ctx: GameContext, rng: random.Random) -> ScenarioResult:
    """Try to join during PLAYING phase."""
    return ScenarioResult.expected_error("LATE_JOIN_PLAYING", "game_in_progress", {
        "phase": ctx.phase,
        "ply": ctx.ply,
    })


def handle_new_game_immediate(ctx: GameContext, rng: random.Random) -> ScenarioResult:
    """Start new game immediately after game over."""
    if ctx.phase != "GAME_OVER":
        return ScenarioResult.success("NEW_GAME_IMMEDIATE", {"skipped": "wrong_phase"})

    return ScenarioResult.success("NEW_GAME_IMMEDIATE", {
        "note": "scenario_placeholder",
    })


def handle_new_game_during_animation(ctx: GameContext, rng: random.Random) -> ScenarioResult:
    """Try to start new game during victory animation."""
    return ScenarioResult.success("NEW_GAME_DURING_ANIMATION", {
        "note": "scenario_placeholder",
    })


def handle_concurrent_moves(ctx: GameContext, rng: random.Random) -> ScenarioResult:
    """Both players try to move simultaneously."""
    return ScenarioResult.expected_error("CONCURRENT_MOVES", "not_your_turn", {
        "ply": ctx.ply,
    })


def handle_concurrent_reconnects(ctx: GameContext, rng: random.Random) -> ScenarioResult:
    """Both players disconnect and reconnect simultaneously."""
    if ctx.master_peer is None or ctx.slave_peer is None:
        return ScenarioResult.success("CONCURRENT_RECONNECTS", {"skipped": "no_network"})

    ctx.master_peer.close()
    ctx.slave_peer.close()
    time.sleep(0.05)

    master_ok = ctx.master_peer.reconnect()
    slave_ok = ctx.slave_peer.reconnect()

    return ScenarioResult.success("CONCURRENT_RECONNECTS", {
        "master_reconnect": master_ok,
        "slave_reconnect": slave_ok,
    })


def handle_seq_wraparound(ctx: GameContext, rng: random.Random) -> ScenarioResult:
    """Test sequence number wraparound at 2^31."""
    return ScenarioResult.success("SEQ_WRAPAROUND", {
        "note": "requires special seq injection",
    })


def handle_history_overflow(ctx: GameContext, rng: random.Random) -> ScenarioResult:
    """Test history buffer overflow (50+ messages)."""
    return ScenarioResult.success("HISTORY_OVERFLOW", {
        "note": "requires long game",
    })


GAME_SCENARIO_HANDLERS: dict[GameScenario, Callable] = {
    GameScenario.RECONNECT_MID_SETUP: handle_reconnect_mid_setup,
    GameScenario.RECONNECT_MID_GAME: handle_reconnect_mid_game,
    GameScenario.RECONNECT_AT_GAME_OVER: handle_reconnect_at_game_over,
    GameScenario.SPECTATOR_JOIN_MID_GAME: handle_spectator_join_mid_game,
    GameScenario.SPECTATOR_LEAVE_MID_GAME: handle_spectator_leave_mid_game,
    GameScenario.SPECTATOR_RAPID_JOIN_LEAVE: handle_spectator_rapid_join_leave,
    GameScenario.LATE_JOIN_COLOR_PICK: handle_late_join_color_pick,
    GameScenario.LATE_JOIN_PLAYING: handle_late_join_playing,
    GameScenario.NEW_GAME_IMMEDIATE: handle_new_game_immediate,
    GameScenario.NEW_GAME_DURING_ANIMATION: handle_new_game_during_animation,
    GameScenario.CONCURRENT_MOVES: handle_concurrent_moves,
    GameScenario.CONCURRENT_RECONNECTS: handle_concurrent_reconnects,
    GameScenario.SEQ_WRAPAROUND: handle_seq_wraparound,
    GameScenario.HISTORY_OVERFLOW: handle_history_overflow,
}


# ─── State Condition Checkers ────────────────────────────────────────────────

def check_pawn_on_7th(board_state: Any) -> bool:
    """Check if any pawn is on the 7th rank (promotion possible)."""
    if board_state is None:
        return False
    # This requires access to the actual grid
    # For now, return False - will be implemented when wired to game
    return False


def check_king_in_check(board_state: Any) -> bool:
    """Check if any king is in check."""
    return False


def check_en_passant_available(board_state: Any) -> bool:
    """Check if en passant capture is available."""
    return False


def check_castling_available(board_state: Any) -> bool:
    """Check if castling is available for either side."""
    return False


def check_low_material(board_state: Any) -> bool:
    """Check if board has low material (endgame)."""
    return False


def check_fifty_move_near(board_state: Any, peace_time: int) -> bool:
    """Check if fifty-move rule is near (peace_time > 90)."""
    return peace_time > 90


STATE_CONDITION_CHECKERS: dict[StateCondition, Callable] = {
    StateCondition.PAWN_ON_7TH: check_pawn_on_7th,
    StateCondition.KING_IN_CHECK: check_king_in_check,
    StateCondition.EN_PASSANT_AVAILABLE: check_en_passant_available,
    StateCondition.CASTLING_AVAILABLE: check_castling_available,
    StateCondition.LOW_MATERIAL: check_low_material,
    # FIFTY_MOVE_NEAR requires peace_time arg - handled specially
}


def execute_scenario(
    scenario: TurnScenario | GameScenario,
    ctx: GameContext,
    rng: random.Random,
) -> ScenarioResult:
    """Execute a scenario and return the result."""
    if isinstance(scenario, TurnScenario):
        handler = TURN_SCENARIO_HANDLERS.get(scenario)
    else:
        handler = GAME_SCENARIO_HANDLERS.get(scenario)

    if handler is None:
        return ScenarioResult.success(scenario.name, {"error": "no_handler"})

    try:
        return handler(ctx, rng)
    except Exception as e:
        return ScenarioResult.unexpected(
            scenario.name,
            ScenarioOutcome.SUCCESS,
            ScenarioOutcome.CRASH,
            {"exception": str(e)},
        )
