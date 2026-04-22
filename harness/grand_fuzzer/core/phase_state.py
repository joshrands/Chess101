"""Game phase state machine for tracking networked game state."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class GamePhase(Enum):
    """Game phases in order of progression."""
    CONNECTING = auto()
    COLOR_PICK = auto()
    WAR_GAMES = auto()
    SETUP = auto()
    PLAYING = auto()
    GAME_OVER = auto()


@dataclass
class PendingAck:
    """Tracks a move awaiting acknowledgment."""
    seq: int
    sent_at: float
    move: dict


@dataclass
class GameState:
    """Tracks complete game state for invariant checking."""

    phase: GamePhase = GamePhase.CONNECTING

    color_idx: dict[str, int | None] = field(default_factory=lambda: {"r": None, "l": None})
    is_ai: dict[str, bool | None] = field(default_factory=lambda: {"r": None, "l": None})

    current_team: str = "r"
    last_team: str | None = None
    move_count: int = 0
    peace_time: int = 0

    host_hash: str | None = None
    guest_hash: str | None = None

    pending_acks: list[PendingAck] = field(default_factory=list)
    moves_after_gameover: list[dict] = field(default_factory=list)

    game_over_reason: str | None = None
    winning_team: str | None = None

    def advance_phase(self, new_phase: GamePhase) -> None:
        """Advance to next phase."""
        self.phase = new_phase

    def record_color_choice(self, team_key: str, color_idx: int) -> None:
        """Record a color choice."""
        self.color_idx[team_key] = color_idx

    def record_war_games_choice(self, team_key: str, is_ai: bool) -> None:
        """Record a war games choice."""
        self.is_ai[team_key] = is_ai

    def apply_move(self, move: dict, board_hash: str, is_host: bool) -> None:
        """Apply a move and update state."""
        if self.phase == GamePhase.GAME_OVER:
            self.moves_after_gameover.append(move)
            return

        self.last_team = self.current_team
        self.current_team = "l" if self.current_team == "r" else "r"
        self.move_count += 1

        if is_host:
            self.host_hash = board_hash
        else:
            self.guest_hash = board_hash

    def record_game_over(self, reason: str, winning_team: str | None = None) -> None:
        """Record game over."""
        self.phase = GamePhase.GAME_OVER
        self.game_over_reason = reason
        self.winning_team = winning_team

    def config_complete(self) -> bool:
        """Check if all config (colors + war games) is set."""
        return (
            self.color_idx["r"] is not None and
            self.color_idx["l"] is not None and
            self.is_ai["r"] is not None and
            self.is_ai["l"] is not None
        )
