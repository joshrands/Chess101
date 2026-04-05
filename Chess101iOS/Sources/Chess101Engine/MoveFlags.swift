import Foundation

/// Metadata attached to every move message — mirrors Python `MoveFlags`.
public struct MoveFlags: Codable {
    public var isCapture: Bool = false
    public var isEnPassant: Bool = false
    public var isCastling: Bool = false
    public var isPromotion: Bool = false
    public var promotedTo: String? = nil        // "Queen", "Rook", etc.
    public var capturedAtRow: Int? = nil
    public var capturedAtCol: Int? = nil
    public var rookFromRow: Int? = nil
    public var rookFromCol: Int? = nil
    public var rookToRow: Int? = nil
    public var rookToCol: Int? = nil

    public init() {}

    // MARK: - Wire encoding (snake_case keys to match Python relay)
    enum CodingKeys: String, CodingKey {
        case isCapture     = "is_capture"
        case isEnPassant   = "is_en_passant"
        case isCastling    = "is_castling"
        case isPromotion   = "is_promotion"
        case promotedTo    = "promoted_to"
        case capturedAtRow = "captured_at_row"
        case capturedAtCol = "captured_at_col"
        case rookFromRow   = "rook_from_row"
        case rookFromCol   = "rook_from_col"
        case rookToRow     = "rook_to_row"
        case rookToCol     = "rook_to_col"
    }
}
