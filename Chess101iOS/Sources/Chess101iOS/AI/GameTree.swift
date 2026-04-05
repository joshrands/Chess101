
/// A node in the alpha-beta game tree.
public final class GameTree {
    public var children: [GameTree] = []
    public let board: Board
    /// The move that produced this node (nil at root).
    public let move: (piece: String, from: Cell, to: Cell)?
    public let teamR: Team
    public let teamL: Team

    public init(board: Board, move: (piece: String, from: Cell, to: Cell)? = nil,
                teamR: Team, teamL: Team) {
        self.board = board
        self.move = move
        self.teamR = teamR
        self.teamL = teamL
    }

    public func addChild(_ child: GameTree) { children.append(child) }

    /// Material balance from teamR's perspective. Positive = teamR is ahead.
    public func getUtility(for team: Team) -> Int {
        var sumR = 0, sumL = 0
        for r in 0..<8 {
            for c in 0..<8 {
                guard let p = board.grid[r][c] else { continue }
                let v = p.getValue(board: board)
                if p.team == teamR { sumR += v } else { sumL += v }
            }
        }
        let balance = sumR - sumL
        return team == teamR ? balance : -balance
    }
}
