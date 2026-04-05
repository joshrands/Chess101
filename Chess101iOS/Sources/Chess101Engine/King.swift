public final class King: Piece {
    public var row: Int
    public var col: Int
    public var team: Team
    public var targets: [Cell] = []
    public var touched: Bool = false
    public var critical: Bool = false
    public var criticalTargets: [Cell] = []

    /// Squares that would resolve the current check (blocking or capturing the attacker).
    public var godSaveTheKing: [Cell] = []

    public var typeName: String { "King" }

    public init(row: Int, col: Int, team: Team) {
        self.row = row; self.col = col; self.team = team
    }

    // MARK: - calcTargets

    /// Computes legal king moves (including castling) and detects check.
    /// - Returns: `true` if the king is currently in check, `false` otherwise.
    @discardableResult
    public func calcTargets(board: Board) -> Bool? {
        targets = []
        godSaveTheKing = []

        // Clear pin flags for all friendly pieces (pin state is re-derived below)
        for r in 0..<8 {
            for c in 0..<8 {
                if let p = board.grid[r][c], p.team == team { p.critical = false }
            }
        }

        // Standard king moves — one square in any direction
        for dr in -1...1 {
            for dc in -1...1 {
                guard dr != 0 || dc != 0 else { continue }
                let nr = row + dr, nc = col + dc
                guard nr >= 0 && nr < 8 && nc >= 0 && nc < 8 else { continue }
                if let occ = board.grid[nr][nc], occ.team == team { continue }
                // Simulate the move to ensure king won't be in check
                let saved = board.grid[row][col]
                let captured = board.grid[nr][nc]
                board.grid[row][col] = nil
                board.grid[nr][nc] = self
                let inDanger = wouldBeInCheck(row: nr, col: nc, board: board)
                board.grid[row][col] = saved
                board.grid[nr][nc] = captured
                if !inDanger { targets.append(Cell(nr, nc)) }
            }
        }

        // Castling
        if !touched {
            tryCastle(board: board, side: -1) // queen-side
            tryCastle(board: board, side:  1) // king-side
        }

        // Check detection: is the king attacked in its current position?
        let inCheck = wouldBeInCheck(row: row, col: col, board: board)

        if inCheck {
            // Compute godSaveTheKing — squares where a piece could block or capture
            computeGodSaveTheKing(board: board)
        }

        // Detect pinned friendly pieces and mark them critical
        detectPins(board: board)

        return inCheck
    }

    // MARK: - Castling

    private func tryCastle(board: Board, side: Int) {
        // Find the rook on this side
        let rookCol = side == -1 ? 0 : 7
        guard let rook = board.grid[row][rookCol] as? Rook,
              rook.team == team, !rook.touched else { return }

        // All squares between king and rook must be empty
        let range = side == -1 ? (1..<col) : ((col+1)..<rookCol)
        for c in range {
            if board.grid[row][c] != nil { return }
        }

        // King must not be in check, nor pass through an attacked square
        if wouldBeInCheck(row: row, col: col, board: board) { return }
        let midCol = col + side
        // Simulate king on midCol
        let saved = board.grid[row][col]
        board.grid[row][col] = nil
        board.grid[row][midCol] = self
        let midDanger = wouldBeInCheck(row: row, col: midCol, board: board)
        board.grid[row][midCol] = nil
        board.grid[row][col] = saved
        if midDanger { return }

        // Also verify the destination square isn't attacked
        let destCol = col + 2 * side
        board.grid[row][col] = nil
        board.grid[row][destCol] = self
        let destDanger = wouldBeInCheck(row: row, col: destCol, board: board)
        board.grid[row][destCol] = nil
        board.grid[row][col] = saved
        if destDanger { return }

        targets.append(Cell(row, col + 2 * side))
    }

    // MARK: - Check detection

    /// Returns `true` if a king at `(row, col)` would be attacked by any enemy piece.
    func wouldBeInCheck(row: Int, col: Int, board: Board) -> Bool {
        // Sliding rays (rook/queen orthogonal, bishop/queen diagonal)
        let ortho = [(0,1),(0,-1),(1,0),(-1,0)]
        let diag  = [(1,1),(1,-1),(-1,1),(-1,-1)]

        for (dr, dc) in ortho {
            if rayHits(row: row, col: col, dr: dr, dc: dc, board: board,
                       types: [Rook.self, Queen.self]) { return true }
        }
        for (dr, dc) in diag {
            if rayHits(row: row, col: col, dr: dr, dc: dc, board: board,
                       types: [Bishop.self, Queen.self]) { return true }
        }

        // Knight attacks
        for (dr, dc) in [(-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)] {
            let nr = row + dr, nc = col + dc
            guard nr >= 0 && nr < 8 && nc >= 0 && nc < 8 else { continue }
            if let p = board.grid[nr][nc], p is Knight, p.team != team { return true }
        }

        // Enemy pawn attacks (pawns attack diagonally in their direction of travel)
        for dc in [-1, 1] {
            for pawnDir in [-1, 1] {
                let nr = row + pawnDir, nc = col + dc
                guard nr >= 0 && nr < 8 && nc >= 0 && nc < 8 else { continue }
                if let p = board.grid[nr][nc] as? Pawn,
                   p.team != team, p.direction == -pawnDir { return true }
            }
        }

        // Enemy king (prevent kings from moving adjacent)
        for dr in -1...1 {
            for dc in -1...1 {
                guard dr != 0 || dc != 0 else { continue }
                let nr = row + dr, nc = col + dc
                guard nr >= 0 && nr < 8 && nc >= 0 && nc < 8 else { continue }
                if let p = board.grid[nr][nc] as? King, p.team != team { return true }
            }
        }

        return false
    }

    private func rayHits(row: Int, col: Int, dr: Int, dc: Int, board: Board,
                         types: [AnyClass]) -> Bool {
        var r = row + dr, c = col + dc
        while r >= 0 && r < 8 && c >= 0 && c < 8 {
            if let p = board.grid[r][c] {
                if p.team != team {
                    return types.contains { $0 === type(of: p) }
                }
                return false // friendly piece blocks
            }
            r += dr; c += dc
        }
        return false
    }

    // MARK: - godSaveTheKing

    private func computeGodSaveTheKing(board: Board) {
        // Any square that, when a friendly piece moves there, removes the check
        for r in 0..<8 {
            for c in 0..<8 {
                let cell = Cell(r, c)
                // Only empty squares or enemy captures make sense
                if let occ = board.grid[r][c], occ.team == team { continue }
                // Simulate placing a friendly blocker
                let wasOcc = board.grid[r][c]
                board.grid[r][c] = DummyPiece(row: r, col: c, team: team)
                let stillCheck = wouldBeInCheck(row: row, col: col, board: board)
                board.grid[r][c] = wasOcc
                if !stillCheck { godSaveTheKing.append(cell) }
            }
        }
    }

    // MARK: - move

    public func move(toRow: Int, toCol: Int, board: Board) -> MoveResult {
        // Detect castling: king moved 2 squares horizontally
        if !touched && abs(toCol - col) == 2 {
            let side = toCol > col ? 1 : -1
            let rookFromCol = side == 1 ? 7 : 0
            let rookToCol   = col + side
            let result = MoveResult.castling(rookFrom: Cell(row, rookFromCol),
                                             rookTo:   Cell(row, rookToCol))
            row = toRow; col = toCol; touched = true
            return result
        }
        row = toRow; col = toCol; touched = true
        return .normal
    }

    public func getValue(board: Board) -> Int { 0 } // Kings are never traded

    // MARK: - Pin detection

    /// Walk all 8 rays from the king; mark any friendly piece that is pinned against us.
    private func detectPins(board: Board) {
        let rays: [(Int, Int)] = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
        for (dr, dc) in rays {
            var friendlyPiece: Piece? = nil
            var r = row + dr, c = col + dc
            while r >= 0 && r < 8 && c >= 0 && c < 8 {
                defer { r += dr; c += dc }
                guard let p = board.grid[r][c] else { continue }
                if p.team == team {
                    if friendlyPiece != nil { break } // second friendly — no pin
                    friendlyPiece = p
                } else {
                    if let fp = friendlyPiece {
                        let isOrtho = (dr == 0 || dc == 0)
                        let isPinner = isOrtho ? (p is Rook || p is Queen) : (p is Bishop || p is Queen)
                        if isPinner {
                            fp.critical = true
                            fp.criticalTargets = pinRayCells(enemyRow: r, enemyCol: c, dr: -dr, dc: -dc)
                        }
                    }
                    break
                }
            }
        }
    }

    /// Cells from the enemy position stepping toward the king (inclusive of enemy, exclusive of king).
    private func pinRayCells(enemyRow: Int, enemyCol: Int, dr: Int, dc: Int) -> [Cell] {
        var cells: [Cell] = []
        var r = enemyRow, c = enemyCol
        while !(r == row && c == col) {
            cells.append(Cell(r, c))
            r += dr; c += dc
        }
        return cells
    }
}

// MARK: - DummyPiece (internal blocker for check simulation)

/// Minimal piece used as a blocker during check/pin analysis — never appears on a real board.
final class DummyPiece: Piece {
    var row: Int; var col: Int; var team: Team
    var targets: [Cell] = []; var touched = false
    var critical = false; var criticalTargets: [Cell] = []
    var typeName: String { "Dummy" }
    init(row: Int, col: Int, team: Team) { self.row=row; self.col=col; self.team=team }
    func calcTargets(board: Board) -> Bool? { nil }
    func move(toRow: Int, toCol: Int, board: Board) -> MoveResult { .normal }
    func getValue(board: Board) -> Int { 0 }
}
