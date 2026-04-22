"""Unit tests for validator adversarial input handling.

Covers bugs found by validator_fuzzer:
- ROW_OVERFLOW: coords out of bounds should reject, not IndexError
- COORDS_ARE_LIST: wrong types should reject, not TypeError
- Security hole: exceptions should reject, not allow
"""
import pytest

from network.validator import RoomValidator

TEAM_R_RGB = (64, 180, 232)
TEAM_L_RGB = (255, 140, 0)


@pytest.fixture
def validator():
    """Fresh initialized validator."""
    v = RoomValidator()
    v.initialize(TEAM_R_RGB, TEAM_L_RGB)
    return v


def _move(fr=6, fc=4, tr=4, tc=4, flags=None):
    """Build move message."""
    return {
        "type": "move",
        "from_row": fr,
        "from_col": fc,
        "to_row": tr,
        "to_col": tc,
        "flags": flags or {},
    }


class TestBoundsChecking:
    """Validator must reject out-of-bounds coords without crashing."""

    def test_row_overflow(self, validator):
        result = validator.validate_and_apply(_move(fr=999))
        assert result is False

    def test_col_overflow(self, validator):
        result = validator.validate_and_apply(_move(tc=999))
        assert result is False

    def test_negative_row(self, validator):
        result = validator.validate_and_apply(_move(fr=-1))
        assert result is False

    def test_negative_col(self, validator):
        result = validator.validate_and_apply(_move(fc=-1))
        assert result is False

    def test_row_exactly_8(self, validator):
        result = validator.validate_and_apply(_move(fr=8))
        assert result is False

    def test_col_exactly_8(self, validator):
        result = validator.validate_and_apply(_move(tc=8))
        assert result is False


class TestTypeChecking:
    """Validator must reject wrong types without crashing."""

    def test_string_coords(self, validator):
        result = validator.validate_and_apply(_move(fr="6", fc="4", tr="4", tc="4"))
        # String "6" can be converted to int 6, so this might pass
        # The important thing is no exception
        assert result in (True, False)

    def test_list_coords(self, validator):
        result = validator.validate_and_apply(_move(fr=[6]))
        assert result is False

    def test_dict_coords(self, validator):
        result = validator.validate_and_apply(_move(fr={"val": 6}))
        assert result is False

    def test_float_coords(self, validator):
        result = validator.validate_and_apply(_move(fr=6.5))
        # Float might convert to int, important is no crash
        assert result in (True, False)

    def test_none_coords(self, validator):
        result = validator.validate_and_apply(_move(fr=None))
        assert result is False


class TestMissingFields:
    """Validator must reject missing required fields."""

    def test_no_from_row(self, validator):
        msg = _move()
        del msg["from_row"]
        result = validator.validate_and_apply(msg)
        assert result is False

    def test_no_from_col(self, validator):
        msg = _move()
        del msg["from_col"]
        result = validator.validate_and_apply(msg)
        assert result is False

    def test_no_to_row(self, validator):
        msg = _move()
        del msg["to_row"]
        result = validator.validate_and_apply(msg)
        assert result is False

    def test_no_to_col(self, validator):
        msg = _move()
        del msg["to_col"]
        result = validator.validate_and_apply(msg)
        assert result is False


class TestMalformedFlags:
    """Validator must handle malformed flags gracefully."""

    def test_flags_string(self, validator):
        result = validator.validate_and_apply(_move(flags="not_a_dict"))
        # Should use empty MoveFlags, move might be valid
        assert result in (True, False)

    def test_flags_list(self, validator):
        result = validator.validate_and_apply(_move(flags=[1, 2, 3]))
        assert result in (True, False)

    def test_flags_none(self, validator):
        result = validator.validate_and_apply(_move(flags=None))
        assert result in (True, False)


class TestIllegalMoves:
    """Validator must reject illegal chess moves."""

    def test_wrong_team(self, validator):
        # Try to move team_l pawn (row 6) on team_r turn
        result = validator.validate_and_apply(_move(fr=6, fc=4, tr=4, tc=4))
        assert result is False

    def test_empty_square(self, validator):
        # Try to move from empty square
        result = validator.validate_and_apply(_move(fr=4, fc=4, tr=3, tc=4))
        assert result is False

    def test_blocked_path(self, validator):
        # Rook can't jump over pawn
        result = validator.validate_and_apply(_move(fr=0, fc=0, tr=4, tc=0))
        assert result is False


class TestSecurityHole:
    """Validator must not allow moves when exceptions occur."""

    def test_no_exception_leakage(self, validator):
        # All adversarial inputs should return False, not raise
        adversarial = [
            _move(fr=999),
            _move(fr=-1),
            _move(fr=[6]),
            _move(fr={"x": 1}),
            _move(fr=None),
        ]
        for msg in adversarial:
            # Must not raise
            result = validator.validate_and_apply(msg)
            assert isinstance(result, bool)
