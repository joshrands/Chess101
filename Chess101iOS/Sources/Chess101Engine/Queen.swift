public final class Queen: Piece {
    public var row: Int
    public var col: Int
    public var team: Team
    public var targets: [Cell] = []
    public var touched: Bool = false
    public var critical: Bool = false
    public var criticalTargets: [Cell] = []
    public var typeName: String { "Queen" }

    public init(row: Int, col: Int, team: Team) {
        self.row = row; self.col = col; self.team = team
    }

    @discardableResult
    public func calcTargets(board: Board) -> Bool? {
        targets = []
        let dirs = [(0,1),(0,-1),(1,0),(-1,0),(1,1),(1,-1),(-1,1),(-1,-1)]
        for (dr, dc) in dirs { bladeRunner(board: board, dr: dr, dc: dc, fromRow: row, fromCol: col) }
        if critical { criticalMan() }
        return nil
    }

    public func move(toRow: Int, toCol: Int, board: Board) -> MoveResult {
        row = toRow; col = toCol; touched = true
        return .normal
    }

    public func getValue(board: Board) -> Int {
        var val = 49
        val += targets.count
        return val
    }
}
