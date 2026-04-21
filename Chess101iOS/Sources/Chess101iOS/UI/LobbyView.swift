import SwiftUI

public struct LobbyView: View {
    @EnvironmentObject var session: GameSession

    private let options: [(LobbyOption, String, String)] = [
        (.playLocally,  "Play Locally",   "person.2.fill"),
        (.hostOnline,   "Host Online",    "antenna.radiowaves.left.and.right"),
        (.joinOnline,   "Join Online",    "arrow.right.circle.fill"),
        (.spectate,     "Watch Online",   "eye.fill"),
    ]

    @State private var selected: LobbyOption = .playLocally
    @State private var showJoinSheet: Bool = false
    @State private var showSpectateSheet: Bool = false
    @State private var joinCode: String = ""
    @State private var showScanner: Bool = false
    @State private var scannedCode: String? = nil
    @State private var scanDebugInfo: ScanDebugInfo = ScanDebugInfo()
    @State private var showScanDebug: Bool = false

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
            codeEntrySheet(title: "ENTER ROOM CODE", buttonLabel: "JOIN") { code in
                session.startJoinGame(code: code)
            }
            .sheet(isPresented: $showScanner) {
                scannerSheet
            }
        }
        .sheet(isPresented: $showSpectateSheet) {
            codeEntrySheet(title: "WATCH A GAME", buttonLabel: "WATCH") { code in
                session.startSpectateGame(code: code)
            }
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
    private func codeEntrySheet(title: String, buttonLabel: String,
                                 onConfirm: @escaping (String) -> Void) -> some View {
        ZStack {
            Color(red: 0.04, green: 0.05, blue: 0.07).ignoresSafeArea()
            VStack(spacing: 24) {
                Text(title)
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
                    let code = joinCode
                    showJoinSheet = false
                    showSpectateSheet = false
                    onConfirm(code)
                } label: {
                    Text(buttonLabel)
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

                Button("Cancel") {
                    showJoinSheet = false
                    showSpectateSheet = false
                }
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
            ScannerView(detectedCode: $scannedCode, debugInfo: $scanDebugInfo)
            VStack {
                HStack {
                    Spacer()
                    Button {
                        showScanDebug.toggle()
                    } label: {
                        Image(systemName: showScanDebug ? "ant.fill" : "ant")
                            .foregroundColor(showScanDebug ? Color(red: 0.0, green: 1.0, blue: 0.53) : Color(white: 0.5))
                            .font(.system(size: 20))
                            .padding(12)
                    }
                }
                Spacer()
                if showScanDebug {
                    ScanDebugOverlay(info: scanDebugInfo)
                        .padding(.bottom, 40)
                }
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
            joinCode = ""
            showSpectateSheet = true
        }
    }
}

// MARK: - ChessMatrix grid display

private struct ChessMatrixGridView: View {
    let roomCode: String

    private static let palette: [Color] = [
        Color.black,                                   // 0 = black
        Color(red: 0.85, green: 0.10, blue: 0.10),    // 1 = red
        Color(red: 0.10, green: 0.75, blue: 0.10),    // 2 = green
        Color(red: 0.10, green: 0.30, blue: 0.90),    // 3 = blue
        Color(white: 0.92),                            // 4 = bright white (L-finder / timing)
        Color(white: 0.04),                            // 5 = near-black  (timing)
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

// MARK: - Scanner debug overlay

#if canImport(UIKit)
private struct ScanDebugOverlay: View {
    let info: ScanDebugInfo

    private let stages: [(String, KeyPath<ScanDebugInfo, Bool>)] = [
        ("Centroid", \.centroidFound),
        ("Axes",     \.axesFound),
        ("Quad",     \.quadFound),
        ("Warp",     \.warpedFound),
        ("Cal",      \.calFound),
        ("Grid",     \.gridFound),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Point camera at ChessMatrix grid")
                .font(.system(size: 13, design: .monospaced))
                .foregroundColor(.white)

            // Pipeline stage indicators
            HStack(spacing: 10) {
                ForEach(stages, id: \.0) { label, kp in
                    let ok = info[keyPath: kp]
                    VStack(spacing: 2) {
                        Image(systemName: ok ? "checkmark.circle.fill" : "xmark.circle")
                            .foregroundColor(ok ? .green : Color(white: 0.4))
                            .font(.system(size: 14))
                        Text(label)
                            .font(.system(size: 9, design: .monospaced))
                            .foregroundColor(ok ? .white : Color(white: 0.4))
                    }
                }
                // 7th stage: RS decode + room code
                let codeOk = info.code != nil
                VStack(spacing: 2) {
                    Image(systemName: codeOk ? "checkmark.circle.fill" : "xmark.circle")
                        .foregroundColor(codeOk ? .green : Color(white: 0.4))
                        .font(.system(size: 14))
                    Text("RS")
                        .font(.system(size: 9, design: .monospaced))
                        .foregroundColor(codeOk ? .white : Color(white: 0.4))
                }
            }

            // Binary + warped thumbnails side by side
            HStack(spacing: 8) {
                if let thumb = info.binaryThumb {
                    VStack(spacing: 2) {
                        pixelsImage(thumb, size: 128, display: 80)
                        Text("binary").font(.system(size: 9, design: .monospaced)).foregroundColor(.gray)
                    }
                }
                if let warped = info.warpedPixels {
                    VStack(spacing: 2) {
                        pixelsImage(warped, size: 128, display: 80)
                        Text("warped").font(.system(size: 9, design: .monospaced)).foregroundColor(.gray)
                    }
                }
            }

            // Calibration color swatches
            if let cal = info.calRGB {
                let names = ["K", "R", "G", "B"]
                HStack(spacing: 8) {
                    ForEach(0..<min(cal.count, 4), id: \.self) { i in
                        let c = cal[i]
                        HStack(spacing: 3) {
                            Circle()
                                .fill(Color(red: Double(c.r)/255, green: Double(c.g)/255, blue: Double(c.b)/255))
                                .frame(width: 12, height: 12)
                                .overlay(Circle().stroke(Color.white.opacity(0.4), lineWidth: 0.5))
                            Text("\(names[i]) \(Int(c.r)),\(Int(c.g)),\(Int(c.b))")
                                .font(.system(size: 9, design: .monospaced))
                                .foregroundColor(.white.opacity(0.8))
                        }
                    }
                }
            }

            if let code = info.code {
                Text("✓ \(code)")
                    .font(.system(size: 18, weight: .bold, design: .monospaced))
                    .foregroundColor(.green)
            }
        }
        .padding(12)
        .background(Color.black.opacity(0.82))
        .cornerRadius(10)
    }

    @ViewBuilder
    private func pixelsImage(_ rgba: [UInt8], size: Int, display: CGFloat) -> some View {
        if let img = makeImage(rgba, size: size) {
            Image(uiImage: img)
                .resizable()
                .interpolation(.none)
                .frame(width: display, height: display)
                .border(Color.white.opacity(0.3), width: 1)
        }
    }

    private func makeImage(_ rgba: [UInt8], size: Int) -> UIImage? {
        var data = rgba
        return data.withUnsafeMutableBytes { ptr in
            guard let base = ptr.baseAddress else { return nil }
            let space = CGColorSpaceCreateDeviceRGB()
            guard let ctx = CGContext(data: base, width: size, height: size,
                                      bitsPerComponent: 8, bytesPerRow: size * 4,
                                      space: space,
                                      bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue),
                  let cgImg = ctx.makeImage() else { return nil }
            return UIImage(cgImage: cgImg)
        }
    }
}
#endif
