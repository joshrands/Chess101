/// A board coordinate (row 0–7, col 0–7).
/// Row 0 is team-R's back rank; row 7 is team-L's back rank.
public struct Cell: Hashable, Equatable, CustomStringConvertible {
    public let row: Int
    public let col: Int

    public init(_ row: Int, _ col: Int) {
        self.row = row
        self.col = col
    }

    public var description: String { "(\(row),\(col))" }

    public var isOnBoard: Bool { row >= 0 && row < 8 && col >= 0 && col < 8 }
}
