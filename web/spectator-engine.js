/**
 * Spectator engine — extracted from spectator.html for Node.js testability.
 *
 * This module implements the spectator's independent move-application logic:
 * applyMove (with en passant, castling, promotion flag handling), applyGrid
 * (full board sync), and initStartingPosition.
 *
 * The spectator grid is simplified: each cell is null or {type, team_r}.
 * Unlike the full chess engine, it has no piece behaviour — it just tracks
 * positions based on move messages received from the relay.
 */

"use strict";

// ── Grid state ────────────────────────────────────────────────────────────

/**
 * Create an empty 8×8 grid.
 * @returns {Array<Array<null>>}
 */
function createGrid() {
  return Array.from({ length: 8 }, () => Array(8).fill(null));
}

/**
 * Initialize the standard starting position.
 * Each cell is null | {type: string, team_r: boolean}.
 * @param {Array<Array<null|object>>} grid — mutated in place
 */
function initStartingPosition(grid) {
  // Clear
  for (let r = 0; r < 8; r++)
    for (let c = 0; c < 8; c++) grid[r][c] = null;

  // team_r back rank (row 0)
  const backR = ["Rook", "Knight", "Bishop", "Queen", "King", "Bishop", "Knight", "Rook"];
  for (let c = 0; c < 8; c++) grid[0][c] = { type: backR[c], team_r: true };
  // team_r pawns (row 1)
  for (let c = 0; c < 8; c++) grid[1][c] = { type: "Pawn", team_r: true };
  // team_l pawns (row 6)
  for (let c = 0; c < 8; c++) grid[6][c] = { type: "Pawn", team_r: false };
  // team_l back rank (row 7)
  const backL = ["Rook", "Knight", "Bishop", "Queen", "King", "Bishop", "Knight", "Rook"];
  for (let c = 0; c < 8; c++) grid[7][c] = { type: backL[c], team_r: false };
}

/**
 * Apply a full board state from the protocol's encoded grid.
 * @param {Array<Array<null|object>>} grid — mutated in place
 * @param {Array<Array<null|object>>} encodedGrid — from protocol.encode_grid
 */
function applyGrid(grid, encodedGrid) {
  for (let r = 0; r < 8; r++) {
    for (let c = 0; c < 8; c++) {
      const cell = encodedGrid[r][c];
      if (!cell) { grid[r][c] = null; continue; }
      // Handle both formats: encode_grid ({team:"r"/"l"}) and spectator ({team_r:bool})
      const isR = cell.team_r != null ? cell.team_r : cell.team === "r";
      grid[r][c] = { type: cell.type, team_r: isR };
    }
  }
}

/**
 * Apply a single move to the local grid using move flags.
 *
 * This is the spectator's independent reimplementation of move application.
 * It handles en passant, castling, and promotion using the flags sent in
 * the wire protocol — any divergence from the game engines is a bug.
 *
 * @param {Array<Array<null|object>>} grid — mutated in place
 * @param {number} fr — from row
 * @param {number} fc — from col
 * @param {number} tr — to row
 * @param {number} tc — to col
 * @param {object} flags — move flags from the wire protocol
 */
function applyMove(grid, fr, fc, tr, tc, flags) {
  const piece = grid[fr][fc];
  if (!piece) return;

  grid[tr][tc] = piece;
  grid[fr][fc] = null;

  // En passant: captured pawn is not at tr,tc
  if (flags && flags.is_en_passant && flags.captured_at) {
    const [er, ec] = flags.captured_at;
    grid[er][ec] = null;
  }
  // Castling: move the rook
  if (flags && flags.is_castling && flags.rook_from && flags.rook_to) {
    const [rfr, rfc] = flags.rook_from;
    const [rtr, rtc] = flags.rook_to;
    grid[rtr][rtc] = grid[rfr][rfc];
    grid[rfr][rfc] = null;
  }
  // Promotion
  if (flags && flags.is_promotion) {
    const promoted = flags.promoted_to || "Queen";
    grid[tr][tc] = { type: promoted, team_r: piece.team_r };
  }
}

/**
 * Serialize the spectator grid to a canonical snapshot for comparison.
 * Returns an 8×8 array of null | {type, team_r}.
 * @param {Array<Array<null|object>>} grid
 * @returns {Array<Array<null|{type: string, team_r: boolean}>>}
 */
function gridSnapshot(grid) {
  return grid.map(row =>
    row.map(cell =>
      cell ? { type: cell.type, team_r: cell.team_r } : null
    )
  );
}

// ── Exports ───────────────────────────────────────────────────────────────

if (typeof module !== "undefined") {
  module.exports = {
    createGrid,
    initStartingPosition,
    applyGrid,
    applyMove,
    gridSnapshot,
  };
}
