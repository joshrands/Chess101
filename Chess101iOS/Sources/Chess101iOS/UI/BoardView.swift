
import SwiftUI
#if SWIFT_PACKAGE
import Chess101Engine
#endif

/// 2D canvas board — 8×8 grid with LED-style glowing cells.
/// Uses TimelineView so animations (check pulse, trails, AI breathing, win/draw) run live.
public struct BoardView: View {
    @EnvironmentObject var session: GameSession

    // Win animation: random inner-cell colors refreshed at ~5 fps
    @State private var winColors: [[Color]] = Array(
        repeating: Array(repeating: Color.black, count: 8), count: 8
    )
    @State private var winTimer: Timer? = nil

    public init() {}

    public var body: some View {
        GeometryReader { geo in
            TimelineView(.animation) { timeline in
                Canvas { ctx, size in
                    drawBoard(ctx: ctx,
                              cellSize: geo.size.width / 8,
                              t: timeline.date.timeIntervalSince1970)
                }
            }
            .contentShape(Rectangle())
            .onTapGesture { loc in
                let cellSize = geo.size.width / 8
                let col = Int(loc.x / cellSize)
                let row = Int(loc.y / cellSize)
                if row >= 0 && row < 8 && col >= 0 && col < 8 {
                    session.cellTapped(Cell(row, col))
                }
            }
        }
        .aspectRatio(1, contentMode: .fit)
        .onChange(of: session.phase) { newPhase in
            if newPhase == .gameOver && session.winner != nil {
                refreshWinColors()
                winTimer?.invalidate()
                winTimer = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { _ in
                    refreshWinColors()
                }
            } else {
                winTimer?.invalidate()
                winTimer = nil
            }
        }
        .onDisappear {
            winTimer?.invalidate()
            winTimer = nil
        }
    }

    // MARK: - Win color refresh (5 fps)

    private func refreshWinColors() {
        var next = winColors
        for r in 1..<7 {
            for c in 1..<7 {
                next[r][c] = Color(
                    red:   Double.random(in: 0.2...1.0),
                    green: Double.random(in: 0.2...1.0),
                    blue:  Double.random(in: 0.2...1.0)
                )
            }
        }
        winColors = next
    }

    // MARK: - Board drawing

    private func drawBoard(ctx: GraphicsContext, cellSize: CGFloat, t: Double) {
        guard let board = session.board else { return }
        let isGameOver = session.phase == .gameOver
        let isWin  = isGameOver && session.winner != nil
        let isDraw = isGameOver && session.isDraw

        let theme = session.theme

        for r in 0..<8 {
            for c in 0..<8 {
                let rect = cellRect(r: r, c: c, cellSize: cellSize)
                let isDark = (r + c) % 2 == 1

                // ── Win animation ─────────────────────────────────────────────
                if isWin {
                    let isPerimeter = r == 0 || r == 7 || c == 0 || c == 7
                    if isPerimeter {
                        // Pulse with winner's team color
                        let pulse = 0.4 + 0.6 * (0.5 + 0.5 * sin(t * Double.pi * 2.0))
                        if let w = session.winner {
                            ctx.fill(Path(rect), with: .color(
                                Color(red: Double(w.r)/255, green: Double(w.g)/255, blue: Double(w.b)/255)
                                    .opacity(pulse)
                            ))
                        }
                    } else {
                        ctx.fill(Path(rect), with: .color(winColors[r][c]))
                    }
                    continue
                }

                // ── Draw animation ────────────────────────────────────────────
                if isDraw {
                    let team = r < 4 ? session.teamR : session.teamL
                    ctx.fill(Path(rect), with: .color(
                        Color(red: Double(team.r)/255, green: Double(team.g)/255, blue: Double(team.b)/255)
                            .opacity(0.55)
                    ))
                    continue
                }

                // ── Base square color (theme) ─────────────────────────────────
                ctx.fill(Path(rect), with: .color(isDark ? theme.darkSquare : theme.lightSquare))

                // ── AI thinking: checker-pattern breathing pulse ───────────────
                if session.aiThinking && !isDark {
                    let pulse = 0.5 + 0.5 * sin(t * 2.0)
                    ctx.fill(Path(rect), with: .color(theme.checkerColor.opacity(0.28 * pulse)))
                }

                // ── Move trail glow ───────────────────────────────────────────
                let now = Date(timeIntervalSince1970: t)
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

                // ── Selected cell highlight ───────────────────────────────────
                if session.selectedCell == Cell(r, c) {
                    ctx.fill(Path(rect), with: .color(Color.white.opacity(0.18)))
                }

                // ── Legal target indicators ───────────────────────────────────
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

                // ── Check — king cell pulses red ──────────────────────────────
                if session.inCheck, let team = session.currentTeam,
                   let p = board.grid[r][c] as? King, p.team == team {
                    let pulse = 0.5 + 0.5 * sin(t * .pi * 4)
                    ctx.fill(Path(rect), with: .color(Color.red.opacity(0.35 * pulse)))
                }

                // ── Piece glyph ───────────────────────────────────────────────
                if let piece = board.grid[r][c] {
                    if let anim = session.activeAnimation,
                       anim.fromRow == r && anim.fromCol == c && !anim.isComplete { continue }
                    drawGlyph(ctx: ctx, piece: piece, rect: rect, cellSize: cellSize)
                }
            }
        }

        // ── Animating piece (arc in flight) ───────────────────────────────────
        if let anim = session.activeAnimation, !anim.isComplete {
            let pos = anim.position(at: Date(timeIntervalSince1970: t))
            let x = CGFloat(pos.col) * cellSize
            let y = CGFloat(pos.row) * cellSize
            let rect = CGRect(x: x, y: y, width: cellSize, height: cellSize)
            if let board = session.board, let piece = board.grid[anim.toRow][anim.toCol] {
                drawGlyph(ctx: ctx, piece: piece, rect: rect, cellSize: cellSize)
            } else {
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
