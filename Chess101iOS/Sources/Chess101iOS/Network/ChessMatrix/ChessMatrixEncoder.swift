import Foundation
#if canImport(UIKit)
import UIKit
#endif

/// Encodes a 6-character room code into a ChessMatrix 8×8 four-color barcode.
/// Color encoding: 0=black, 1=red, 2=green, 3=blue.
public enum ChessMatrixEncoder {

    // MARK: - Room code → 8×8 color grid

    /// Returns an 8×8 grid of color values 0–3.
    public static func encode(roomCode: String) -> [[Int]] {
        let bytes = roomCodeToBytes(roomCode)
        let codeword = RSCodec.encode(bytes)  // 8 bytes
        let dibits = codeword.flatMap { byteToDibits($0) }  // 32 dibits

        var grid = [[Int]](repeating: [Int](repeating: 0, count: 8), count: 8)
        applyStructuralCells(&grid)

        var di = 0
        for r in 0..<8 {
            for c in 0..<8 {
                guard isDataCell(r: r, c: c) else { continue }
                grid[r][c] = Int(dibits[di]); di += 1
            }
        }
        return grid
    }

    // MARK: - Room code → bytes (5 bits per char, big-endian)

    static func roomCodeToBytes(_ code: String) -> [UInt8] {
        let chars = Array(code.uppercased())
        var bits: [Int] = []
        for ch in chars {
            let v = Int(ch.asciiValue! - 65)  // A=0, B=1, …, Z=25
            for i in stride(from: 4, through: 0, by: -1) { bits.append((v >> i) & 1) }
        }
        // Pad to 32 bits
        while bits.count < 32 { bits.append(0) }
        return (0..<4).map { i -> UInt8 in
            let slice = bits[(i*8)..<(i*8+8)]
            return UInt8(slice.enumerated().reduce(0) { $0 | ($1.element << (7 - $1.offset)) })
        }
    }

    private static func byteToDibits(_ b: UInt8) -> [UInt8] {
        [(b >> 6) & 3, (b >> 4) & 3, (b >> 2) & 3, b & 3]
    }

    // MARK: - Structural cells

    /// Returns `true` if (r, c) is a data cell (not border/anchor/timing).
    static func isDataCell(r: Int, c: Int) -> Bool {
        !isStructuralCell(r: r, c: c)
    }

    static func isStructuralCell(r: Int, c: Int) -> Bool {
        // Border ring
        if r == 0 || r == 7 || c == 0 || c == 7 { return true }
        // Calibration anchor corners (single cells)
        return (r == 1 || r == 6) && (c == 1 || c == 6)
    }

    private static func applyStructuralCells(_ grid: inout [[Int]]) {
        // Border: alternating black(0)/white(-1 represented as 3)
        for i in 0..<8 {
            grid[0][i] = i % 2 == 0 ? 0 : 3
            grid[7][i] = i % 2 == 0 ? 0 : 3
            grid[i][0] = i % 2 == 0 ? 0 : 3
            grid[i][7] = i % 2 == 0 ? 0 : 3
        }
        // Calibration anchors: K=black(0), R=red(1), G=green(2), B=blue(3)
        grid[1][1] = 0; grid[1][6] = 1; grid[6][1] = 2; grid[6][6] = 3
    }

    // MARK: - Render to RGB pixel buffer

    /// Returns a flat RGBA byte array (width × height × 4) suitable for `CGImage`.
    public static func renderToRGBA(roomCode: String, cellSize: Int = 16) -> (bytes: [UInt8], width: Int, height: Int) {
        let grid = encode(roomCode: roomCode)
        let palette: [(r: UInt8, g: UInt8, b: UInt8)] = [
            (0, 0, 0),       // 0 = black
            (220, 50, 50),   // 1 = red
            (50, 200, 80),   // 2 = green
            (60, 120, 220),  // 3 = blue
        ]
        let size = 8 * cellSize
        var bytes = [UInt8](repeating: 255, count: size * size * 4)
        for r in 0..<8 {
            for c in 0..<8 {
                let col = palette[grid[r][c]]
                for dr in 0..<cellSize {
                    for dc in 0..<cellSize {
                        let px = ((r * cellSize + dr) * size + (c * cellSize + dc)) * 4
                        bytes[px] = col.r; bytes[px+1] = col.g; bytes[px+2] = col.b; bytes[px+3] = 255
                    }
                }
            }
        }
        return (bytes, size, size)
    }
}
