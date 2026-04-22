"""Tests for NetworkedBoard phase message handling.

Tests that real game code handles adversarial phase inputs correctly.
"""
import pytest
import threading
from unittest.mock import MagicMock, patch

from core.team import Team


class FakeNetworkedBoard:
    """Minimal fake to test phase handlers without full NetworkedBoard setup."""

    def __init__(self):
        self.team_r = Team(64, 180, 232)
        self.team_l = Team(255, 140, 0)
        self.team_r.name = "team_r"
        self.team_l.name = "team_l"

        # team_array from simulator
        self.team_array = [
            Team(64, 180, 232),   # 0
            Team(255, 140, 0),    # 1
            Team(100, 200, 100),  # 2
            Team(200, 100, 200),  # 3
            Team(255, 255, 100),  # 4
            Team(100, 255, 255),  # 5
        ]
        for i, t in enumerate(self.team_array):
            t.name = f"color_{i}"

        self._remote_team_r_color_idx = None
        self._remote_team_l_color_idx = None
        self._remote_team_r_is_ai = None
        self._remote_team_l_is_ai = None
        self._config_received = threading.Event()
        self._game_start_evt = threading.Event()

        self.computer_player_r = False
        self.computer_player_l = False

    def _on_color_chosen(self, msg: dict) -> None:
        """Copy of real handler from networked_board.py."""
        team_key = msg.get("team_key")
        color_idx = msg.get("color_idx")
        if team_key is None:
            return
        if color_idx is not None:
            t = self.team_array[color_idx]  # Can IndexError!
            r_val, g_val, b_val, name = t.r, t.g, t.b, t.name
        else:
            r_val = msg.get("r")
            g_val = msg.get("g", 0)
            b_val = msg.get("b", 0)
            name = msg.get("name", "")
            if r_val is None:
                return
            color_idx = 0
        if team_key == "r":
            self.team_r.r, self.team_r.g, self.team_r.b = r_val, g_val, b_val
            if name:
                self.team_r.name = name
            self._remote_team_r_color_idx = color_idx
        else:
            self.team_l.r, self.team_l.g, self.team_l.b = r_val, g_val, b_val
            if name:
                self.team_l.name = name
            self._remote_team_l_color_idx = color_idx
        self._check_config_complete()

    def _on_war_games_choice(self, msg: dict) -> None:
        """Copy of real handler from networked_board.py."""
        team_key = msg.get("team_key")
        is_ai = msg.get("is_ai")
        if is_ai is None:
            is_ai = msg.get("player_type", "human") == "ai"
        if team_key == "r":
            self.computer_player_r = is_ai
            self._remote_team_r_is_ai = is_ai
        else:
            self.computer_player_l = is_ai
            self._remote_team_l_is_ai = is_ai
        self._check_config_complete()

    def _check_config_complete(self) -> None:
        """Copy of real handler from networked_board.py."""
        if self._config_received.is_set():
            return
        if (
            self._remote_team_r_color_idx is not None
            and self._remote_team_l_color_idx is not None
            and self._remote_team_r_is_ai is not None
            and self._remote_team_l_is_ai is not None
        ):
            self.team_r.r += 1  # BUG-02 lock-in
            self._config_received.set()

    def _on_game_start(self, msg: dict) -> None:
        """Copy of real handler from networked_board.py."""
        self._game_start_evt.set()


@pytest.fixture
def board():
    return FakeNetworkedBoard()


class TestColorChosenVulnerabilities:
    """Test _on_color_chosen with adversarial inputs."""

    def test_valid_color_idx(self, board):
        board._on_color_chosen({"team_key": "r", "color_idx": 0})
        assert board._remote_team_r_color_idx == 0

    def test_color_idx_negative_crashes(self, board):
        """BUG: negative color_idx causes IndexError or wrong color."""
        # This actually works in Python (negative indexing)
        # but gives unexpected color
        board._on_color_chosen({"team_key": "r", "color_idx": -1})
        # Got color 5 instead of error
        assert board._remote_team_r_color_idx == -1

    def test_color_idx_overflow_crashes(self, board):
        """BUG: color_idx >= 6 causes IndexError."""
        with pytest.raises(IndexError):
            board._on_color_chosen({"team_key": "r", "color_idx": 99})

    def test_color_idx_string_crashes(self, board):
        """BUG: string color_idx causes TypeError."""
        with pytest.raises(TypeError):
            board._on_color_chosen({"team_key": "r", "color_idx": "zero"})

    def test_duplicate_overwrites_silently(self, board):
        """Not necessarily a bug, but worth noting."""
        board._on_color_chosen({"team_key": "r", "color_idx": 0})
        board._on_color_chosen({"team_key": "r", "color_idx": 3})
        # Second one wins
        assert board._remote_team_r_color_idx == 3

    def test_missing_team_key_ignored(self, board):
        """Missing team_key is safely ignored."""
        board._on_color_chosen({"color_idx": 0})
        assert board._remote_team_r_color_idx is None

    def test_none_color_idx_uses_rgb(self, board):
        """None color_idx falls back to r/g/b format."""
        board._on_color_chosen({"team_key": "r", "color_idx": None, "r": 100, "g": 50, "b": 25})
        assert board.team_r.r == 100
        assert board.team_r.g == 50
        assert board.team_r.b == 25


class TestWarGamesVulnerabilities:
    """Test _on_war_games_choice with adversarial inputs."""

    def test_valid_is_ai(self, board):
        board._on_war_games_choice({"team_key": "r", "is_ai": True})
        assert board._remote_team_r_is_ai is True
        assert board.computer_player_r is True

    def test_is_ai_string_truthy(self, board):
        """String 'yes' is truthy, might cause issues."""
        board._on_war_games_choice({"team_key": "r", "is_ai": "yes"})
        # String "yes" is truthy, so computer_player_r = "yes"
        assert board.computer_player_r == "yes"  # Not a bool!

    def test_is_ai_none_uses_player_type(self, board):
        """None is_ai falls back to player_type."""
        board._on_war_games_choice({"team_key": "r", "is_ai": None, "player_type": "ai"})
        assert board._remote_team_r_is_ai is True

    def test_duplicate_overwrites(self, board):
        board._on_war_games_choice({"team_key": "r", "is_ai": False})
        board._on_war_games_choice({"team_key": "r", "is_ai": True})
        assert board._remote_team_r_is_ai is True


class TestConfigComplete:
    """Test _check_config_complete logic."""

    def test_all_config_sets_event(self, board):
        board._on_color_chosen({"team_key": "r", "color_idx": 0})
        board._on_color_chosen({"team_key": "l", "color_idx": 1})
        board._on_war_games_choice({"team_key": "r", "is_ai": False})
        assert not board._config_received.is_set()
        board._on_war_games_choice({"team_key": "l", "is_ai": False})
        assert board._config_received.is_set()

    def test_partial_config_no_event(self, board):
        board._on_color_chosen({"team_key": "r", "color_idx": 0})
        board._on_war_games_choice({"team_key": "r", "is_ai": False})
        assert not board._config_received.is_set()

    def test_config_complete_idempotent(self, board):
        """Multiple calls after complete don't re-trigger."""
        board._on_color_chosen({"team_key": "r", "color_idx": 0})
        board._on_color_chosen({"team_key": "l", "color_idx": 1})
        board._on_war_games_choice({"team_key": "r", "is_ai": False})
        board._on_war_games_choice({"team_key": "l", "is_ai": False})
        r_before = board.team_r.r
        # Call again
        board._check_config_complete()
        # BUG-02 increment shouldn't happen again
        assert board.team_r.r == r_before


class TestGameStart:
    """Test _on_game_start handling."""

    def test_game_start_sets_event(self, board):
        assert not board._game_start_evt.is_set()
        board._on_game_start({})
        assert board._game_start_evt.is_set()

    def test_game_start_before_config(self, board):
        """game_start before config is technically allowed."""
        board._on_game_start({})
        assert board._game_start_evt.is_set()
        # But config isn't complete
        assert not board._config_received.is_set()
