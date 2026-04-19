#!/usr/bin/env python
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Optional

from samplebase import SampleBase

logger = logging.getLogger(__name__)
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from core.team import Team
from pieces.pawn import Pawn
from pieces.bishop import Bishop
from pieces.rook import Rook
from pieces.knight import Knight
from pieces.king import King
from pieces.queen import Queen
import time
from core.cell import Cell
from pieces.piece import BoardGrid
import random
from hardware.master import Master
from hardware.sensor import BoardSensor
from core.constants import CellOccupancy
from game import rules as _rules
from ui.renderer import light_cell as _light_cell
from ai.tree import Tree
from ai.ai import AI
import copy
import argparse
import os
import numpy as np


class Board(SampleBase):
    """Central game controller for the Chess101 physical board.

    Extends SampleBase to access the RGB LED matrix. Orchestrates the full
    game lifecycle: color selection, piece setup, turn processing (human or AI),
    mismatch detection between physical sensor state and software state, and
    end-game displays. Communicates with eight row Arduinos via the BoardSensor
    interface.

    Attributes:
        team_r: Team object for the player occupying rows 0-1.
        team_l: Team object for the player occupying rows 6-7.
        grid: 8x8 list of Piece | None representing the logical board state.
        master: BoardSensor used to query physical reed-switch sensor data.
        computer_player_r: Whether team_r is controlled by the AI.
        computer_player_l: Whether team_l is controlled by the AI.
        checker_brightness: Current brightness level of the pulsing checker animation.
        checker_brightness_dir: Direction (+/-) of brightness pulse each frame.
        game_over: Flag set to True when the game has ended.
        peace_time: Consecutive moves without a capture or pawn move (fifty-move rule counter).
        team_array: Palette of 8 Team colour options shown during colour selection.
    """

    def __init__(self, *args, sensor: BoardSensor | None = None, **kwargs):
        super(Board, self).__init__(*args, **kwargs)

        self.team_r = Team(64, 180, 232)
        self.team_l = Team(255, 140, 0)
        self.grid: BoardGrid = []
        self.master: BoardSensor = sensor if sensor is not None else Master()
        self.computer_player_r: Optional[bool] = False
        self.computer_player_l: Optional[bool] = False

        self.checker_brightness = 0
        self.checker_brightness_dir = 2

        self.counters: dict = {}

        self.game_over = False
        self.peace_time = 0
        self.days_left_since_injury: list = []
        self.days_right_since_injury: list = []
        self.double_left_jeopardy: list = []
        self.double_right_jeopardy: list = []

        self.team_array = []
        self.team_array.append(Team(64, 180, 232))    # Blue
        self.team_array.append(Team(190, 25, 255))    # Purple
        self.team_array.append(Team(254, 220, 0))     # Yellow
        self.team_array.append(Team(250, 125, 125))   # Pink
        self.team_array.append(Team(25, 255, 35))     # Green
        self.team_array.append(Team(245, 125, 0))     # Orange
        self.team_array.append(Team(0, 25, 230))      # Dark Blue
        self.team_array.append(Team(28, 225, 180))    # Cyan

        for row in range(8):
            self.grid.append([None, None, None, None, None, None, None, None])

    def run(self, skip_setup: bool = False, init_num: str = "") -> None:
        """Execute the full game loop from setup to game-over.

        Calls color_picker, war_games, and create_players to configure the
        session, then runs interactive_setup for both teams before entering
        the main alternating turn loop until self.game_over is set.

        Args:
            skip_setup: If True, skip color_picker / war_games / interactive_setup
                and jump directly to the board initialisation.  Used by
                ``samplebase.process(skip_setup=True)`` for quick-start modes.
            init_num: Suffix appended to ``initialize_game_board`` when calling
                via ``eval()``.  Empty string selects the standard starting
                position; ``"2"`` / ``"3"`` select alternate test positions.
        """
        logger.info("Running game...")
        self.canvas = self.matrix.CreateFrameCanvas()

        if not skip_setup:
            self.color_picker()
            self.war_games()
            self.create_players()

            self.canvas.Clear()
            temp_canvas = self.matrix.SwapOnVSync(self.canvas)

            self.interactive_setup(self.team_r)
            self.interactive_setup(self.team_l)

            temp_canvas.Clear()
            self.light_checker_town(temp_canvas)
            self.canvas = self.matrix.SwapOnVSync(temp_canvas)

        eval("self.initialize_game_board{}()".format(init_num))

        while not self.game_over:
            self.canvas.Clear()
            self.light_checker_town(self.canvas)
            self.canvas = self.matrix.SwapOnVSync(self.canvas)

            self.canvas.Clear()

            if self.computer_player_r:
                self.computer_move(self.team_r)
            else:
                self.do_turn(self.team_r)

            self.canvas.Clear()

            if self.game_over:
                break

            if self.computer_player_l:
                self.computer_move(self.team_l)
            else:
                self.do_turn(self.team_l)

            self.canvas = self.matrix.SwapOnVSync(self.canvas)

    def light_path(self, start_row, start_col, end_row, end_col):
        """Compute incremental steps for animating a path between two cells.

        Args:
            start_row: Row index of the path origin.
            start_col: Column index of the path origin.
            end_row: Row index of the path destination.
            end_col: Column index of the path destination.
        """
        row_increment = (end_row - start_row) / 8.0
        col_increment = (end_col - start_col) / 8.0

    def light_checker_town(self, canvas, color: tuple[int, int, int] | None = None) -> None:
        """Paint the alternating checker pattern on the given canvas.

        Lights every dark square of the standard chess checkerboard in the
        given colour so players can orient the physical board.

        Args:
            canvas: The RGBMatrix frame canvas to draw onto.
            color: RGB tuple used for the lit squares (default uses
                ``self.theme_checker_color`` if set, otherwise full white).
        """
        if color is None:
            color = getattr(self, "theme_checker_color", (255, 255, 255))
        r, g, b = color
        for x in range(4):
            for y in range(4):
                self.light_cell(canvas, 1 + 2 * x, 2 * y, r, g, b)
        for x in range(4):
            for y in range(4):
                self.light_cell(canvas, 2 * x, 1 + 2 * y, r, g, b)

    def choose_light_checker_town(self, color: tuple[int, int, int] | None = None) -> None:
        """Paint the checker pattern at the current pulsing brightness level.

        Scales each channel of *color* by ``checker_brightness / 255``,
        producing the breathing animation shown during AI thinking and piece
        setup.  Draws onto self.canvas directly.

        Args:
            color: Base RGB tuple to scale (default uses
                ``self.theme_checker_color`` if set, otherwise full white).
        """
        if color is None:
            color = getattr(self, "theme_checker_color", (255, 255, 255))
        r, g, b = map(lambda val: int(val * (self.checker_brightness / 255)), color)
        self.light_checker_town(self.canvas, color=(r, g, b))

    def interactive_setup(self, team):
        """Guide a team through placing all 16 pieces on the physical board.

        Sequentially calls detect_piece for each back-rank piece and
        detect_pawns for the pawn row, waiting for reed switches to confirm
        each placement before moving on.

        Args:
            team: The Team whose pieces are being set up (team_r or team_l).
        """
        if team == self.team_r:
            self.detect_piece(team, "Rook", 0, 0)
            self.detect_piece(team, "Rook", 0, 7)
            self.detect_piece(team, "Knight", 0, 1)
            self.detect_piece(team, "Knight", 0, 6)
            self.detect_piece(team, "Bishop", 0, 2)
            self.detect_piece(team, "Bishop", 0, 5)
            self.detect_piece(team, "Queen", 0, 3)
            self.detect_piece(team, "King", 0, 4)
            self.detect_pawns(team, 1)
        else:
            self.detect_piece(team, "Rook", 7, 0)
            self.detect_piece(team, "Rook", 7, 7)
            self.detect_piece(team, "Knight", 7, 1)
            self.detect_piece(team, "Knight", 7, 6)
            self.detect_piece(team, "Bishop", 7, 2)
            self.detect_piece(team, "Bishop", 7, 5)
            self.detect_piece(team, "Queen", 7, 3)
            self.detect_piece(team, "King", 7, 4)
            self.detect_pawns(team, 6)

    def detect_mismatch(self):
        """Block until the physical board matches the logical grid for both teams.

        Polls the reed-switch sensors and highlights in red any cell where the
        software expects a piece but the sensor reads EMPTY. Loops separately
        for team_r and team_l until both pass without a discrepancy.

        Returns:
            True once both teams' physical positions match the software state.
        """
        bg_color = (255, 0, 0)    # red checkerboard
        piece_color = (255, 255, 0)  # yellow mismatched pieces
        pr, pg, pb = piece_color
        team_r_pieces = self.get_team_pieces(self.team_r)
        team_l_pieces = self.get_team_pieces(self.team_l)
        went_red = False

        while True:
            self.master.read_data()
            mismatch = False
            for piece in team_r_pieces + team_l_pieces:
                state = self.master.get_cell_state(piece.row, piece.col)
                if state == CellOccupancy.EMPTY:
                    mismatch = True
                    break

            if not mismatch:
                if went_red:
                    # Restore normal white checkerboard
                    self.canvas.Clear()
                    self.light_checker_town(self.canvas)
                    self.canvas = self.matrix.SwapOnVSync(self.canvas)
                return True

            # Show red checkerboard with yellow highlights on missing pieces
            went_red = True
            self.canvas.Clear()
            self.light_checker_town(self.canvas, color=bg_color)
            for piece in team_r_pieces + team_l_pieces:
                state = self.master.get_cell_state(piece.row, piece.col)
                if state == CellOccupancy.EMPTY:
                    self.light_cell(self.canvas, piece.row, piece.col, pr, pg, pb)
            self.canvas = self.matrix.SwapOnVSync(self.canvas)
            time.sleep(0.2)

    def detect_pawns(self, team, row):
        """Wait for all eight pawns to be placed on the given row.

        Lights unoccupied cells white and switches them to the team colour once
        the reed switch detects a piece. Loops until all eight cells in the row
        are occupied.

        Args:
            team: The Team whose pawns are being placed (determines LED colour).
            row: Board row index (0–7) where the pawns belong.
        """
        for col in range(8):
            self.light_cell(self.canvas, row, col, 255, 255, 255)
        placed = False
        while not placed:
            placed = True
            self.master.read_data()
            for col in range(8):
                if self.master.get_cell_state(row, col) == CellOccupancy.EMPTY:
                    placed = False
                    self.light_cell(self.canvas, row, col, 255, 255, 255)
                else:
                    self.light_cell(self.canvas, row, col, team.r, team.g, team.b)
            time.sleep(0.1)

    def detect_piece(self, team, piece, row, col):
        """Wait for a single piece to be placed on the specified cell.

        Lights the target cell white until the reed switch at (row, col)
        reports OCCUPIED, then switches the LED to the team colour.

        Args:
            team: The Team that owns the piece (determines LED colour).
            piece: String name of the piece type (e.g. "King", "Rook").
            row: Board row index of the expected cell.
            col: Board column index of the expected cell.
        """
        self.light_cell(self.canvas, row, col, 255, 255, 255)
        placed = False
        while not placed:
            self.master.read_data()
            if self.master.get_cell_state(row, col) == CellOccupancy.OCCUPIED:
                placed = True
            time.sleep(0.01)
        self.light_cell(self.canvas, row, col, team.r, team.g, team.b)

    def detect_lift_off(self, team):
        """Check whether a team's piece has been lifted from the board.

        Scans all pieces belonging to team and returns the first one whose
        cell now reads EMPTY on the sensor.

        Args:
            team: The Team whose pieces are checked for lift-off.

        Returns:
            A tuple (valid, lifted) where valid is True if a piece was lifted
            and lifted is the Piece object that was picked up, or None if no
            piece was lifted.
        """
        valid_pieces = self.get_team_pieces(team)
        self.master.read_data()
        valid = False
        lifted = None
        for piece in valid_pieces:
            state = self.master.get_cell_state(piece.row, piece.col)
            if state == CellOccupancy.EMPTY and not valid:
                valid = True
                lifted = piece
        return valid, lifted

    def get_team_pieces(self, team, grid=None):
        """Return a flat list of all pieces belonging to a team on a given grid.

        Args:
            team: The Team to filter by (matched via team.r colour value).
            grid: Optional 8x8 board state to search; defaults to self.grid.

        Returns:
            A list of Piece objects whose team colour matches the given team.
        """
        if grid is None:
            grid = self.grid
        valid_pieces = []
        for row in grid:
            for piece in row:
                if piece is not None and piece.team.r == team.r:
                    valid_pieces.append(piece)
        return valid_pieces

    def detect_landing(self, piece):
        """Detect where a lifted piece has been set down.

        Checks the piece's origin cell and each of its valid target cells
        against the sensor. If the piece is set down on an occupied target,
        pulses the target LED until the captured piece is physically removed.

        Args:
            piece: The Piece that was lifted, whose targets list is inspected.

        Returns:
            A tuple (valid, cell) where valid is True if the piece landed on a
            legal square and cell is the Cell it landed on, or (False, None)
            if no landing was detected yet.
        """
        self.master.read_data()
        targets = piece.targets
        valid = False
        activated_target = None
        state = self.master.get_cell_state(piece.row, piece.col)
        if state == CellOccupancy.OCCUPIED:
            return_cell = Cell(piece.row, piece.col)
            return True, return_cell
        for cell in targets:
            state = self.master.get_cell_state(cell.row, cell.col)
            if self.grid[cell.row][cell.col] is not None:
                if state == CellOccupancy.EMPTY:
                    activated_target = cell
                    while state == CellOccupancy.EMPTY:
                        self.canvas.Clear()
                        self.light_checker_town(self.canvas)
                        if ((time.time() - int(time.time())) * 1000) % 250 > 125:
                            self.light_cell(
                                self.canvas, cell.row, cell.col,
                                piece.team.r, piece.team.g, piece.team.b)
                        self.canvas = self.matrix.SwapOnVSync(self.canvas)
                        self.master.read_data()
                        state = self.master.get_cell_state(cell.row, cell.col)
                    valid = True
            elif state == CellOccupancy.OCCUPIED:
                valid = True
                activated_target = cell
        return valid, activated_target

    def seth_victory(self, team):
        """Display the victory animation for the winning team.

        The border of the LED matrix is lit in the winner's colour and the
        interior cells cycle through random colours. Loops until check_new_game
        signals that pieces have been reset for a new game.

        Args:
            team: The Team that lost (the opposite team's colour is displayed
                as the winner).
        """
        if team == self.team_l:
            team = self.team_r
        else:
            team = self.team_l
        while True:
            if self.check_new_game():
                return
            time.sleep(0.05)
            self.canvas.Clear()
            for m in range(8):
                self.light_cell(self.canvas, m, 0, team.r, team.g, team.b)
                self.light_cell(self.canvas, 0, m, team.r, team.g, team.b)
                self.light_cell(self.canvas, m, 7, team.r, team.g, team.b)
                self.light_cell(self.canvas, 7, m, team.r, team.g, team.b)
            for j in range(1, 7):
                for k in range(1, 7):
                    self.light_cell(self.canvas, j, k,
                                    random.randint(0, 255),
                                    random.randint(0, 255),
                                    random.randint(0, 255))
            self.canvas = self.matrix.SwapOnVSync(self.canvas)

    def stale_mate(self):
        """Display the stalemate animation splitting the board between both teams.

        The top four rows are lit in team_r's colour and the bottom four in
        team_l's colour. Loops until check_new_game signals a board reset.
        """
        self.canvas.Clear()
        for i in range(4):
            for j in range(8):
                self.light_cell(self.canvas, i, j, self.team_r.r, self.team_r.g, self.team_r.b)
        for i in range(4, 8):
            for j in range(8):
                self.light_cell(self.canvas, i, j, self.team_l.r, self.team_l.g, self.team_l.b)
        self.canvas = self.matrix.SwapOnVSync(self.canvas)
        while True:
            if self.check_new_game():
                return

    def do_turn(self, team):
        """Process a single human player turn for the given team.

        Calculates legal moves for all pieces, checks for checkmate and
        stalemate, verifies the physical board state, then waits for the
        player to lift a piece and set it down on a valid target square.
        Updates the logical grid and calls _apply_move once a valid move is
        confirmed.

        Args:
            team: The Team whose turn it is (team_r or team_l).
        """
        if self.bob_ross(team, self.grid):
            return

        check = False
        king_row = -1
        king_col = -1
        pieces_with_moves = 0

        for row in self.grid:
            for piece in row:
                if piece is not None:
                    if isinstance(piece, King) and piece.team == team:
                        check = piece.calc_targets(self.grid)
                        if len(piece.get_targets()) > 0:
                            pieces_with_moves += 1
                        king_row = piece.row
                        king_col = piece.col

        for row in self.grid:
            for piece in row:
                if isinstance(piece, Pawn) and piece.team == team:
                    piece.en_passantable = False
                if piece is not None and not isinstance(piece, King):
                    piece.calc_targets(self.grid)
                    if check:
                        piece.sky_fall(self.grid[king_row][king_col])
                    if len(piece.get_targets()) > 0 and piece.team == team:
                        pieces_with_moves += 1

        if pieces_with_moves == 0:
            if not check:
                self.game_over = True
                self._on_game_over("stalemate", team)
                self.stale_mate()
                return
            elif check:
                self.game_over = True
                self._on_game_over("checkmate", team)
                self.seth_victory(team)
                return

        self.detect_mismatch()

        time.sleep(0.25)

        move = False
        row = 0
        col = 0
        logger.info("Player: %s's move.", team.name)

        while not move:
            self.canvas.Clear()
            piece_lifted = False
            lifted_piece = None
            while not piece_lifted:
                piece_lifted, lifted_piece = self.detect_lift_off(team)

            row = lifted_piece.row
            col = lifted_piece.col
            self.light_checker_town(self.canvas)
            self.light_targets(self.grid[row][col])
            self.canvas = self.matrix.SwapOnVSync(self.canvas)

            move = True
            valid_move = False
            while not valid_move:
                placed = False
                returned = False
                while not placed:
                    self.canvas.Clear()
                    self.light_checker_town(self.canvas)
                    self.light_targets(self.grid[row][col])
                    if time.time() - int(time.time()) > 0.5:
                        self.light_cell(
                            self.canvas, row, col,
                            lifted_piece.team.r, lifted_piece.team.g, lifted_piece.team.b)
                    self.canvas = self.matrix.SwapOnVSync(self.canvas)
                    placed, target_cell = self.detect_landing(self.grid[row][col])
                    if placed:
                        if target_cell.row == row and target_cell.col == col:
                            returned = True
                if returned:
                    move = False
                    valid_move = True
                    self.canvas.Clear()
                    self.light_checker_town(self.canvas)
                    self.canvas = self.matrix.SwapOnVSync(self.canvas)

                if move:
                    target_row = target_cell.row
                    target_col = target_cell.col

                    for cell in self.grid[row][col].get_targets():
                        if cell.row == target_row and cell.col == target_col:
                            valid_move = True
                            pre_capture = self.grid[target_row][target_col]
                            if pre_capture is not None:
                                self.peace_time = 0
                            else:
                                self.peace_time += 1
                            self.grid[target_row][target_col] = self.grid[row][col]
                            self._apply_move(row, col, target_row, target_col)
                            moved = self.grid[target_row][target_col]
                            if (isinstance(moved, Pawn)
                                    and (moved.starting_row + 6) % 12 == target_row):
                                self.upgrade_pawn(Cell(row, col),
                                                  Cell(target_row, target_col), team)
                            self._on_local_move(row, col, target_row, target_col, pre_capture)

                    if not valid_move:
                        logger.debug("Invalid target.")
                    else:
                        self.canvas.Clear()
                        self.light_checker_town(self.canvas)
                        self.canvas = self.matrix.SwapOnVSync(self.canvas)

    def light_targets(self, piece):
        """Illuminate all valid target squares for a piece in its team colour.

        Reads piece.get_targets() and calls light_cell for each target cell
        using the piece's team RGB values.

        Args:
            piece: The Piece whose target squares should be highlighted.
        """
        r = piece.team.r
        g = piece.team.g
        b = piece.team.b
        targets = piece.get_targets()
        for cell in targets:
            self.light_cell(self.canvas, cell.row, cell.col, r, g, b)

    def blink_cell(
        self,
        canvas,
        cell: Cell,
        fps: float = 4,
        duty_cycle: float = 50,
        color: tuple[int, int, int] = (255, 255, 255),
    ) -> None:
        """Light a cell for the on-phase of a blink cycle, do nothing during off-phase.

        Args:
            canvas: The RGBMatrix frame canvas to draw onto.
            cell: Board cell to blink.
            fps: Blink frequency in flashes per second.
            duty_cycle: Percentage of each period the cell is on (0–100).
            color: RGB colour for the on-phase.
        """
        blink_time = 1000 / fps  # ms per cycle
        on_time = (duty_cycle / 100) * blink_time
        r, g, b = color
        if ((time.time() - int(time.time())) * 1000) % blink_time > on_time:
            self.light_cell(canvas, cell.row, cell.col, r, g, b)

    def is_lifted(self, cells: list[Cell]) -> list[Cell]:
        """Return the subset of *cells* whose reed switches report EMPTY.

        Args:
            cells: Board cells to check.

        Returns:
            List of cells that the sensor reports as unoccupied (piece lifted).
        """
        self.master.read_data()
        lifted = []
        for cell in cells:
            state = self.master.get_cell_state(cell.row, cell.col)
            if state:
                lifted.append(cell)
        return lifted

    def initialize_game_board(self):
        """Populate self.grid with the standard chess starting position.

        Places all 32 pieces for both teams: team_r occupies rows 0–1 and
        team_l occupies rows 6–7 with the conventional piece arrangement.
        """
        for col in range(8):
            self.grid[1][col] = Pawn(1, col, self.team_r)
        self.grid[0][2] = Bishop(0, 2, self.team_r)
        self.grid[0][5] = Bishop(0, 5, self.team_r)
        self.grid[0][0] = Rook(0, 0, self.team_r)
        self.grid[0][7] = Rook(0, 7, self.team_r)
        self.grid[0][1] = Knight(0, 1, self.team_r)
        self.grid[0][6] = Knight(0, 6, self.team_r)
        self.grid[0][3] = Queen(0, 3, self.team_r)
        self.grid[0][4] = King(0, 4, self.team_r)

        for col in range(8):
            self.grid[6][col] = Pawn(6, col, self.team_l)
        self.grid[7][2] = Bishop(7, 2, self.team_l)
        self.grid[7][5] = Bishop(7, 5, self.team_l)
        self.grid[7][0] = Rook(7, 0, self.team_l)
        self.grid[7][7] = Rook(7, 7, self.team_l)
        self.grid[7][1] = Knight(7, 1, self.team_l)
        self.grid[7][6] = Knight(7, 6, self.team_l)
        self.grid[7][3] = Queen(7, 3, self.team_l)
        self.grid[7][4] = King(7, 4, self.team_l)

    def initialize_game_board2(self):
        """Populate self.grid with a custom mid-game test position (scenario 2).

        Places a reduced set of pieces for both teams in a specific layout used
        for development and testing of chess logic.
        """
        for col in range(7):
            self.grid[1][col] = Pawn(1, col, self.team_r)
        self.grid[5][7] = Pawn(5, 7, self.team_r)

        for col in range(6):
            if col == 3:
                continue
            self.grid[6][col] = Pawn(6, col, self.team_l)
        self.grid[3][5] = Bishop(3, 5, self.team_l)
        self.grid[7][0] = Rook(7, 0, self.team_l)
        self.grid[7][7] = Rook(7, 7, self.team_l)
        self.grid[7][1] = Knight(7, 1, self.team_l)
        self.grid[6][6] = Queen(6, 6, self.team_l)
        self.grid[7][4] = King(7, 4, self.team_l)

    def initialize_game_board3(self):
        """Populate self.grid with a custom mid-game test position (scenario 3).

        Places pieces for both teams in a specific layout with pre-touched kings
        used for development and testing of castling and pin logic.
        """
        self.grid[1][0] = Pawn(1, 0, self.team_r)
        self.grid[2][1] = Pawn(2, 1, self.team_r)
        self.grid[1][6] = Pawn(1, 6, self.team_r)
        self.grid[1][7] = Pawn(1, 7, self.team_r)
        self.grid[5][2] = Pawn(5, 2, self.team_r)
        self.grid[0][2] = Bishop(0, 2, self.team_r)
        self.grid[4][7] = Bishop(4, 7, self.team_r)
        self.grid[0][7] = Rook(0, 7, self.team_r)
        self.grid[1][4] = Knight(1, 4, self.team_r)
        self.grid[2][2] = Queen(2, 2, self.team_r)
        self.grid[0][5] = King(0, 5, self.team_r)
        self.grid[0][5].touched = True

        self.grid[5][0] = Pawn(5, 0, self.team_l)
        self.grid[5][0].direction = -1
        self.grid[6][1] = Pawn(6, 1, self.team_l)
        self.grid[6][2] = Pawn(6, 2, self.team_l)
        self.grid[5][3] = Pawn(5, 3, self.team_l)
        self.grid[5][3].direction = -1
        self.grid[6][7] = Pawn(6, 7, self.team_l)
        self.grid[1][5] = Bishop(1, 5, self.team_l)
        self.grid[7][0] = Rook(7, 0, self.team_l)
        self.grid[7][6] = Rook(7, 6, self.team_l)
        self.grid[0][0] = Knight(0, 0, self.team_l)
        self.grid[4][5] = Queen(4, 5, self.team_l)
        self.grid[6][4] = King(6, 4, self.team_l)
        self.grid[6][4].touched = True

    def initialize_game_board4(self):
        """Populate self.grid with a custom mid-game test position (scenario 4).

        Similar to scenario 3 but with a different pawn and rook layout, used
        for development and testing of specific endgame patterns.
        """
        self.grid[1][0] = Pawn(1, 0, self.team_r)
        self.grid[2][1] = Pawn(2, 1, self.team_r)
        self.grid[1][6] = Pawn(1, 6, self.team_r)
        self.grid[1][7] = Pawn(1, 7, self.team_r)
        self.grid[6][1] = Pawn(6, 1, self.team_r)
        self.grid[0][2] = Bishop(0, 2, self.team_r)
        self.grid[4][7] = Bishop(4, 7, self.team_r)
        self.grid[0][7] = Rook(0, 7, self.team_r)
        self.grid[1][4] = Knight(1, 4, self.team_r)
        self.grid[2][2] = Queen(2, 2, self.team_r)
        self.grid[0][5] = King(0, 5, self.team_r)
        self.grid[0][5].touched = True

        self.grid[5][0] = Pawn(5, 0, self.team_l)
        self.grid[5][0].direction = -1
        self.grid[6][2] = Pawn(6, 2, self.team_l)
        self.grid[5][3] = Pawn(5, 3, self.team_l)
        self.grid[5][3].direction = -1
        self.grid[6][7] = Pawn(6, 7, self.team_l)
        self.grid[1][5] = Bishop(1, 5, self.team_l)
        self.grid[7][0] = Rook(7, 0, self.team_l)
        self.grid[0][0] = Knight(0, 0, self.team_l)
        self.grid[4][5] = Queen(4, 5, self.team_l)
        self.grid[6][4] = King(6, 4, self.team_l)
        self.grid[6][4].touched = True

    def initialize_game_board5(self):
        """Populate self.grid with a minimal pawn-and-king endgame (scenario 5).

        Places a single pawn for team_r and a rook plus king for team_l, used
        for testing pawn promotion and basic endgame scenarios.
        """
        self.grid[6][1] = Pawn(6, 1, self.team_r)
        self.grid[6][1].direction = 1
        self.grid[6][1].starting_row = 1
        self.grid[0][5] = King(0, 5, self.team_r)
        self.grid[0][5].touched = True

        self.grid[7][0] = Rook(7, 0, self.team_l)
        self.grid[6][4] = King(6, 4, self.team_l)
        self.grid[6][4].touched = True

    def initialize_game_board6(self):
        """Populate self.grid with a complex multi-piece test position (scenario 6).

        Places pawns, rooks, bishops, and kings for both teams with pre-set
        directions and touched flags, used for testing advanced move logic
        including passed pawns and rook activity.
        """
        self.grid[1][0] = Pawn(1, 0, self.team_r)
        self.grid[1][0].direction = 1
        self.grid[1][0].starting_row = 1
        self.grid[1][1] = Pawn(1, 1, self.team_r)
        self.grid[1][1].direction = 1
        self.grid[1][1].starting_row = 1
        self.grid[1][6] = Pawn(1, 6, self.team_r)
        self.grid[1][6].direction = 1
        self.grid[1][6].starting_row = 1
        self.grid[1][7] = Pawn(1, 7, self.team_r)
        self.grid[1][7].direction = 1
        self.grid[1][7].starting_row = 1
        self.grid[0][3] = King(0, 3, self.team_r)
        self.grid[0][3].touched = True
        self.grid[0][0] = Rook(0, 0, self.team_r)
        self.grid[3][4] = Rook(3, 4, self.team_r)
        self.grid[1][3] = Bishop(1, 3, self.team_r)

        self.grid[6][1] = Pawn(6, 1, self.team_l)
        self.grid[6][1].direction = -1
        self.grid[6][1].starting_row = 6
        self.grid[5][1] = Pawn(5, 1, self.team_l)
        self.grid[5][1].direction = -1
        self.grid[5][1].starting_row = 6
        self.grid[5][1].touched = True
        self.grid[3][3] = Pawn(3, 3, self.team_l)
        self.grid[3][3].direction = -1
        self.grid[3][3].starting_row = 6
        self.grid[3][3].touched = True
        self.grid[5][5] = Pawn(5, 5, self.team_l)
        self.grid[5][5].direction = -1
        self.grid[5][5].starting_row = 6
        self.grid[5][5].touched = True
        self.grid[5][6] = Pawn(5, 6, self.team_l)
        self.grid[5][6].direction = -1
        self.grid[5][6].starting_row = 6
        self.grid[5][6].touched = True
        self.grid[6][7] = Pawn(6, 7, self.team_l)
        self.grid[6][7].direction = -1
        self.grid[6][7].starting_row = 6
        self.grid[7][0] = Rook(7, 0, self.team_l)
        self.grid[7][7] = Rook(7, 7, self.team_l)
        self.grid[7][5] = Bishop(7, 5, self.team_l)
        self.grid[1][5] = Knight(1, 5, self.team_l)
        self.grid[7][3] = King(7, 3, self.team_l)
        self.grid[7][3].touched = True

    def create_players(self):
        """Assign display names to both teams based on human/computer flags.

        Sets team names to "Computer"/"Human" for AI games, or "Player 1"/
        "Player 2" for two-human games, using the computer_player_r and
        computer_player_l flags set during war_games.
        """
        if self.computer_player_r:
            self.team_r.set_name("Computer")
            self.team_l.set_name("Human")
        elif self.computer_player_l:
            self.team_l.set_name("Computer")
            self.team_r.set_name("Human")
        else:
            self.team_l.set_name("Player 2")
            self.team_r.set_name("Player 1")

    def light_cell(self, canvas, x, y, r, g, b):
        """Light an 8x8 pixel block on the LED matrix for board cell (x, y).

        Delegates to the ui.renderer.light_cell helper, which maps the logical
        (row, col) cell coordinate to the corresponding pixel region.

        Args:
            canvas: The RGBMatrix frame canvas to draw onto.
            x: Board row index (0–7).
            y: Board column index (0–7).
            r: Red component (0–255).
            g: Green component (0–255).
            b: Blue component (0–255).
        """
        _light_cell(canvas, x, y, r, g, b)

    def print_board_states(self, grid=None):
        """Print each row of the board state to stdout for debugging.

        Args:
            grid: Optional 8x8 board state to print; defaults to self.grid.
        """
        if grid is None:
            grid = self.grid
        for r in range(8):
            print(grid[r])

    def computer_move(self, team, depth=2):
        """Compute and execute the AI's best move for the given team.

        Calculates legal moves, checks for checkmate/stalemate, builds the
        alpha-beta game tree via add_nodes, queries the AI for the best move,
        then guides the physical board interaction (waiting for the human
        operator to move the piece) before updating the logical grid.

        Args:
            team: The Team the AI is playing for (team_r or team_l).
            depth: Minimax search depth; defaults to 2.
        """
        if self.bob_ross(team, self.grid):
            return

        check = False
        king_row = -1
        king_col = -1
        pieces_with_moves = 0
        self.checker_brightness = 255

        for row in self.grid:
            for piece in row:
                if piece is not None:
                    if isinstance(piece, King) and piece.team == team:
                        check = piece.calc_targets(self.grid)
                        if len(piece.get_targets()) > 0:
                            pieces_with_moves += 1
                        king_row = piece.row
                        king_col = piece.col

        for row in self.grid:
            for piece in row:
                if isinstance(piece, Pawn) and piece.team == team:
                    piece.en_passantable = False
                if piece is not None and not isinstance(piece, King):
                    piece.calc_targets(self.grid)
                    if check:
                        piece.sky_fall(self.grid[king_row][king_col])
                    if len(piece.get_targets()) > 0 and piece.team == team:
                        pieces_with_moves += 1

        if pieces_with_moves == 0:
            if not check:
                self.game_over = True
                self.stale_mate()
                return
            elif check:
                self.game_over = True
                self.seth_victory(team)
                return

        root = Tree(copy.deepcopy(self.grid), None, None, self.team_r, self.team_l)
        self.add_nodes(root, team, depth)

        computer_player = AI(root, team)
        best_move = computer_player.alpha_beta_search()

        logger.debug("the best move involves moving the piece at square %s%s to %s%s",
                     best_move.old_cell.row, best_move.old_cell.col,
                     best_move.new_cell.row, best_move.new_cell.col)

        state = 0

        self.canvas.Clear()
        self.light_checker_town(self.canvas)
        self.canvas = self.matrix.SwapOnVSync(self.canvas)
        self.detect_mismatch()

        if self.grid[best_move.new_cell.row][best_move.new_cell.col] is None:
            self.peace_time += 1
            while state == CellOccupancy.OCCUPIED:
                self.master.read_data()
                self.canvas.Clear()
                self.light_checker_town(self.canvas)
                self.light_cell(self.canvas, best_move.old_cell.row, best_move.old_cell.col,
                                team.r, team.g, team.b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                state = self.master.get_cell_state(best_move.old_cell.row, best_move.old_cell.col)
            while state == CellOccupancy.EMPTY:
                self.master.read_data()
                self.canvas.Clear()
                self.light_checker_town(self.canvas)
                self.light_cell(self.canvas, best_move.new_cell.row, best_move.new_cell.col,
                                team.r, team.g, team.b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                time.sleep(.1)
                self.canvas.Clear()
                self.light_checker_town(self.canvas)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                state = self.master.get_cell_state(best_move.new_cell.row, best_move.new_cell.col)
        else:
            state = 0
            while state == CellOccupancy.OCCUPIED:
                self.master.read_data()
                self.canvas.Clear()
                self.light_checker_town(self.canvas)
                self.light_cell(self.canvas, best_move.old_cell.row, best_move.old_cell.col,
                                team.r, team.g, team.b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                state = self.master.get_cell_state(best_move.old_cell.row, best_move.old_cell.col)
            state = 0
            while state == CellOccupancy.OCCUPIED:
                self.master.read_data()
                self.canvas.Clear()
                self.light_checker_town(self.canvas)
                self.light_cell(self.canvas, best_move.new_cell.row, best_move.new_cell.col,
                                team.r, team.g, team.b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                state = self.master.get_cell_state(best_move.new_cell.row, best_move.new_cell.col)
            time.sleep(.1)
            while state == CellOccupancy.EMPTY:
                self.master.read_data()
                self.canvas.Clear()
                self.light_checker_town(self.canvas)
                self.light_cell(self.canvas, best_move.new_cell.row, best_move.new_cell.col,
                                team.r, team.g, team.b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                time.sleep(.1)
                self.canvas.Clear()
                self.light_checker_town(self.canvas)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                state = self.master.get_cell_state(best_move.new_cell.row, best_move.new_cell.col)

        self.grid[best_move.new_cell.row][best_move.new_cell.col] = (
            self.grid[best_move.old_cell.row][best_move.old_cell.col])
        self._apply_move(best_move.old_cell.row, best_move.old_cell.col,
                         best_move.new_cell.row, best_move.new_cell.col)

        self.canvas.Clear()
        self.light_checker_town(self.canvas)
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

    def _on_local_move(self, fr: int, fc: int, tr: int, tc: int, pre_capture) -> None:
        """Hook called after each local human move is applied.

        No-op in the base class.  Override in subclasses (e.g. NetworkedBoard)
        to transmit the move over a network connection.

        Args:
            fr: From-row of the moving piece.
            fc: From-col of the moving piece.
            tr: To-row of the destination.
            tc: To-col of the destination.
            pre_capture: Whatever occupied grid[tr][tc] before the move
                (None if the destination was empty).
        """

    def _on_game_over(self, event: str, losing_team) -> None:
        """Hook called when do_turn detects checkmate or stalemate.

        No-op in the base class.  Override in subclasses to notify a peer.

        Args:
            event: ``"checkmate"`` or ``"stalemate"``.
            losing_team: The Team that has no legal moves.
        """

    def _apply_move(self, old_row, old_col, target_row, target_col):
        """Dispatch piece movement after grid[target] = grid[old] is set.

        Handles Pawn (en passant + LED animation), King (castling), and
        standard pieces. Resets peace_time for pawn moves. Clears old square.
        """
        piece = self.grid[target_row][target_col]
        if isinstance(piece, Pawn):
            self.peace_time = 0
            enemy = piece.move(target_row, target_col, self.grid)
            if enemy is not None:
                self.grid[enemy.row][enemy.col] = None
                state = self.master.get_cell_state(enemy.row, enemy.col)
                while state == CellOccupancy.OCCUPIED:
                    self.master.read_data()
                    time.sleep(0.4)
                    for r in range(201):
                        self.canvas.Clear()
                        self.light_checker_town(self.canvas)
                        self.light_cell(self.canvas, enemy.row, enemy.col, 50 + r, 0, 0)
                        self.canvas = self.matrix.SwapOnVSync(self.canvas)
                        time.sleep(0.002)
                    self.master.read_data()
                    time.sleep(0.4)
                    for r in range(201):
                        self.canvas.Clear()
                        self.light_checker_town(self.canvas)
                        self.light_cell(self.canvas, enemy.row, enemy.col, 255 - r, 0, 0)
                        self.canvas = self.matrix.SwapOnVSync(self.canvas)
                        time.sleep(0.002)
                    state = self.master.get_cell_state(enemy.row, enemy.col)
        elif isinstance(piece, King):
            rook_location, rook_target = piece.move(target_row, target_col, self.grid)
            if rook_location is not None:
                self.grid[rook_target.row][rook_target.col] = (
                    self.grid[rook_location.row][rook_location.col])
                self.grid[rook_location.row][rook_location.col] = None
                self.grid[rook_target.row][rook_target.col].move(
                    rook_target.row, rook_target.col, self.grid)
        else:
            piece.move(target_row, target_col, self.grid)
        self.grid[old_row][old_col] = None

    @contextmanager
    def canvas_swap(self):
        """Context manager: clear canvas, yield it, then swap to display."""
        self.canvas.Clear()
        yield self.canvas
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

    @contextmanager
    def fresh_checker_town(self, color: tuple[int, int, int] = (255, 255, 255)):
        """Context manager: clear, draw checker pattern in *color*, yield canvas, swap.

        Args:
            color: RGB colour for the checker squares (default white).
        """
        with self.canvas_swap() as canvas:
            self.light_checker_town(canvas, color)
            yield canvas

    def upgrade_pawn(self, start_cell: Cell, end_cell: Cell, team) -> None:
        """Interactive pawn promotion: let the player choose Queen/Knight/Bishop/Rook.

        Waits for the player to lift the promoted pawn from end_cell, then
        cycles through the four candidate pieces while the player holds the
        piece over start_cell (the square it came from).  Placing the piece
        back on end_cell confirms the selection and updates self.grid.

        Args:
            start_cell: The cell the pawn moved FROM (used as the cycle trigger).
            end_cell: The cell the pawn moved TO (promotion square).
            team: The team whose pawn was promoted.
        """
        candidates = [
            Queen(end_cell.row, end_cell.col, team),
            Knight(end_cell.row, end_cell.col, team),
            Bishop(end_cell.row, end_cell.col, team),
            Rook(end_cell.row, end_cell.col, team),
        ]
        index = 0

        # Wait for player to lift pawn from promotion square to begin
        while not self.is_lifted([end_cell]):
            with self.fresh_checker_town() as canvas:
                self.blink_cell(canvas, end_cell, fps=2,
                                color=(team.r, team.g, team.b))

        # Player has lifted the piece — cycle through candidates
        test_grid: BoardGrid = [[None] * 8 for _ in range(8)]
        examining = True
        self.reset_counter("switch_trigger")
        self.reset_counter("select_trigger")
        while True:
            with self.fresh_checker_town() as canvas:
                pick = candidates[index]
                test_grid[end_cell.row][end_cell.col] = pick
                pick.calc_targets(test_grid)
                if start_cell in pick.targets:
                    pick.targets.remove(start_cell)
                self.light_targets(pick)
                self.light_cell(canvas, end_cell.row, end_cell.col,
                                team.r, team.g, team.b)
                if examining:
                    self.blink_cell(canvas, start_cell,
                                    color=(team.r, team.g, team.b))
                else:
                    self.light_cell(canvas, start_cell.row, start_cell.col,
                                    team.r, team.g, team.b)

            if not self.confident("switch_trigger",
                                  self.is_lifted([start_cell]), True, threshold=2):
                if examining:
                    index = (index + 1) % len(candidates)
                examining = False
            elif not self.confident("select_trigger",
                                    self.is_lifted([end_cell]), True, threshold=5):
                break
            else:
                examining = True

        self.grid[end_cell.row][end_cell.col] = candidates[index]
        logger.info("Pawn promoted to %s at (%d,%d)",
                    type(candidates[index]).__name__, end_cell.row, end_cell.col)

    def draw_board(self, board_state):
        """Render a board state to the LED matrix with a pulsing checker background.

        Advances the checker brightness animation by one step, draws the
        checker pattern at the current brightness, then overlays each piece
        in its team colour.

        Args:
            board_state: An 8x8 list of Piece | None to render.
        """
        self.canvas.Clear()
        self.checker_brightness += self.checker_brightness_dir
        if self.checker_brightness <= 0:
            self.checker_brightness_dir *= -1
            self.checker_brightness = 0
        elif self.checker_brightness >= 255:
            self.checker_brightness_dir *= -1
            self.checker_brightness = 255

        for row in board_state:
            for piece in row:
                if piece is not None:
                    self.light_cell(self.canvas, piece.row, piece.col,
                                    piece.team.r, piece.team.g, piece.team.b)

        self.choose_light_checker_town()
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

    def color_picker(self):
        """Display the colour-selection UI and wait for both teams to choose colours.

        Shows eight colour swatches on rows 2 and 5 of the LED matrix. Players
        place a piece on their chosen column to select that colour. Rows 3 and 4
        act as shutdown/restart triggers when both are occupied simultaneously.
        Loops until team_r (row 2) and team_l (row 5) have each made a selection.
        """
        self.canvas.Clear()

        for i in range(8):
            self.light_cell(self.canvas, 2, i,
                            self.team_array[i].r, self.team_array[i].g, self.team_array[i].b)
            self.light_cell(self.canvas, 5, i,
                            self.team_array[i].r, self.team_array[i].g, self.team_array[i].b)

        team1_found = False
        team2_found = False
        shut_down_key1 = False
        shut_down_key2 = False
        restart_key1 = False
        restart_key2 = False

        self.canvas = self.matrix.SwapOnVSync(self.canvas)

        while not (team1_found and team2_found):
            team1_found = False
            team2_found = False
            shut_down_key1 = False
            shut_down_key2 = False
            restart_key1 = False
            restart_key2 = False
            self.master.read_data()
            for i in range(8):
                if self.master.get_cell_state(2, i) == CellOccupancy.OCCUPIED:
                    team1_found = True
                    self.team_r.r = self.team_array[i].r
                    self.team_r.g = self.team_array[i].g
                    self.team_r.b = self.team_array[i].b
                if self.master.get_cell_state(5, i) == CellOccupancy.OCCUPIED:
                    team2_found = True
                    self.team_l.r = self.team_array[i].r
                    self.team_l.g = self.team_array[i].g
                    self.team_l.b = self.team_array[i].b
            for i in range(8):
                if self.master.get_cell_state(3, i) == CellOccupancy.OCCUPIED:
                    shut_down_key1 = True
                    if i == 7:
                        restart_key1 = True
                if self.master.get_cell_state(4, i) == CellOccupancy.OCCUPIED:
                    shut_down_key2 = True
                    if i == 7:
                        restart_key2 = True

            if shut_down_key1 and shut_down_key2:
                self.canvas.Clear()
                for i in range(12):
                    self.canvas.Clear()
                    for j in range(i, 32 - i):
                        for k in range(32):
                            self.canvas.SetPixel(j, k, 255, 0, 0)
                    self.canvas = self.matrix.SwapOnVSync(self.canvas)
                    time.sleep(0.035 * np.exp(-1 / 16 * (i - 12)))
                for i in range(16):
                    self.canvas.Clear()
                    for j in range(i, 32 - i):
                        for k in range(12, 20):
                            self.canvas.SetPixel(k, j, 255, 0, 0)
                    self.canvas = self.matrix.SwapOnVSync(self.canvas)
                    time.sleep(0.025 * np.exp(-1 / 16 * (i - 16)))
                self.canvas.Clear()
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                if restart_key1 and restart_key2:
                    os.system("sudo reboot now")
                    while True:
                        time.sleep(1)
                else:
                    os.system("sudo shutdown now")
                    while True:
                        time.sleep(1)
            self.canvas.Clear()
            if team1_found and team2_found:
                for i in range(8):
                    if self.master.get_cell_state(2, i) == CellOccupancy.OCCUPIED:
                        self.light_cell(self.canvas, 2, i,
                                        self.team_array[i].r, self.team_array[i].g, self.team_array[i].b)
                    if self.master.get_cell_state(5, i) == CellOccupancy.OCCUPIED:
                        self.light_cell(self.canvas, 5, i,
                                        self.team_array[i].r, self.team_array[i].g, self.team_array[i].b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                time.sleep(2)
            elif team1_found:
                for i in range(8):
                    if self.master.get_cell_state(2, i) == CellOccupancy.OCCUPIED:
                        self.light_cell(self.canvas, 2, i,
                                        self.team_array[i].r, self.team_array[i].g, self.team_array[i].b)
                for i in range(8):
                    self.light_cell(self.canvas, 5, i,
                                    self.team_array[i].r, self.team_array[i].g, self.team_array[i].b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
            elif team2_found:
                for i in range(8):
                    if self.master.get_cell_state(5, i) == CellOccupancy.OCCUPIED:
                        self.light_cell(self.canvas, 5, i,
                                        self.team_array[i].r, self.team_array[i].g, self.team_array[i].b)
                for i in range(8):
                    self.light_cell(self.canvas, 2, i,
                                    self.team_array[i].r, self.team_array[i].g, self.team_array[i].b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
            else:
                for i in range(8):
                    self.light_cell(self.canvas, 2, i,
                                    self.team_array[i].r, self.team_array[i].g, self.team_array[i].b)
                    self.light_cell(self.canvas, 5, i,
                                    self.team_array[i].r, self.team_array[i].g, self.team_array[i].b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
        self.team_r.r = self.team_r.r + 1

    def war_games(self):
        """Display the human-vs-computer selection UI and wait for both teams to decide.

        Rows 3 and 4 are used as input rows. Columns 0–3 select "Human" and
        columns 4–7 select "Computer" for each respective team. Animates a
        pulsing indicator while waiting, then breaks once both teams have
        committed to a choice.
        """
        self.canvas.Clear()
        logger.info("The only winning move is not to play")

        team1_decided = False
        team2_decided = False

        think = 0
        think_l = 0
        think_r = 0

        while True:
            team1_decided = False
            team2_decided = False
            self.master.read_data()

            for i in range(8):
                if i < 4:
                    if self.master.get_cell_state(3, i) == CellOccupancy.OCCUPIED and not team1_decided:
                        team1_decided = True
                        self.computer_player_r = False
                    if self.master.get_cell_state(4, i) == CellOccupancy.OCCUPIED and not team2_decided:
                        team2_decided = True
                        self.computer_player_l = True
                else:
                    if self.master.get_cell_state(3, i) == CellOccupancy.OCCUPIED and not team1_decided:
                        team1_decided = True
                        self.computer_player_r = True
                    if self.master.get_cell_state(4, i) == CellOccupancy.OCCUPIED and not team2_decided:
                        team2_decided = True
                        self.computer_player_l = False
                if team1_decided and team2_decided:
                    break

            if team1_decided:
                if self.computer_player_r:
                    for i in range(8):
                        if i == 7 - think_r:
                            self.light_cell(self.canvas, 3, 7 - think_r,
                                            self.team_r.r, self.team_r.g, self.team_r.b)
                        else:
                            self.light_cell(self.canvas, 3, i, 255, 255, 255)
                else:
                    for i in range(8):
                        self.light_cell(self.canvas, 3, i, self.team_r.r, self.team_r.g, self.team_r.b)
            else:
                for i in range(8):
                    if i < 4:
                        self.light_cell(self.canvas, 3, i, self.team_r.r, self.team_r.g, self.team_r.b)
                    else:
                        if i == 7 - think:
                            self.light_cell(self.canvas, 3, 7 - think,
                                            self.team_r.r, self.team_r.g, self.team_r.b)
                        else:
                            self.light_cell(self.canvas, 3, i, 255, 255, 255)

            if team2_decided:
                if self.computer_player_l:
                    for i in range(8):
                        if i == think_l:
                            self.light_cell(self.canvas, 4, think_l,
                                            self.team_l.r, self.team_l.g, self.team_l.b)
                        else:
                            self.light_cell(self.canvas, 4, i, 255, 255, 255)
                else:
                    for i in range(8):
                        self.light_cell(self.canvas, 4, i, self.team_l.r, self.team_l.g, self.team_l.b)
            else:
                for i in range(8):
                    if i < 4:
                        if i == think:
                            self.light_cell(self.canvas, 4, think,
                                            self.team_l.r, self.team_l.g, self.team_l.b)
                        else:
                            self.light_cell(self.canvas, 4, i, 255, 255, 255)
                    else:
                        self.light_cell(self.canvas, 4, i, self.team_l.r, self.team_l.g, self.team_l.b)

            self.canvas = self.matrix.SwapOnVSync(self.canvas)
            self.canvas.Clear()
            time.sleep(0.2)

            think = (think + 1) % 4
            think_l = (think_l + 1) % 8
            think_r = (think_r + 1) % 8

            if team1_decided and team2_decided:
                break

    def add_nodes(self, current_node, team, depth=2):
        """Recursively expand the game tree by generating all legal moves.

        For the given team at the current node, computes legal moves for every
        piece (respecting check constraints), creates a deep-copied child board
        state for each move, renders it via draw_board, and recurses for the
        opposing team at depth - 1.

        Args:
            current_node: The Tree node whose children are to be populated.
            team: The Team whose moves are generated at this ply.
            depth: Remaining search depth; stops recursing when 0.
        """
        if depth == 0:
            return
        team_king = None
        check = False
        for piece in self.get_team_pieces(team, current_node.board_state):
            if isinstance(piece, King):
                team_king = piece
                check = team_king.calc_targets(current_node.board_state)
                if check:
                    logger.debug("KING IS IN CHECK")

        for piece in self.get_team_pieces(team, current_node.board_state):
            piece.calc_targets(current_node.board_state)
            if check and not isinstance(piece, King):
                piece.sky_fall(team_king)
            for target in piece.targets:
                new_board = copy.deepcopy(current_node.board_state)
                new_piece = new_board[piece.row][piece.col]
                new_board[target.row][target.col] = new_piece
                new_piece.move(target.row, target.col, new_board)
                new_board[piece.row][piece.col] = None

                self.draw_board(new_board)
                current_node.add_child(Tree(
                    new_board,
                    Cell(piece.row, piece.col),
                    Cell(target.row, target.col),
                    self.team_r,
                    self.team_l,
                ))

        logger.debug("done adding children for depth %s! boards created = %s", depth, len(current_node.children))

        if team == self.team_l:
            team = self.team_r
        else:
            team = self.team_l

        for child in current_node.children:
            self.add_nodes(child, team, depth - 1)

    def check_new_game(self):
        """Determine whether the physical board has been reset for a new game.

        Counts occupied cells per row. Returns True if the board is completely
        empty or if rows 0, 1, 6, and 7 are all fully occupied (standard
        starting position).

        Returns:
            True if a new game should begin, False otherwise.
        """
        self.master.read_data()
        row_counts = [0] * 8
        total = 0
        for i in range(8):
            for j in range(8):
                row_counts[i] += (self.master.get_cell_state(i, j) + 1) % 2
                total += (self.master.get_cell_state(i, j) + 1) % 2
        if total == 0:
            return True
        elif row_counts[0] == 8 and row_counts[1] == 8 and row_counts[6] == 8 and row_counts[7] == 8:
            return True
        else:
            return False

    def bob_ross(self, team, board_state):
        """Check whether the fifty-move rule triggers a draw.

        Delegates to the game.rules module. If the rule is triggered, the draw
        is declared and the method returns True so the caller can return early.

        Args:
            team: The Team whose turn is being checked.
            board_state: The current 8x8 board grid to evaluate.

        Returns:
            True if the fifty-move rule ends the game, False otherwise.
        """
        return _rules.bob_ross(self, team, board_state)

    def check_threefold_repetition(self, team, board_state, days_since_injury, double_jeopardy):
        """Check whether the threefold repetition rule triggers a draw.

        Delegates to the game.rules module. Compares the current board state
        against the history tracked in days_since_injury and double_jeopardy.

        Args:
            team: The Team whose turn is being checked.
            board_state: The current 8x8 board grid to evaluate.
            days_since_injury: List tracking prior board states for this team.
            double_jeopardy: List tracking repeated occurrences of states.

        Returns:
            True if threefold repetition ends the game, False otherwise.
        """
        return _rules.check_threefold_repetition(
            self, team, board_state, days_since_injury, double_jeopardy)

    # ── Counter helpers (used by upgrade_pawn for debouncing sensor reads) ────

    def query_counter(self, name: str) -> tuple:
        """Return (first_value, count) for *name*, or (None, 0) if unknown."""
        if name in self.counters:
            return self.counters[name][0], len(self.counters[name])
        return None, 0

    def update_counter(self, name: str, value) -> None:
        """Append *value* to the run for *name* if equal to the last entry; else restart."""
        if name not in self.counters:
            self.counters[name] = [copy.copy(value)]
            return
        if self.counters[name] and self.counters[name][-1] == value:
            self.counters[name].append(copy.copy(value))
        else:
            self.counters[name] = [copy.copy(value)]

    def reset_counter(self, name: str) -> None:
        """Clear the history for *name*."""
        self.counters[name] = []

    def confident(self, name: str, value, expected, threshold: int = 5):
        """Return *value* once it has been stable for *threshold* consecutive reads.

        Updates the counter for *name* with *value*.  If the run length has
        reached *threshold*, returns the stable value; otherwise returns
        *expected* (the "not yet confident" fallback).

        Args:
            name: Counter key.
            value: Current sensor reading.
            expected: Value to return until confidence is reached.
            threshold: Number of consecutive identical reads required.
        """
        self.update_counter(name, value)
        confident_value, count = self.query_counter(name)
        if count >= threshold:
            return confident_value
        return expected
