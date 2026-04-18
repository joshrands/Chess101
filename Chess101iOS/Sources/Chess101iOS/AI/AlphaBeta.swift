
import Foundation
#if SWIFT_PACKAGE
import Chess101Engine
#endif

/// Alpha-beta minimax search. Runs as a Swift `actor` for safe background execution.
public actor AlphaBeta {
    private let maxDepth: Int

    public init(depth: Int = 2) { self.maxDepth = depth }

    // MARK: - Public entry point

    /// Returns the best child node from the root's children (i.e., the best move for `team`).
    public func search(root: GameTree, team: Team) -> GameTree? {
        addNodes(node: root, team: team, depth: maxDepth)
        guard !root.children.isEmpty else { return nil }

        var best: GameTree? = nil
        var bestVal = Int.min
        for child in root.children {
            let val = minValue(child, alpha: Int.min, beta: Int.max, depth: maxDepth - 1, team: team)
            if val > bestVal { bestVal = val; best = child }
        }
        return best
    }

    // MARK: - Minimax

    private func maxValue(_ node: GameTree, alpha: Int, beta: Int, depth: Int, team: Team) -> Int {
        if depth == 0 || isTerminal(node) { return node.getUtility(for: team) }
        addNodes(node: node, team: team, depth: depth)
        var a = alpha, v = Int.min
        for child in node.children {
            v = max(v, minValue(child, alpha: a, beta: beta, depth: depth - 1, team: team))
            if v >= beta { return v }
            a = max(a, v)
        }
        return v
    }

    private func minValue(_ node: GameTree, alpha: Int, beta: Int, depth: Int, team: Team) -> Int {
        let opponent = node.teamR == team ? node.teamL : node.teamR
        if depth == 0 || isTerminal(node) { return node.getUtility(for: team) }
        addNodes(node: node, team: opponent, depth: depth)
        var b = beta, v = Int.max
        for child in node.children {
            v = min(v, maxValue(child, alpha: alpha, beta: b, depth: depth - 1, team: team))
            if v <= alpha { return v }
            b = min(b, v)
        }
        return v
    }

    private func isTerminal(_ node: GameTree) -> Bool {
        // Terminal if no moves exist for either side
        let r = node.board.pieces(for: node.teamR)
        let l = node.board.pieces(for: node.teamL)
        return r.isEmpty || l.isEmpty
    }

    // MARK: - Tree expansion

    /// Expand `node` by generating all legal moves for `team` at this depth.
    private func addNodes(node: GameTree, team: Team, depth: Int) {
        guard depth > 0, node.children.isEmpty else { return }

        let board = node.board
        let myPieces = board.pieces(for: team)

        // Find the king and compute check state
        var king: King? = nil
        var inCheck = false
        for p in myPieces {
            if let k = p as? King {
                king = k
                inCheck = (k.calcTargets(board: board) == true)
            }
        }

        // Compute targets for all non-king pieces; apply filters
        for p in myPieces {
            guard !(p is King) else { continue }
            p.calcTargets(board: board)
            if p.critical { p.criticalMan() }
            if inCheck, let k = king { p.skyFall(king: k) }
        }

        // Generate child nodes
        for p in myPieces {
            for target in p.targets {
                let copy = board.copy()
                guard let cp = copy.grid[p.row][p.col] else { continue }
                copy.applyMove(piece: cp, toRow: target.row, toCol: target.col)
                let moveInfo = (piece: p.typeName, from: Cell(p.row, p.col), to: target)
                let child = GameTree(board: copy, move: moveInfo,
                                     teamR: node.teamR, teamL: node.teamL)
                node.addChild(child)
            }
        }
    }
}
