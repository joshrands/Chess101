/// RGB color identity for a chess side.
/// Equality is determined by the red channel only (BUG-03 preserved — matches Python behavior).
public struct Team: Equatable, Hashable, CustomStringConvertible {
    public var r: Int
    public var g: Int
    public var b: Int
    public var name: String

    public init(r: Int, g: Int, b: Int, name: String = "Player") {
        self.r = r
        self.g = g
        self.b = b
        self.name = name
    }

    /// BUG-03: identity uses only the red channel, mirroring the Python codebase.
    public static func == (lhs: Team, rhs: Team) -> Bool { lhs.r == rhs.r }
    public func hash(into hasher: inout Hasher) { hasher.combine(r) }

    public var description: String { "\(name) (\(r),\(g),\(b))" }
}

public extension Team {
    /// Serialization key used in the wire protocol ("r" or "l").
    static let keyR = "r"
    static let keyL = "l"
}
