
import SwiftUI

/// Material balance bar — wider teamR segment means teamR is ahead.
public struct EvalBarView: View {
    public let board: Board
    public let teamR: Team
    public let teamL: Team

    private static let vals: [String: Int] = [
        "Pawn": 1, "Knight": 3, "Bishop": 3, "Rook": 5, "Queen": 9
    ]

    private var eval: Int {
        var sumR = 0, sumL = 0
        for r in 0..<8 { for c in 0..<8 {
            guard let p = board.grid[r][c] else { continue }
            let v = Self.vals[p.typeName] ?? 0
            if p.team == teamR { sumR += v } else { sumL += v }
        }}
        return sumR - sumL
    }

    private var rPct: Double { max(5, min(95, 50 + Double(eval) / 39 * 50)) }

    public init(board: Board, teamR: Team, teamL: Team) {
        self.board = board; self.teamR = teamR; self.teamL = teamL
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("EVAL")
                .font(.system(size: 10, design: .monospaced))
                .foregroundColor(Color(red: 0.23, green: 0.29, blue: 0.38))

            GeometryReader { geo in
                HStack(spacing: 0) {
                    Rectangle()
                        .fill(Color(red: Double(teamR.r)/255, green: Double(teamR.g)/255, blue: Double(teamR.b)/255))
                        .frame(width: geo.size.width * rPct / 100)
                    Rectangle()
                        .fill(Color(red: Double(teamL.r)/255, green: Double(teamL.g)/255, blue: Double(teamL.b)/255))
                }
                .clipShape(RoundedRectangle(cornerRadius: 3))
            }
            .frame(height: 8)

            Text(evalLabel)
                .font(.system(size: 10, design: .monospaced))
                .foregroundColor(Color(red: 0.4, green: 0.47, blue: 0.6))
        }
    }

    private var evalLabel: String {
        if eval == 0 { return "Even" }
        return eval > 0 ? "\(teamR.name) +\(eval)" : "\(teamL.name) +\(-eval)"
    }
}
