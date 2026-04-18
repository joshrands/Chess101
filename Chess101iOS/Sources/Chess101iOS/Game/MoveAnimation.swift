
import Foundation
#if SWIFT_PACKAGE
import Chess101Engine
#endif

/// Tracks a single piece animation (arc from source to destination).
public struct MoveAnimation {
    public let piece: String          // typeName of the moving piece
    public let team: Team
    public let fromRow: Int
    public let fromCol: Int
    public let toRow: Int
    public let toCol: Int
    public let startTime: Date
    public let duration: TimeInterval  // seconds

    /// Ease-out progress in [0, 1].
    public func progress(at now: Date) -> Double {
        let t = min(1, now.timeIntervalSince(startTime) / duration)
        return 1 - pow(1 - t, 2)  // ease-out quadratic
    }

    /// Interpolated board position (fractional row/col) at `now`.
    public func position(at now: Date) -> (row: Double, col: Double) {
        let p = progress(at: now)
        return (Double(fromRow) + Double(toRow - fromRow) * p,
                Double(fromCol) + Double(toCol - fromCol) * p)
    }

    public var isComplete: Bool { Date().timeIntervalSince(startTime) >= duration }

    public init(piece: String, team: Team, fromRow: Int, fromCol: Int,
                toRow: Int, toCol: Int, duration: TimeInterval = 0.3) {
        self.piece = piece; self.team = team
        self.fromRow = fromRow; self.fromCol = fromCol
        self.toRow = toRow; self.toCol = toCol
        self.startTime = Date(); self.duration = duration
    }
}

/// A move-trail entry: cells that glow and fade after a move.
public struct MoveTrail {
    public let cells: [Cell]
    public let team: Team
    public let startTime: Date
    public let duration: TimeInterval = 0.6

    public func alpha(at now: Date) -> Double {
        max(0, 1 - now.timeIntervalSince(startTime) / duration)
    }

    public var isExpired: Bool { Date().timeIntervalSince(startTime) >= duration }
}
