#!/usr/bin/env python
from __future__ import annotations

import logging

from samplebase import SampleBase

logger = logging.getLogger(__name__)
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from Team import Team
from Pawn import Pawn
from Bishop import Bishop
from Rook import Rook
from Knight import Knight
from King import King
from Queen import Queen
import time
from Cell import Cell
import random
from Master import Master
from hardware.sensor import BoardSensor
from Tree import Tree
from AI import AI
import copy
import argparse
import os
import numpy as np


class Board(SampleBase):

    def __init__(self, *args, sensor: BoardSensor | None = None, **kwargs):
        super(Board, self).__init__(*args, **kwargs)

        self.team_r = Team(64, 180, 232)
        self.team_l = Team(255, 140, 0)
        self.grid = []
        self.master: BoardSensor = sensor if sensor is not None else Master()
        self.computer_player_r = False
        self.computer_player_l = False

        self.checker_brightness = 0
        self.checker_brightness_dir = 2

        self.game_over = False
        self.peace_time = 0
        self.days_left_since_injury = []
        self.days_right_since_injury = []
        self.double_left_jeopardy = []
        self.double_right_jeopardy = []

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

    # RUN GAME
    def run(self, skip_setup=False, init_num=""):
        logger.info("Running game...")
        self.canvas = self.matrix.CreateFrameCanvas()

        if not skip_setup:
            self.color_picker()
            self.war_games()

        self.create_players()

        # begin interactive setup
        self.canvas.Clear()
        temp_canvas = self.matrix.SwapOnVSync(self.canvas)

        if not skip_setup:
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
        row_increment = (end_row - start_row) / 8.0
        col_increment = (end_col - start_col) / 8.0

    def light_checker_town(self, canvas, color=(255, 255, 255)):
        r, g, b = color
        for x in range(4):
            for y in range(4):
                self.light_cell(canvas, 1 + 2 * x, 2 * y, r, g, b)
        for x in range(4):
            for y in range(4):
                self.light_cell(canvas, 2 * x, 1 + 2 * y, r, g, b)

    def choose_light_checker_town(self, color=(255, 255, 255)):
        r, g, b = map(lambda val: int(val * (self.checker_brightness / 255)), color)
        self.light_checker_town(self.canvas, color=(r, g, b))

    def interactive_setup(self, team):
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
        self.master.read_data()
        bg_color = (255, 0, 0)  # red
        piece_color = (255, 255, 0)  # yellow
        r, g, b = piece_color
        team_r_pieces = self.get_team_pieces(self.team_r)
        team_l_pieces = self.get_team_pieces(self.team_l)
        mismatch = True
        self.canvas.Clear()
        self.light_checker_town(self.canvas)
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

        while mismatch:
            mismatch = False
            self.master.read_data()
            time.sleep(0.2)
            self.canvas.Clear()
            self.light_checker_town(self.canvas, color=bg_color)
            for piece in team_r_pieces + team_l_pieces:
                state = self.master.get_cell_state(piece.row, piece.col)
                if state == 1:
                    mismatch = True
                    self.light_cell(self.canvas, piece.row, piece.col, r, g, b)
            self.canvas = self.matrix.SwapOnVSync(self.canvas)
        # mismatch complete return true
        self.canvas.Clear()
        self.light_checker_town(self.canvas)
        self.canvas = self.matrix.SwapOnVSync(self.canvas)


        return True

    def detect_pawns(self, team, row):
        for col in range(8):
            self.light_cell(self.canvas, row, col, 255, 255, 255)
        placed = False
        while not placed:
            placed = True
            self.master.read_data()
            for col in range(8):
                if self.master.get_cell_state(row, col) == 1:
                    placed = False
                    self.light_cell(self.canvas, row, col, 255, 255, 255)
                else:
                    self.light_cell(self.canvas, row, col, team.r, team.g, team.b)
            time.sleep(0.1)

    def detect_piece(self, team, piece, row, col):
        self.light_cell(self.canvas, row, col, 255, 255, 255)
        placed = False
        while not placed:
            self.master.read_data()
            if self.master.get_cell_state(row, col) == 0:
                placed = True
            time.sleep(0.01)
        self.light_cell(self.canvas, row, col, team.r, team.g, team.b)

    def detect_lift_off(self, team):
        valid_pieces = self.get_team_pieces(team)
        self.master.read_data()
        valid = False
        lifted = None
        for piece in valid_pieces:
            state = self.master.get_cell_state(piece.row, piece.col)
            if state == 1 and not valid:
                valid = True
                lifted = piece
        return valid, lifted

    def get_team_pieces(self, team, grid=None):
        if grid is None:
            grid = self.grid
        valid_pieces = []
        for row in grid:
            for piece in row:
                if piece is not None and piece.team.r == team.r:
                    valid_pieces.append(piece)
        return valid_pieces

    def detect_landing(self, piece):
        self.master.read_data()
        targets = piece.targets
        valid = False
        activated_target = None
        state = self.master.get_cell_state(piece.row, piece.col)
        if state == 0:
            return_cell = Cell(piece.row, piece.col)
            return True, return_cell
        for cell in targets:
            state = self.master.get_cell_state(cell.row, cell.col)
            if self.grid[cell.row][cell.col] is not None:
                if state == 1:
                    activated_target = cell
                    while state == 1:
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
            elif state == 0:
                valid = True
                activated_target = cell
        return valid, activated_target

    def declare_victory(self, team):
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

    def declare_stalemate(self):
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
        if self.check_fifty_move_rule(team, self.grid):
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
                        piece.filter_to_king_escape(self.grid[king_row][king_col])
                    if len(piece.get_targets()) > 0 and piece.team == team:
                        pieces_with_moves += 1

        if pieces_with_moves == 0:
            if not check:
                self.game_over = True
                self.declare_stalemate()
                return
            elif check:
                self.game_over = True
                self.declare_victory(team)
                return

        self.detect_mismatch()
        self.light_checker_town(self.canvas)
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

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
                            if self.grid[target_row][target_col] is not None:
                                self.peace_time = 0
                            else:
                                self.peace_time += 1
                            self.grid[target_row][target_col] = self.grid[row][col]
                            if isinstance(self.grid[target_row][target_col], Pawn):
                                self.peace_time = 0
                                enemy = self.grid[target_row][target_col].move(
                                    target_row, target_col, self.grid)
                                if enemy is not None:
                                    self.grid[enemy.row][enemy.col] = None
                                    state = self.master.get_cell_state(enemy.row, enemy.col)
                                    while state == 0:
                                        self.master.read_data()
                                        time.sleep(0.4)
                                        for r in range(201):
                                            self.canvas.Clear()
                                            self.light_checker_town(self.canvas)
                                            self.light_cell(
                                                self.canvas, enemy.row, enemy.col, 50 + r, 0, 0)
                                            self.canvas = self.matrix.SwapOnVSync(self.canvas)
                                            time.sleep(0.002)
                                        self.master.read_data()
                                        time.sleep(0.4)
                                        for r in range(201):
                                            self.canvas.Clear()
                                            self.light_checker_town(self.canvas)
                                            self.light_cell(
                                                self.canvas, enemy.row, enemy.col, 255 - r, 0, 0)
                                            self.canvas = self.matrix.SwapOnVSync(self.canvas)
                                            time.sleep(0.002)
                                        state = self.master.get_cell_state(enemy.row, enemy.col)
                            elif isinstance(self.grid[target_row][target_col], King):
                                rook_location, rook_target = self.grid[target_row][target_col].move(
                                    target_row, target_col, self.grid)
                                if rook_location is not None:
                                    self.grid[rook_target.row][rook_target.col] = (
                                        self.grid[rook_location.row][rook_location.col])
                                    self.grid[rook_location.row][rook_location.col] = None
                                    self.grid[rook_target.row][rook_target.col].move(
                                        rook_target.row, rook_target.col, self.grid)
                            else:
                                self.grid[target_row][target_col].move(
                                    target_row, target_col, self.grid)

                            self.grid[row][col] = None

                    if not valid_move:
                        print("Invalid target.")
                    else:
                        self.canvas.Clear()
                        self.light_checker_town(self.canvas)
                        self.canvas = self.matrix.SwapOnVSync(self.canvas)

    def light_targets(self, piece):
        r = piece.team.r
        g = piece.team.g
        b = piece.team.b
        targets = piece.get_targets()
        for cell in targets:
            self.light_cell(self.canvas, cell.row, cell.col, r, g, b)

    def initialize_game_board(self):
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
        self.grid[6][1] = Pawn(6, 1, self.team_r)
        self.grid[6][1].direction = 1
        self.grid[6][1].starting_row = 1
        self.grid[0][5] = King(0, 5, self.team_r)
        self.grid[0][5].touched = True

        self.grid[7][0] = Rook(7, 0, self.team_l)
        self.grid[6][4] = King(6, 4, self.team_l)
        self.grid[6][4].touched = True

    def initialize_game_board6(self):
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
        for i in range(4):
            for j in range(4):
                canvas.SetPixel(x * 4 + i, y * 4 + j, r, g, b)

    def print_board_states(self, grid=None):
        if grid is None:
            grid = self.grid
        for r in range(8):
            print(grid[r])

    def computer_move(self, team, depth=2):
        if self.check_fifty_move_rule(team, self.grid):
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
                        piece.filter_to_king_escape(self.grid[king_row][king_col])
                    if len(piece.get_targets()) > 0 and piece.team == team:
                        pieces_with_moves += 1

        if pieces_with_moves == 0:
            if not check:
                self.game_over = True
                self.declare_stalemate()
                return
            elif check:
                self.game_over = True
                self.declare_victory(team)
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
        self.detect_mismatch()
        self.light_checker_town(self.canvas)
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

        if self.grid[best_move.new_cell.row][best_move.new_cell.col] is None:
            self.peace_time += 1
            while state == 0:
                self.master.read_data()
                self.canvas.Clear()
                self.light_checker_town(self.canvas)
                self.light_cell(self.canvas, best_move.old_cell.row, best_move.old_cell.col,
                                team.r, team.g, team.b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                state = self.master.get_cell_state(best_move.old_cell.row, best_move.old_cell.col)
            while state == 1:
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
            while state == 0:
                self.master.read_data()
                self.canvas.Clear()
                self.light_checker_town(self.canvas)
                self.light_cell(self.canvas, best_move.old_cell.row, best_move.old_cell.col,
                                team.r, team.g, team.b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                state = self.master.get_cell_state(best_move.old_cell.row, best_move.old_cell.col)
            state = 0
            while state == 0:
                self.master.read_data()
                self.canvas.Clear()
                self.light_checker_town(self.canvas)
                self.light_cell(self.canvas, best_move.new_cell.row, best_move.new_cell.col,
                                team.r, team.g, team.b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                state = self.master.get_cell_state(best_move.new_cell.row, best_move.new_cell.col)
            time.sleep(.1)
            while state == 1:
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

        if isinstance(self.grid[best_move.new_cell.row][best_move.new_cell.col], Pawn):
            self.peace_time = 0
            enemy = self.grid[best_move.new_cell.row][best_move.new_cell.col].move(
                best_move.new_cell.row, best_move.new_cell.col, self.grid)
            if enemy is not None:
                self.grid[enemy.row][enemy.col] = None
                state = self.master.get_cell_state(enemy.row, enemy.col)
                while state == 0:
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

        elif isinstance(self.grid[best_move.new_cell.row][best_move.new_cell.col], King):
            rook_location, rook_target = self.grid[best_move.new_cell.row][best_move.new_cell.col].move(
                best_move.new_cell.row, best_move.new_cell.col, self.grid)
            if rook_location is not None:
                self.grid[rook_target.row][rook_target.col] = (
                    self.grid[rook_location.row][rook_location.col])
                self.grid[rook_location.row][rook_location.col] = None
                self.grid[rook_target.row][rook_target.col].move(
                    rook_target.row, rook_target.col, self.grid)
        else:
            self.grid[best_move.new_cell.row][best_move.new_cell.col].move(
                best_move.new_cell.row, best_move.new_cell.col, self.grid)

        self.grid[best_move.old_cell.row][best_move.old_cell.col] = None

        self.canvas.Clear()
        self.light_checker_town(self.canvas)
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

    def draw_board(self, board_state):
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
                if self.master.get_cell_state(2, i) == 0:
                    team1_found = True
                    self.team_r.r = self.team_array[i].r
                    self.team_r.g = self.team_array[i].g
                    self.team_r.b = self.team_array[i].b
                if self.master.get_cell_state(5, i) == 0:
                    team2_found = True
                    self.team_l.r = self.team_array[i].r
                    self.team_l.g = self.team_array[i].g
                    self.team_l.b = self.team_array[i].b
            for i in range(8):
                if self.master.get_cell_state(3, i) == 0:
                    shut_down_key1 = True
                    if i == 7:
                        restart_key1 = True
                if self.master.get_cell_state(4, i) == 0:
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
                    if self.master.get_cell_state(2, i) == 0:
                        self.light_cell(self.canvas, 2, i,
                                        self.team_array[i].r, self.team_array[i].g, self.team_array[i].b)
                    if self.master.get_cell_state(5, i) == 0:
                        self.light_cell(self.canvas, 5, i,
                                        self.team_array[i].r, self.team_array[i].g, self.team_array[i].b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                time.sleep(2)
            elif team1_found:
                for i in range(8):
                    if self.master.get_cell_state(2, i) == 0:
                        self.light_cell(self.canvas, 2, i,
                                        self.team_array[i].r, self.team_array[i].g, self.team_array[i].b)
                for i in range(8):
                    self.light_cell(self.canvas, 5, i,
                                    self.team_array[i].r, self.team_array[i].g, self.team_array[i].b)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
            elif team2_found:
                for i in range(8):
                    if self.master.get_cell_state(5, i) == 0:
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
                    if self.master.get_cell_state(3, i) == 0 and not team1_decided:
                        team1_decided = True
                        self.computer_player_r = False
                    if self.master.get_cell_state(4, i) == 0 and not team2_decided:
                        team2_decided = True
                        self.computer_player_l = True
                else:
                    if self.master.get_cell_state(3, i) == 0 and not team1_decided:
                        team1_decided = True
                        self.computer_player_r = True
                    if self.master.get_cell_state(4, i) == 0 and not team2_decided:
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
        if depth == 0:
            return
        team_king = None
        check = False
        for piece in self.get_team_pieces(team, current_node.board_state):
            if isinstance(piece, King):
                team_king = piece
                check = team_king.calc_targets(current_node.board_state)
                if check:
                    print("KING IS IN CHECK")

        for piece in self.get_team_pieces(team, current_node.board_state):
            piece.calc_targets(current_node.board_state)
            if check and not isinstance(piece, King):
                piece.filter_to_king_escape(team_king)
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

    def check_fifty_move_rule(self, team, board_state):
        logger.debug("peace_time=%s", self.peace_time)
        if self.peace_time >= 50:
            self.game_over = True
            self.declare_stalemate()
            return True
        else:
            if team == self.team_l:
                return self.check_threefold_repetition(
                    team, board_state,
                    self.days_left_since_injury, self.double_left_jeopardy)
            else:
                return self.check_threefold_repetition(
                    team, board_state,
                    self.days_right_since_injury, self.double_right_jeopardy)

    def check_threefold_repetition(self, team, board_state, days_since_injury, double_jeopardy):
        if self.peace_time == 0:
            days_since_injury.clear()
            double_jeopardy.clear()
            days_since_injury.append(copy.deepcopy(board_state))
        else:
            second_match = False
            for state in double_jeopardy:
                second_match = True
                for row in range(8):
                    for col in range(8):
                        if not type(state[row][col]) is type(board_state[row][col]):
                            second_match = False
                            break
                    if not second_match:
                        break
                if second_match:
                    break
            if second_match:
                self.game_over = True
                self.declare_stalemate()
                return True
            else:
                first_match = False
                for state in days_since_injury:
                    first_match = True
                    for row in range(8):
                        for col in range(8):
                            if not type(state[row][col]) is type(board_state[row][col]):
                                first_match = False
                                break
                        if not first_match:
                            break
                    if first_match:
                        break
                if first_match:
                    double_jeopardy.append(copy.deepcopy(board_state))
                else:
                    days_since_injury.append(copy.deepcopy(board_state))
        return False
