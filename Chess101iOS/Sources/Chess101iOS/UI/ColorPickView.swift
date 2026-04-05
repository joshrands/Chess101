
import SwiftUI

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
                    swatch(idx: selectedR, label: "RIGHT")
                    swatch(idx: selectedL, label: "LEFT")
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
                .disabled(selectedR == selectedL)
                .padding(.horizontal, 24)
                .padding(.bottom, 40)
            }
        }
    }

    @ViewBuilder
    private func colorCell(idx: Int, r: Double, g: Double, b: Double, name: String) -> some View {
        let isR = selectedR == idx, isL = selectedL == idx
        Button {
            if isR { selectedR = -1 }
            else if isL { selectedL = -1 }
            else if selectedR == -1 { selectedR = idx }
            else { selectedL = idx }
        } label: {
            ZStack {
                RoundedRectangle(cornerRadius: 8)
                    .fill(Color(red: r, green: g, blue: b))
                    .frame(height: 60)
                if isR { Text("R").font(.system(size: 13, weight: .bold, design: .monospaced)).foregroundColor(.black) }
                if isL { Text("L").font(.system(size: 13, weight: .bold, design: .monospaced)).foregroundColor(.white.opacity(0.8)) }
            }
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(isR || isL ? Color.white : Color.clear, lineWidth: 2))
        }
    }

    @ViewBuilder
    private func swatch(idx: Int, label: String) -> some View {
        let c = idx >= 0 ? PALETTE[idx] : (0.2, 0.2, 0.2, "—")
        HStack(spacing: 8) {
            Circle().fill(Color(red: c.0, green: c.1, blue: c.2)).frame(width: 18, height: 18)
            Text("\(label): \(c.3)")
                .font(.system(size: 12, design: .monospaced))
                .foregroundColor(Color(red: 0.6, green: 0.7, blue: 0.8))
        }
    }

    private func applyAndAdvance() {
        guard selectedR >= 0 && selectedL >= 0 && selectedR != selectedL else { return }
        let cr = PALETTE[selectedR], cl = PALETTE[selectedL]
        session.teamR = Team(r: Int(cr.r * 255), g: Int(cr.g * 255), b: Int(cr.b * 255), name: cr.name)
        session.teamL = Team(r: Int(cl.r * 255), g: Int(cl.g * 255), b: Int(cl.b * 255), name: cl.name)
        session.confirmColors()
    }
}
