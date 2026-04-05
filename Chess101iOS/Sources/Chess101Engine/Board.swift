import Foundation

public typealias BoardGrid = [[Piece?]]

// MARK: - Board

public final class Board {
    public var grid: [[Piece?]]
    public var teamR: Team
    public var teamL: Team
    public var peaceTime: Int = 0
    public var positionHistory: [String] = []

    public init(teamR: Team, teamL: Team) {
        self.teamR = teamR
        self.teamL = teamL
        self.grid = Array(repeating: Array(repeating: nil, count: 8), count: 8)
    }

    // MARK: - Standard setup

    public func initStandardPosition() {
        grid = Array(repeating: Array(repeating: nil, count: 8), count: 8)

        // teamR: rows 0–1
        let backR: [Piece] = [Rook(row:0,col:0,team:teamR), Knight(row:0,col:1,team:teamR),
                               Bishop(row:0,col:2,team:teamR), Queen(row:0,col:3,team:teamR),
                               King(row:0,col:4,team:teamR), Bishop(row:0,col:5,team:teamR),
                               Knight(row:0,col:6,team:teamR), Rook(row:0,col:7,team:teamR)]
        for p in backR { grid[0][p.col] = p }
        for c in 0..<8 { grid[1][c] = Pawn(row:1, col:c, team:teamR) }

        // teamL: rows 6–7
        for c in 0..<8 { grid[6][c] = Pawn(row:6, col:c, team:teamL) }
        let backL: [Piece] = [Rook(row:7,col:0,team:teamL), Knight(row:7,col:1,team:teamL),
                               Bishop(row:7,col:2,team:teamL), Queen(row:7,col:3,team:teamL),
                               King(row:7,col:4,team:teamL), Bishop(row:7,col:5,team:teamL),
                               Knight(row:7,col:6,team:teamL), Rook(row:7,col:7,team:teamL)]
        for p in backL { grid[7][p.col] = p }
    }

    // MARK: - Query helpers

    public func pieces(for team: Team) -> [Piece] {
        grid.flatMap { $0 }.compactMap { $0 }.filter { $0.team == team }
    }

    public func king(for team: Team) -> King? {
        pieces(for: team).first { $0 is King } as? King
    }

    // MARK: - Apply move

    /// Apply a validated move. Returns the piece that was captured (if any).
    @discardableResult
    public func applyMove(piece: Piece, toRow: Int, toCol: Int) -> Piece? {
        let captured = grid[toRow][toCol]
        let fromRow = piece.row, fromCol = piece.col  // Save before move() updates them
        let result = piece.move(toRow: toRow, toCol: toCol, board: self)
        grid[fromRow][fromCol] = nil  // Clear the source square
        grid[toRow][toCol] = piece

        switch result {
        case .normal:
            break
        case .enPassantCapture(let at):
            grid[at.row][at.col] = nil
        case .castling(let rookFrom, let rookTo):
            if let rook = grid[rookFrom.row][rookFrom.col] {
                grid[rookFrom.row][rookFrom.col] = nil
                rook.row = rookTo.row; rook.col = rookTo.col
                rook.touched = true
                grid[rookTo.row][rookTo.col] = rook
            }
        }

        // Auto-promote pawn at back rank
        if let pawn = piece as? Pawn {
            let backRank = pawn.direction == 1 ? 7 : 0
            if pawn.row == backRank {
                let queen = Queen(row: pawn.row, col: pawn.col, team: pawn.team)
                queen.touched = true  // Matches Python: promoted queen has touched=True
                grid[pawn.row][pawn.col] = queen
            }
        }

        // Reset en-passant flags for all friendly pawns after each move
        for p in pieces(for: piece.team) {
            if let pw = p as? Pawn, pw !== piece { pw.enPassantable = false }
        }

        return captured
    }

    // MARK: - Deep copy

    public func copy() -> Board {
        let b = Board(teamR: teamR, teamL: teamL)
        b.peaceTime = peaceTime
        b.positionHistory = positionHistory
        for r in 0..<8 {
            for c in 0..<8 {
                guard let p = grid[r][c] else { continue }
                b.grid[r][c] = copyPiece(p)
            }
        }
        return b
    }

    private func copyPiece(_ p: Piece) -> Piece {
        switch p {
        case let pw as Pawn:
            let n = Pawn(row: pw.row, col: pw.col, team: pw.team)
            n.touched = pw.touched; n.direction = pw.direction
            n.startingRow = pw.startingRow; n.startingCol = pw.startingCol
            n.enPassantable = pw.enPassantable
            n.enPassantLoc = pw.enPassantLoc
            return n
        case let r as Rook:
            let n = Rook(row: r.row, col: r.col, team: r.team); n.touched = r.touched; return n
        case let b as Bishop:
            let n = Bishop(row: b.row, col: b.col, team: b.team); n.touched = b.touched; return n
        case let k as Knight:
            let n = Knight(row: k.row, col: k.col, team: k.team); n.touched = k.touched; return n
        case let q as Queen:
            let n = Queen(row: q.row, col: q.col, team: q.team); n.touched = q.touched; return n
        case let k as King:
            let n = King(row: k.row, col: k.col, team: k.team); n.touched = k.touched; return n
        default:
            fatalError("Unknown piece type: \(type(of: p))")
        }
    }

    // MARK: - Canonical position string (for hash + threefold)

    public func canonicalString(currentTeamKey: String) -> String {
        var parts: [String] = []
        for r in 0..<8 {
            for c in 0..<8 {
                if let p = grid[r][c] {
                    let tk = p.team == teamR ? "r" : "l"
                    var s = "\(r),\(c),\(p.typeName),\(tk),\(p.touched ? 1 : 0)"
                    if let pw = p as? Pawn { s += ",\(pw.enPassantable ? 1 : 0)" }
                    parts.append(s)
                } else {
                    parts.append("\(r),\(c),-")
                }
            }
        }
        return parts.joined(separator: "|") + "|peace=\(peaceTime)|turn=\(currentTeamKey)"
    }
}
