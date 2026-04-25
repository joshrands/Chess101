"""Corpus replay engine for lockstep disagreement reproduction.

Replays a corpus file through the Python chess engine (and optionally the JS
engine via JsBridge), yielding comparison results at each ply.  Used by both
``tests/test_corpus_replay.py`` (automated regression) and
``simulator/replay_runner.py`` (interactive visual replay).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.team import Team
from network.protocol import board_hash
from pieces.pawn import Pawn

from chess_helpers import (
    TEAM_R_RGB,
    TEAM_L_RGB,
    py_init_board,
    py_grid_to_json,
    py_apply_move,
    py_legal_moves,
    py_grid_snapshot,
    js_grid_to_snapshot,
    grids_equal,
    clear_en_passant,
)
from corpus import is_chaos_corpus, extract_moves_from_timeline


@dataclass
class ReplayResult:
    """Result of replaying a single ply."""

    ply: int
    move: dict
    py_hash: str
    js_hash: Optional[str] = None
    hashes_match: Optional[bool] = None
    grid_mismatch: Optional[str] = None


class ReplayEngine:
    """Replay a corpus through Python and optionally JS engines step by step.

    Parameters
    ----------
    corpus:
        Loaded corpus dict (from ``corpus.load_corpus``).
    bridge:
        Optional ``JsBridge`` instance.  When provided, each step also applies
        the move on the JS engine (and JS spectator for ``type=="networked"``).
    """

    def __init__(self, corpus: dict, bridge=None):
        self.corpus = corpus
        self.bridge = bridge
        self.is_chaos = is_chaos_corpus(corpus)

        if self.is_chaos:
            self.team_r = Team(*corpus.get("team_r_rgb", TEAM_R_RGB))
            self.team_l = Team(*corpus.get("team_l_rgb", TEAM_L_RGB))
            self._moves = extract_moves_from_timeline(corpus["timeline"])
        else:
            self.team_r = Team(*corpus["team_r_rgb"])
            self.team_l = Team(*corpus["team_l_rgb"])
            self._moves = corpus["moves"]

        self.py_grid: list = []
        self.peace_time: int = 0
        self.current_key: str = "r"
        self.ply: int = 0

        self._js_grid_json: Optional[list] = None
        self._spec_grid: Optional[list] = None

    def init(self) -> None:
        """Set up starting position on all engines."""
        self.py_grid = py_init_board(self.team_r, self.team_l)
        self.peace_time = 0
        self.current_key = "r"
        self.ply = 0

        if self.bridge:
            self._js_grid_json = self.bridge.chess_init(
                TEAM_R_RGB, TEAM_L_RGB,
            )
            corpus_type = self.corpus.get("type", "chess")
            if corpus_type == "networked":
                self._spec_grid = self.bridge.spectator_init()

    def step(self) -> ReplayResult:
        """Apply the next move from the corpus. Returns comparison results."""
        move = self._moves[self.ply]
        fr, fc, tr, tc = move["fr"], move["fc"], move["tr"], move["tc"]

        team = self.team_r if self.current_key == "r" else self.team_l

        # Clear en passant on current team (window expired)
        clear_en_passant(self.py_grid, team)

        # Compute en_passant_loc on the moving pawn (if it is a pawn) so
        # the serialized grid carries the correct value for the JS engine.
        # Without this, JS Pawn.move() can't detect en passant captures
        # because enPassantLoc would always be null.
        piece = self.py_grid[fr][fc]
        if isinstance(piece, Pawn):
            piece.calc_targets(self.py_grid)

        # Snapshot grid for JS before mutation
        grid_json = py_grid_to_json(self.py_grid, self.team_r) if self.bridge else None

        # Detect capture/pawn for peace_time before mutation
        is_capture = self.py_grid[tr][tc] is not None
        is_pawn = isinstance(self.py_grid[fr][fc], Pawn)

        # Apply on Python engine
        flags = py_apply_move(self.py_grid, fr, fc, tr, tc)

        self.peace_time = 0 if (is_capture or is_pawn) else self.peace_time + 1
        next_key = "l" if self.current_key == "r" else "r"

        # Compute Python hash
        py_hash = board_hash(
            self.py_grid, self.peace_time, next_key, self.team_r,
        )

        js_hash = None
        hashes_match = None
        grid_mismatch_desc = None

        if self.bridge:
            # Apply on JS engine
            js_result = self.bridge.chess_apply_move(
                grid_json, TEAM_R_RGB, TEAM_L_RGB,
                fr, fc, tr, tc, self.current_key, next_key, self.peace_time,
            )
            self._js_grid_json = js_result["grid"]
            js_hash = js_result["board_hash"]
            hashes_match = py_hash == js_hash

            # Apply on JS spectator (networked corpus only)
            corpus_type = self.corpus.get("type", "chess")
            if corpus_type == "networked" and self._spec_grid is not None:
                self._spec_grid = self.bridge.spectator_apply_move(
                    self._spec_grid, fr, fc, tr, tc, flags,
                )
                py_snap = py_grid_snapshot(self.py_grid, self.team_r)
                match, diff = grids_equal(py_snap, self._spec_grid)
                if not match:
                    grid_mismatch_desc = diff

        result = ReplayResult(
            ply=self.ply,
            move=move,
            py_hash=py_hash,
            js_hash=js_hash,
            hashes_match=hashes_match,
            grid_mismatch=grid_mismatch_desc,
        )

        self.ply += 1
        self.current_key = next_key

        return result

    @property
    def remaining(self) -> int:
        """Number of moves left to replay."""
        return len(self._moves) - self.ply

    @property
    def is_complete(self) -> bool:
        """True when all corpus moves have been replayed."""
        return self.ply >= len(self._moves)

    def grid_snapshot(self) -> list:
        """Current Python grid as JSON (for interactive mode)."""
        return py_grid_to_json(self.py_grid, self.team_r)
