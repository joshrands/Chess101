# tests/test_lockstep_runner.py
"""Unit tests for lockstep_runner module."""
from __future__ import annotations

import pytest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.lockstep_runner import PythonEngine, JsEngine, SwiftEngine, HilEngine, LockstepRunner


class TestLockstepRunner:
    def test_run_game_both_agree(self):
        """Two engines that agree should return True."""
        py = PythonEngine()
        js = JsEngine()
        try:
            runner = LockstepRunner(
                engines=[py, js],
                crashes_dir=Path("/tmp/test_crashes"),
                seed=42,
                max_ply=10,
            )
            ok = runner.run_game(12345)
            assert ok is True
        finally:
            js.close()

    def test_run_fuzzing_returns_stats(self):
        """run_fuzzing should return (total, ok, disagree)."""
        py = PythonEngine()
        js = JsEngine()
        try:
            runner = LockstepRunner(
                engines=[py, js],
                crashes_dir=Path("/tmp/test_crashes"),
                seed=42,
                max_ply=20,
            )
            total, ok, disagree = runner.run_fuzzing(3)
            assert total == 3
            assert ok == 3
            assert disagree == 0
        finally:
            js.close()


class TestPythonEngine:
    def test_name(self):
        engine = PythonEngine()
        assert engine.name == "python"

    def test_init_game(self):
        engine = PythonEngine()
        engine.init_game((64, 180, 232), (255, 140, 0))
        # Should not raise

    def test_legal_moves_initial_position(self):
        engine = PythonEngine()
        engine.init_game((64, 180, 232), (255, 140, 0))
        moves = engine.legal_moves("r")
        # 20 legal moves for white in starting position
        assert len(moves) == 20
        # Check a known pawn move exists
        assert (1, 0, 2, 0) in moves  # a2-a3
        assert (1, 0, 3, 0) in moves  # a2-a4

    def test_apply_move(self):
        engine = PythonEngine()
        engine.init_game((64, 180, 232), (255, 140, 0))
        result = engine.apply_move(1, 4, 3, 4, "r", "l", 0)  # e2-e4
        assert "grid" in result
        assert "board_hash" in result
        assert isinstance(result["board_hash"], str)
        assert len(result["board_hash"]) == 64  # SHA-256 hex


class TestJsEngine:
    def test_name(self):
        engine = JsEngine()
        try:
            assert engine.name == "js"
        finally:
            engine.close()

    def test_init_and_legal_moves(self):
        engine = JsEngine()
        try:
            engine.init_game((64, 180, 232), (255, 140, 0))
            moves = engine.legal_moves("r")
            assert len(moves) == 20
        finally:
            engine.close()

    def test_apply_move(self):
        engine = JsEngine()
        try:
            engine.init_game((64, 180, 232), (255, 140, 0))
            result = engine.apply_move(1, 4, 3, 4, "r", "l", 0)
            assert "board_hash" in result
        finally:
            engine.close()


class TestSwiftEngine:
    def test_name(self):
        engine = SwiftEngine()
        try:
            assert engine.name == "swift"
        finally:
            engine.close()

    def test_init_and_legal_moves(self):
        engine = SwiftEngine()
        try:
            engine.init_game((64, 180, 232), (255, 140, 0))
            moves = engine.legal_moves("r")
            assert len(moves) == 20
        finally:
            engine.close()

    def test_apply_move(self):
        engine = SwiftEngine()
        try:
            engine.init_game((64, 180, 232), (255, 140, 0))
            result = engine.apply_move(1, 4, 3, 4, "r", "l", 0)
            assert "board_hash" in result
        finally:
            engine.close()


class TestHilEngine:
    def test_name(self):
        engine = HilEngine("ws://localhost:8766")
        assert engine.name == "hil"

    @pytest.mark.skip(reason="Requires running HIL container")
    def test_connect_and_legal_moves(self):
        engine = HilEngine("ws://localhost:8766")
        try:
            engine.connect()
            engine.init_game((64, 180, 232), (255, 140, 0))
            moves = engine.legal_moves("r")
            assert len(moves) == 20
        finally:
            engine.close()