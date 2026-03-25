"""Wire protocol for Chess101 multiplayer: message construction, board
serialization, and hash-based desync detection.

All message dicts produced here are JSON-serialisable.  The board hash uses
SHA-256 over a canonical piece-list string so both sides can verify state
agreement after every move.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pieces.piece import BoardGrid
    from core.team import Team

# Piece class names → import mapping (used in decode_grid)
_PIECE_TYPES: dict[str, type] = {}


def _piece_registry() -> dict[str, type]:
    """Lazily build the piece-name → class map on first use."""
    if not _PIECE_TYPES:
        from pieces.pawn import Pawn
        from pieces.rook import Rook
        from pieces.knight import Knight
        from pieces.bishop import Bishop
        from pieces.queen import Queen
        from pieces.king import King
        _PIECE_TYPES.update({
            "Pawn": Pawn, "Rook": Rook, "Knight": Knight,
            "Bishop": Bishop, "Queen": Queen, "King": King,
        })
    return _PIECE_TYPES


# ---------------------------------------------------------------------------
# MoveFlags
# ---------------------------------------------------------------------------

@dataclass
class MoveFlags:
    """All special-case metadata for a single move.

    Attributes:
        is_capture: True if the destination cell held an opponent piece.
        is_en_passant: True if a pawn captured via en passant.
        is_castling: True if this is a castling king move.
        is_promotion: True if a pawn reached the back rank (player selects Queen/Knight/Bishop/Rook).
        captured_at: (row, col) of the captured pawn for en passant; None otherwise.
        rook_from: (row, col) of the rook before castling; None otherwise.
        rook_to: (row, col) of the rook after castling; None otherwise.
    """

    is_capture: bool = False
    is_en_passant: bool = False
    is_castling: bool = False
    is_promotion: bool = False
    promoted_to: Optional[str] = None   # class name of chosen piece, e.g. "Queen"
    captured_at: Optional[tuple[int, int]] = None
    rook_from: Optional[tuple[int, int]] = None
    rook_to: Optional[tuple[int, int]] = None

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "is_capture": self.is_capture,
            "is_en_passant": self.is_en_passant,
            "is_castling": self.is_castling,
            "is_promotion": self.is_promotion,
            "promoted_to": self.promoted_to,
            "captured_at": list(self.captured_at) if self.captured_at else None,
            "rook_from": list(self.rook_from) if self.rook_from else None,
            "rook_to": list(self.rook_to) if self.rook_to else None,
        }

    @staticmethod
    def from_dict(d: dict) -> "MoveFlags":
        """Reconstruct a MoveFlags from a dict produced by to_dict()."""
        return MoveFlags(
            is_capture=d.get("is_capture", False),
            is_en_passant=d.get("is_en_passant", False),
            is_castling=d.get("is_castling", False),
            is_promotion=d.get("is_promotion", False),
            promoted_to=d.get("promoted_to"),
            captured_at=tuple(d["captured_at"]) if d.get("captured_at") else None,  # type: ignore[arg-type]
            rook_from=tuple(d["rook_from"]) if d.get("rook_from") else None,  # type: ignore[arg-type]
            rook_to=tuple(d["rook_to"]) if d.get("rook_to") else None,  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Grid serialization
# ---------------------------------------------------------------------------

def encode_grid(grid: "BoardGrid", team_r: "Team") -> list[list[Optional[dict]]]:
    """Serialise an 8×8 grid to a JSON-safe nested list.

    Each non-None cell becomes a dict:
        {"type": "Pawn", "team": "r", "row": 1, "col": 3,
         "touched": False, "en_passantable": False, "direction": 1}

    ``en_passantable`` and ``direction`` are only included for Pawns.
    ``touched`` is always included (needed for castling / first-move logic).

    Args:
        grid: 8×8 list of Piece | None.
        team_r: The Team object for the right/top team.  Any piece whose
            ``team.r`` matches ``team_r.r`` is labelled ``"r"``; others ``"l"``.

    Returns:
        8×8 nested list of dicts or None values.
    """
    from pieces.pawn import Pawn as _Pawn

    encoded: list[list[Optional[dict]]] = []
    for row in grid:
        enc_row: list[Optional[dict]] = []
        for piece in row:
            if piece is None:
                enc_row.append(None)
            else:
                d: dict = {
                    "type": type(piece).__name__,
                    "team": "r" if piece.team.r == team_r.r else "l",
                    "row": piece.row,
                    "col": piece.col,
                    "touched": getattr(piece, "touched", False),
                }
                if isinstance(piece, _Pawn):
                    d["en_passantable"] = piece.en_passantable
                    d["direction"] = piece.direction
                enc_row.append(d)
        encoded.append(enc_row)
    return encoded


def decode_grid(
    encoded: list[list[Optional[dict]]],
    team_r: "Team",
    team_l: "Team",
) -> "BoardGrid":
    """Reconstruct an 8×8 grid from the output of encode_grid().

    Args:
        encoded: 8×8 nested list of dicts or None (as produced by encode_grid).
        team_r: Team object to assign to pieces labelled ``"r"``.
        team_l: Team object to assign to pieces labelled ``"l"``.

    Returns:
        8×8 list of Piece | None.
    """
    from pieces.pawn import Pawn as _Pawn

    registry = _piece_registry()
    grid: "BoardGrid" = []
    for enc_row in encoded:
        row: list = []
        for cell in enc_row:
            if cell is None:
                row.append(None)
            else:
                cls = registry[cell["type"]]
                team = team_r if cell["team"] == "r" else team_l
                piece = cls(cell["row"], cell["col"], team)
                piece.touched = cell.get("touched", False)
                if isinstance(piece, _Pawn):
                    piece.en_passantable = cell.get("en_passantable", False)
                    piece.direction = cell.get("direction", 1)
                row.append(piece)
        grid.append(row)
    return grid


# ---------------------------------------------------------------------------
# Board hash
# ---------------------------------------------------------------------------

def board_hash(
    grid: "BoardGrid",
    peace_time: int,
    current_team_key: str,
    team_r: "Team",
) -> str:
    """Compute a SHA-256 hash of the full board state.

    The canonical string is built row-by-row, cell-by-cell, in a fixed format
    so both machines produce identical output for the same position.

    Format per piece: ``"R,C,TYPE,TEAM,TOUCHED[,EP]"``
    where EP (en_passantable) is appended only for Pawns.
    Empty cells are encoded as ``"R,C,-"``

    The peace_time and current_team_key are appended at the end so that
    fifty-move and side-to-move differences are captured.

    Args:
        grid: 8×8 board state.
        peace_time: Consecutive moves without capture or pawn push.
        current_team_key: ``"r"`` or ``"l"`` identifying whose turn it is.
        team_r: Team object used to determine team keys.

    Returns:
        64-character lowercase hex SHA-256 digest.
    """
    from pieces.pawn import Pawn as _Pawn

    parts: list[str] = []
    for r_idx, row in enumerate(grid):
        for c_idx, piece in enumerate(row):
            if piece is None:
                parts.append(f"{r_idx},{c_idx},-")
            else:
                team_key = "r" if piece.team.r == team_r.r else "l"
                touched = "1" if getattr(piece, "touched", False) else "0"
                entry = f"{r_idx},{c_idx},{type(piece).__name__},{team_key},{touched}"
                if isinstance(piece, _Pawn):
                    ep = "1" if piece.en_passantable else "0"
                    entry += f",{ep}"
                parts.append(entry)
    parts.append(f"peace={peace_time}")
    parts.append(f"turn={current_team_key}")
    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

def build_move_msg(
    seq: int,
    fr: int,
    fc: int,
    tr: int,
    tc: int,
    piece_name: str,
    flags: MoveFlags,
    hash_: str,
) -> dict:
    """Build a ``move`` message dict ready to send over the wire.

    Args:
        seq: Monotonically increasing sequence number for this connection.
        fr: From-row.
        fc: From-col.
        tr: To-row.
        tc: To-col.
        piece_name: Class name of the moving piece (e.g. ``"Pawn"``).
        flags: MoveFlags describing any special-case aspects of the move.
        hash_: board_hash() of the position *after* the move is applied.

    Returns:
        JSON-serialisable dict with ``type == "move"``.
    """
    return {
        "type": "move",
        "seq": seq,
        "from_row": fr,
        "from_col": fc,
        "to_row": tr,
        "to_col": tc,
        "piece": piece_name,
        "flags": flags.to_dict(),
        "board_hash": hash_,
    }
