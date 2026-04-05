public final class Pawn: Piece {
    public var row: Int
    public var col: Int
    public var team: Team
    public var targets: [Cell] = []
    public var touched: Bool = false
    public var critical: Bool = false
    public var criticalTargets: [Cell] = []

    /// Direction of travel: +1 (started row 1) or -1 (started row 6).
    /// Note: direction is set by starting row, not team — BUG-01 preserved.
    public var direction: Int
    public var startingRow: Int
    public var startingCol: Int
    public var enPassantable: Bool = false
    public var enPassantLoc: Cell? = nil

    public var typeName: String { "Pawn" }

    public init(row: Int, col: Int, team: Team) {
        self.row = row
        self.col = col
        self.team = team
        self.startingRow = row
        self.startingCol = col
        self.direction = (row == 6) ? -1 : 1
    }

    @discardableResult
    public func calcTargets(board: Board) -> Bool? {
        targets = []
        enPassantLoc = nil  // Reset stale location from previous turns — matches Python
        let r = row, c = col, d = direction

        // One square forward
        if r + d >= 0 && r + d < 8 && board.grid[r + d][c] == nil {
            targets.append(Cell(r + d, c))
            // Two squares forward only from the starting row — matches Python (uses row, not touched)
            if r == startingRow && r + 2 * d >= 0 && r + 2 * d < 8 && board.grid[r + 2 * d][c] == nil {
                targets.append(Cell(r + 2 * d, c))
            }
        }

        // Diagonal captures
        for dc in [-1, 1] {
            let nr = r + d, nc = c + dc
            guard nr >= 0 && nr < 8 && nc >= 0 && nc < 8 else { continue }
            if let target = board.grid[nr][nc], target.team != team {
                targets.append(Cell(nr, nc))
            }
            // En passant
            if nc >= 0 && nc < 8, let neighbor = board.grid[r][nc] as? Pawn,
               neighbor.team != team, neighbor.enPassantable {
                targets.append(Cell(nr, nc))
                enPassantLoc = Cell(nr, nc)
            }
        }

        if critical { criticalMan() }
        return nil
    }

    public func move(toRow: Int, toCol: Int, board: Board) -> MoveResult {
        let wasEnPassant = enPassantLoc == Cell(toRow, toCol) && board.grid[toRow][toCol] == nil
        let fromRow = row  // save before mutation
        row = toRow; col = toCol
        // Note: do NOT set touched = true — Python Pawn.move() preserves touched=False (matches hash)
        // Set enPassantable only when double-stepping FROM the starting row — matches Python
        enPassantable = (fromRow == startingRow && abs(toRow - fromRow) == 2)
        if wasEnPassant {
            return .enPassantCapture(capturedAt: Cell(fromRow, toCol))
        }
        return .normal
    }

    /// Pawn-specific skyFall: also allows en passant when the captured pawn is the checker.
    public func skyFall(king: King) {
        let originalTargets = targets
        var newTargets = targets.filter { king.godSaveTheKing.contains($0) }

        // En passant special case: the captured pawn is at (enPassantLoc.row - direction, col),
        // not at the destination square — so the standard filter misses it.
        if let loc = enPassantLoc {
            let capturedRow = loc.row - direction
            let capturesChecker = king.godSaveTheKing.contains(Cell(capturedRow, loc.col))
            if capturesChecker && originalTargets.contains(loc) && !newTargets.contains(loc) {
                newTargets.append(loc)
            }
        }
        targets = newTargets
    }

    public func getValue(board: Board) -> Int {
        var val = 5
        // Center bonus
        let cr = abs(row - 3) <= 1 ? 1 : 0
        let cc = abs(col - 3) <= 1 ? 1 : 0
        val += cr + cc
        return val
    }
}
