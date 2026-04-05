import XCTest
@testable import Chess101iOS

final class RSCodecTests: XCTestCase {

    func testEncodeDecode_NoErrors() {
        let data: [UInt8] = [0x12, 0x34, 0x56, 0x78]
        let codeword = RSCodec.encode(data)
        XCTAssertEqual(codeword.count, 8)
        let decoded = RSCodec.decode(codeword)
        XCTAssertEqual(decoded, data)
    }

    func testEncodeDecode_OneError() {
        let data: [UInt8] = [0xAB, 0xCD, 0xEF, 0x01]
        var codeword = RSCodec.encode(data)
        codeword[2] ^= 0xFF  // flip one byte
        let decoded = RSCodec.decode(codeword)
        XCTAssertEqual(decoded, data)
    }

    func testEncodeDecode_TwoErrors() {
        let data: [UInt8] = [0x10, 0x20, 0x30, 0x40]
        var codeword = RSCodec.encode(data)
        codeword[1] ^= 0x55
        codeword[5] ^= 0xAA
        let decoded = RSCodec.decode(codeword)
        XCTAssertEqual(decoded, data)
    }

    func testEncodeDecode_ThreeErrors_FailsGracefully() {
        let data: [UInt8] = [0x11, 0x22, 0x33, 0x44]
        var codeword = RSCodec.encode(data)
        codeword[0] ^= 0xFF; codeword[3] ^= 0xFF; codeword[6] ^= 0xFF
        // 3 errors exceed RS(8,4) capacity — may return nil or wrong data, must not crash
        _ = RSCodec.decode(codeword)
    }
}

final class ChessMatrixRoundTripTests: XCTestCase {

    func testRoundTrip_AllCodes() {
        // Test a sample of room codes via the grid decode path (matches JS decodeColorGrid)
        for code in ["ABCDEF", "ZZZZZZ", "AAAAAA", "MNJKQR"] {
            let grid = ChessMatrixEncoder.encode(roomCode: code)
            XCTAssertEqual(grid.count, 8)
            XCTAssertEqual(grid[0].count, 8)
            let decoded = ChessMatrixDecoder.decodeColorGrid(grid)
            XCTAssertEqual(decoded, code, "Round-trip failed for \(code)")
        }
    }

    func testDataCellCount() {
        var count = 0
        for r in 0..<8 { for c in 0..<8 {
            if ChessMatrixEncoder.isDataCell(r: r, c: c) { count += 1 }
        }}
        XCTAssertEqual(count, 32)  // 8 bytes × 4 dibits
    }
}
