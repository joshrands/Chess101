"""Server-side chess move validator for the relay anti-cheat layer.

Maintains an independent board state per game room and validates each
incoming ``move`` message against the legal-move set computed by the same
chess engine used by the clients.  The relay calls ``validate_and_apply()``
before forwarding; illegal moves are rejected without being forwarded.

Hardware modules (rgbmatrix, smbus) are stubbed at import time so this
module runs cleanly on any Python 3.9+ host (VPS, CI, developer Mac).
"""
from __future__ import annotations

import sys
import types
from typing import Optional

# ── Stub Pi hardware before any game-module import ───────────────────────────
if "rgbmatrix" not in sys.modules:
    _rmod = types.ModuleType("rgbmatrix")

    class _FakeCanvas:
        def SetPixel(self, *a) -> None: pass
        def Clear(self) -> None: pass

    class _FakeMatrix:
        def CreateFrameCanvas(self) -> _FakeCanvas: return _FakeCanvas()
        def SwapOnVSync(self, c: _FakeCanvas) -> _FakeCanvas: return c

    class _FakeOptions:
        def __setattr__(self, name: str, value: object) -> None:
            object.__setattr__(self, name, value)

    _rmod.RGBMatrix        = _FakeMatrix   # type: ignore[attr-defined]
    _rmod.RGBMatrixOptions = _FakeOptions  # type: ignore[attr-defined]
    _rmod.FrameCanvas      = _FakeCanvas   # type: ignore[attr-defined]
    sys.modules["rgbmatrix"]      = _rmod
    sys.modules["rgbmatrix.core"] = _rmod

if "smbus" not in sys.modules:
    _smbus = types.ModuleType("smbus")

    class _SMBus:
        def __init__(self, *a, **kw) -> None: pass
        def read_byte(self, *a, **kw) -> int: return 0
        def write_byte(self, *a, **kw) -> None: pass

    _smbus.SMBus = _SMBus  # type: ignore[attr-defined]
    sys.modules["smbus"] = _smbus

# ── Chess engine imports (safe after stubs) ───────────────────────────────────
from core.team import Team           # noqa: E402
from network.protocol import MoveFlags  # noqa: E402
from pieces.bishop import Bishop     # noqa: E402
from pieces.king import King         # noqa: E402
from pieces.knight import Knight     # noqa: E402
from pieces.pawn import Pawn         # noqa: E402
from pieces.queen import Queen       # noqa: E402
from pieces.rook import Rook         # noqa: E402


class RoomValidator:
    """Validates chess moves for a single game room.

    Lifecycle
    ---------
    1. Create one ``RoomValidator`` per room when the game starts.
    2. On each ``game_start`` message received from the HOST, call
       ``initialize(team_r_rgb, team_l_rgb)`` to set up the starting
       position with the chosen team colours.
    3. Before forwarding every ``move`` message, call
       ``validate_and_apply(msg)``.  Returns ``True`` if the move is
       legal (and applies it internally); ``False`` to reject.
    """

    def __init__(self) -> None:
        self._grid: list[list] = [[None] * 8 for _ in range(8)]
        self._team_r: Optional[Team] = None
        self._team_l: Optional[Team] = None
        self._current_team: Optional[Team] = None
        self._active = False   # False until initialize() is called

    # ── Setup ──────────────────────────────────────────────────────────────────

    def initialize(
        self,
        team_r_rgb: tuple[int, int, int],
        team_l_rgb: tuple[int, int, int],
    ) -> None:
        """Place all 32 pieces in the standard starting position.

        Args:
            team_r_rgb: (r, g, b) colour for team_r (rows 0–1).
            team_l_rgb: (r, g, b) colour for team_l (rows 6–7).
        """
        r, g, b = team_r_rgb
        self._team_r = Team(r, g, b)
        r, g, b = team_l_rgb
        self._team_l = Team(r, g, b)
        self._grid = [[None] * 8 for _ in range(8)]
        self._place_pieces()
        self._current_team = self._team_r
        self._active = True

    def _place_pieces(self) -> None:
        g, tr, tl = self._grid, self._team_r, self._team_l
        for col in range(8):
            g[1][col] = Pawn(1, col, tr)
        g[0][0] = Rook(0, 0, tr);    g[0][7] = Rook(0, 7, tr)
        g[0][1] = Knight(0, 1, tr);  g[0][6] = Knight(0, 6, tr)
        g[0][2] = Bishop(0, 2, tr);  g[0][5] = Bishop(0, 5, tr)
        g[0][3] = Queen(0, 3, tr);   g[0][4] = King(0, 4, tr)
        for col in range(8):
            g[6][col] = Pawn(6, col, tl)
        g[7][0] = Rook(7, 0, tl);    g[7][7] = Rook(7, 7, tl)
        g[7][1] = Knight(7, 1, tl);  g[7][6] = Knight(7, 6, tl)
        g[7][2] = Bishop(7, 2, tl);  g[7][5] = Bishop(7, 5, tl)
        g[7][3] = Queen(7, 3, tl);   g[7][4] = King(7, 4, tl)

    # ── Public API ─────────────────────────────────────────────────────────────

    def validate_and_apply(self, msg: dict) -> bool:
        """Validate a ``move`` message and apply it if legal.

        Args:
            msg: A game-protocol ``move`` message dict with keys
                ``from_row``, ``from_col``, ``to_row``, ``to_col``,
                ``flags``.

        Returns:
            ``True`` if the move is legal (and was applied to the
            internal board state).  ``False`` if the move is illegal
            and should be rejected by the relay.
        """
        if not self._active:
            return True   # not yet initialised — allow through

        fr = msg.get("from_row")
        fc = msg.get("from_col")
        tr = msg.get("to_row")
        tc = msg.get("to_col")
        if any(v is None for v in (fr, fc, tr, tc)):
            return False

        raw_flags = msg.get("flags", {})
        flags = (
            MoveFlags.from_dict(raw_flags)
            if isinstance(raw_flags, dict)
            else MoveFlags()
        )
        return self._validate_and_apply(int(fr), int(fc), int(tr), int(tc), flags)

    # ── Internals ──────────────────────────────────────────────────────────────

    def _find_king(self, team: Team) -> Optional[King]:
        for row in self._grid:
            for piece in row:
                if isinstance(piece, King) and piece.team.r == team.r:
                    return piece
        return None

    def _validate_and_apply(
        self, fr: int, fc: int, tr: int, tc: int, flags: MoveFlags
    ) -> bool:
        g = self._grid
        current = self._current_team
        if current is None:
            return False

        piece = g[fr][fc]
        if piece is None:
            return False
        if piece.team.r != current.r:
            return False   # wrong team's turn

        # Mirror _begin_turn: reset en_passantable for current team's pawns.
        for row in g:
            for p in row:
                if isinstance(p, Pawn) and p.team.r == current.r:
                    p.en_passantable = False

        # King's calc_targets calls am_i_gonna_die(), which:
        #   • marks pinned ally pieces as critical=True
        #   • populates king.god_save_the_king when in check
        #   • returns True if the king is currently in check
        king = self._find_king(current)
        if king is None:
            return False
        in_check = king.calc_targets(g)

        # Compute the moving piece's legal targets.
        # Each piece's calc_targets() applies critical_man() internally
        # when self.critical is True (set by am_i_gonna_die above).
        piece.calc_targets(g)

        # If the king is in check, only moves that resolve it are legal.
        # Do NOT apply sky_fall to the King itself — the King's calc_targets()
        # already filters its own unsafe escape squares via simulation.  sky_fall
        # restricts targets to the attack-ray (blocking/capturing) squares, which
        # would incorrectly remove King escape moves that exit the ray diagonally.
        if in_check and not isinstance(piece, King):
            piece.sky_fall(king)

        legal = any(t.row == tr and t.col == tc for t in piece.targets)
        if not legal:
            return False

        self._apply(fr, fc, tr, tc)
        assert self._team_r is not None and self._team_l is not None
        self._current_team = (
            self._team_l if current.r == self._team_r.r else self._team_r
        )
        return True

    def _apply(self, fr: int, fc: int, tr: int, tc: int) -> None:
        """Apply a validated move to the internal grid.

        Mirrors ``Board._apply_move()``: the piece is placed at the
        destination before ``piece.move()`` is called, then the source
        square is cleared.
        """
        g = self._grid
        piece = g[fr][fc]
        assert self._team_r is not None

        # Place piece at destination (mirrors board._apply_move caller pattern)
        g[tr][tc] = piece

        if isinstance(piece, Pawn):
            enemy = piece.move(tr, tc, g)
            if enemy is not None:
                # En-passant capture: remove the pawn that was captured.
                g[enemy.row][enemy.col] = None
            # Auto-promote to Queen (mirrors simulator behaviour).
            promo_row = 7 if piece.team.r == self._team_r.r else 0
            if tr == promo_row:
                g[tr][tc] = Queen(tr, tc, piece.team)
                g[tr][tc].touched = True

        elif isinstance(piece, King):
            rook_from, rook_to = piece.move(tr, tc, g)
            if rook_from is not None:
                # Castling: move the rook to its post-castle square.
                g[rook_to.row][rook_to.col] = g[rook_from.row][rook_from.col]
                g[rook_from.row][rook_from.col] = None
                rook = g[rook_to.row][rook_to.col]
                if rook is not None:
                    rook.move(rook_to.row, rook_to.col, g)

        else:
            piece.move(tr, tc, g)

        g[fr][fc] = None
