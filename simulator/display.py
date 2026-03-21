from __future__ import annotations

from typing import Optional

import pygame

CELL_PX = 72
BOARD_OFFSET_X = 40
BOARD_OFFSET_Y = 52
LIGHT_SQUARE = (240, 217, 181)
DARK_SQUARE = (181, 136, 99)
BG_COLOR = (30, 30, 30)
SIDEBAR_BG = (40, 40, 40)
SIDEBAR_X = BOARD_OFFSET_X + 8 * CELL_PX + 20  # 636

_PIECE_INITIAL = {
    "King": "K", "Queen": "Q", "Rook": "R",
    "Bishop": "B", "Knight": "N", "Pawn": "P",
}

_SWATCH_RADIUS = 38
_SWATCH_GAP = 10
_SWATCH_SPACING = _SWATCH_RADIUS * 2 + _SWATCH_GAP          # 86
_TOTAL_SWATCH_W = 8 * _SWATCH_RADIUS * 2 + 7 * _SWATCH_GAP  # 678
_SWATCH_START_X = (860 - _TOTAL_SWATCH_W) // 2 + _SWATCH_RADIUS  # 129


class SimDisplay:
    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        pygame.font.init()
        self._font_large = pygame.font.SysFont(None, 42)
        self._font_mid = pygame.font.SysFont(None, 28)
        self._font_small = pygame.font.SysFont(None, 22)
        self._font_piece = pygame.font.SysFont(None, 30, bold=True)

        # Pre-render semi-transparent valid-move overlays
        self._move_dot = pygame.Surface((CELL_PX, CELL_PX), pygame.SRCALPHA)
        pygame.draw.circle(self._move_dot, (0, 200, 0, 110),
                           (CELL_PX // 2, CELL_PX // 2), 14)

        self._capture_ring = pygame.Surface((CELL_PX, CELL_PX), pygame.SRCALPHA)
        pygame.draw.circle(self._capture_ring, (0, 200, 0, 160),
                           (CELL_PX // 2, CELL_PX // 2), CELL_PX // 2 - 4, 6)

        # Hit-test storage (populated during render calls)
        self._swatch_centers_r: list[tuple[int, int]] = []
        self._swatch_centers_l: list[tuple[int, int]] = []
        self._player_buttons: dict[str, pygame.Rect] = {}
        self._new_game_btn: Optional[pygame.Rect] = None

    # ── Hit tests ─────────────────────────────────────────────────────────────

    def get_board_cell(self, px: int, py: int) -> Optional[tuple[int, int]]:
        bx = px - BOARD_OFFSET_X
        by = py - BOARD_OFFSET_Y
        if 0 <= bx < 8 * CELL_PX and 0 <= by < 8 * CELL_PX:
            return by // CELL_PX, bx // CELL_PX
        return None

    def get_color_swatch_r(self, px: int, py: int) -> int:
        return self._hit_swatch(px, py, self._swatch_centers_r)

    def get_color_swatch_l(self, px: int, py: int) -> int:
        return self._hit_swatch(px, py, self._swatch_centers_l)

    def _hit_swatch(self, px: int, py: int, centers: list[tuple[int, int]]) -> int:
        for i, (cx, cy) in enumerate(centers):
            if (px - cx) ** 2 + (py - cy) ** 2 <= _SWATCH_RADIUS ** 2:
                return i
        return -1

    def get_player_select_click(self, px: int, py: int) -> Optional[str]:
        for key, rect in self._player_buttons.items():
            if rect.collidepoint(px, py):
                return key
        return None

    def get_new_game_button(self, px: int, py: int) -> bool:
        return self._new_game_btn is not None and self._new_game_btn.collidepoint(px, py)

    # ── Drawing helpers ────────────────────────────────────────────────────────

    def _text_center(self, text: str, font, color, cx: int, cy: int) -> None:
        surf = font.render(text, True, color)
        self.screen.blit(surf, surf.get_rect(center=(cx, cy)))

    def _text(self, text: str, font, color, x: int, y: int) -> None:
        self.screen.blit(font.render(text, True, color), (x, y))

    def _draw_board_squares(self) -> None:
        for row in range(8):
            for col in range(8):
                color = LIGHT_SQUARE if (row + col) % 2 == 0 else DARK_SQUARE
                pygame.draw.rect(
                    self.screen, color,
                    pygame.Rect(BOARD_OFFSET_X + col * CELL_PX,
                                BOARD_OFFSET_Y + row * CELL_PX,
                                CELL_PX, CELL_PX),
                )

    def _draw_pieces(self, grid) -> None:
        for row in range(8):
            for col in range(8):
                piece = grid[row][col]
                if piece is None:
                    continue
                cx = BOARD_OFFSET_X + col * CELL_PX + CELL_PX // 2
                cy = BOARD_OFFSET_Y + row * CELL_PX + CELL_PX // 2
                t = piece.team
                pygame.draw.circle(self.screen, (t.r, t.g, t.b), (cx, cy), CELL_PX // 2 - 6)
                initial = _PIECE_INITIAL.get(type(piece).__name__, "?")
                self._text_center(initial, self._font_piece, (255, 255, 255), cx, cy)

    def _draw_selected(self, piece) -> None:
        cx = BOARD_OFFSET_X + piece.col * CELL_PX + CELL_PX // 2
        cy = BOARD_OFFSET_Y + piece.row * CELL_PX + CELL_PX // 2
        pygame.draw.circle(self.screen, (255, 220, 0), (cx, cy), CELL_PX // 2 - 4, 4)

    def _draw_valid_moves(self, grid, targets) -> None:
        for cell in targets:
            x = BOARD_OFFSET_X + cell.col * CELL_PX
            y = BOARD_OFFSET_Y + cell.row * CELL_PX
            if grid[cell.row][cell.col] is not None:
                self.screen.blit(self._capture_ring, (x, y))
            else:
                self.screen.blit(self._move_dot, (x, y))

    def _draw_check_ring(self, king_check_pos: tuple[int, int]) -> None:
        row, col = king_check_pos
        cx = BOARD_OFFSET_X + col * CELL_PX + CELL_PX // 2
        cy = BOARD_OFFSET_Y + row * CELL_PX + CELL_PX // 2
        pygame.draw.circle(self.screen, (220, 40, 40), (cx, cy), CELL_PX // 2 - 3, 5)

    def _draw_coord_labels(self) -> None:
        for col in range(8):
            cx = BOARD_OFFSET_X + col * CELL_PX + CELL_PX // 2
            self._text_center("abcdefgh"[col], self._font_small, (160, 160, 160),
                              cx, BOARD_OFFSET_Y + 8 * CELL_PX + 14)
        for row in range(8):
            cy = BOARD_OFFSET_Y + row * CELL_PX + CELL_PX // 2
            self._text_center(str(8 - row), self._font_small, (160, 160, 160),
                              BOARD_OFFSET_X - 14, cy)

    def _draw_sidebar(self, team_r, team_l, current_team,
                      ai_thinking: bool, status_line: str) -> None:
        sx = SIDEBAR_X
        pygame.draw.rect(self.screen, SIDEBAR_BG,
                         pygame.Rect(sx - 10, 0, 860 - sx + 10, 680))

        self._text("Turn:", self._font_mid, (200, 200, 200), sx, 30)
        if current_team is not None:
            t = current_team
            pygame.draw.circle(self.screen, (t.r, t.g, t.b), (sx + 20, 82), 18)
            self._text(t.name, self._font_mid, (220, 220, 220), sx + 46, 72)

        if status_line:
            self._text(status_line, self._font_mid, (220, 80, 80), sx, 132)

        if ai_thinking:
            self._text("AI Thinking...", self._font_small, (180, 180, 100), sx, 172)

        self._text("Teams:", self._font_small, (160, 160, 160), sx, 222)
        pygame.draw.circle(self.screen, (team_r.r, team_r.g, team_r.b), (sx + 14, 258), 12)
        self._text(team_r.name, self._font_small, (200, 200, 200), sx + 32, 249)
        pygame.draw.circle(self.screen, (team_l.r, team_l.g, team_l.b), (sx + 14, 288), 12)
        self._text(team_l.name, self._font_small, (200, 200, 200), sx + 32, 279)

        btn = pygame.Rect(sx, 600, 180, 44)
        pygame.draw.rect(self.screen, (60, 120, 60), btn, border_radius=6)
        self._text_center("New Game", self._font_mid, (255, 255, 255),
                          btn.centerx, btn.centery)
        self._new_game_btn = btn

    # ── Phase renderers ────────────────────────────────────────────────────────

    def render_color_pick(self, team_array, selected_r_idx, selected_l_idx) -> None:
        self.screen.fill(BG_COLOR)
        self._text_center("Choose Team Colors", self._font_large, (220, 220, 220), 430, 60)
        self._text_center("Team R  (rows 0–1)", self._font_mid, (200, 200, 200), 430, 140)
        self._text_center("Team L  (rows 6–7)", self._font_mid, (200, 200, 200), 430, 330)

        self._swatch_centers_r = []
        self._swatch_centers_l = []

        for i, team in enumerate(team_array):
            cx = _SWATCH_START_X + i * _SWATCH_SPACING
            color = (team.r, team.g, team.b)

            # Team R row
            cy_r = 210
            pygame.draw.circle(self.screen, color, (cx, cy_r), _SWATCH_RADIUS)
            if selected_r_idx == i:
                pygame.draw.circle(self.screen, (255, 220, 0), (cx, cy_r), _SWATCH_RADIUS + 4, 4)
            self._swatch_centers_r.append((cx, cy_r))

            # Team L row
            cy_l = 400
            pygame.draw.circle(self.screen, color, (cx, cy_l), _SWATCH_RADIUS)
            if selected_l_idx == i:
                pygame.draw.circle(self.screen, (255, 220, 0), (cx, cy_l), _SWATCH_RADIUS + 4, 4)
            self._swatch_centers_l.append((cx, cy_l))

        if selected_r_idx is not None and selected_l_idx is not None:
            self._text_center("Starting game...", self._font_mid, (100, 220, 100), 430, 530)

    def render_player_select(self, team_r, team_l, computer_r, computer_l) -> None:
        self.screen.fill(BG_COLOR)
        self._text_center("Select Player Types", self._font_large, (220, 220, 220), 430, 60)

        self._player_buttons = {}

        for side, team, comp, px0 in [
            ("r", team_r, computer_r, 80),
            ("l", team_l, computer_l, 470),
        ]:
            panel = pygame.Rect(px0, 130, 310, 260)
            pygame.draw.rect(self.screen, (50, 50, 50), panel, border_radius=8)

            t = team
            pygame.draw.circle(self.screen, (t.r, t.g, t.b), (px0 + 155, 182), 22)
            self._text_center(t.name, self._font_mid, (220, 220, 220), px0 + 155, 218)

            h_btn = pygame.Rect(px0 + 25, 258, 115, 44)
            c_btn = pygame.Rect(px0 + 170, 258, 115, 44)

            h_color = (40, 140, 40) if comp is False else (60, 60, 60)
            c_color = (40, 40, 140) if comp is True else (60, 60, 60)

            pygame.draw.rect(self.screen, h_color, h_btn, border_radius=6)
            pygame.draw.rect(self.screen, c_color, c_btn, border_radius=6)
            self._text_center("Human", self._font_small, (255, 255, 255),
                              h_btn.centerx, h_btn.centery)
            self._text_center("Computer", self._font_small, (255, 255, 255),
                              c_btn.centerx, c_btn.centery)

            self._player_buttons[f"{side}_human"] = h_btn
            self._player_buttons[f"{side}_computer"] = c_btn

        if computer_r is not None and computer_l is not None:
            self._text_center("Press Enter to start", self._font_mid,
                              (100, 220, 100), 430, 470)

    def render_playing(self, grid, team_r, team_l, current_team,
                       selected_piece, targets, in_check, king_check_pos,
                       ai_thinking: bool, status_line: str) -> None:
        self.screen.fill(BG_COLOR)
        self._draw_board_squares()
        self._draw_valid_moves(grid, targets)
        self._draw_pieces(grid)
        if selected_piece is not None:
            self._draw_selected(selected_piece)
        if in_check and king_check_pos is not None:
            self._draw_check_ring(king_check_pos)
        self._draw_coord_labels()
        self._draw_sidebar(team_r, team_l, current_team, ai_thinking, status_line)

    def render_game_over(self, grid, winner_team, is_draw, team_r, team_l) -> None:
        self.screen.fill(BG_COLOR)
        self._draw_board_squares()
        self._draw_pieces(grid)
        self._draw_coord_labels()
        self._draw_sidebar(team_r, team_l, None, False, "")

        # Dark overlay on board area
        overlay = pygame.Surface((8 * CELL_PX, 8 * CELL_PX), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (BOARD_OFFSET_X, BOARD_OFFSET_Y))

        board_cx = BOARD_OFFSET_X + 4 * CELL_PX
        board_cy = BOARD_OFFSET_Y + 4 * CELL_PX

        if is_draw:
            msg = "STALEMATE / DRAW"
            color = (220, 220, 100)
        elif winner_team is not None:
            msg = f"CHECKMATE — {winner_team.name} Wins!"
            color = (min(winner_team.r + 60, 255),
                     min(winner_team.g + 60, 255),
                     min(winner_team.b + 60, 255))
        else:
            msg = "Game Over"
            color = (220, 220, 220)

        self._text_center(msg, self._font_large, color, board_cx, board_cy - 20)
        self._text_center("Press N or click New Game to restart",
                          self._font_small, (180, 180, 180), board_cx, board_cy + 28)
