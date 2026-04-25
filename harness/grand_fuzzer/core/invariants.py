"""Invariant checkers for game fuzzing.

Validates that game state satisfies phase-specific invariants.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .phase_state import GamePhase, GamePhaseState


@dataclass
class InvariantViolation:
    """Represents an invariant violation."""
    phase: GamePhase
    invariant: str
    message: str
    state: dict


class InvariantChecker:
    """Checks game state invariants at each phase."""

    def __init__(self):
        self._violations: list[InvariantViolation] = []

    @property
    def violations(self) -> list[InvariantViolation]:
        """Get all recorded violations."""
        return self._violations[:]

    def clear(self) -> None:
        """Clear recorded violations."""
        self._violations.clear()

    def check(self, state: GamePhaseState) -> bool:
        """Check all invariants for current phase. Returns True if all pass."""
        checkers = {
            GamePhase.LOBBY: self._check_lobby,
            GamePhase.COLOR_PICK: self._check_color_pick,
            GamePhase.WAR_GAMES: self._check_war_games,
            GamePhase.SETUP: self._check_setup,
            GamePhase.PLAYING: self._check_playing,
            GamePhase.GAME_OVER: self._check_game_over,
        }
        checker = checkers.get(state.phase, lambda s: True)
        return checker(state)

    def _record(self, state: GamePhaseState, invariant: str, message: str) -> None:
        """Record an invariant violation."""
        self._violations.append(InvariantViolation(
            phase=state.phase,
            invariant=invariant,
            message=message,
            state={
                "team_r_color": state.team_r.color_idx,
                "team_l_color": state.team_l.color_idx,
                "team_r_ai": state.team_r.is_ai,
                "team_l_ai": state.team_l.is_ai,
                "game_started": state.game_started,
                "ply": state.ply,
            }
        ))

    def _check_lobby(self, state: GamePhaseState) -> bool:
        """Invariants for LOBBY phase."""
        ok = True

        if state.team_r.color_idx is not None:
            self._record(state, "lobby_no_color", "team_r has color in LOBBY")
            ok = False

        if state.team_l.color_idx is not None:
            self._record(state, "lobby_no_color", "team_l has color in LOBBY")
            ok = False

        if state.game_started:
            self._record(state, "lobby_no_start", "game_started in LOBBY")
            ok = False

        return ok

    def _check_color_pick(self, state: GamePhaseState) -> bool:
        """Invariants for COLOR_PICK phase."""
        ok = True

        if state.game_started:
            self._record(state, "color_pick_no_start", "game_started in COLOR_PICK")
            ok = False

        if state.team_r.is_ai is not None:
            self._record(state, "color_pick_no_ai", "team_r has is_ai in COLOR_PICK")
            ok = False

        if state.team_l.is_ai is not None:
            self._record(state, "color_pick_no_ai", "team_l has is_ai in COLOR_PICK")
            ok = False

        return ok

    def _check_war_games(self, state: GamePhaseState) -> bool:
        """Invariants for WAR_GAMES phase."""
        ok = True

        if state.team_r.color_idx is None:
            self._record(state, "war_games_needs_color", "team_r missing color")
            ok = False

        if state.team_l.color_idx is None:
            self._record(state, "war_games_needs_color", "team_l missing color")
            ok = False

        if state.team_r.color_idx == state.team_l.color_idx:
            self._record(state, "war_games_diff_colors", "teams have same color")
            ok = False

        if state.game_started:
            self._record(state, "war_games_no_start", "game_started in WAR_GAMES")
            ok = False

        return ok

    def _check_setup(self, state: GamePhaseState) -> bool:
        """Invariants for SETUP phase."""
        ok = True

        if state.team_r.color_idx is None:
            self._record(state, "setup_needs_color", "team_r missing color")
            ok = False

        if state.team_l.color_idx is None:
            self._record(state, "setup_needs_color", "team_l missing color")
            ok = False

        if state.team_r.is_ai is None:
            self._record(state, "setup_needs_ai", "team_r missing is_ai")
            ok = False

        if state.team_l.is_ai is None:
            self._record(state, "setup_needs_ai", "team_l missing is_ai")
            ok = False

        return ok

    def _check_playing(self, state: GamePhaseState) -> bool:
        """Invariants for PLAYING phase."""
        ok = True

        if not state.game_started:
            self._record(state, "playing_needs_start", "not game_started in PLAYING")
            ok = False

        if not state.team_r.setup_complete:
            self._record(state, "playing_needs_setup", "team_r setup incomplete")
            ok = False

        if not state.team_l.setup_complete:
            self._record(state, "playing_needs_setup", "team_l setup incomplete")
            ok = False

        if state.current_team not in ("r", "l"):
            self._record(state, "playing_valid_turn", f"invalid current_team: {state.current_team}")
            ok = False

        return ok

    def _check_game_over(self, state: GamePhaseState) -> bool:
        """Invariants for GAME_OVER phase."""
        ok = True

        if state.ply == 0:
            self._record(state, "game_over_has_moves", "GAME_OVER with no moves played")
            ok = False

        return ok


def check_board_invariants(grid: list[list], team_r_rgb: tuple, team_l_rgb: tuple) -> list[str]:
    """Check chess board invariants. Returns list of violations."""
    violations = []

    if len(grid) != 8:
        violations.append(f"Grid has {len(grid)} rows, expected 8")
        return violations

    for r, row in enumerate(grid):
        if len(row) != 8:
            violations.append(f"Row {r} has {len(row)} cols, expected 8")

    king_r = 0
    king_l = 0
    for r in range(8):
        for c in range(8):
            cell = grid[r][c]
            if cell is None:
                continue
            piece_type = cell.get("type") or cell.get("piece_type", "")
            team = cell.get("team") or cell.get("team_key", "")
            if piece_type.lower() == "king":
                if team == "r":
                    king_r += 1
                elif team == "l":
                    king_l += 1

    if king_r != 1:
        violations.append(f"team_r has {king_r} kings, expected 1")
    if king_l != 1:
        violations.append(f"team_l has {king_l} kings, expected 1")

    return violations
