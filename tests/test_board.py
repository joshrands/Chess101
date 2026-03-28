"""
test_board.py — tests for Board with hardware mocked.

Hardware is mocked via conftest.py sys.modules stubs.  The board_instance
fixture (also from conftest.py) provides a Board with canvas and matrix
replaced by MagicMocks.

Tests focus on:
  - __init__ defaults
  - initialize_game_board() piece placement
  - get_team_pieces() including the red-channel-only bug
  - peace_time / check_fifty_move_rule (50-move rule, including half-move threshold bug)
  - check_threefold_repetition (threefold repetition, including type-only comparison bug)
  - light_cell() pixel coordinates
  - add_nodes() tree depth behavior
  - light_checker_town() colour parameter (from origin/master)
  - choose_light_checker_town() brightness-scaled colour (from origin/master)
  - run(skip_setup, init_num) quick-start flags (from origin/master)
  - detect_mismatch() red bg + yellow pieces + both teams (from origin/master)
"""
import copy
import pytest
from unittest.mock import MagicMock, patch

from Team import Team
from Cell import Cell
from Rook import Rook
from Bishop import Bishop
from Knight import Knight
from Pawn import Pawn
from Queen import Queen
from King import King
from Tree import Tree


# ─────────────────────────────────────────────────────────────────────────────
# Board.__init__ defaults
# ─────────────────────────────────────────────────────────────────────────────

class TestBoardInit:
    def test_default_teamR(self, board_instance):
        b = board_instance
        assert b.team_r.r == 64
        assert b.team_r.g == 180
        assert b.team_r.b == 232

    def test_default_teamL(self, board_instance):
        b = board_instance
        assert b.team_l.r == 255
        assert b.team_l.g == 140
        assert b.team_l.b == 0

    def test_grid_is_8x8(self, board_instance):
        b = board_instance
        assert len(b.grid) == 8
        assert all(len(row) == 8 for row in b.grid)

    def test_grid_starts_all_none(self, board_instance):
        b = board_instance
        assert all(cell is None for row in b.grid for cell in row)

    def test_peace_time_starts_zero(self, board_instance):
        assert board_instance.peace_time == 0

    def test_game_over_starts_false(self, board_instance):
        assert board_instance.game_over is False

    def test_computer_player_flags_false(self, board_instance):
        b = board_instance
        assert b.computer_player_r is False
        assert b.computer_player_l is False


# ─────────────────────────────────────────────────────────────────────────────
# initialize_game_board()
# ─────────────────────────────────────────────────────────────────────────────

class TestInitializeGameBoard:
    def test_teamR_pawns_at_row1(self, board_instance):
        b = board_instance
        b.initialize_game_board()
        for col in range(8):
            assert isinstance(b.grid[1][col], Pawn)
            assert b.grid[1][col].team is b.team_r

    def test_teamL_pawns_at_row6(self, board_instance):
        b = board_instance
        b.initialize_game_board()
        for col in range(8):
            assert isinstance(b.grid[6][col], Pawn)
            assert b.grid[6][col].team is b.team_l

    def test_teamR_back_rank_row0(self, board_instance):
        b = board_instance
        b.initialize_game_board()
        expected = [Rook, Knight, Bishop, Queen, King, Bishop, Knight, Rook]
        for col, piece_type in enumerate(expected):
            assert isinstance(b.grid[0][col], piece_type), (
                f"col {col}: expected {piece_type.__name__}, "
                f"got {type(b.grid[0][col]).__name__}"
            )

    def test_teamL_back_rank_row7(self, board_instance):
        b = board_instance
        b.initialize_game_board()
        expected = [Rook, Knight, Bishop, Queen, King, Bishop, Knight, Rook]
        for col, piece_type in enumerate(expected):
            assert isinstance(b.grid[7][col], piece_type)
            assert b.grid[7][col].team is b.team_l

    def test_middle_rows_are_empty(self, board_instance):
        b = board_instance
        b.initialize_game_board()
        for row in range(2, 6):
            for col in range(8):
                assert b.grid[row][col] is None, f"Expected None at ({row},{col})"

    def test_teamR_back_rank_team_is_teamR(self, board_instance):
        b = board_instance
        b.initialize_game_board()
        for col in range(8):
            assert b.grid[0][col].team is b.team_r


# ─────────────────────────────────────────────────────────────────────────────
# get_team_pieces()
# ─────────────────────────────────────────────────────────────────────────────

class TestGetTeamPieces:
    def test_returns_correct_team_pieces(self, board_instance):
        b = board_instance
        b.initialize_game_board()
        pieces = b.get_team_pieces(b.team_r)
        assert len(pieces) == 16
        assert all(p.team is b.team_r for p in pieces)

    def test_excludes_other_team(self, board_instance):
        b = board_instance
        b.initialize_game_board()
        pieces = b.get_team_pieces(b.team_r)
        assert all(p.team is not b.team_l for p in pieces)

    def test_red_channel_only_comparison_bug(self, board_instance):
        # BUG #8 LOCK-IN: get_team_pieces uses piece.team.r == team.r only.
        # A piece with the same red channel but different g/b is included.
        b = board_instance
        impostor_team = Team(b.team_r.r, 0, 0)   # same r, different g/b
        impostor_rook = Rook(3, 3, impostor_team)
        b.grid[3][3] = impostor_rook
        pieces = b.get_team_pieces(b.team_r)
        # Impostor is included because impostor_team.r == team_r.r
        assert impostor_rook in pieces

    def test_custom_grid_is_used_when_provided(self, board_instance):
        b = board_instance
        custom_grid = [[None] * 8 for _ in range(8)]
        custom_grid[0][0] = Rook(0, 0, b.team_r)
        pieces = b.get_team_pieces(b.team_r, custom_grid)
        assert len(pieces) == 1

    def test_default_grid_is_self_grid(self, board_instance):
        b = board_instance
        b.grid[0][0] = Rook(0, 0, b.team_r)
        pieces = b.get_team_pieces(b.team_r)
        assert any(p is b.grid[0][0] for p in pieces)


# ─────────────────────────────────────────────────────────────────────────────
# peace_time / check_fifty_move_rule (50-move rule)
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckFiftyMoveRule:
    def test_does_not_trigger_at_49(self, board_instance):
        b = board_instance
        b.peace_time = 49
        with patch.object(b, 'stale_mate'):
            result = b.bob_ross(b.team_r, b.grid)
        assert result is False
        assert b.game_over is False

    def test_triggers_at_50_half_moves(self, board_instance):
        # BUG #4 LOCK-IN: threshold is 50 HALF-moves (not 100).
        # Real chess 50-move rule uses 50 full moves (= 100 half-moves).
        b = board_instance
        b.peace_time = 50
        with patch.object(b, 'stale_mate') as mock_stale:
            result = b.bob_ross(b.team_r, b.grid)
        assert result is True
        assert b.game_over is True
        mock_stale.assert_called_once()

    def test_triggers_at_above_50(self, board_instance):
        b = board_instance
        b.peace_time = 99
        with patch.object(b, 'stale_mate'):
            result = b.bob_ross(b.team_r, b.grid)
        assert result is True


# ─────────────────────────────────────────────────────────────────────────────
# check_threefold_repetition
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckThreefoldRepetition:
    def _call(self, board_instance, team, tron, days, double):
        """Direct call to check_threefold_repetition, patching declare_stalemate to avoid infinite loop."""
        b = board_instance
        with patch.object(b, 'stale_mate'):
            return b.check_threefold_repetition(team, tron, days, double)

    def test_new_state_returns_false(self, board_instance):
        b = board_instance
        days = []
        double = []
        b.peace_time = 1  # non-zero so we go into the else branch
        result = self._call(b, b.team_r, b.grid, days, double)
        assert result is False
        assert len(days) == 1  # state added to singles

    def test_peace_time_zero_clears_history(self, board_instance):
        b = board_instance
        days = [copy.deepcopy(b.grid)]
        double = [copy.deepcopy(b.grid)]
        b.peace_time = 0
        self._call(b, b.team_r, b.grid, days, double)
        # History cleared, then current state added
        assert len(double) == 0
        assert len(days) == 1

    def test_first_repeat_moves_to_double_jeopardy(self, board_instance):
        b = board_instance
        # Start with one state already in singles
        b.peace_time = 1
        snapshot = copy.deepcopy(b.grid)
        days = [snapshot]
        double = []
        # Call with the SAME board state → first match
        result = self._call(b, b.team_r, b.grid, days, double)
        assert result is False
        assert len(double) == 1

    def test_second_repeat_triggers_stalemate(self, board_instance):
        b = board_instance
        b.peace_time = 1
        snapshot = copy.deepcopy(b.grid)
        # Put current state in doubleJeopardy already
        days = [snapshot]
        double = [snapshot]
        with patch.object(b, 'stale_mate') as mock_stale:
            result = b.check_threefold_repetition(b.team_r, b.grid, days, double)
        assert result is True
        assert b.game_over is True
        mock_stale.assert_called_once()

    def test_uses_type_not_team_for_comparison(self, board_instance):
        # BUG #6 LOCK-IN: comparison is `type(state[r][c]) is type(tron[r][c])`.
        # A Pawn of team_r and a Pawn of team_l at the same square are considered
        # identical because type(Pawn) is type(Pawn).
        b = board_instance
        b.peace_time = 1

        # Build snapshot: team_r pawn at (3,3)
        snapshot = [[None] * 8 for _ in range(8)]
        snapshot[3][3] = Pawn(3, 3, b.team_r)

        # Current board: team_l pawn at (3,3) — DIFFERENT team, same type
        current = [[None] * 8 for _ in range(8)]
        current[3][3] = Pawn(3, 3, b.team_l)

        days = [snapshot]
        double = []
        # check_threefold_repetition should (incorrectly) see these as matching states
        result = self._call(b, b.team_r, current, days, double)
        # Incorrectly treated as a first match → moved to doubleJeopardy
        assert len(double) == 1

    def test_different_piece_types_no_match(self, board_instance):
        b = board_instance
        b.peace_time = 1

        snapshot = [[None] * 8 for _ in range(8)]
        snapshot[3][3] = Rook(3, 3, b.team_r)

        current = [[None] * 8 for _ in range(8)]
        current[3][3] = Pawn(3, 3, b.team_r)  # different type

        days = [snapshot]
        double = []
        result = self._call(b, b.team_r, current, days, double)
        assert result is False
        assert len(double) == 0
        assert len(days) == 2  # new distinct state added

    def test_double_jeopardy_mismatch_does_not_trigger(self, board_instance):
        # double_jeopardy has one state that does NOT match the current board.
        # This covers lines 99-100 (second_match=False; break inner col loop)
        # and line 102 (break outer row loop) in game/rules.py.
        b = board_instance
        b.peace_time = 1

        # double_jeopardy state has a rook at (3,3)
        mismatch_state = [[None] * 8 for _ in range(8)]
        mismatch_state[3][3] = Rook(3, 3, b.team_r)

        # current board is entirely empty — no match
        current = [[None] * 8 for _ in range(8)]

        days = []
        double = [mismatch_state]
        result = self._call(b, b.team_r, current, days, double)
        assert result is False
        # mismatch in double → falls through to first_match check → added to days
        assert len(days) == 1


# ─────────────────────────────────────────────────────────────────────────────
# light_cell()
# ─────────────────────────────────────────────────────────────────────────────

class TestLightCell:
    def test_calls_set_pixel_exactly_16_times(self, board_instance):
        b = board_instance
        canvas = MagicMock()
        b.light_cell(canvas, 2, 3, 255, 0, 128)
        assert canvas.SetPixel.call_count == 16

    def test_correct_pixel_coordinates(self, board_instance):
        b = board_instance
        canvas = MagicMock()
        b.light_cell(canvas, 2, 3, 255, 0, 128)
        calls = canvas.SetPixel.call_args_list
        pixel_coords = [(args[0], args[1]) for args, _ in calls]
        expected = [
            (2 * 4 + i, 3 * 4 + j)
            for i in range(4)
            for j in range(4)
        ]
        assert sorted(pixel_coords) == sorted(expected)

    def test_passes_rgb_values_correctly(self, board_instance):
        b = board_instance
        canvas = MagicMock()
        b.light_cell(canvas, 0, 0, 10, 20, 30)
        for call in canvas.SetPixel.call_args_list:
            args, _ = call
            assert args[2] == 10
            assert args[3] == 20
            assert args[4] == 30


# ─────────────────────────────────────────────────────────────────────────────
# add_nodes() — AI tree construction
# ─────────────────────────────────────────────────────────────────────────────

class TestAddNodes:
    def test_depth0_adds_no_children(self, board_instance):
        b = board_instance
        b.initialize_game_board()
        root = Tree(copy.deepcopy(b.grid), None, None, b.team_r, b.team_l)
        b.add_nodes(root, b.team_r, 0)
        assert len(root.children) == 0

    def test_depth1_adds_children_for_each_legal_move(self, board_instance):
        b = board_instance
        # Simple board: just one team_r rook that can move in two directions
        b.grid = [[None] * 8 for _ in range(8)]
        rook = Rook(4, 4, b.team_r)
        b.grid[4][4] = rook
        root = Tree(copy.deepcopy(b.grid), None, None, b.team_r, b.team_l)
        b.add_nodes(root, b.team_r, 1)
        # Rook at (4,4) on otherwise empty board has 14 targets
        assert len(root.children) == 14

    def test_depth2_adds_grandchildren(self, board_instance):
        b = board_instance
        b.grid = [[None] * 8 for _ in range(8)]
        rook_r = Rook(0, 0, b.team_r)
        rook_l = Rook(7, 7, b.team_l)
        b.grid[0][0] = rook_r
        b.grid[7][7] = rook_l
        root = Tree(copy.deepcopy(b.grid), None, None, b.team_r, b.team_l)
        b.add_nodes(root, b.team_r, 2)
        # Root children represent team_r moves; each child has children for team_l
        assert len(root.children) > 0
        # At least one child should have grandchildren
        assert any(len(child.children) > 0 for child in root.children)

    def test_depth1_each_child_has_old_and_new_cell(self, board_instance):
        b = board_instance
        b.grid = [[None] * 8 for _ in range(8)]
        b.grid[4][4] = Rook(4, 4, b.team_r)
        root = Tree(copy.deepcopy(b.grid), None, None, b.team_r, b.team_l)
        b.add_nodes(root, b.team_r, 1)
        for child in root.children:
            assert child.old_cell is not None
            assert child.new_cell is not None
            # Old cell must be the rook's original position
            assert child.old_cell.row == 4
            assert child.old_cell.col == 4


# ─────────────────────────────────────────────────────────────────────────────
# light_checker_town(canvas, color) — colour parameter (from origin/master)
# ─────────────────────────────────────────────────────────────────────────────

class TestLightCheckerTown:
    def test_default_color_is_white(self, board_instance):
        b = board_instance
        canvas = MagicMock()
        b.light_checker_town(canvas)
        for call in canvas.SetPixel.call_args_list:
            args, _ = call
            assert args[2] == 255  # r
            assert args[3] == 255  # g
            assert args[4] == 255  # b

    def test_custom_color_is_passed_through(self, board_instance):
        b = board_instance
        canvas = MagicMock()
        b.light_checker_town(canvas, color=(255, 0, 0))
        for call in canvas.SetPixel.call_args_list:
            args, _ = call
            assert args[2] == 255  # r
            assert args[3] == 0    # g
            assert args[4] == 0    # b

    def test_lights_exactly_32_cells(self, board_instance):
        # 16 odd-row/even-col dark squares + 16 even-row/odd-col dark squares
        b = board_instance
        canvas = MagicMock()
        b.light_checker_town(canvas)
        # Each cell = 4×4 pixels = 16 SetPixel calls; 32 cells = 512 total
        assert canvas.SetPixel.call_count == 32 * 16

    def test_only_dark_squares_are_lit(self, board_instance):
        # Dark squares: (row%2==1, col%2==0) and (row%2==0, col%2==1)
        b = board_instance
        canvas = MagicMock()
        b.light_checker_town(canvas)
        lit_cells: set[tuple[int, int]] = set()
        for call in canvas.SetPixel.call_args_list:
            args, _ = call
            row = args[0] // 4
            col = args[1] // 4
            lit_cells.add((row, col))
        for row, col in lit_cells:
            assert (row % 2) != (col % 2), (
                f"Light square ({row},{col}) should not be lit"
            )


# ─────────────────────────────────────────────────────────────────────────────
# choose_light_checker_town(color) — brightness scaling (from origin/master)
# ─────────────────────────────────────────────────────────────────────────────

class TestChooseLightCheckerTown:
    def test_default_uses_brightness_for_white(self, board_instance):
        b = board_instance
        b.checker_brightness = 128
        with patch.object(b, 'light_checker_town') as mock_lct:
            b.choose_light_checker_town()
        mock_lct.assert_called_once()
        _, kwargs = mock_lct.call_args
        r, g, bl = kwargs['color']
        assert r == g == bl  # grey (scaled white)
        assert r == int(255 * (128 / 255))

    def test_custom_color_scaled_by_brightness(self, board_instance):
        b = board_instance
        b.checker_brightness = 128
        with patch.object(b, 'light_checker_town') as mock_lct:
            b.choose_light_checker_town(color=(200, 100, 50))
        _, kwargs = mock_lct.call_args
        r, g, bl = kwargs['color']
        assert r == int(200 * (128 / 255))
        assert g == int(100 * (128 / 255))
        assert bl == int(50 * (128 / 255))

    def test_full_brightness_preserves_color(self, board_instance):
        b = board_instance
        b.checker_brightness = 255
        with patch.object(b, 'light_checker_town') as mock_lct:
            b.choose_light_checker_town(color=(200, 100, 50))
        _, kwargs = mock_lct.call_args
        assert kwargs['color'] == (200, 100, 50)

    def test_zero_brightness_produces_black(self, board_instance):
        b = board_instance
        b.checker_brightness = 0
        with patch.object(b, 'light_checker_town') as mock_lct:
            b.choose_light_checker_town(color=(200, 100, 50))
        _, kwargs = mock_lct.call_args
        assert kwargs['color'] == (0, 0, 0)


# ─────────────────────────────────────────────────────────────────────────────
# run(skip_setup, init_num) — quick-start flags (from origin/master)
# ─────────────────────────────────────────────────────────────────────────────

class TestRunSkipSetup:
    def _patched_run(self, board_instance, **run_kwargs):
        """Call run() with all blocking methods patched; return the mocks."""
        b = board_instance
        b.matrix.CreateFrameCanvas.return_value = MagicMock()
        # Make game_over True after first iteration to exit the while loop
        b.game_over = True
        with patch.object(b, 'color_picker') as cp, \
             patch.object(b, 'war_games') as wg, \
             patch.object(b, 'create_players') as crp, \
             patch.object(b, 'interactive_setup') as isu, \
             patch.object(b, 'initialize_game_board') as igb, \
             patch.object(b, 'initialize_game_board2') as igb2:
            b.run(**run_kwargs)
        return cp, wg, crp, isu, igb, igb2

    def test_skip_setup_false_calls_color_picker(self, board_instance):
        cp, wg, crp, isu, igb, igb2 = self._patched_run(board_instance, skip_setup=False)
        cp.assert_called_once()

    def test_skip_setup_false_calls_interactive_setup_twice(self, board_instance):
        cp, wg, crp, isu, igb, igb2 = self._patched_run(board_instance, skip_setup=False)
        assert isu.call_count == 2

    def test_skip_setup_true_skips_color_picker(self, board_instance):
        cp, wg, crp, isu, igb, igb2 = self._patched_run(board_instance, skip_setup=True)
        cp.assert_not_called()

    def test_skip_setup_true_skips_war_games(self, board_instance):
        cp, wg, crp, isu, igb, igb2 = self._patched_run(board_instance, skip_setup=True)
        wg.assert_not_called()

    def test_skip_setup_true_skips_interactive_setup(self, board_instance):
        cp, wg, crp, isu, igb, igb2 = self._patched_run(board_instance, skip_setup=True)
        isu.assert_not_called()

    def test_init_num_empty_calls_initialize_game_board(self, board_instance):
        cp, wg, crp, isu, igb, igb2 = self._patched_run(board_instance, skip_setup=True, init_num="")
        igb.assert_called_once()
        igb2.assert_not_called()

    def test_init_num_2_calls_initialize_game_board2(self, board_instance):
        cp, wg, crp, isu, igb, igb2 = self._patched_run(board_instance, skip_setup=True, init_num="2")
        igb2.assert_called_once()
        igb.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# detect_mismatch() — red bg + yellow pieces + both teams (from origin/master)
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectMismatch:
    def test_uses_red_background_for_checker_town(self, board_instance):
        b = board_instance
        b.initialize_game_board()
        # master returns 0 (OCCUPIED) so no mismatch — exits immediately
        b.master.get_cell_state.return_value = 0
        with patch.object(b, 'light_checker_town') as mock_lct:
            b.detect_mismatch()
        called_colors = [
            kwargs.get('color') or args[1] if len(args) > 1 else kwargs.get('color')
            for args, kwargs in mock_lct.call_args_list
        ]
        assert (255, 0, 0) in called_colors, "red background never passed to light_checker_town"

    def test_mismatched_piece_lit_yellow(self, board_instance):
        # Make one piece report EMPTY (state==1) on first poll, then OCCUPIED on subsequent
        b = board_instance
        b.initialize_game_board()
        call_count = [0]

        def _side_effect(row, col):
            from core.constants import CellOccupancy
            call_count[0] += 1
            # First few reads: one cell is EMPTY → triggers mismatch
            if call_count[0] <= 2:
                return CellOccupancy.EMPTY.value
            return CellOccupancy.OCCUPIED.value

        b.master.get_cell_state.side_effect = _side_effect
        canvas_mock = MagicMock()
        b.canvas = canvas_mock
        b.matrix.SwapOnVSync.return_value = canvas_mock
        with patch.object(b, 'light_checker_town'):
            b.detect_mismatch()
        # Extract all RGB tuples passed to light_cell via SetPixel
        set_pixel_calls = canvas_mock.SetPixel.call_args_list
        colors_seen = {(args[2], args[3], args[4]) for args, _ in set_pixel_calls}
        assert (255, 255, 0) in colors_seen, "yellow (255,255,0) never used for mismatched piece"

    def test_checks_both_team_r_and_team_l_pieces(self, board_instance):
        b = board_instance
        b.initialize_game_board()
        b.master.get_cell_state.return_value = 0
        with patch.object(b, 'get_team_pieces', wraps=b.get_team_pieces) as mock_gtp:
            b.detect_mismatch()
        teams_queried = [call.args[0] for call in mock_gtp.call_args_list]
        assert b.team_r in teams_queried, "team_r not checked in detect_mismatch"
        assert b.team_l in teams_queried, "team_l not checked in detect_mismatch"

    def test_returns_true_when_no_mismatch(self, board_instance):
        b = board_instance
        b.initialize_game_board()
        b.master.get_cell_state.return_value = 0  # all pieces present
        result = b.detect_mismatch()
        assert result is True
