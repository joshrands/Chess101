
import XCTest
@testable import Chess101iOS
import Chess101Engine

final class EngineTests: XCTestCase {

    var teamR: Team!
    var teamL: Team!
    var board: Board!

    override func setUp() {
        super.setUp()
        teamR = Team(r: 200, g: 200, b: 200, name: "White")
        teamL = Team(r: 40,  g: 40,  b: 40,  name: "Black")
        board = Board(teamR: teamR, teamL: teamL)
        board.initStandardPosition()
    }

    // MARK: - Board init

    func testStandardPosition_PieceCounts() {
        XCTAssertEqual(board.pieces(for: teamR).count, 16)
        XCTAssertEqual(board.pieces(for: teamL).count, 16)
    }

    func testStandardPosition_KingsPresent() {
        XCTAssertNotNil(board.king(for: teamR))
        XCTAssertNotNil(board.king(for: teamL))
    }

    func testStandardPosition_PawnsOnRow1And6() {
        for c in 0..<8 {
            XCTAssert(board.grid[1][c] is Pawn)
            XCTAssert(board.grid[6][c] is Pawn)
        }
    }

    // MARK: - Team equality (BUG-03 preserved)

    func testTeamEquality_RedChannelOnly() {
        let a = Team(r: 100, g: 0,   b: 0)
        let b = Team(r: 100, g: 200, b: 200)
        XCTAssertEqual(a, b)
        let c = Team(r: 101, g: 0, b: 0)
        XCTAssertNotEqual(a, c)
    }

    // MARK: - King check detection

    func testKing_NotInCheckAtStart() {
        let king = board.king(for: teamR)!
        let check = king.calcTargets(board: board) ?? false
        XCTAssertFalse(check)
    }

    func testKing_InCheckWhenAttacked() {
        // Place a black rook directly in front of the white king
        let king = board.king(for: teamR)!
        // Clear the row between king and an enemy piece position
        let rook = Rook(row: king.row, col: king.col + 1, team: teamL)
        board.grid[king.row][king.col + 1] = rook
        // Remove any friendly piece that might block
        board.grid[king.row][king.col - 1] = nil
        // Now put a rook on the same row far away — but need to clear path
        let testRook = Rook(row: king.row, col: 7, team: teamL)
        for c in (king.col + 1)..<7 { board.grid[king.row][c] = nil }
        board.grid[king.row][7] = testRook
        let check = king.calcTargets(board: board) ?? false
        XCTAssertTrue(check)
    }

    // MARK: - Pawn movement

    func testPawn_TwoSquaresOnFirstMove() {
        let pawn = board.grid[1][3] as! Pawn
        pawn.calcTargets(board: board)
        XCTAssertTrue(pawn.targets.contains(Cell(2, 3)))
        XCTAssertTrue(pawn.targets.contains(Cell(3, 3)))
    }

    func testPawn_DirectionFromStartingRow() {
        let pawR = board.grid[1][0] as! Pawn
        XCTAssertEqual(pawR.direction, 1)
        let pawL = board.grid[6][0] as! Pawn
        XCTAssertEqual(pawL.direction, -1)
    }

    // MARK: - Fifty-move rule (BUG-04 preserved)

    func testFiftyMoveRule_FiresAt50() {
        XCTAssertFalse(Rules.fiftyMoveRule(peaceTime: 49))
        XCTAssertTrue(Rules.fiftyMoveRule(peaceTime: 50))
    }

    // MARK: - Board hash

    func testBoardHash_ConsistentForSamePosition() {
        let h1 = boardHash(board: board, currentTeamKey: "r")
        let h2 = boardHash(board: board, currentTeamKey: "r")
        XCTAssertEqual(h1, h2)
    }

    func testBoardHash_DiffersAfterMove() {
        let h1 = boardHash(board: board, currentTeamKey: "r")
        let pawn = board.grid[1][0] as! Pawn
        board.applyMove(piece: pawn, toRow: 2, toCol: 0)
        let h2 = boardHash(board: board, currentTeamKey: "l")
        XCTAssertNotEqual(h1, h2)
    }

    // MARK: - Board copy

    func testBoardCopy_Independent() {
        let copy = board.copy()
        let pawn = copy.grid[1][0] as! Pawn
        copy.applyMove(piece: pawn, toRow: 2, toCol: 0)
        // Original board unchanged
        XCTAssert(board.grid[1][0] is Pawn)
        XCTAssertNil(board.grid[2][0])
    }
}
