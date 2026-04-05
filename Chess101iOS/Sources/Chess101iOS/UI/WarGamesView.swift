
import SwiftUI

public struct WarGamesView: View {
    @EnvironmentObject var session: GameSession
    @State private var typeR: PlayerType = .human
    @State private var typeL: PlayerType = .ai

    public init() {}

    public var body: some View {
        ZStack {
            Color(red: 0.04, green: 0.05, blue: 0.07).ignoresSafeArea()
            VStack(spacing: 0) {
                Text("WAR GAMES")
                    .font(.system(size: 20, weight: .bold, design: .monospaced))
                    .foregroundColor(Color(red: 0.0, green: 1.0, blue: 0.53))
                    .padding(.vertical, 28)

                row(team: session.teamR, type: $typeR, label: "RIGHT")
                    .padding(.bottom, 12)
                row(team: session.teamL, type: $typeL, label: "LEFT")

                Spacer()

                Button {
                    session.playerTypeR = typeR
                    session.playerTypeL = typeL
                    session.confirmWarGames()
                } label: {
                    Text("START GAME")
                        .font(.system(size: 14, weight: .bold, design: .monospaced))
                        .foregroundColor(.black)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .background(Color(red: 0.0, green: 1.0, blue: 0.53))
                        .cornerRadius(4)
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 40)
            }
        }
    }

    @ViewBuilder
    private func row(team: Team, type: Binding<PlayerType>, label: String) -> some View {
        HStack(spacing: 0) {
            Circle()
                .fill(Color(red: Double(team.r)/255, green: Double(team.g)/255, blue: Double(team.b)/255))
                .frame(width: 14, height: 14)
                .padding(.leading, 24)
            Text("  \(team.name)")
                .font(.system(size: 14, design: .monospaced))
                .foregroundColor(Color(red: 0.7, green: 0.8, blue: 0.9))
            Spacer()
            Picker("", selection: type) {
                Text("Human").tag(PlayerType.human)
                Text("AI").tag(PlayerType.ai)
            }
            .pickerStyle(.segmented)
            .frame(width: 160)
            .padding(.trailing, 24)
        }
        .frame(height: 52)
        .background(Color.white.opacity(0.04))
        .cornerRadius(6)
        .padding(.horizontal, 16)
    }
}
