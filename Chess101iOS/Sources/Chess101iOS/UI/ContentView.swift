import SwiftUI

/// Root view — switches between phases via the shared GameSession.
public struct ContentView: View {
    @StateObject private var session = GameSession()
    @State private var show3D = false

    public init() {}

    public var body: some View {
        ZStack {
            Color(red: 0.04, green: 0.05, blue: 0.07).ignoresSafeArea()
            switch session.phase {
            case .lobby:
                LobbyView()
            case .colorPick:
                ColorPickView()
            case .warGames:
                WarGamesView()
            case .playing, .gameOver:
                gameScreen
            }
        }
        .environmentObject(session)
    }

    // MARK: - Game screen layout

    @ViewBuilder
    private var gameScreen: some View {
        GeometryReader { geo in
            let isLandscape = geo.size.width > geo.size.height
            if isLandscape {
                HStack(spacing: 0) {
                    boardArea(size: geo.size.height)
                    PanelView().frame(width: 260)
                }
            } else {
                VStack(spacing: 0) {
                    boardArea(size: geo.size.width)
                    PanelView()
                }
            }
        }
        .overlay(alignment: .topTrailing) {
            if session.phase == .playing {
                Button {
                    show3D.toggle()
                } label: {
                    Text(show3D ? "2D" : "3D")
                        .font(.system(size: 12, weight: .bold, design: .monospaced))
                        .foregroundColor(Color(red: 0.0, green: 1.0, blue: 0.53))
                        .padding(8)
                        .background(Color.white.opacity(0.07))
                        .cornerRadius(4)
                }
                .padding(12)
            }
        }
        .overlay {
            if session.phase == .gameOver { GameOverView() }
        }
    }

    @ViewBuilder
    private func boardArea(size: CGFloat) -> some View {
        ZStack {
            if show3D {
                #if canImport(UIKit)
                Board3DView(board: session.board,
                            teamR: session.teamR,
                            teamL: session.teamL,
                            currentTeam: session.currentTeam,
                            selectedCell: session.selectedCell,
                            legalTargets: session.legalTargets,
                            trails: session.trails,
                            activeAnimation: session.activeAnimation,
                            aiThinking: session.aiThinking,
                            onCellTapped: session.cellTapped)
                #endif
            } else {
                BoardView()
            }
        }
        .frame(width: size, height: size)
    }
}

// MARK: - Splash screen

struct SplashView: View {
    let onFinish: () -> Void

    @State private var revealedRows = 0
    @State private var titleVisible = false

    private let green     = Color(red: 0.0,  green: 1.0,  blue: 0.53)
    private let lightCell = Color(red: 0.22, green: 0.25, blue: 0.28)
    private let darkCell  = Color(red: 0.07, green: 0.08, blue: 0.10)

    var body: some View {
        ZStack {
            Color(red: 0.04, green: 0.05, blue: 0.07).ignoresSafeArea()
            VStack(spacing: 22) {
                VStack(spacing: 3) {
                    ForEach(0..<8, id: \.self) { row in
                        HStack(spacing: 3) {
                            ForEach(0..<8, id: \.self) { col in
                                RoundedRectangle(cornerRadius: 2)
                                    .fill((row + col) % 2 == 0 ? lightCell : darkCell)
                                    .frame(width: 30, height: 30)
                            }
                        }
                        .opacity(row < revealedRows ? 1 : 0)
                        .offset(y: row < revealedRows ? 0 : -6)
                        .animation(.spring(response: 0.28, dampingFraction: 0.72)
                                       .delay(Double(row) * 0.07),
                                   value: revealedRows)
                    }
                }

                Text("CHESS 101")
                    .font(.system(size: 28, weight: .bold, design: .monospaced))
                    .foregroundColor(green)
                    .opacity(titleVisible ? 1 : 0)
                    .animation(.easeIn(duration: 0.4), value: titleVisible)
            }
        }
        .onAppear {
            revealedRows = 8
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.65) { titleVisible = true }
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.8)  { onFinish() }
        }
    }
}
