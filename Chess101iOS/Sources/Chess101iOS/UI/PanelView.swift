
import SwiftUI
#if SWIFT_PACKAGE
import Chess101Engine
#endif

public struct PanelView: View {
    @EnvironmentObject var session: GameSession

    public init() {}

    public var body: some View {
        ZStack {
            Color(red: 0.028, green: 0.047, blue: 0.094).ignoresSafeArea()
            VStack(alignment: .leading, spacing: 0) {
                topSection
                Divider().background(Color.white.opacity(0.07)).padding(.vertical, 6)
                logSection
            }
            .padding(.horizontal, 14)
            .padding(.top, 10)
        }
    }

    // MARK: - Top section

    @ViewBuilder
    private var topSection: some View {
        Group {
            if let team = session.currentTeam {
                label("TURN")
                HStack(spacing: 6) {
                    Circle()
                        .fill(Color(red: Double(team.r)/255, green: Double(team.g)/255, blue: Double(team.b)/255))
                        .frame(width: 10, height: 10)
                    Text(team.name)
                        .font(.system(size: 13, design: .monospaced))
                        .foregroundColor(Color(red: 0.78, green: 0.82, blue: 0.88))
                }
                .padding(.bottom, 6)

                label("MOVE")
                value("\(session.moveCount)").padding(.bottom, 6)

                // Peace bar
                label("PEACE  \(session.peaceTime)/50")
                GeometryReader { g in
                    ZStack(alignment: .leading) {
                        RoundedRectangle(cornerRadius: 2).fill(Color.white.opacity(0.07)).frame(height: 4)
                        RoundedRectangle(cornerRadius: 2)
                            .fill(session.peaceTime > 40 ? Color.red : Color(red: 0.0, green: 1.0, blue: 0.53))
                            .frame(width: g.size.width * CGFloat(min(session.peaceTime, 50)) / 50, height: 4)
                    }
                }.frame(height: 4).padding(.bottom, 8)

                // Eval bar
                if let board = session.board {
                    EvalBarView(board: board, teamR: session.teamR, teamL: session.teamL)
                        .padding(.bottom, 8)
                }

                // Alerts
                if session.inCheck {
                    alertBadge("⚠ CHECK", color: .red)
                }
                if session.aiThinking {
                    alertBadge("AI thinking…", color: .blue)
                }
                if let code = session.roomCode {
                    alertBadge("ROOM: \(code)", color: Color(red: 0.0, green: 1.0, blue: 0.53))
                }

                // Board theme
                HStack(spacing: 0) {
                    Text("THEME")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundColor(Color(red: 0.23, green: 0.29, blue: 0.38))
                    Spacer()
                    Button {
                        session.cycleTheme()
                    } label: {
                        HStack(spacing: 4) {
                            Text(BOARD_THEMES[session.themeIndex].name.uppercased())
                                .font(.system(size: 10, design: .monospaced))
                                .foregroundColor(Color(red: 0.50, green: 0.56, blue: 0.63))
                            Text("[T]")
                                .font(.system(size: 9, design: .monospaced))
                                .foregroundColor(Color(red: 0.30, green: 0.36, blue: 0.44))
                        }
                    }
                    .buttonStyle(.plain)
                }
                .padding(.top, 4)
                .padding(.bottom, 6)
            }
        }
    }

    // MARK: - Log

    @ViewBuilder
    private var logSection: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(Array(session.moveLog.suffix(30).enumerated()), id: \.offset) { i, line in
                        Text(line)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundColor(i >= session.moveLog.count - 3
                                ? Color(red: 0.5, green: 0.56, blue: 0.63)
                                : Color(red: 0.29, green: 0.38, blue: 0.5))
                            .id(i)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .onChange(of: session.moveLog.count) { _ in
                let last = max(0, session.moveLog.count - 1)
                withAnimation { proxy.scrollTo(last) }
            }
        }
    }

    // MARK: - Helpers

    @ViewBuilder private func label(_ s: String) -> some View {
        Text(s).font(.system(size: 10, design: .monospaced))
            .foregroundColor(Color(red: 0.23, green: 0.29, blue: 0.38))
            .padding(.bottom, 2)
    }

    @ViewBuilder private func value(_ s: String) -> some View {
        Text(s).font(.system(size: 13, design: .monospaced))
            .foregroundColor(Color(red: 0.78, green: 0.82, blue: 0.88))
    }

    @ViewBuilder private func alertBadge(_ s: String, color: Color) -> some View {
        Text(s)
            .font(.system(size: 11, design: .monospaced))
            .foregroundColor(color)
            .padding(.horizontal, 8).padding(.vertical, 4)
            .overlay(RoundedRectangle(cornerRadius: 2).stroke(color.opacity(0.4), lineWidth: 1))
            .padding(.bottom, 6)
    }
}
