
import SwiftUI

public struct GameOverView: View {
    @EnvironmentObject var session: GameSession

    public init() {}

    public var body: some View {
        ZStack {
            Color(red: 0.04, green: 0.05, blue: 0.07).ignoresSafeArea()
            VStack(spacing: 20) {
                Spacer()
                if session.isDraw {
                    Text("DRAW")
                        .font(.system(size: 36, weight: .bold, design: .monospaced))
                        .foregroundColor(Color(red: 0.6, green: 0.7, blue: 0.8))
                } else if let winner = session.winner {
                    Text("\(winner.name.uppercased())")
                        .font(.system(size: 32, weight: .bold, design: .monospaced))
                        .foregroundColor(
                            Color(red: Double(winner.r)/255, green: Double(winner.g)/255, blue: Double(winner.b)/255)
                        )
                    Text("WINS BY CHECKMATE")
                        .font(.system(size: 14, design: .monospaced))
                        .foregroundColor(Color(red: 0.5, green: 0.6, blue: 0.7))
                }
                Spacer()
                Button {
                    session.newGame()
                } label: {
                    Text("NEW GAME")
                        .font(.system(size: 14, weight: .bold, design: .monospaced))
                        .foregroundColor(.black)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .background(Color(red: 0.0, green: 1.0, blue: 0.53))
                        .cornerRadius(4)
                }
                .padding(.horizontal, 40)
                .padding(.bottom, 50)
            }
        }
    }
}
