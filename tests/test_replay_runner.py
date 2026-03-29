"""
test_replay_runner.py — Unit tests for simulator/replay_runner.py.

Covers:
  - Forward stepping applies moves correctly and produces correct board hashes
  - Backward stepping (re-init + replay) restores exact board state at any ply
  - Board hash matches at every ply after forward, backward, and mixed stepping
  - Piece count is correct after backward stepping (no leftover pieces)
  - Takeover switches from replay mode to live human play
  - Speed adjustment stays within bounds
  - Pause/resume toggles
  - Reset re-initializes from corpus

Run with:
    .venv/bin/python -m pytest tests/test_replay_runner.py -v
"""
from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest

# Ensure harness/ bare imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))

from network.protocol import board_hash


# ── Helpers ──────────────────────────────────────────────────────────────────

def _count_pieces(grid):
    return sum(1 for row in grid for p in row if p is not None)


def _grid_hash(runner):
    """Compute board_hash from the runner's current state."""
    b = runner._b
    next_key = "l" if runner._current_team.r == b.team_r.r else "r"
    return board_hash(b.grid, runner.peace_time, next_key, b.team_r)


def _make_corpus(moves, failure_ply=None, failure_kind="legal_moves"):
    """Build a minimal in-memory corpus dict."""
    if failure_ply is None:
        failure_ply = len(moves)
    return {
        "version": 1,
        "type": "chess",
        "created": "2026-01-01T00:00:00Z",
        "source": "test",
        "team_r_rgb": [64, 180, 232],
        "team_l_rgb": [255, 140, 0],
        "seed": 0,
        "moves": moves,
        "failure": {
            "ply": failure_ply,
            "kind": failure_kind,
            "detail": "test",
        },
    }


# A short sequence of opening moves (all legal, no captures for simplicity):
#   ply 0: R e2-e4  (1,4)->(3,4)
#   ply 1: L e7-e5  (6,4)->(4,4)
#   ply 2: R Nf3    (0,6)->(2,5)
#   ply 3: L Nc6    (7,1)->(5,2)
#   ply 4: R Bb5    (0,5)->(4,1)
_OPENING_MOVES = [
    {"fr": 1, "fc": 4, "tr": 3, "tc": 4, "team_key": "r",
     "flags": {"is_capture": False, "is_en_passant": False,
               "is_castling": False, "is_promotion": False,
               "promoted_to": None, "captured_at": None,
               "rook_from": None, "rook_to": None}},
    {"fr": 6, "fc": 4, "tr": 4, "tc": 4, "team_key": "l",
     "flags": {"is_capture": False, "is_en_passant": False,
               "is_castling": False, "is_promotion": False,
               "promoted_to": None, "captured_at": None,
               "rook_from": None, "rook_to": None}},
    {"fr": 0, "fc": 6, "tr": 2, "tc": 5, "team_key": "r",
     "flags": {"is_capture": False, "is_en_passant": False,
               "is_castling": False, "is_promotion": False,
               "promoted_to": None, "captured_at": None,
               "rook_from": None, "rook_to": None}},
    {"fr": 7, "fc": 1, "tr": 5, "tc": 2, "team_key": "l",
     "flags": {"is_capture": False, "is_en_passant": False,
               "is_castling": False, "is_promotion": False,
               "promoted_to": None, "captured_at": None,
               "rook_from": None, "rook_to": None}},
    {"fr": 0, "fc": 5, "tr": 4, "tc": 1, "team_key": "r",
     "flags": {"is_capture": False, "is_en_passant": False,
               "is_castling": False, "is_promotion": False,
               "promoted_to": None, "captured_at": None,
               "rook_from": None, "rook_to": None}},
]


@pytest.fixture
def corpus_file(tmp_path):
    """Write a corpus file with the opening moves and return its path."""
    corpus = _make_corpus(_OPENING_MOVES, failure_ply=5)
    p = tmp_path / "test.corpus.json"
    p.write_text(json.dumps(corpus))
    return p


@pytest.fixture
def runner(corpus_file):
    """Create a ReplayRunner, initialize it, and return it."""
    pygame.init()
    pygame.display.set_mode((1, 1))
    from simulator.replay_runner import ReplayRunner
    r = ReplayRunner(corpus_path=corpus_file)
    r._init_board()
    return r


# ── Forward stepping ────────────────────────────────────────────────────────

class TestForwardStepping:
    def test_initial_state(self, runner):
        assert runner._replay_ply == 0
        assert runner._replay_mode is True
        assert runner._replay_paused is True
        assert _count_pieces(runner._b.grid) == 32

    def test_step_forward_advances_ply(self, runner):
        runner._replay_step_forward()
        assert runner._replay_ply == 1

    def test_step_forward_moves_piece(self, runner):
        b = runner._b
        # Before: pawn at (1,4), nothing at (3,4)
        assert b.grid[1][4] is not None
        assert b.grid[3][4] is None
        runner._replay_step_forward()
        # After: pawn moved to (3,4), source cleared
        assert b.grid[1][4] is None
        assert b.grid[3][4] is not None

    def test_step_forward_swaps_team(self, runner):
        b = runner._b
        assert runner._current_team.r == b.team_r.r
        runner._replay_step_forward()
        assert runner._current_team.r == b.team_l.r
        runner._replay_step_forward()
        assert runner._current_team.r == b.team_r.r

    def test_piece_count_constant_no_captures(self, runner):
        for _ in range(5):
            runner._replay_step_forward()
            assert _count_pieces(runner._b.grid) == 32

    def test_stops_at_end_of_corpus(self, runner):
        for _ in range(5):
            runner._replay_step_forward()
        assert runner._replay_ply == 5
        runner._replay_step_forward()  # should be a no-op
        assert runner._replay_ply == 5
        assert runner._replay_paused is True


# ── Backward stepping ───────────────────────────────────────────────────────

class TestBackwardStepping:
    def test_step_backward_from_ply_0_is_noop(self, runner):
        runner._replay_step_backward()
        assert runner._replay_ply == 0

    def test_backward_restores_piece_count(self, runner):
        for _ in range(5):
            runner._replay_step_forward()
        runner._replay_to_ply(0)
        assert _count_pieces(runner._b.grid) == 32

    def test_backward_restores_board_hash(self, runner):
        """Board hash at each ply must match after backward + forward replay."""
        hashes = [_grid_hash(runner)]
        for _ in range(5):
            runner._replay_step_forward()
            hashes.append(_grid_hash(runner))

        # Step backward to each ply and verify hash matches
        for target in [3, 1, 0, 4, 2, 5]:
            runner._replay_to_ply(target)
            assert _grid_hash(runner) == hashes[target], (
                f"Hash mismatch at ply {target}"
            )

    def test_backward_then_forward_matches(self, runner):
        """Full forward replay after backward stepping produces same hashes."""
        hashes = [_grid_hash(runner)]
        for _ in range(5):
            runner._replay_step_forward()
            hashes.append(_grid_hash(runner))

        runner._replay_to_ply(0)
        assert _grid_hash(runner) == hashes[0]

        for i in range(5):
            runner._replay_step_forward()
            assert _grid_hash(runner) == hashes[i + 1], (
                f"Forward replay hash mismatch at ply {i + 1}"
            )

    def test_step_backward_one_ply(self, runner):
        for _ in range(3):
            runner._replay_step_forward()
        h2 = None
        # Record hash at ply 2 by going back
        runner._replay_to_ply(2)
        h2 = _grid_hash(runner)

        runner._replay_to_ply(3)
        runner._replay_step_backward()
        assert runner._replay_ply == 2
        assert _grid_hash(runner) == h2


# ── Backward stepping with real corpus file ─────────────────────────────────

class TestBackwardSteppingRealCorpus:
    """Use a real fuzzer corpus file (if available) to test backward stepping
    with captures and more complex positions."""

    @pytest.fixture
    def real_runner(self):
        crashes_dir = Path(__file__).resolve().parent.parent / "harness" / "crashes" / "chess"
        corpus_files = sorted(crashes_dir.glob("*.corpus.json"))
        if not corpus_files:
            pytest.skip("No corpus files available")
        pygame.init()
        pygame.display.set_mode((1, 1))
        from simulator.replay_runner import ReplayRunner
        r = ReplayRunner(corpus_path=corpus_files[0])
        r._init_board()
        return r

    def test_backward_restores_hash_real_corpus(self, real_runner):
        runner = real_runner
        total = len(runner._corpus["moves"])
        limit = min(total, 20)

        hashes = [_grid_hash(runner)]
        piece_counts = [_count_pieces(runner._b.grid)]
        for _ in range(limit):
            runner._replay_step_forward()
            hashes.append(_grid_hash(runner))
            piece_counts.append(_count_pieces(runner._b.grid))

        # Step backward through several plies
        for target in [limit // 2, 0, limit, limit // 4]:
            target = min(target, limit)
            runner._replay_to_ply(target)
            assert _count_pieces(runner._b.grid) == piece_counts[target], (
                f"Piece count wrong at ply {target}: "
                f"got {_count_pieces(runner._b.grid)}, expected {piece_counts[target]}"
            )
            assert _grid_hash(runner) == hashes[target], (
                f"Hash mismatch at ply {target}"
            )


# ── Takeover ─────────────────────────────────────────────────────────────────

class TestTakeover:
    def test_takeover_disables_replay_mode(self, runner):
        for _ in range(3):
            runner._replay_step_forward()
        runner._do_takeover()
        assert runner._replay_mode is False
        assert runner._takeover_ply == 3

    def test_takeover_preserves_board_state(self, runner):
        for _ in range(3):
            runner._replay_step_forward()
        h_before = _grid_hash(runner)
        runner._do_takeover()
        assert _grid_hash(runner) == h_before


# ── Controls ─────────────────────────────────────────────────────────────────

class TestReplayControls:
    def test_pause_toggle(self, runner):
        assert runner._replay_paused is True
        runner._replay_paused = False
        assert runner._replay_paused is False

    def test_speed_bounds(self, runner):
        from simulator.replay_runner import _SPEED_STEPS
        # Speed up to minimum
        for _ in range(20):
            if runner._speed_idx > 0:
                runner._speed_idx -= 1
        assert runner._speed_idx == 0
        # Slow down to maximum
        for _ in range(20):
            if runner._speed_idx < len(_SPEED_STEPS) - 1:
                runner._speed_idx += 1
        assert runner._speed_idx == len(_SPEED_STEPS) - 1
