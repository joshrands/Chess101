import SwiftUI

public struct LobbyView: View {
    @EnvironmentObject var session: GameSession

    private let options: [(LobbyOption, String, String)] = [
        (.playLocally,  "Play Locally",  "person.2.fill"),
        (.hostOnline,   "Host Online",   "antenna.radiowaves.left.and.right"),
        (.joinOnline,   "Join Online",   "arrow.right.circle.fill"),
    ]

    @State private var selected: LobbyOption = .playLocally
    @State private var showJoinSheet: Bool = false
    @State private var joinCode: String = ""
    @State private var showScanner: Bool = false
    @State private var scannedCode: String? = nil

    public init() {}

    public var body: some View {
        ZStack {
            Color(red: 0.04, green: 0.05, blue: 0.07).ignoresSafeArea()
            VStack(spacing: 0) {
                Text("CHESS 101")
                    .font(.system(size: 28, weight: .bold, design: .monospaced))
                    .foregroundColor(Color(red: 0.0, green: 1.0, blue: 0.53))
                    .padding(.top, 48)
                    .padding(.bottom, 32)

                ForEach(options, id: \.0) { opt, label, icon in
                    let isSel = selected == opt
                    Button {
                        selected = opt
                    } label: {
                        HStack(spacing: 14) {
                            Image(systemName: icon)
                                .frame(width: 22)
                            Text(label)
                                .font(.system(size: 16, weight: .medium, design: .monospaced))
                            Spacer()
                            if isSel { Image(systemName: "chevron.right") }
                        }
                        .padding(.horizontal, 24)
                        .padding(.vertical, 16)
                        .background(isSel ? Color.white.opacity(0.06) : Color.clear)
                        .foregroundColor(isSel ? Color(red: 0.0, green: 1.0, blue: 0.53) : Color(red: 0.5, green: 0.6, blue: 0.7))
                        .cornerRadius(6)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 2)
                }

                // Online status display
                if !session.onlineStatus.isEmpty {
                    Text(session.onlineStatus)
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundColor(Color(red: 0.5, green: 0.7, blue: 0.9))
                        .padding(.top, 20)
                        .padding(.horizontal, 24)

                    if let code = session.roomCode {
                        Text(code)
                            .font(.system(size: 32, weight: .bold, design: .monospaced))
                            .foregroundColor(Color(red: 0.0, green: 1.0, blue: 0.53))
                            .padding(.top, 8)

                        // ChessMatrix grid for host to display
                        ChessMatrixGridView(roomCode: code)
                            .frame(width: 200, height: 200)
                            .padding(.top, 12)
                    }
                }

                Spacer()

                Button {
                    confirm(selected)
                } label: {
                    Text("CONFIRM")
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
        .sheet(isPresented: $showJoinSheet) {
            joinSheet
                .sheet(isPresented: $showScanner) {
                    scannerSheet
                }
        }
        .onChange(of: scannedCode) { code in
            if let code {
                joinCode = code
                scannedCode = nil
                showScanner = false
            }
        }
    }

    @ViewBuilder
    private var joinSheet: some View {
        ZStack {
            Color(red: 0.04, green: 0.05, blue: 0.07).ignoresSafeArea()
            VStack(spacing: 24) {
                Text("ENTER ROOM CODE")
                    .font(.system(size: 18, weight: .bold, design: .monospaced))
                    .foregroundColor(Color(red: 0.0, green: 1.0, blue: 0.53))

                TextField("ABCDEF", text: $joinCode)
                    .font(.system(size: 28, weight: .bold, design: .monospaced))
                    .foregroundColor(.white)
                    .multilineTextAlignment(.center)
#if canImport(UIKit)
                    .textInputAutocapitalization(.characters)
#endif
                    .autocorrectionDisabled()
                    .padding()
                    .background(Color.white.opacity(0.06))
                    .cornerRadius(8)
                    .padding(.horizontal, 40)

                Button {
                    showJoinSheet = false
                    session.startJoinGame(code: joinCode)
                } label: {
                    Text("JOIN")
                        .font(.system(size: 14, weight: .bold, design: .monospaced))
                        .foregroundColor(.black)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .background(Color(red: 0.0, green: 1.0, blue: 0.53))
                        .cornerRadius(4)
                }
                .disabled(joinCode.count < 4)
                .padding(.horizontal, 40)

                Button {
                    showScanner = true
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "camera.viewfinder")
                        Text("Scan ChessMatrix")
                            .font(.system(size: 14, weight: .medium, design: .monospaced))
                    }
                    .foregroundColor(Color(red: 0.0, green: 1.0, blue: 0.53))
                }
                .padding(.horizontal, 40)

                Button("Cancel") { showJoinSheet = false }
                    .foregroundColor(Color(red: 0.5, green: 0.6, blue: 0.7))
            }
            .padding(.top, 40)
        }
        .presentationDetents([.medium])
    }

    @ViewBuilder
    private var scannerSheet: some View {
#if canImport(UIKit)
        ZStack {
            Color.black.ignoresSafeArea()
            ScannerView(detectedCode: $scannedCode)
            VStack {
                Spacer()
                Text("Point camera at ChessMatrix grid")
                    .font(.system(size: 14, design: .monospaced))
                    .foregroundColor(.white)
                    .padding(8)
                    .background(Color.black.opacity(0.6))
                    .cornerRadius(6)
                    .padding(.bottom, 40)
            }
        }
        .presentationDetents([.large])
#else
        Text("Camera not available on this platform")
            .foregroundColor(.white)
#endif
    }

    private func confirm(_ opt: LobbyOption) {
        switch opt {
        case .playLocally:
            session.startLocalGame()
        case .hostOnline:
            session.startHostGame()
        case .joinOnline:
            joinCode = ""
            showJoinSheet = true
        case .spectate:
            break // Not yet implemented
        }
    }
}

// MARK: - ChessMatrix grid display

private struct ChessMatrixGridView: View {
    let roomCode: String

    // color 0=black, 1=red, 2=green, 3=blue
    private static let palette: [Color] = [
        Color.black,
        Color(red: 0.85, green: 0.1, blue: 0.1),
        Color(red: 0.1, green: 0.75, blue: 0.1),
        Color(red: 0.1, green: 0.3, blue: 0.9)
    ]

    var body: some View {
        let grid = ChessMatrixEncoder.encode(roomCode: roomCode)
        Canvas { ctx, size in
            let cell = size.width / 8
            for r in 0..<8 {
                for c in 0..<8 {
                    let color = Self.palette[grid[r][c]]
                    let rect = CGRect(x: CGFloat(c) * cell, y: CGFloat(r) * cell,
                                     width: cell, height: cell)
                    ctx.fill(Path(rect), with: .color(color))
                }
            }
        }
        .border(Color.white.opacity(0.3), width: 1)
    }
}
