public final class Knight: Piece {
    public var row: Int
    public var col: Int
    public var team: Team
    public var targets: [Cell] = []
    public var touched: Bool = false
    public var critical: Bool = false
    public var criticalTargets: [Cell] = []
    public var typeName: String { "Knight" }

    private static let moves = [(-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)]

    public init(row: Int, col: Int, team: Team) {
        self.row = row; self.col = col; self.team = team
    }

    @discardableResult
    public func calcTargets(board: Board) -> Bool? {
        targets = []
        for (dr, dc) in Knight.moves {
            let nr = row + dr, nc = col + dc
            guard nr >= 0 && nr < 8 && nc >= 0 && nc < 8 else { continue }
            if board.grid[nr][nc] == nil || board.grid[nr][nc]!.team != team {
                targets.append(Cell(nr, nc))
            }
        }
        if critical { criticalMan() }
        return nil
    }

    public func move(toRow: Int, toCol: Int, board: Board) -> MoveResult {
        row = toRow; col = toCol; touched = true
        return .normal
    }

    public func getValue(board: Board) -> Int {
        var val = 13
        val += targets.count
        let cr = abs(row - 3) <= 1 ? 1 : 0; let cc = abs(col - 3) <= 1 ? 1 : 0
        val += cr + cc
        return val
    }
}
