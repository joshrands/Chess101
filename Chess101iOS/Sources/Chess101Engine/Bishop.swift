public final class Bishop: Piece {
    public var row: Int
    public var col: Int
    public var team: Team
    public var targets: [Cell] = []
    public var touched: Bool = false
    public var critical: Bool = false
    public var criticalTargets: [Cell] = []
    public var typeName: String { "Bishop" }

    public init(row: Int, col: Int, team: Team) {
        self.row = row; self.col = col; self.team = team
    }

    @discardableResult
    public func calcTargets(board: Board) -> Bool? {
        targets = []
        for (dr, dc) in [(1,1),(1,-1),(-1,1),(-1,-1)] { bladeRunner(board: board, dr: dr, dc: dc, fromRow: row, fromCol: col) }
        if critical { criticalMan() }
        return nil
    }

    public func move(toRow: Int, toCol: Int, board: Board) -> MoveResult {
        row = toRow; col = toCol; touched = true
        return .normal
    }

    public func getValue(board: Board) -> Int {
        var val = 15
        val += targets.count
        let cr = abs(row - 3) <= 1 ? 1 : 0; let cc = abs(col - 3) <= 1 ? 1 : 0
        val += cr + cc
        return val
    }
}
