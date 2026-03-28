"""
test_validator_unit.py — unit tests for network/validator.py RoomValidator.

Covers edge cases not exercised by the integration-level relay tests:
  - validate_and_apply when not yet initialized (line 135)
  - missing coordinate fields in the move message (line 142)
  - current_team forced to None while active (line 167)
  - no piece at the from-square (line 171)
  - moving the opponent's piece (line 173)
  - king removed from grid so _find_king returns None (lines 159, 187)
  - king in check: sky_fall called for non-King piece (line 201)
  - _apply for pawn promotion (lines 236-237)
  - _apply for castling (lines 243-250)
  - _apply for pawn en-passant capture (line 232)
"""
from __future__ import annotations

import pytest


def _make_validator(active=True):
    from network.validator import RoomValidator
    v = RoomValidator()
    if active:
        v.initialize((64, 180, 232), (255, 140, 0))
    return v


def _move(fr, fc, tr, tc, flags=None):
    return {
        "from_row": fr, "from_col": fc,
        "to_row": tr, "to_col": tc,
        "flags": flags or {},
    }


# ── Guard checks in validate_and_apply ───────────────────────────────────────

class TestValidateAndApplyGuards:
    def test_not_initialized_allows_any_move(self):
        # Line 135: _active is False → return True
        v = _make_validator(active=False)
        assert v.validate_and_apply(_move(0, 0, 1, 0)) is True

    def test_missing_fields_returns_false(self):
        # Line 142: required coordinate keys absent → return False
        v = _make_validator()
        assert v.validate_and_apply({"from_row": 1, "from_col": 0}) is False

    def test_current_team_none_returns_false(self):
        # Line 167: _current_team forcibly set to None → return False
        v = _make_validator()
        v._current_team = None
        assert v.validate_and_apply(_move(1, 0, 2, 0)) is False

    def test_no_piece_at_source_returns_false(self):
        # Line 171: empty square at (from_row, from_col) → return False
        v = _make_validator()
        # Row 3 is empty in the starting position
        assert v.validate_and_apply(_move(3, 0, 4, 0)) is False

    def test_wrong_team_returns_false(self):
        # Line 173: team_r goes first; trying to move a team_l piece is illegal
        v = _make_validator()
        # team_l pawns are at row 6
        assert v.validate_and_apply(_move(6, 0, 5, 0)) is False

    def test_king_not_found_returns_false(self):
        # Lines 159, 187: remove team_r king so _find_king returns None
        v = _make_validator()
        v._grid[0][4] = None  # remove team_r king
        assert v.validate_and_apply(_move(1, 0, 2, 0)) is False


# ── sky_fall called for non-King piece when king is in check ──────────────────

class TestSkyFallOnCheck:
    def test_non_king_move_rejected_when_does_not_resolve_check(self):
        # Line 201: piece.sky_fall(king) is called when king is in check.
        # A rook moving to a square that does not block/capture the attacker
        # must be rejected.
        from network.validator import RoomValidator
        from pieces.rook import Rook
        from pieces.queen import Queen
        from pieces.king import King
        from core.team import Team

        v = RoomValidator()
        # Build a minimal board: team_r king at (0,4), team_r rook at (0,0),
        # enemy queen at (7,4) giving check along col 4.
        team_r = Team(64, 180, 232)
        team_l = Team(255, 140, 0)
        for r in range(8):
            v._grid[r] = [None] * 8

        v._grid[0][4] = King(0, 4, team_r)
        v._grid[0][0] = Rook(0, 0, team_r)
        v._grid[7][4] = Queen(7, 4, team_l)

        v._team_r = team_r
        v._team_l = team_l
        v._current_team = team_r
        v._active = True

        # Rook at (0,0) moving to (1,0) doesn't block check on col 4
        result = v.validate_and_apply(_move(0, 0, 1, 0))
        assert result is False


# ── _apply for pawn promotion ─────────────────────────────────────────────────

class TestApplyPawnPromotion:
    def test_pawn_promoted_to_queen_on_back_rank(self):
        # Lines 236-237: a team_r pawn reaching row 7 is replaced by a Queen.
        from network.validator import RoomValidator
        from pieces.pawn import Pawn
        from pieces.queen import Queen
        from pieces.king import King
        from core.team import Team

        v = RoomValidator()
        team_r = Team(64, 180, 232)
        team_l = Team(255, 140, 0)
        for r in range(8):
            v._grid[r] = [None] * 8

        # team_r pawn one step from promotion (col 5, away from kings in col 4)
        pawn = Pawn(1, 5, team_r)
        pawn.row = 6
        v._grid[6][5] = pawn
        # kings required for _validate_and_apply; keep them away from pawn's path
        v._grid[0][4] = King(0, 4, team_r)
        v._grid[7][0] = King(7, 0, team_l)  # team_l king not blocking col 5

        v._team_r = team_r
        v._team_l = team_l
        v._current_team = team_r
        v._active = True

        result = v.validate_and_apply(_move(6, 5, 7, 5))
        assert result is True
        assert isinstance(v._grid[7][5], Queen), \
            "Pawn reaching the back rank must be promoted to Queen"


# ── _apply for castling ───────────────────────────────────────────────────────

class TestApplyCastling:
    def test_queenside_castling_moves_rook(self):
        # Lines 243-250: King.move() returns rook cells on castling;
        # _apply must reposition the rook accordingly.
        from network.validator import RoomValidator
        from pieces.rook import Rook
        from pieces.king import King
        from core.team import Team

        v = RoomValidator()
        team_r = Team(64, 180, 232)
        team_l = Team(255, 140, 0)
        for r in range(8):
            v._grid[r] = [None] * 8

        king = King(0, 4, team_r)
        rook_q = Rook(0, 0, team_r)
        v._grid[0][4] = king
        v._grid[0][0] = rook_q
        v._grid[7][4] = King(7, 4, team_l)

        v._team_r = team_r
        v._team_l = team_l
        v._current_team = team_r
        v._active = True

        result = v.validate_and_apply(_move(0, 4, 0, 2))
        assert result is True
        # After queenside castling, king at (0,2) and rook at (0,3)
        assert isinstance(v._grid[0][2], King)
        assert isinstance(v._grid[0][3], Rook)
        assert v._grid[0][0] is None  # old rook square cleared


# ── _apply for pawn en-passant capture ───────────────────────────────────────

class TestApplyEnPassant:
    def test_en_passant_removes_captured_pawn(self):
        # Line 232: enemy pawn removed from the board after an en-passant capture.
        from network.validator import RoomValidator
        from pieces.pawn import Pawn
        from pieces.king import King
        from core.team import Team

        v = RoomValidator()
        team_r = Team(64, 180, 232)
        team_l = Team(255, 140, 0)
        for r in range(8):
            v._grid[r] = [None] * 8

        # team_r pawn at (4,4), team_l pawn at (4,3) just advanced two squares
        pawn_r = Pawn(1, 4, team_r)
        pawn_r.row = 4
        enemy_pawn = Pawn(6, 3, team_l)
        enemy_pawn.row = 4
        enemy_pawn.en_passantable = True

        v._grid[4][4] = pawn_r
        v._grid[4][3] = enemy_pawn
        v._grid[0][4] = King(0, 4, team_r)
        v._grid[7][4] = King(7, 4, team_l)

        v._team_r = team_r
        v._team_l = team_l
        v._current_team = team_r
        v._active = True

        # En-passant: pawn_r captures to (5, 3), removing enemy pawn at (4, 3)
        result = v.validate_and_apply(_move(4, 4, 5, 3))
        assert result is True
        assert v._grid[4][3] is None, "Captured pawn must be removed from (4, 3)"
        assert isinstance(v._grid[5][3], Pawn), "Capturing pawn must be at (5, 3)"
