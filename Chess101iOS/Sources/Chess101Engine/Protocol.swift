import Foundation
import CryptoKit

// MARK: - Board hash

/// SHA-256 of a canonical board string — identical algorithm to Python `board_hash()`.
public func boardHash(board: Board, currentTeamKey: String) -> String {
    let canonical = board.canonicalString(currentTeamKey: currentTeamKey)
    let digest = SHA256.hash(data: Data(canonical.utf8))
    return digest.map { String(format: "%02x", $0) }.joined()
}

// MARK: - Grid serialization

/// Encode the board grid to a JSON-compatible array (matches Python `encode_grid`).
public func encodeGrid(board: Board, teamR: Team, teamL: Team) -> [[String: Any]] {
    var result: [[String: Any]] = []
    for r in 0..<8 {
        for c in 0..<8 {
            guard let p = board.grid[r][c] else { continue }
            let tk = p.team == teamR ? "r" : "l"
            var entry: [String: Any] = [
                "type": p.typeName,
                "team": tk,
                "row": p.row,
                "col": p.col,
                "touched": p.touched,
            ]
            if let pw = p as? Pawn {
                entry["en_passantable"] = pw.enPassantable
                entry["direction"] = pw.direction
            }
            if let k = p as? King {
                entry["direction"] = k.row == 0 ? 1 : -1  // same convention as Python
            }
            result.append(entry)
        }
    }
    return result
}

/// Decode a grid from JSON (matches Python `decode_grid`).
public func decodeGrid(from entries: [[String: Any]], teamR: Team, teamL: Team) -> Board {
    let board = Board(teamR: teamR, teamL: teamL)
    for entry in entries {
        guard let type = entry["type"] as? String,
              let teamKey = entry["team"] as? String,
              let row = entry["row"] as? Int,
              let col = entry["col"] as? Int else { continue }
        let team = teamKey == "r" ? teamR : teamL
        let touched = entry["touched"] as? Bool ?? false
        let piece: Piece
        switch type {
        case "Pawn":
            let p = Pawn(row: row, col: col, team: team)
            p.touched = touched
            p.direction = entry["direction"] as? Int ?? (row <= 3 ? 1 : -1)
            p.enPassantable = entry["en_passantable"] as? Bool ?? false
            piece = p
        case "Rook":
            let p = Rook(row: row, col: col, team: team); p.touched = touched; piece = p
        case "Bishop":
            let p = Bishop(row: row, col: col, team: team); p.touched = touched; piece = p
        case "Knight":
            let p = Knight(row: row, col: col, team: team); p.touched = touched; piece = p
        case "Queen":
            let p = Queen(row: row, col: col, team: team); p.touched = touched; piece = p
        case "King":
            let p = King(row: row, col: col, team: team); p.touched = touched; piece = p
        default: continue
        }
        board.grid[row][col] = piece
    }
    return board
}

// MARK: - Move message builder

public func buildMoveMessage(piece: Piece, fromRow: Int, fromCol: Int,
                              toRow: Int, toCol: Int,
                              flags: MoveFlags, board: Board,
                              teamKey: String, seq: Int) -> [String: Any] {
    let encoder = JSONEncoder()
    let flagsData = (try? encoder.encode(flags)).flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any] ?? [:]
    return [
        "type": "move",
        "seq": seq,
        "from_row": fromRow,
        "from_col": fromCol,
        "to_row": toRow,
        "to_col": toCol,
        "piece": piece.typeName,
        "flags": flagsData,
        "board_hash": boardHash(board: board, currentTeamKey: teamKey),
    ]
}
