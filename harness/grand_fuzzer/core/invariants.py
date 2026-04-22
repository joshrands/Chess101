"""Per-phase invariant checkers."""
from __future__ import annotations

from .phase_state import GamePhase, GameState

NUM_COLORS = 6
ACK_TIMEOUT_S = 30.0


class PhaseInvariants:
    """Per-phase invariant checkers."""

    @staticmethod
    def check(state: GameState, clock_now: float) -> list[str]:
        """Run all invariants for current phase."""
        errors: list[str] = []

        if state.phase == GamePhase.COLOR_PICK:
            errors.extend(PhaseInvariants.color_pick(state))
        elif state.phase == GamePhase.WAR_GAMES:
            errors.extend(PhaseInvariants.war_games(state))
        elif state.phase == GamePhase.PLAYING:
            errors.extend(PhaseInvariants.playing(state, clock_now))
        elif state.phase == GamePhase.GAME_OVER:
            errors.extend(PhaseInvariants.game_over(state))

        return errors

    @staticmethod
    def color_pick(state: GameState) -> list[str]:
        """Check color pick invariants."""
        errors: list[str] = []

        for team_key in ("r", "l"):
            idx = state.color_idx.get(team_key)
            if idx is not None and not (0 <= idx < NUM_COLORS):
                errors.append(f"{team_key} color_idx {idx} out of range [0, {NUM_COLORS})")

        r_idx = state.color_idx.get("r")
        l_idx = state.color_idx.get("l")
        if r_idx is not None and l_idx is not None and r_idx == l_idx:
            errors.append(f"Both teams chose same color index: {r_idx}")

        return errors

    @staticmethod
    def war_games(state: GameState) -> list[str]:
        """Check war games invariants."""
        errors: list[str] = []

        for team_key in ("r", "l"):
            choice = state.is_ai.get(team_key)
            if choice is not None and not isinstance(choice, bool):
                errors.append(f"{team_key} is_ai not boolean: {choice!r}")

        return errors

    @staticmethod
    def playing(state: GameState, clock_now: float) -> list[str]:
        """Check playing phase invariants."""
        errors: list[str] = []

        if state.host_hash and state.guest_hash:
            if state.host_hash != state.guest_hash:
                errors.append(
                    f"Hash mismatch: host={state.host_hash[:16]}... "
                    f"guest={state.guest_hash[:16]}..."
                )

        for pending in state.pending_acks:
            elapsed = clock_now - pending.sent_at
            if elapsed > ACK_TIMEOUT_S:
                errors.append(f"Move ack timeout: seq={pending.seq} elapsed={elapsed:.1f}s")

        if state.last_team == state.current_team and state.move_count > 0:
            errors.append(f"Same team moved twice in a row: {state.current_team}")

        return errors

    @staticmethod
    def game_over(state: GameState) -> list[str]:
        """Check game over invariants."""
        errors: list[str] = []

        if state.moves_after_gameover:
            errors.append(
                f"Moves accepted after game_over: {len(state.moves_after_gameover)}"
            )

        return errors
