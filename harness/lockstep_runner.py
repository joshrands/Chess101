# harness/lockstep_runner.py
"""Modular lockstep chess engine testing framework.

Provides a pluggable architecture for testing multiple chess engine
implementations in lockstep. Each engine implements the ChessEngine
protocol; the LockstepRunner plays games through all engines and
detects disagreements.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Set, Tuple

from core.team import Team
from network.protocol import board_hash
from harness.chess_helpers import (
    TEAM_R_RGB,
    TEAM_L_RGB,
    py_init_board,
    py_grid_to_json,
    py_legal_moves,
    py_apply_move,
    clear_en_passant,
)
from harness.python_bridge import JsBridge
from harness.swift_bridge import SwiftBridge


class ChessEngine(ABC):
    """Protocol for lockstep-testable chess engines."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable engine name for error reporting."""
        ...

    @abstractmethod
    def init_game(
        self,
        team_r_rgb: tuple[int, int, int],
        team_l_rgb: tuple[int, int, int],
    ) -> None:
        """Initialize a new game with the given team colors."""
        ...

    @abstractmethod
    def legal_moves(self, team_key: str) -> Set[Tuple[int, int, int, int]]:
        """Return set of (fr, fc, tr, tc) legal moves for the team."""
        ...

    @abstractmethod
    def apply_move(
        self,
        fr: int, fc: int, tr: int, tc: int,
        team_key: str, next_key: str, peace_time: int,
    ) -> dict:
        """Apply move and return {'grid': ..., 'board_hash': ...}."""
        ...

    def close(self) -> None:
        """Clean up resources (optional)."""
        pass


class PythonEngine(ChessEngine):
    """Python chess engine using chess_helpers directly."""

    def __init__(self) -> None:
        self._grid: list | None = None
        self._team_r: Team | None = None
        self._team_l: Team | None = None

    @property
    def name(self) -> str:
        return "python"

    def init_game(
        self,
        team_r_rgb: tuple[int, int, int],
        team_l_rgb: tuple[int, int, int],
    ) -> None:
        self._team_r = Team(*team_r_rgb)
        self._team_l = Team(*team_l_rgb)
        self._grid = py_init_board(self._team_r, self._team_l)

    def legal_moves(self, team_key: str) -> Set[Tuple[int, int, int, int]]:
        if self._grid is None or self._team_r is None or self._team_l is None:
            raise RuntimeError("Game not initialized")
        team = self._team_r if team_key == "r" else self._team_l
        clear_en_passant(self._grid, team)
        return py_legal_moves(self._grid, team)

    def apply_move(
        self,
        fr: int, fc: int, tr: int, tc: int,
        team_key: str, next_key: str, peace_time: int,
    ) -> dict:
        if self._grid is None or self._team_r is None:
            raise RuntimeError("Game not initialized")
        py_apply_move(self._grid, fr, fc, tr, tc)
        grid_json = py_grid_to_json(self._grid, self._team_r)
        hash_val = board_hash(self._grid, peace_time, next_key, self._team_r)
        return {"grid": grid_json, "board_hash": hash_val}


class JsEngine(ChessEngine):
    """JavaScript chess engine via JsBridge subprocess."""

    def __init__(self) -> None:
        self._bridge = JsBridge()
        self._grid: list | None = None
        self._team_r_rgb: tuple[int, int, int] = TEAM_R_RGB
        self._team_l_rgb: tuple[int, int, int] = TEAM_L_RGB

    @property
    def name(self) -> str:
        return "js"

    def init_game(
        self,
        team_r_rgb: tuple[int, int, int],
        team_l_rgb: tuple[int, int, int],
    ) -> None:
        self._team_r_rgb = team_r_rgb
        self._team_l_rgb = team_l_rgb
        self._grid = self._bridge.chess_init(team_r_rgb, team_l_rgb)

    def legal_moves(self, team_key: str) -> Set[Tuple[int, int, int, int]]:
        if self._grid is None:
            raise RuntimeError("Game not initialized")
        raw = self._bridge.chess_legal_moves(
            self._grid, self._team_r_rgb, self._team_l_rgb, team_key
        )
        return {tuple(m) for m in raw}

    def apply_move(
        self,
        fr: int, fc: int, tr: int, tc: int,
        team_key: str, next_key: str, peace_time: int,
    ) -> dict:
        if self._grid is None:
            raise RuntimeError("Game not initialized")
        result = self._bridge.chess_apply_move(
            self._grid, self._team_r_rgb, self._team_l_rgb,
            fr, fc, tr, tc, team_key, next_key, peace_time,
        )
        self._grid = result["grid"]
        return result

    def close(self) -> None:
        self._bridge.close()


class SwiftEngine(ChessEngine):
    """Swift chess engine via SwiftBridge subprocess."""

    def __init__(self) -> None:
        self._bridge = SwiftBridge()
        self._grid: list | None = None
        self._team_r_rgb: tuple[int, int, int] = TEAM_R_RGB
        self._team_l_rgb: tuple[int, int, int] = TEAM_L_RGB

    @property
    def name(self) -> str:
        return "swift"

    def init_game(
        self,
        team_r_rgb: tuple[int, int, int],
        team_l_rgb: tuple[int, int, int],
    ) -> None:
        self._team_r_rgb = team_r_rgb
        self._team_l_rgb = team_l_rgb
        self._grid = self._bridge.chess_init(team_r_rgb, team_l_rgb)

    def legal_moves(self, team_key: str) -> Set[Tuple[int, int, int, int]]:
        if self._grid is None:
            raise RuntimeError("Game not initialized")
        raw = self._bridge.chess_legal_moves(
            self._grid, self._team_r_rgb, self._team_l_rgb, team_key
        )
        return {tuple(m) for m in raw}

    def apply_move(
        self,
        fr: int, fc: int, tr: int, tc: int,
        team_key: str, next_key: str, peace_time: int,
    ) -> dict:
        if self._grid is None:
            raise RuntimeError("Game not initialized")
        result = self._bridge.chess_apply_move(
            self._grid, self._team_r_rgb, self._team_l_rgb,
            fr, fc, tr, tc, team_key, next_key, peace_time,
        )
        self._grid = result["grid"]
        return result

    def close(self) -> None:
        self._bridge.close()
