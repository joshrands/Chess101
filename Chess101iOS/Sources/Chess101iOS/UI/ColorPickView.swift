
import SwiftUI
#if SWIFT_PACKAGE
import Chess101Engine
#endif

private let PALETTE: [(r: Double, g: Double, b: Double, name: String)] = [
    (64/255,  180/255, 232/255, "Blue"),      (190/255, 25/255,  255/255, "Purple"),
    (254/255, 220/255, 0/255,   "Yellow"),    (250/255, 125/255, 125/255, "Pink"),
    (25/255,  255/255, 35/255,  "Green"),     (245/255, 125/255, 0/255,   "Orange"),
    (0/255,   25/255,  230/255, "Dark Blue"), (28/255,  225/255, 180/255, "Cyan"),
]

public struct ColorPickView: View {
    @EnvironmentObject var session: GameSession
    @State private var selectedR: Int = 0
    @State private var selectedL: Int = 1

    public init() {}

    // In online mode, each player only picks their own team's color.
    private var isOnlineHost: Bool  { session.isOnline && session.localTeamKey == "r" }
    private var isOnlineGuest: Bool { session.isOnline && session.localTeamKey == "l" }
    private var isOnline: Bool      { session.isOnline }

    // CONFIRM is disabled when the local slot is unset, or (local only) when both same.
    private var confirmDisabled: Bool {
        if isOnlineHost  { return selectedR < 0 }
        if isOnlineGuest { return selectedL < 0 }
        return selectedR < 0 || selectedL < 0 || selectedR == selectedL
    }

    public var body: some View {
        ZStack {
            Color(red: 0.04, green: 0.05, blue: 0.07).ignoresSafeArea()
            VStack(spacing: 0) {
                Text("CHOOSE COLORS")
                    .font(.system(size: 20, weight: .bold, design: .monospaced))
                    .foregroundColor(Color(red: 0.0, green: 1.0, blue: 0.53))
                    .padding(.vertical, 28)

                Grid(horizontalSpacing: 10, verticalSpacing: 10) {
                    ForEach(0..<4) { row in
                        GridRow {
                            ForEach(0..<2) { col in
                                let idx = row * 2 + col
                                let c = PALETTE[idx]
                                colorCell(idx: idx, r: c.r, g: c.g, b: c.b, name: c.name)
                            }
                        }
                    }
                }
                .padding(.horizontal, 24)

                Spacer()

                HStack(spacing: 20) {
                    swatch(idx: selectedR, label: "RIGHT",
                           isOpponent: isOnlineGuest,
                           opponentColor: session.teamR)
                    swatch(idx: selectedL, label: "LEFT",
                           isOpponent: isOnlineHost,
                           opponentColor: session.teamL)
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 16)

                Button {
                    applyAndAdvance()
                } label: {
                    Text("CONFIRM")
                        .font(.system(size: 14, weight: .bold, design: .monospaced))
                        .foregroundColor(.black)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .background(Color(red: 0.0, green: 1.0, blue: 0.53))
                        .cornerRadius(4)
                }
                .disabled(confirmDisabled)
                .padding(.horizontal, 24)
                .padding(.bottom, 40)

                if isOnline && !session.onlineStatus.isEmpty {
                    Text(session.onlineStatus)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundColor(Color(red: 0.5, green: 0.7, blue: 0.9))
                        .padding(.bottom, 12)
                }
            }
        }
    }

    @ViewBuilder
    private func colorCell(idx: Int, r: Double, g: Double, b: Double, name: String) -> some View {
        let isR = selectedR == idx, isL = selectedL == idx
        Button {
            if isOnlineHost {
                // HOST picks only their right-team color
                selectedR = (selectedR == idx) ? -1 : idx
            } else if isOnlineGuest {
                // GUEST picks only their left-team color
                selectedL = (selectedL == idx) ? -1 : idx
            } else {
                // Local: toggle between R and L slots
                if isR      { selectedR = -1 }
                else if isL { selectedL = -1 }
                else if selectedR == -1 { selectedR = idx }
                else        { selectedL = idx }
            }
        } label: {
            ZStack {
                RoundedRectangle(cornerRadius: 8)
                    .fill(Color(red: r, green: g, blue: b))
                    .frame(height: 60)
                if isR { Text("R").font(.system(size: 13, weight: .bold, design: .monospaced)).foregroundColor(.black) }
                if isL { Text("L").font(.system(size: 13, weight: .bold, design: .monospaced)).foregroundColor(.white.opacity(0.8)) }
            }
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(isR || isL ? Color.white : Color.clear, lineWidth: 2))
            // Dim the opponent's slot in online mode
            .opacity(dimmed(idx: idx) ? 0.35 : 1.0)
        }
        .disabled(dimmed(idx: idx))
    }

    /// Returns true when this color slot belongs to the opponent (should not be interactive online).
    private func dimmed(idx: Int) -> Bool {
        guard isOnline else { return false }
        // Dimmed colors are those already selected by the opponent (not the local player's choice)
        return false  // all 8 colors always visible; opponent's slot just isn't interactive
    }

    @ViewBuilder
    private func swatch(idx: Int, label: String, isOpponent: Bool, opponentColor: Team) -> some View {
        if isOpponent {
            // Opponent's color: show "waiting" until peerConfirmedColors
            HStack(spacing: 8) {
                Circle()
                    .fill(Color(red: 0.2, green: 0.2, blue: 0.2))
                    .frame(width: 18, height: 18)
                Text("\(label): —")
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundColor(Color(red: 0.4, green: 0.5, blue: 0.6))
            }
        } else {
            let c = idx >= 0 ? PALETTE[idx] : (0.2, 0.2, 0.2, "—")
            HStack(spacing: 8) {
                Circle().fill(Color(red: c.0, green: c.1, blue: c.2)).frame(width: 18, height: 18)
                Text("\(label): \(c.3)")
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundColor(Color(red: 0.6, green: 0.7, blue: 0.8))
            }
        }
    }

    private func applyAndAdvance() {
        if isOnlineHost {
            guard selectedR >= 0 else { return }
            let cr = PALETTE[selectedR]
            session.teamR = Team(r: Int(cr.r * 255), g: Int(cr.g * 255), b: Int(cr.b * 255), name: cr.name)
            session.confirmColors()
        } else if isOnlineGuest {
            guard selectedL >= 0 else { return }
            let cl = PALETTE[selectedL]
            session.teamL = Team(r: Int(cl.r * 255), g: Int(cl.g * 255), b: Int(cl.b * 255), name: cl.name)
            session.confirmColors()
        } else {
            guard selectedR >= 0 && selectedL >= 0 && selectedR != selectedL else { return }
            let cr = PALETTE[selectedR], cl = PALETTE[selectedL]
            session.teamR = Team(r: Int(cr.r * 255), g: Int(cr.g * 255), b: Int(cr.b * 255), name: cr.name)
            session.teamL = Team(r: Int(cl.r * 255), g: Int(cl.g * 255), b: Int(cl.b * 255), name: cl.name)
            session.confirmColors()
        }
    }
}
