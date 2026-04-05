import Foundation

/// Stateless rule checks for the fifty-move rule and threefold repetition.
/// BUG-04 preserved: fires at 50 half-moves (not the standard 100).
public enum Rules {

    // MARK: - Fifty-move rule

    /// Returns `true` if a draw should be declared under the fifty-move rule.
    /// Fires at 50 half-moves — BUG-04 intentionally preserved.
    public static func fiftyMoveRule(peaceTime: Int) -> Bool {
        peaceTime >= 50
    }

    // MARK: - Threefold repetition

    /// Returns `true` if the current position has appeared three or more times.
    /// Uses piece-type-only comparison — BUG-05 intentionally preserved.
    public static func threefoldRepetition(history: [String], current: String) -> Bool {
        let count = history.filter { $0 == current }.count
        return count >= 3
    }

    /// Builds a position key from the board for repetition checking.
    /// Compares piece types and positions only — does NOT include team identity (BUG-05).
    public static func positionKey(board: Board) -> String {
        var parts: [String] = []
        for r in 0..<8 {
            for c in 0..<8 {
                if let p = board.grid[r][c] {
                    parts.append("\(r),\(c),\(p.typeName)")
                } else {
                    parts.append("\(r),\(c),-")
                }
            }
        }
        return parts.joined(separator: "|")
    }
}
