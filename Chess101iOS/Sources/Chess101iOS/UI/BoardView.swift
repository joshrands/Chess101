
import SwiftUI

/// 2D canvas board — 8×8 grid with LED-style glowing cells.
public struct BoardView: View {
    @EnvironmentObject var session: GameSession

    public init() {}

    public var body: some View {
        GeometryReader { geo in
            let cellSize = geo.size.width / 8
            Canvas { ctx, size in
                drawBoard(ctx: ctx, cellSize: cellSize)
            }
            .contentShape(Rectangle())
            .onTapGesture { loc in
                let col = Int(loc.x / cellSize)
                let row = Int(loc.y / cellSize)
                if row >= 0 && row < 8 && col >= 0 && col < 8 {
                    session.cellTapped(Cell(row, col))
                }
            }
        }
        .aspectRatio(1, contentMode: .fit)
    }

    private func drawBoard(ctx: GraphicsContext, cellSize: CGFloat) {
        guard let board = session.board else { return }
        let now = Date()

        for r in 0..<8 {
            for c in 0..<8 {
                let rect = cellRect(r: r, c: c, cellSize: cellSize)
                let isDark = (r + c) % 2 == 1

                // Base square
                let baseColor: Color = isDark
                    ? Color(red: 0.04, green: 0.055, blue: 0.086)
                    : Color(red: 0.078, green: 0.118, blue: 0.173)
                ctx.fill(Path(rect), with: .color(baseColor))

                // Move trail glow
                for trail in session.trails {
                    if trail.cells.contains(Cell(r, c)) {
                        let a = trail.alpha(at: now)
                        let tc = trail.team
                        ctx.fill(Path(rect), with: .color(
                            Color(red: Double(tc.r)/255, green: Double(tc.g)/255, blue: Double(tc.b)/255)
                                .opacity(a * 0.55)
                        ))
                    }
                }

                // Selected cell highlight
                if session.selectedCell == Cell(r, c) {
                    ctx.fill(Path(rect), with: .color(Color.white.opacity(0.18)))
                }

                // Legal target dots
                if session.legalTargets.contains(Cell(r, c)) {
                    if board.grid[r][c] != nil {
                        ctx.stroke(Path(ellipseIn: rect.insetBy(dx: 3, dy: 3)),
                                   with: .color(Color.white.opacity(0.4)), lineWidth: 2)
                    } else {
                        let dot = CGRect(x: rect.midX - cellSize * 0.15, y: rect.midY - cellSize * 0.15,
                                        width: cellSize * 0.3, height: cellSize * 0.3)
                        ctx.fill(Path(ellipseIn: dot), with: .color(Color.white.opacity(0.35)))
                    }
                }

                // Check — king cell pulses red
                if session.inCheck, let team = session.currentTeam,
                   let p = board.grid[r][c] as? King, p.team == team {
                    let pulse = 0.5 + 0.5 * sin(now.timeIntervalSince1970 * .pi * 4)
                    ctx.fill(Path(rect), with: .color(Color.red.opacity(0.35 * pulse)))
                }

                // Piece glyph
                if let piece = board.grid[r][c] {
                    // Skip if this cell is animating
                    if let anim = session.activeAnimation,
                       anim.fromRow == r && anim.fromCol == c && !anim.isComplete { continue }
                    drawGlyph(ctx: ctx, piece: piece, rect: rect, cellSize: cellSize)
                }
            }
        }

        // Animating piece
        if let anim = session.activeAnimation, !anim.isComplete {
            let pos = anim.position(at: now)
            let x = CGFloat(pos.col) * cellSize
            let y = CGFloat(pos.row) * cellSize
            let rect = CGRect(x: x, y: y, width: cellSize, height: cellSize)
            // Find piece at destination to get type
            if let board = session.board, let piece = board.grid[anim.toRow][anim.toCol] {
                drawGlyph(ctx: ctx, piece: piece, rect: rect, cellSize: cellSize)
            } else {
                // Fallback: draw colored circle
                let tc = anim.team
                ctx.fill(Path(ellipseIn: rect.insetBy(dx: 8, dy: 8)),
                         with: .color(Color(red: Double(tc.r)/255, green: Double(tc.g)/255, blue: Double(tc.b)/255)))
            }
        }
    }

    private func drawGlyph(ctx: GraphicsContext, piece: Piece, rect: CGRect, cellSize: CGFloat) {
        let glyphsR: [String: String] = [
            "Pawn": "♙", "Rook": "♖", "Knight": "♘",
            "Bishop": "♗", "Queen": "♕", "King": "♔"
        ]
        let glyphsL: [String: String] = [
            "Pawn": "♟", "Rook": "♜", "Knight": "♞",
            "Bishop": "♝", "Queen": "♛", "King": "♚"
        ]
        let isR = piece.team == session.teamR
        guard let glyph = (isR ? glyphsR : glyphsL)[piece.typeName] else { return }

        // Team-color pedestal glow (matches JS sim drawOnePiece)
        let tc = piece.team
        let pedestalRadius = cellSize * 0.42
        let pedestalRect = CGRect(
            x: rect.midX - pedestalRadius, y: rect.midY - pedestalRadius,
            width: pedestalRadius * 2, height: pedestalRadius * 2
        )
        ctx.fill(Path(ellipseIn: pedestalRect), with: .color(
            Color(red: Double(tc.r)/255, green: Double(tc.g)/255, blue: Double(tc.b)/255)
                .opacity(0.35)
        ))

        // Piece glyph — white for team_r, dark for team_l (matches JS sim)
        let textColor: Color = isR
            ? Color(red: 245.0/255.0, green: 245.0/255.0, blue: 245.0/255.0)
            : Color(red: 20.0/255.0, green: 20.0/255.0, blue: 20.0/255.0)
        let font = Font.system(size: cellSize * 0.52)
        ctx.draw(Text(glyph).font(font).foregroundColor(textColor),
                 at: CGPoint(x: rect.midX, y: rect.midY))
    }

    private func cellRect(r: Int, c: Int, cellSize: CGFloat) -> CGRect {
        CGRect(x: CGFloat(c) * cellSize, y: CGFloat(r) * cellSize, width: cellSize, height: cellSize)
    }
}
