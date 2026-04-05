/// Result of applying a move — captures special-case side effects.
public enum MoveResult {
    case normal
    case enPassantCapture(capturedAt: Cell)
    case castling(rookFrom: Cell, rookTo: Cell)
}

// MARK: - Piece protocol

/// Abstract chess piece. All concrete types (Pawn, Rook, …) conform to this protocol.
public protocol Piece: AnyObject {
    var row: Int { get set }
    var col: Int { get set }
    var team: Team { get set }
    /// Legal destination squares, populated by `calcTargets(board:)`.
    var targets: [Cell] { get set }
    /// True once the piece has moved (disables castling, double pawn push).
    var touched: Bool { get set }
    /// True when the piece is pinned to the king along a ray.
    var critical: Bool { get set }
    /// When `critical`, only moves to these squares are legal (the pin ray).
    var criticalTargets: [Cell] { get set }

    /// Populate `targets` with all pseudo-legal destinations.
    /// - Returns: `true`/`false` (check state) for King; `nil` for all others.
    @discardableResult
    func calcTargets(board: Board) -> Bool?

    /// Move to `(toRow, toCol)`, set `touched`, and return any side effects.
    func move(toRow: Int, toCol: Int, board: Board) -> MoveResult

    /// Restrict `targets` to squares that block or capture the attacker (called when king is in check).
    func skyFall(king: King)

    /// Restrict `targets` to the pin-ray squares (called when `critical == true`).
    func criticalMan()

    /// Heuristic piece value for AI evaluation.
    func getValue(board: Board) -> Int

    /// The canonical type name used in serialization ("Pawn", "Rook", etc.).
    var typeName: String { get }
}

// MARK: - Shared helpers

public extension Piece {
    func criticalMan() {
        guard critical else { return }
        targets = targets.filter { criticalTargets.contains($0) }
    }

    func skyFall(king: King) {
        targets = targets.filter { king.godSaveTheKing.contains($0) }
    }

    /// Slide along a ray (dr, dc) from the given position, appending reachable squares.
    func bladeRunner(board: Board, dr: Int, dc: Int, fromRow: Int, fromCol: Int) {
        var r = fromRow + dr
        var c = fromCol + dc
        while r >= 0 && r < 8 && c >= 0 && c < 8 {
            if let occupant = board.grid[r][c] {
                if occupant.team != team { targets.append(Cell(r, c)) }
                return
            }
            targets.append(Cell(r, c))
            r += dr; c += dc
        }
    }
}
