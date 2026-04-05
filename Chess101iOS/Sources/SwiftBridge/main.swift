/**
 SwiftBridge — stdin/stdout JSON bridge for Chess101 lockstep testing.

 Reads newline-delimited JSON from stdin, dispatches to the chess engine,
 and writes a JSON response to stdout.  Protocol matches js_bridge.js exactly:

   stdin  <- {"op": "chess_legal_moves", "grid": [...], "team_r": [...], ...}
   stdout -> {"result": [[fr,fc,tr,tc], ...]}
             {"error": "..."}

 Supported ops: ping, chess_init, chess_legal_moves, chess_apply_move,
                chess_board_hash
 */

import Foundation
import Chess101Engine

// MARK: - stdout helpers

func respond(_ obj: [String: Any]) {
    let data = try! JSONSerialization.data(withJSONObject: obj)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([0x0a]))  // newline
}

func respondResult(_ val: Any) { respond(["result": val]) }
func respondError(_ msg: String) { respond(["error": msg]) }

// MARK: - Grid JSON ↔ Board  (8×8 array format matching js_bridge.js)

/// Build a Board from the 8×8 JSON grid used by the Python fuzzer / JS bridge.
func boardFromJSON(_ grid: [[Any?]], teamR: Team, teamL: Team) -> Board {
    let board = Board(teamR: teamR, teamL: teamL)
    for r in 0..<8 {
        for c in 0..<8 {
            guard r < grid.count, c < grid[r].count,
                  let cell = grid[r][c] as? [String: Any] else { continue }
            guard let type = cell["type"] as? String,
                  let teamKey = cell["team_key"] as? String else { continue }
            let team = teamKey == "r" ? teamR : teamL
            let touched = cell["touched"] as? Bool ?? false
            let piece: Piece
            switch type {
            case "Pawn":
                let p = Pawn(row: r, col: c, team: team)
                p.touched = touched
                p.direction    = cell["direction"] as? Int ?? (r <= 3 ? 1 : -1)
                p.startingRow  = cell["starting_row"] as? Int ?? r
                p.enPassantable = cell["en_passantable"] as? Bool ?? false
                if let loc = cell["en_passant_loc"] as? [Int], loc.count == 2 {
                    p.enPassantLoc = Cell(loc[0], loc[1])
                }
                piece = p
            case "Rook":
                let p = Rook(row: r, col: c, team: team); p.touched = touched; piece = p
            case "Bishop":
                let p = Bishop(row: r, col: c, team: team); p.touched = touched; piece = p
            case "Knight":
                let p = Knight(row: r, col: c, team: team); p.touched = touched; piece = p
            case "Queen":
                let p = Queen(row: r, col: c, team: team); p.touched = touched; piece = p
            case "King":
                let p = King(row: r, col: c, team: team); p.touched = touched; piece = p
            default: continue
            }
            board.grid[r][c] = piece
        }
    }
    return board
}

/// Serialise a Board to the 8×8 JSON grid format.
func boardToJSON(_ board: Board) -> [[Any?]] {
    (0..<8).map { r in
        (0..<8).map { c -> Any? in
            guard let p = board.grid[r][c] else { return NSNull() }
            let tk = p.team == board.teamR ? "r" : "l"
            var obj: [String: Any] = [
                "type": p.typeName,
                "row": r, "col": c,
                "team_key": tk,
                "touched": p.touched,
            ]
            if let pw = p as? Pawn {
                obj["direction"]      = pw.direction
                obj["starting_row"]   = pw.startingRow
                obj["en_passantable"] = pw.enPassantable
                if let loc = pw.enPassantLoc {
                    obj["en_passant_loc"] = [loc.row, loc.col]
                } else {
                    obj["en_passant_loc"] = NSNull()
                }
            }
            if let k = p as? King {
                obj["direction"] = k.row == 0 ? 1 : -1
            }
            return obj
        }
    }
}

// MARK: - Legal moves

/// Clear en_passantable for the active team (window expired — matches Python/JS).
func clearEnPassant(board: Board, team: Team) {
    for r in 0..<8 {
        for c in 0..<8 {
            if let pw = board.grid[r][c] as? Pawn, pw.team == team {
                pw.enPassantable = false
            }
        }
    }
}

/// Compute all legal moves for `team`.  Returns [[fr, fc, tr, tc], ...].
func legalMoves(board: Board, team: Team) -> [[Int]] {
    var king: King? = nil
    var check = false
    for p in board.pieces(for: team) {
        if let k = p as? King { king = k; check = (k.calcTargets(board: board) == true) }
    }
    guard let king else { return [] }
    var moves: [[Int]] = []
    for t in king.targets { moves.append([king.row, king.col, t.row, t.col]) }
    for p in board.pieces(for: team) {
        guard !(p is King) else { continue }
        p.calcTargets(board: board)
        if p.critical { p.criticalMan() }
        if check { p.skyFall(king: king) }
        for t in p.targets { moves.append([p.row, p.col, t.row, t.col]) }
    }
    return moves
}

/// Compute game status for `nextTeam` after a move has been applied.
func gameStatus(board: Board, nextTeam: Team) -> String {
    var king: King? = nil
    var check = false
    for p in board.pieces(for: nextTeam) {
        if let k = p as? King { king = k; check = (k.calcTargets(board: board) == true) }
    }
    guard let king else { return "playing" }
    var totalMoves = king.targets.count
    for p in board.pieces(for: nextTeam) {
        guard !(p is King) else { continue }
        p.calcTargets(board: board)
        if check { p.skyFall(king: king) }
        totalMoves += p.targets.count
    }
    if totalMoves == 0 { return check ? "checkmate" : "stalemate" }
    return check ? "check" : "playing"
}

// MARK: - Op handlers

func handlePing() { respondResult("pong") }

func handleChessInit(_ msg: [String: Any]) {
    guard let tr = msg["team_r"] as? [Int], tr.count == 3,
          let tl = msg["team_l"] as? [Int], tl.count == 3 else {
        return respondError("chess_init: missing team_r/team_l")
    }
    let teamR = Team(r: tr[0], g: tr[1], b: tr[2], name: "r")
    let teamL = Team(r: tl[0], g: tl[1], b: tl[2], name: "l")
    let board = Board(teamR: teamR, teamL: teamL)
    board.initStandardPosition()
    respondResult(["grid": boardToJSON(board)])
}

func handleChessLegalMoves(_ msg: [String: Any]) {
    guard let gridRaw = msg["grid"] as? [[Any?]],
          let tr = msg["team_r"] as? [Int], tr.count == 3,
          let tl = msg["team_l"] as? [Int], tl.count == 3,
          let activeKey = msg["active_team_key"] as? String else {
        return respondError("chess_legal_moves: missing fields")
    }
    let teamR = Team(r: tr[0], g: tr[1], b: tr[2], name: "r")
    let teamL = Team(r: tl[0], g: tl[1], b: tl[2], name: "l")
    let board = boardFromJSON(gridRaw, teamR: teamR, teamL: teamL)
    let team  = activeKey == "r" ? teamR : teamL
    clearEnPassant(board: board, team: team)
    respondResult(legalMoves(board: board, team: team))
}

func handleChessApplyMove(_ msg: [String: Any]) {
    guard let gridRaw = msg["grid"] as? [[Any?]],
          let tr = msg["team_r"] as? [Int], tr.count == 3,
          let tl = msg["team_l"] as? [Int], tl.count == 3,
          let fr = msg["fr"] as? Int, let fc = msg["fc"] as? Int,
          let toR = msg["tr"] as? Int, let toC = msg["tc"] as? Int,
          let activeKey = msg["active_team_key"] as? String,
          let nextKey   = msg["next_team_key"] as? String,
          let peaceTime = msg["peace_time"] as? Int else {
        return respondError("chess_apply_move: missing fields")
    }
    let teamR = Team(r: tr[0], g: tr[1], b: tr[2], name: "r")
    let teamL = Team(r: tl[0], g: tl[1], b: tl[2], name: "l")
    let board = boardFromJSON(gridRaw, teamR: teamR, teamL: teamL)
    let activeTeam = activeKey == "r" ? teamR : teamL
    // Clear en_passantable for active team before applying (matches Python/JS)
    clearEnPassant(board: board, team: activeTeam)
    guard let piece = board.grid[fr][fc] else {
        return respondError("chess_apply_move: no piece at (\(fr),\(fc))")
    }
    board.applyMove(piece: piece, toRow: toR, toCol: toC)
    board.peaceTime = peaceTime
    let hash   = boardHash(board: board, currentTeamKey: nextKey)
    let nextTeam = nextKey == "r" ? teamR : teamL
    let status = gameStatus(board: board, nextTeam: nextTeam)
    respondResult([
        "grid": boardToJSON(board),
        "board_hash": hash,
        "status": status,
    ])
}

func handleChessBoardHash(_ msg: [String: Any]) {
    guard let gridRaw = msg["grid"] as? [[Any?]],
          let tr = msg["team_r"] as? [Int], tr.count == 3,
          let tl = msg["team_l"] as? [Int], tl.count == 3,
          let peaceTime    = msg["peace_time"] as? Int,
          let currentKey   = msg["current_team_key"] as? String else {
        return respondError("chess_board_hash: missing fields")
    }
    let teamR = Team(r: tr[0], g: tr[1], b: tr[2], name: "r")
    let teamL = Team(r: tl[0], g: tl[1], b: tl[2], name: "l")
    let board = boardFromJSON(gridRaw, teamR: teamR, teamL: teamL)
    board.peaceTime = peaceTime
    respondResult(boardHash(board: board, currentTeamKey: currentKey))
}

// MARK: - Main loop

var buffer = ""
while let line = readLine(strippingNewline: false) {
    buffer += line
    guard buffer.contains("\n") else { continue }
    let lines = buffer.components(separatedBy: "\n")
    for i in 0..<(lines.count - 1) {
        let raw = lines[i].trimmingCharacters(in: .whitespaces)
        guard !raw.isEmpty else { continue }
        guard let data = raw.data(using: .utf8),
              let msg = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let op = msg["op"] as? String else {
            respondError("JSON parse error or missing 'op'")
            continue
        }
        switch op {
        case "ping":                handlePing()
        case "chess_init":          handleChessInit(msg)
        case "chess_legal_moves":   handleChessLegalMoves(msg)
        case "chess_apply_move":    handleChessApplyMove(msg)
        case "chess_board_hash":    handleChessBoardHash(msg)
        default:                    respondError("Unknown op: \(op)")
        }
    }
    buffer = lines.last ?? ""
}
