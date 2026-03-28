/**
 * Node.js bridge for lockstep testing.
 *
 * Reads newline-delimited JSON from stdin, dispatches to the appropriate
 * JS function, and writes a JSON response to stdout.
 *
 * Protocol:
 *   stdin  <- {"op": "decode_frame", "rgba_b64": "...", "w": 320, "h": 240}
 *   stdout -> {"result": "ABCDEF"}  or  {"result": null}  or  {"error": "..."}
 */

"use strict";

const crypto = require("crypto");
const path = require("path");
const scanner = require(path.join(__dirname, "..", "web", "chessmatrix-scanner.js"));
const { decodeFrame } = scanner;
const engine = require(path.join(__dirname, "..", "web", "chess-engine.js"));
const { Cell, Team, Pawn, Rook, Bishop, Knight, Queen, King, deepCopyGrid } = engine;
const spectator = require(path.join(__dirname, "..", "web", "spectator-engine.js"));

// ── helpers ────────────────────────────────────────────────────────────────

function respond(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

// ── chess helpers ─────────────────────────────────────────────────────────

const PIECE_MAP = { Pawn, Rook, Bishop, Knight, Queen, King };

/** Reconstruct an 8×8 grid from the Python-side JSON representation. */
function gridFromJson(data, teamR, teamL) {
  return data.map(row => row.map(cell => {
    if (cell === null) return null;
    const team = cell.team_key === "r" ? teamR : teamL;
    const Cls = PIECE_MAP[cell.type];
    const p = new Cls(cell.row, cell.col, team);
    p.touched = cell.touched;
    if (p instanceof Pawn) {
      p.startingRow = cell.starting_row;
      p.direction = cell.direction;
      p.enPassantable = cell.en_passantable;
      p.enPassantLoc = cell.en_passant_loc
        ? new Cell(cell.en_passant_loc[0], cell.en_passant_loc[1]) : null;
    }
    if (p instanceof King && cell.direction !== undefined) {
      p.direction = cell.direction;
    }
    return p;
  }));
}

/** Compute board_hash identical to Python's network.protocol.board_hash. */
function boardHash(grid, peaceTime, currentTeamKey, teamR) {
  const parts = [];
  for (let r = 0; r < 8; r++) {
    for (let c = 0; c < 8; c++) {
      const p = grid[r][c];
      if (p === null) { parts.push(`${r},${c},-`); continue; }
      const tk = p.team.r === teamR.r ? "r" : "l";
      const touched = p.touched ? "1" : "0";
      let entry = `${r},${c},${p.constructor.name},${tk},${touched}`;
      if (p instanceof Pawn) entry += `,${p.enPassantable ? "1" : "0"}`;
      parts.push(entry);
    }
  }
  parts.push(`peace=${peaceTime}`);
  parts.push(`turn=${currentTeamKey}`);
  return crypto.createHash("sha256").update(parts.join("|")).digest("hex");
}

/** Compute all legal moves for a team. Returns [[fr,fc,tr,tc], ...]. */
function legalMoves(grid, teamR, teamL, teamKey) {
  const team = teamKey === "r" ? teamR : teamL;
  // Clear en_passantable on current team's pawns (window expired, matching Python do_turn)
  for (const row of grid) for (const p of row)
    if (p instanceof Pawn && p.team.r === team.r) p.enPassantable = false;
  const pieces = [];
  let king = null;
  for (const row of grid) for (const p of row)
    if (p && p.team.r === team.r) pieces.push(p);
  for (const p of pieces) if (p instanceof King) king = p;
  const check = king.calcTargets(grid);
  const moves = [];
  // King moves first
  for (const t of king.targets) moves.push([king.row, king.col, t.row, t.col]);
  // Other pieces
  for (const p of pieces) {
    if (p instanceof King) continue;
    p.calcTargets(grid);
    if (check) p.skyFall(king);
    for (const t of p.targets) moves.push([p.row, p.col, t.row, t.col]);
  }
  return moves;
}

/** Apply a move to the grid (mutates). Returns {captured_at, rook_from, rook_to, promoted}. */
function applyMove(grid, fr, fc, tr, tc, teamR, teamL) {
  const piece = grid[fr][fc];
  const captured = grid[tr][tc];
  grid[tr][tc] = piece;
  grid[fr][fc] = null;
  const flags = { captured_at: null, rook_from: null, rook_to: null, promoted: false };
  if (piece instanceof Pawn) {
    const enemy = piece.move(tr, tc, grid);
    if (enemy) { grid[enemy.row][enemy.col] = null; flags.captured_at = [enemy.row, enemy.col]; }
    // auto-promote
    if ((piece.startingRow + 6) % 12 === tr) {
      grid[tr][tc] = new Queen(tr, tc, piece.team);
      grid[tr][tc].touched = true;
      flags.promoted = true;
    }
  } else if (piece instanceof King) {
    const [rl, rt] = piece.move(tr, tc, grid);
    if (rl && rt) {
      grid[rt.row][rt.col] = grid[rl.row][rl.col];
      grid[rl.row][rl.col] = null;
      const rook = grid[rt.row][rt.col];
      if (rook) rook.move(rt.row, rt.col, grid);
      flags.rook_from = [rl.row, rl.col]; flags.rook_to = [rt.row, rt.col];
    }
  } else {
    piece.move(tr, tc, grid);
  }
  if (captured) flags.captured_at = [tr, tc];
  return flags;
}

/** Initialize starting position grid. */
function initBoard(teamR, teamL) {
  const grid = Array.from({length: 8}, () => Array(8).fill(null));
  // team_r back rank (row 0) and pawns (row 1)
  grid[0][0]=new Rook(0,0,teamR);grid[0][1]=new Knight(0,1,teamR);grid[0][2]=new Bishop(0,2,teamR);
  grid[0][3]=new Queen(0,3,teamR);grid[0][4]=new King(0,4,teamR);grid[0][5]=new Bishop(0,5,teamR);
  grid[0][6]=new Knight(0,6,teamR);grid[0][7]=new Rook(0,7,teamR);
  for(let c=0;c<8;c++)grid[1][c]=new Pawn(1,c,teamR);
  // team_l pawns (row 6) and back rank (row 7)
  for(let c=0;c<8;c++)grid[6][c]=new Pawn(6,c,teamL);
  grid[7][0]=new Rook(7,0,teamL);grid[7][1]=new Knight(7,1,teamL);grid[7][2]=new Bishop(7,2,teamL);
  grid[7][3]=new Queen(7,3,teamL);grid[7][4]=new King(7,4,teamL);grid[7][5]=new Bishop(7,5,teamL);
  grid[7][6]=new Knight(7,6,teamL);grid[7][7]=new Rook(7,7,teamL);
  return grid;
}

/** Serialize grid for sending back to Python. */
function gridToJson(grid, teamR) {
  return grid.map(row => row.map(p => {
    if (p === null) return null;
    const obj = {
      type: p.constructor.name,
      row: p.row, col: p.col,
      team_key: p.team.r === teamR.r ? "r" : "l",
      touched: p.touched,
    };
    if (p instanceof Pawn) {
      obj.starting_row = p.startingRow;
      obj.direction = p.direction;
      obj.en_passantable = p.enPassantable;
      obj.en_passant_loc = p.enPassantLoc ? [p.enPassantLoc.row, p.enPassantLoc.col] : null;
    }
    if (p instanceof King) {
      obj.direction = p.direction;
    }
    return obj;
  }));
}

// ── op handlers ──────────────────────────────────────────────���─────────────

const OPS = {
  decode_frame(msg) {
    const rgba = Buffer.from(msg.rgba_b64, "base64");
    const result = decodeFrame(new Uint8Array(rgba), msg.w, msg.h);
    respond({ result: result || null });
  },

  chess_init(msg) {
    const teamR = new Team(msg.team_r[0], msg.team_r[1], msg.team_r[2]);
    const teamL = new Team(msg.team_l[0], msg.team_l[1], msg.team_l[2]);
    const grid = initBoard(teamR, teamL);
    respond({ result: { grid: gridToJson(grid, teamR) } });
  },

  chess_legal_moves(msg) {
    const teamR = new Team(msg.team_r[0], msg.team_r[1], msg.team_r[2]);
    const teamL = new Team(msg.team_l[0], msg.team_l[1], msg.team_l[2]);
    const grid = gridFromJson(msg.grid, teamR, teamL);
    const moves = legalMoves(grid, teamR, teamL, msg.active_team_key);
    respond({ result: moves });
  },

  chess_apply_move(msg) {
    const teamR = new Team(msg.team_r[0], msg.team_r[1], msg.team_r[2]);
    const teamL = new Team(msg.team_l[0], msg.team_l[1], msg.team_l[2]);
    const grid = gridFromJson(msg.grid, teamR, teamL);
    // Clear en_passantable on the active team before applying (matches Python do_turn)
    const activeTeam = msg.active_team_key === "r" ? teamR : teamL;
    for (const row of grid) for (const p of row)
      if (p instanceof Pawn && p.team.r === activeTeam.r) p.enPassantable = false;
    const flags = applyMove(grid, msg.fr, msg.fc, msg.tr, msg.tc, teamR, teamL);
    const hash = boardHash(grid, msg.peace_time, msg.next_team_key, teamR);
    // Detect check/checkmate/stalemate for the next team
    const nextTeamKey = msg.next_team_key;
    const nextTeam = nextTeamKey === "r" ? teamR : teamL;
    const pieces2 = [];
    let king2 = null;
    for (const row of grid) for (const p of row)
      if (p && p.team.r === nextTeam.r) pieces2.push(p);
    for (const p of pieces2) if (p instanceof King) king2 = p;
    const check2 = king2.calcTargets(grid);
    let totalMoves = king2.targets.length;
    for (const p of pieces2) {
      if (p instanceof King) continue;
      p.calcTargets(grid);
      if (check2) p.skyFall(king2);
      totalMoves += p.targets.length;
    }
    let status = "playing";
    if (totalMoves === 0) status = check2 ? "checkmate" : "stalemate";
    else if (check2) status = "check";
    respond({
      result: {
        grid: gridToJson(grid, teamR),
        board_hash: hash,
        status,
        flags,
      },
    });
  },

  chess_board_hash(msg) {
    const teamR = new Team(msg.team_r[0], msg.team_r[1], msg.team_r[2]);
    const teamL = new Team(msg.team_l[0], msg.team_l[1], msg.team_l[2]);
    const grid = gridFromJson(msg.grid, teamR, teamL);
    const hash = boardHash(grid, msg.peace_time, msg.current_team_key, teamR);
    respond({ result: hash });
  },

  // ── spectator ops ──────────────────────────────────────────────────────

  spectator_init() {
    const grid = spectator.createGrid();
    spectator.initStartingPosition(grid);
    respond({ result: spectator.gridSnapshot(grid) });
  },

  spectator_apply_move(msg) {
    // Reconstruct grid from snapshot
    const grid = msg.grid.map(row => row.map(c => c ? { type: c.type, team_r: c.team_r } : null));
    spectator.applyMove(grid, msg.fr, msg.fc, msg.tr, msg.tc, msg.flags || {});
    respond({ result: spectator.gridSnapshot(grid) });
  },

  spectator_apply_grid(msg) {
    const grid = spectator.createGrid();
    spectator.applyGrid(grid, msg.encoded_grid);
    respond({ result: spectator.gridSnapshot(grid) });
  },

  ping() {
    respond({ result: "pong" });
  },
};

// ── main loop ──────────────────────────────────────────────────────────────

let buf = "";

process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  buf += chunk;
  let nl;
  while ((nl = buf.indexOf("\n")) !== -1) {
    const line = buf.slice(0, nl).trim();
    buf = buf.slice(nl + 1);
    if (!line) continue;
    let msg;
    try {
      msg = JSON.parse(line);
    } catch (e) {
      respond({ error: `JSON parse error: ${e.message}` });
      continue;
    }
    const handler = OPS[msg.op];
    if (!handler) {
      respond({ error: `Unknown op: ${msg.op}` });
      continue;
    }
    try {
      handler(msg);
    } catch (e) {
      respond({ error: `${msg.op} threw: ${e.message}` });
    }
  }
});

process.stdin.on("end", () => process.exit(0));
