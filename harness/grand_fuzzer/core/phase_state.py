"""Game phase state machine for fuzzing.

Tracks game phases and validates transitions:
LOBBY -> COLOR_PICK -> WAR_GAMES -> SETUP -> PLAYING -> GAME_OVER
"""
from __future__ import annotations

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Callable


class GamePhase(Enum):
    """Game phases matching simulator/app.py."""
    LOBBY = auto()
    COLOR_PICK = auto()
    WAR_GAMES = auto()
    SETUP = auto()
    PLAYING = auto()
    GAME_OVER = auto()


@dataclass
class PhaseConfig:
    """Configuration for a player in the game."""
    color_idx: int | None = None
    color_rgb: tuple[int, int, int] | None = None
    is_ai: bool | None = None
    setup_complete: bool = False


@dataclass
class GamePhaseState:
    """Tracks complete game state across phases."""
    phase: GamePhase = GamePhase.LOBBY
    team_r: PhaseConfig = field(default_factory=PhaseConfig)
    team_l: PhaseConfig = field(default_factory=PhaseConfig)
    game_started: bool = False
    current_team: str = "r"
    ply: int = 0
    errors: list[str] = field(default_factory=list)

    def transition_to(self, new_phase: GamePhase) -> bool:
        """Attempt phase transition. Returns True if valid."""
        valid_transitions = {
            GamePhase.LOBBY: {GamePhase.COLOR_PICK},
            GamePhase.COLOR_PICK: {GamePhase.WAR_GAMES},
            GamePhase.WAR_GAMES: {GamePhase.SETUP},
            GamePhase.SETUP: {GamePhase.PLAYING},
            GamePhase.PLAYING: {GamePhase.GAME_OVER},
            GamePhase.GAME_OVER: {GamePhase.LOBBY},
        }
        if new_phase in valid_transitions.get(self.phase, set()):
            self.phase = new_phase
            return True
        self.errors.append(f"Invalid transition: {self.phase.name} -> {new_phase.name}")
        return False

    def handle_color_chosen(self, msg: dict) -> bool:
        """Handle color_chosen message. Returns True if valid."""
        if self.phase != GamePhase.COLOR_PICK:
            self.errors.append(f"color_chosen in wrong phase: {self.phase.name}")
            return False

        team_key = msg.get("team_key")
        color_idx = msg.get("color_idx")
        r = msg.get("r")
        g = msg.get("g", 0)
        b = msg.get("b", 0)

        config = self.team_r if team_key == "r" else self.team_l

        if config.color_idx is not None:
            self.errors.append(f"Duplicate color_chosen for team_{team_key}")
            return False

        if color_idx is not None:
            if not isinstance(color_idx, int) or not (0 <= color_idx <= 5):
                self.errors.append(f"Invalid color_idx: {color_idx}")
                return False
            config.color_idx = color_idx
        elif r is not None:
            config.color_rgb = (r, g, b)
            config.color_idx = 0
        else:
            self.errors.append("color_chosen missing color_idx and r/g/b")
            return False

        if self._both_colors_set():
            if self.team_r.color_idx == self.team_l.color_idx:
                self.errors.append("Both teams chose same color")
                return False
            self.transition_to(GamePhase.WAR_GAMES)

        return True

    def handle_war_games_choice(self, msg: dict) -> bool:
        """Handle war_games_choice message. Returns True if valid."""
        if self.phase != GamePhase.WAR_GAMES:
            self.errors.append(f"war_games_choice in wrong phase: {self.phase.name}")
            return False

        team_key = msg.get("team_key")
        is_ai = msg.get("is_ai")
        if is_ai is None:
            is_ai = msg.get("player_type", "human") == "ai"

        config = self.team_r if team_key == "r" else self.team_l

        if config.is_ai is not None:
            self.errors.append(f"Duplicate war_games_choice for team_{team_key}")
            return False

        if not isinstance(is_ai, bool):
            self.errors.append(f"is_ai not boolean: {type(is_ai)}")
            return False

        config.is_ai = is_ai

        if self._both_war_games_set():
            self.transition_to(GamePhase.SETUP)

        return True

    def handle_game_start(self, msg: dict) -> bool:
        """Handle game_start message. Returns True if valid."""
        if self.phase != GamePhase.SETUP:
            self.errors.append(f"game_start in wrong phase: {self.phase.name}")
            return False

        if self.game_started:
            self.errors.append("Duplicate game_start")
            return False

        self.game_started = True
        return True

    def handle_setup_complete(self, msg: dict) -> bool:
        """Handle setup_complete message. Returns True if valid."""
        if self.phase != GamePhase.SETUP:
            self.errors.append(f"setup_complete in wrong phase: {self.phase.name}")
            return False

        if not self.game_started:
            self.errors.append("setup_complete before game_start")
            return False

        team_key = msg.get("team_key")
        config = self.team_r if team_key == "r" else self.team_l

        if config.setup_complete:
            self.errors.append(f"Duplicate setup_complete for team_{team_key}")
            return False

        config.setup_complete = True

        if self.team_r.setup_complete and self.team_l.setup_complete:
            self.transition_to(GamePhase.PLAYING)

        return True

    def handle_move(self, msg: dict) -> bool:
        """Handle move message. Returns True if valid."""
        if self.phase != GamePhase.PLAYING:
            self.errors.append(f"move in wrong phase: {self.phase.name}")
            return False
        self.ply += 1
        self.current_team = "l" if self.current_team == "r" else "r"
        return True

    def handle_game_over(self, msg: dict) -> bool:
        """Handle game_over message. Returns True if valid."""
        if self.phase != GamePhase.PLAYING:
            self.errors.append(f"game_over in wrong phase: {self.phase.name}")
            return False
        self.transition_to(GamePhase.GAME_OVER)
        return True

    def handle_message(self, msg: dict) -> bool:
        """Route message to appropriate handler. Returns True if valid."""
        msg_type = msg.get("type", "")
        handlers = {
            "color_chosen": self.handle_color_chosen,
            "war_games_choice": self.handle_war_games_choice,
            "game_start": self.handle_game_start,
            "setup_complete": self.handle_setup_complete,
            "move": self.handle_move,
            "game_over": self.handle_game_over,
        }
        handler = handlers.get(msg_type)
        if handler:
            return handler(msg)
        return True  # Unknown message types are allowed through

    def _both_colors_set(self) -> bool:
        return self.team_r.color_idx is not None and self.team_l.color_idx is not None

    def _both_war_games_set(self) -> bool:
        return self.team_r.is_ai is not None and self.team_l.is_ai is not None

    def config_complete(self) -> bool:
        """Check if all config is complete and ready for PLAYING."""
        return (
            self._both_colors_set()
            and self._both_war_games_set()
            and self.game_started
            and self.team_r.setup_complete
            and self.team_l.setup_complete
        )

    def reset(self) -> None:
        """Reset to initial state."""
        self.phase = GamePhase.LOBBY
        self.team_r = PhaseConfig()
        self.team_l = PhaseConfig()
        self.game_started = False
        self.current_team = "r"
        self.ply = 0
        self.errors.clear()
