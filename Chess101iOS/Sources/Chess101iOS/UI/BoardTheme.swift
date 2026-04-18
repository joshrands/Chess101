import SwiftUI

public struct BoardTheme {
    public let name: String
    public let lightSquare: Color
    public let darkSquare: Color
    /// Color used for the AI thinking breathing pulse and game-over overlay.
    public let checkerColor: Color
}

public let BOARD_THEMES: [BoardTheme] = [
    // Default matches the physical LED board: bright white light squares, dark off squares.
    BoardTheme(name: "Default",
               lightSquare: Color(red: 0.82, green: 0.84, blue: 0.88),
               darkSquare:  Color(red: 0.038, green: 0.048, blue: 0.065),
               checkerColor: .white),
    BoardTheme(name: "Inferno",
               lightSquare: Color(red: 0.150, green: 0.060, blue: 0.020),
               darkSquare:  Color(red: 0.050, green: 0.020, blue: 0.010),
               checkerColor: Color(red: 1.000, green: 0.314, blue: 0.078)),
    BoardTheme(name: "Void",
               lightSquare: Color(red: 0.030, green: 0.080, blue: 0.140),
               darkSquare:  Color(red: 0.010, green: 0.020, blue: 0.050),
               checkerColor: Color(red: 0.000, green: 0.710, blue: 1.000)),
    BoardTheme(name: "Jade",
               lightSquare: Color(red: 0.030, green: 0.130, blue: 0.050),
               darkSquare:  Color(red: 0.010, green: 0.040, blue: 0.020),
               checkerColor: Color(red: 0.100, green: 0.784, blue: 0.314)),
    BoardTheme(name: "Frost",
               lightSquare: Color(red: 0.080, green: 0.120, blue: 0.200),
               darkSquare:  Color(red: 0.020, green: 0.040, blue: 0.090),
               checkerColor: Color(red: 0.627, green: 0.824, blue: 1.000)),
]
