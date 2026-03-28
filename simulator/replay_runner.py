"""Interactive corpus replay runner for the Pygame simulator.

Replays a ``.corpus.json`` file move-by-move in the visual simulator,
with pause/step/speed controls and human takeover.

Controls during replay:
    Space        Pause / resume auto-play
    Right arrow  Step forward one ply (when paused)
    Left arrow   Step backward one ply (re-inits from start)
    Up arrow     Speed up (shorter delay between moves)
    Down arrow   Slow down (longer delay between moves)
    T            Takeover — switch to live human play from current position
    N            Reset (same as normal GameRunner)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pygame

from core.team import Team
from pieces.pawn import Pawn
from pieces.king import King
from simulator.app import GameRunner, Phase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))

from chess_helpers import clear_en_passant, py_apply_move  # noqa: E402
from corpus import load_corpus  # noqa: E402

logger = logging.getLogger(__name__)

# Speed presets (ms delay between auto-played moves)
_SPEED_STEPS = [100, 200, 350, 500, 750, 1000, 1500, 2000]
_DEFAULT_SPEED_IDX = 3  # 500ms


class ReplayRunner(GameRunner):
    """GameRunner subclass that replays a corpus file interactively."""

    def __init__(self, corpus_path: Path) -> None:
        super().__init__(skip_lobby=True)
        self._corpus_path = corpus_path
        self._corpus: dict = {}
        self._replay_ply: int = 0
        self._replay_mode: bool = True
        self._replay_paused: bool = True  # start paused so user can orient
        self._speed_idx: int = _DEFAULT_SPEED_IDX
        self._last_replay_ms: int = 0
        self._takeover_ply: int | None = None

    # ── board setup ──────────────────────────────────────────────────────

    def _init_board(self) -> None:
        self._corpus = load_corpus(self._corpus_path)
        super()._init_board()

        b = self._b

        # Set team colours from corpus
        r, g, bl = self._corpus["team_r_rgb"]
        b.team_r = Team(r, g, bl)
        b.team_r.name = "Right"
        r, g, bl = self._corpus["team_l_rgb"]
        b.team_l = Team(r, g, bl)
        b.team_l.name = "Left"

        # Both sides are human (no AI during replay)
        b.computer_player_r = False
        b.computer_player_l = False

        # Set up the standard starting position
        b.initialize_game_board()

        # Jump straight to PLAYING
        self.phase = Phase.PLAYING
        self._current_team = b.team_r
        self._replay_ply = 0
        self._begin_turn(self._current_team)

        logger.info(
            "Corpus loaded: %d moves, failure at ply %d (%s)",
            len(self._corpus["moves"]),
            self._corpus["failure"]["ply"],
            self._corpus["failure"].get("kind", "?"),
        )

    # ── replay step logic ────────────────────────────────────────────────

    def _replay_step_forward(self) -> None:
        """Apply the next corpus move to the board."""
        if self._replay_ply >= len(self._corpus["moves"]):
            self._replay_paused = True
            return

        move = self._corpus["moves"][self._replay_ply]
        fr, fc, tr, tc = move["fr"], move["fc"], move["tr"], move["tc"]
        b = self._b

        # Clear en passant on current team (same as fuzzer)
        clear_en_passant(b.grid, self._current_team)

        # Move piece on the board grid
        b.grid[tr][tc] = b.grid[fr][fc]
        self._apply_move(fr, fc, tr, tc)

        self._move_count += 1
        self._replay_ply += 1

        # Update peace_time
        flags = move.get("flags", {})
        if flags.get("is_capture") or isinstance(b.grid[tr][tc], Pawn):
            self.peace_time = 0
        else:
            self.peace_time += 1

        # Swap turn
        self._next_turn()

    def _replay_to_ply(self, target_ply: int) -> None:
        """Re-initialize and replay to a specific ply. Fast (no rendering)."""
        b = self._b
        b.initialize_game_board()
        self._current_team = b.team_r
        self._move_count = 0
        self.peace_time = 0
        self._replay_ply = 0
        self._in_check = False
        self._king_check_pos = None
        self._selected_piece = None

        for _ in range(target_ply):
            if self._replay_ply >= len(self._corpus["moves"]):
                break
            self._replay_step_forward()

    def _replay_step_backward(self) -> None:
        """Step back one ply by re-initializing from start."""
        if self._replay_ply <= 0:
            return
        self._replay_to_ply(self._replay_ply - 1)

    def _do_takeover(self) -> None:
        """Switch from replay mode to live human play."""
        self._replay_mode = False
        self._takeover_ply = self._replay_ply
        self._selected_piece = None
        # _begin_turn was already called by _next_turn at end of last replay step
        logger.info("Takeover at ply %d — human play begins", self._replay_ply)

    # ── event handling ───────────────────────────────────────────────────

    def _handle_playing(self, event: pygame.event.Event) -> None:
        if not self._replay_mode:
            # Normal human play after takeover
            super()._handle_playing(event)
            return

        if event.type != pygame.KEYDOWN:
            return

        if event.key == pygame.K_SPACE:
            self._replay_paused = not self._replay_paused
            logger.info("Replay %s", "paused" if self._replay_paused else "resumed")

        elif event.key == pygame.K_RIGHT:
            if self._replay_ply < len(self._corpus["moves"]):
                self._replay_step_forward()
            else:
                logger.info("End of corpus reached")

        elif event.key == pygame.K_LEFT:
            self._replay_step_backward()

        elif event.key == pygame.K_UP:
            if self._speed_idx > 0:
                self._speed_idx -= 1
            logger.info("Replay speed: %d ms", _SPEED_STEPS[self._speed_idx])

        elif event.key == pygame.K_DOWN:
            if self._speed_idx < len(_SPEED_STEPS) - 1:
                self._speed_idx += 1
            logger.info("Replay speed: %d ms", _SPEED_STEPS[self._speed_idx])

        elif event.key == pygame.K_t:
            self._do_takeover()

        elif event.key == pygame.K_n:
            self._reset()
            self._init_board()

    # ── update (auto-play) ───────────────────────────────────────────────

    def _update(self) -> None:
        if not self._replay_mode:
            super()._update()
            return

        if self._replay_paused:
            return

        now = pygame.time.get_ticks()
        delay = _SPEED_STEPS[self._speed_idx]
        if now - self._last_replay_ms < delay:
            return

        if self._replay_ply < len(self._corpus["moves"]):
            self._replay_step_forward()
            self._last_replay_ms = now
        else:
            self._replay_paused = True

    # ── panel extra ──────────────────────────────────────────────────────

    def _render_panel_extra(self, text, sep, pfont_sm, pfont_md) -> None:
        sep()
        total = len(self._corpus["moves"])
        failure_ply = self._corpus["failure"]["ply"]

        if self._replay_mode:
            status = "PAUSED" if self._replay_paused else "PLAYING"
            text(f"Replay: {status}", pfont_md, (180, 220, 255), 0)
            text(f"Ply {self._replay_ply}/{total}", pfont_sm, (200, 200, 200), 0)
            text(f"Speed: {_SPEED_STEPS[self._speed_idx]}ms", pfont_sm, (160, 160, 160), 0)

            # Show current move info
            if 0 < self._replay_ply <= total:
                m = self._corpus["moves"][self._replay_ply - 1]
                flags = m.get("flags", {})
                flag_parts = []
                if flags.get("is_capture"):
                    flag_parts.append("capture")
                if flags.get("is_en_passant"):
                    flag_parts.append("e.p.")
                if flags.get("is_castling"):
                    flag_parts.append("castle")
                if flags.get("is_promotion"):
                    flag_parts.append("promo")
                flag_str = " ".join(flag_parts) if flag_parts else ""
                text(
                    f"({m['fr']},{m['fc']})->({m['tr']},{m['tc']}) {flag_str}",
                    pfont_sm, (180, 180, 180), 0,
                )

            # Highlight failure ply
            if self._replay_ply == failure_ply:
                text(
                    f">> FAILURE PLY ({self._corpus['failure'].get('kind', '?')})",
                    pfont_md, (255, 80, 80), 0,
                )
            elif self._replay_ply > failure_ply:
                text("(past failure ply)", pfont_sm, (200, 100, 100), 0)

            sep()
            text("Space: pause/play", pfont_sm, (120, 120, 120), 0)
            text("Left/Right: step", pfont_sm, (120, 120, 120), 0)
            text("Up/Down: speed", pfont_sm, (120, 120, 120), 0)
            text("T: takeover", pfont_sm, (120, 120, 120), 0)
        else:
            text(f"TAKEOVER from ply {self._takeover_ply}", pfont_md, (100, 255, 100), 0)
            text(f"Failure was at ply {failure_ply}", pfont_sm, (160, 160, 160), 0)
