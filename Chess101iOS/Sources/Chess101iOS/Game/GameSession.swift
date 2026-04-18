
import Foundation
import Combine
import SwiftUI
#if SWIFT_PACKAGE
import Chess101Engine
#endif

/// Central game state owned by the SwiftUI view hierarchy.
/// All mutations happen on the MainActor.
@MainActor
public final class GameSession: ObservableObject {

    // MARK: - Published state

    @Published public var phase: GamePhase = .lobby
    @Published public var board: Board?
    @Published public var currentTeam: Team?
    @Published public var teamR: Team = Team(r: 64,  g: 180, b: 232, name: "Blue")
    @Published public var teamL: Team = Team(r: 190, g: 25,  b: 255, name: "Purple")
    @Published public var playerTypeR: PlayerType = .human
    @Published public var playerTypeL: PlayerType = .human
    @Published public var selectedCell: Cell? = nil
    @Published public var legalTargets: [Cell] = []
    @Published public var inCheck: Bool = false
    @Published public var isDraw: Bool = false
    @Published public var winner: Team? = nil
    @Published public var moveLog: [String] = []
    @Published public var peaceTime: Int = 0
    @Published public var aiThinking: Bool = false
    @Published public var activeAnimation: MoveAnimation? = nil
    @Published public var trails: [MoveTrail] = []
    @Published public var kibitzOn: Bool = true
    @Published public var moveCount: Int = 0

    // Online multiplayer
    @Published public var relayClient: RelayClient?
    @Published public var roomCode: String?
    @Published public var isOnline: Bool = false
    @Published public var isMyTurn: Bool = true
    @Published public var onlineStatus: String = ""
    @Published public var connectionLost: Bool = false

    /// "r" for host, "l" for joiner, "spectator" for watch-only
    public var localTeamKey: String = "r"
    public private(set) var isSpectator: Bool = false

    // Board theme
    @Published public var themeIndex: Int = 0
    public var theme: BoardTheme { BOARD_THEMES[themeIndex] }
    public func cycleTheme() { themeIndex = (themeIndex + 1) % BOARD_THEMES.count }

    private let aiEngine = AlphaBeta(depth: 2)
    private var seq: Int = 0
    private var relayListenTask: Task<Void, Never>?

    // Online setup protocol gates
    private var localConfirmedColors = false
    private var peerConfirmedColors  = false
    private var localConfirmedWG     = false
    private var peerConfirmedWG      = false

    // MARK: - Phase transitions

    public func startLocalGame() {
        reset()
        phase = .colorPick
    }

    public func startHostGame() {
        reset()
        isOnline = true
        localTeamKey = "r"
        onlineStatus = "Creating room..."
        let relay = RelayClient()
        relayClient = relay
        Task {
            do {
                let code = try await relay.createRoom(playerName: "Host")
                roomCode = code
                onlineStatus = "Room \(code) — waiting for opponent..."
                startRelayListener()
            } catch {
                onlineStatus = "Error: \(error.localizedDescription)"
                isOnline = false
            }
        }
    }

    public func startJoinGame(code: String) {
        reset()
        isOnline = true
        localTeamKey = "l"
        onlineStatus = "Joining room \(code.uppercased())..."
        let relay = RelayClient()
        relayClient = relay
        Task {
            do {
                _ = try await relay.joinRoom(code: code, playerName: "Guest")
                roomCode = code.uppercased()
                onlineStatus = "Waiting for host to start..."
                startRelayListener()
            } catch {
                onlineStatus = "Error: \(error.localizedDescription)"
                isOnline = false
            }
        }
    }

    public func startSpectateGame(code: String) {
        reset()
        isOnline = true
        isSpectator = true
        localTeamKey = "spectator"
        isMyTurn = false
        onlineStatus = "Connecting to game \(code.uppercased())..."
        let relay = RelayClient()
        relayClient = relay
        Task {
            do {
                try await relay.spectate(code: code)
                roomCode = code.uppercased()
                onlineStatus = "Watching \(code.uppercased())"
                startRelayListener()
            } catch {
                onlineStatus = "Error: \(error.localizedDescription)"
                isOnline = false
                isSpectator = false
            }
        }
    }

    private func startRelayListener() {
        guard let relay = relayClient else { return }
        relay.onConnectionLost = { [weak self] in
            Task { @MainActor [weak self] in
                self?.connectionLost = true
            }
        }
        relay.startKeepalive()
        relayListenTask = Task { [weak self] in
            for await msg in relay.messageStream {
                guard let self else { return }
                await MainActor.run { self.handleRelayMessage(msg) }
            }
        }
    }

    // MARK: - Setup protocol

    /// Called by ColorPickView after the local player confirms their color.
    public func confirmColors() {
        if isOnline {
            let teamKey = localTeamKey
            let team = localTeamKey == "r" ? teamR : teamL
            let msg: [String: Any] = [
                "type": "color_chosen",
                "team_key": teamKey,
                "r": team.r, "g": team.g, "b": team.b, "name": team.name
            ]
            try? relayClient?.send(msg)
            localConfirmedColors = true
            onlineStatus = "Waiting for opponent's color..."
            if peerConfirmedColors { phase = .warGames }
        } else {
            phase = .warGames
        }
    }

    /// Called by WarGamesView after the local player confirms their player-type choice.
    public func confirmWarGames() {
        if isOnline {
            let teamKey = localTeamKey
            let pt = localTeamKey == "r" ? playerTypeR : playerTypeL
            let msg: [String: Any] = [
                "type": "war_games_choice",
                "team_key": teamKey,
                "player_type": pt == .ai ? "ai" : "human"
            ]
            try? relayClient?.send(msg)
            localConfirmedWG = true
            onlineStatus = "Waiting for opponent..."
            if peerConfirmedWG {
                finishSetupAsHost()
            }
            // GUEST: startBoard() triggered by incoming game_start
        } else {
            startBoard()
        }
    }

    private func finishSetupAsHost() {
        guard localTeamKey == "r" else { return }
        let startMsg: [String: Any] = [
            "type": "game_start",
            "tRr": teamR.r, "tRg": teamR.g, "tRb": teamR.b, "tRname": teamR.name,
            "tLr": teamL.r, "tLg": teamL.g, "tLb": teamL.b, "tLname": teamL.name,
            "ptR": playerTypeR == .ai ? "ai" : "human",
            "ptL": playerTypeL == .ai ? "ai" : "human"
        ]
        try? relayClient?.send(startMsg)
        startBoard()
    }

    private func startBoard() {
        let b = Board(teamR: teamR, teamL: teamL)
        b.initStandardPosition()
        board = b
        currentTeam = teamR
        moveCount = 0
        peaceTime = 0
        if isOnline { isMyTurn = localTeamKey == "r" }
        phase = .playing
        beginTurn()
    }

    public func newGame() {
        reset()
        phase = .lobby
    }

    private func reset() {
        board = nil; currentTeam = nil; selectedCell = nil; legalTargets = []
        inCheck = false; isDraw = false; winner = nil
        moveLog = []; peaceTime = 0; aiThinking = false
        activeAnimation = nil; trails = []; moveCount = 0; seq = 0
        relayListenTask?.cancel(); relayListenTask = nil
        relayClient?.disconnect(); relayClient = nil
        roomCode = nil; isOnline = false; isMyTurn = true; onlineStatus = ""
        isSpectator = false; connectionLost = false
        localConfirmedColors = false; peerConfirmedColors = false
        localConfirmedWG = false; peerConfirmedWG = false
    }

    // MARK: - Turn logic

    private func beginTurn() {
        guard let board, let team = currentTeam else { return }

        var king: King? = nil
        var check = false
        for p in board.pieces(for: team) {
            if let k = p as? King { king = k; check = k.calcTargets(board: board) == true }
        }
        for p in board.pieces(for: team) {
            guard !(p is King) else { continue }
            p.calcTargets(board: board)
            if p.critical { p.criticalMan() }
            if check, let k = king { p.skyFall(king: k) }
        }

        inCheck = check
        let hasMoves = board.pieces(for: team).contains { !$0.targets.isEmpty }
        if !hasMoves {
            if check { endGame(winner: opponent(of: team)) }
            else      { endGame(winner: nil) }
            return
        }

        if Rules.fiftyMoveRule(peaceTime: peaceTime) ||
           Rules.threefoldRepetition(history: board.positionHistory,
                                      current: Rules.positionKey(board: board)) {
            endGame(winner: nil)
            return
        }

        if !isSpectator && isAI(team: team) { triggerAI() }
    }

    // MARK: - Human move

    public func cellTapped(_ cell: Cell) {
        guard phase == .playing, let board, let team = currentTeam else { return }
        guard isMyTurn, !aiThinking else { return }

        if let sel = selectedCell {
            if legalTargets.contains(cell) {
                guard let piece = board.grid[sel.row][sel.col], piece.team == team else {
                    selectedCell = nil; legalTargets = []; return
                }
                executeMove(piece: piece, to: cell)
            } else if let p = board.grid[cell.row][cell.col], p.team == team {
                selectedCell = cell
                legalTargets = p.targets
            } else {
                selectedCell = nil; legalTargets = []
            }
        } else {
            if let p = board.grid[cell.row][cell.col], p.team == team {
                selectedCell = cell
                legalTargets = p.targets
            }
        }
    }

    private func executeMove(piece: Piece, to: Cell) {
        guard let board else { return }
        let from = Cell(piece.row, piece.col)
        let captured = board.applyMove(piece: piece, toRow: to.row, toCol: to.col)
        moveCount += 1
        peaceTime = (captured != nil || piece is Pawn) ? 0 : peaceTime + 1
        board.positionHistory.append(Rules.positionKey(board: board))

        addTrail(from: from, to: to, team: piece.team, piece: piece)
        let anim = MoveAnimation(piece: piece.typeName, team: piece.team,
                                  fromRow: from.row, fromCol: from.col,
                                  toRow: to.row, toCol: to.col)
        activeAnimation = anim
        // Clear after arc completes so the 3D view re-renders and shows the piece at destination.
        DispatchQueue.main.asyncAfter(deadline: .now() + anim.duration + 0.05) { [weak self] in
            self?.activeAnimation = nil
        }
        logMove(piece: piece, from: from, to: to, captured: captured)

        if isOnline && !isSpectator { sendMove(piece: piece, from: from, to: to, captured: captured) }

        selectedCell = nil; legalTargets = []
        swapTurns()
    }

    // MARK: - AI

    private func triggerAI() {
        guard let board, let team = currentTeam else { return }
        aiThinking = true
        let root = GameTree(board: board.copy(), teamR: teamR, teamL: teamL)
        Task.detached(priority: .userInitiated) { [weak self] in
            guard let self else { return }
            let best = await self.aiEngine.search(root: root, team: team)
            await MainActor.run {
                self.aiThinking = false
                guard let move = best?.move, let board = self.board else { return }
                guard let piece = board.grid[move.from.row][move.from.col] else { return }
                self.executeMove(piece: piece, to: move.to)
            }
        }
    }

    // MARK: - Game over

    private func endGame(winner w: Team?) {
        winner = w; isDraw = w == nil; phase = .gameOver
        if let w { moveLog.append("\(w.name) wins by checkmate!") }
        else      { moveLog.append("Draw!") }
    }

    // MARK: - Helpers

    private func swapTurns() {
        guard let team = currentTeam else { return }
        currentTeam = (team == teamR) ? teamL : teamR
        if isOnline {
            let nextTeamKey = currentTeam == teamR ? "r" : "l"
            isMyTurn = nextTeamKey == localTeamKey
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
            self?.beginTurn()
        }
    }

    private func opponent(of team: Team) -> Team { team == teamR ? teamL : teamR }

    private func isAI(team: Team) -> Bool {
        team == teamR ? playerTypeR == .ai : playerTypeL == .ai
    }

    private func logMove(piece: Piece, from: Cell, to: Cell, captured: Piece?) {
        var s = "\(piece.typeName) \(from)→\(to)"
        if let c = captured { s += " ×\(c.typeName)" }
        moveLog.append(s)
    }

    private func addTrail(from: Cell, to: Cell, team: Team, piece: Piece) {
        var cells = [from]
        if piece is Rook || piece is Bishop || piece is Queen {
            let dr = to.row == from.row ? 0 : (to.row > from.row ? 1 : -1)
            let dc = to.col == from.col ? 0 : (to.col > from.col ? 1 : -1)
            var r = from.row + dr, c = from.col + dc
            while r != to.row || c != to.col { cells.append(Cell(r, c)); r += dr; c += dc }
        }
        trails.append(MoveTrail(cells: cells, team: team, startTime: Date()))
        trails = trails.filter { !$0.isExpired }
    }

    // MARK: - Online send

    private func sendMove(piece: Piece, from: Cell, to: Cell, captured: Piece?) {
        guard let relay = relayClient, let board, let team = currentTeam else { return }
        var flags = MoveFlags()
        flags.isCapture = captured != nil
        let teamKey = team == teamR ? "r" : "l"
        let msg = buildMoveMessage(piece: piece, fromRow: from.row, fromCol: from.col,
                                    toRow: to.row, toCol: to.col,
                                    flags: flags, board: board, teamKey: teamKey, seq: seq)
        seq += 1
        try? relay.send(msg)
    }

    // MARK: - Online receive

    public func handleRelayMessage(_ msg: [String: Any]) {
        guard let type = msg["type"] as? String else { return }
        switch type {

        case "move":
            applyRemoteMove(msg)

        case "relay_peer_connected":
            onlineStatus = "Opponent connected!"
            moveLog.append("Opponent connected")
            // HOST advances to color pick and signals guest to do the same
            if localTeamKey == "r" && phase == .lobby {
                phase = .colorPick
                try? relayClient?.send(["type": "start_setup"])
            }

        case "relay_peer_disconnected":
            onlineStatus = "Opponent disconnected"
            moveLog.append("Opponent disconnected")

        case "start_setup":
            // Guest advances to color pick
            guard localTeamKey == "l" && phase == .lobby else { return }
            phase = .colorPick
            onlineStatus = "Choose your color"

        case "color_chosen":
            guard let teamKey = msg["team_key"] as? String,
                  let r = msg["r"] as? Int, let g = msg["g"] as? Int,
                  let b = msg["b"] as? Int, let name = msg["name"] as? String else { return }
            guard teamKey != localTeamKey else { return }  // ignore own echo
            let team = Team(r: r, g: g, b: b, name: name)
            if teamKey == "r" { teamR = team } else { teamL = team }
            peerConfirmedColors = true
            if localConfirmedColors {
                onlineStatus = "Colors set — choose human or AI"
                phase = .warGames
            }

        case "war_games_choice":
            guard let teamKey = msg["team_key"] as? String,
                  let ptStr = msg["player_type"] as? String else { return }
            guard teamKey != localTeamKey else { return }  // ignore own echo
            let pt: PlayerType = ptStr == "ai" ? .ai : .human
            if teamKey == "r" { playerTypeR = pt } else { playerTypeL = pt }
            peerConfirmedWG = true
            if localConfirmedWG {
                finishSetupAsHost()
            }

        case "game_start":
            // Guest and spectators start the board when host is ready
            guard localTeamKey == "l" || isSpectator else { return }
            // Apply full team info (needed for spectators joining after setup)
            if let r = msg["tRr"] as? Int, let g = msg["tRg"] as? Int,
               let b = msg["tRb"] as? Int, let name = msg["tRname"] as? String {
                teamR = Team(r: r, g: g, b: b, name: name)
            }
            if let r = msg["tLr"] as? Int, let g = msg["tLg"] as? Int,
               let b = msg["tLb"] as? Int, let name = msg["tLname"] as? String {
                teamL = Team(r: r, g: g, b: b, name: name)
            }
            if let ptR = msg["ptR"] as? String { playerTypeR = ptR == "ai" ? .ai : .human }
            if let ptL = msg["ptL"] as? String { playerTypeL = ptL == "ai" ? .ai : .human }
            startBoard()

        case "pong":
            break  // Handled by RelayClient keepalive

        default: break
        }
    }

    private func applyRemoteMove(_ msg: [String: Any]) {
        guard let board,
              let fr = msg["from_row"] as? Int, let fc = msg["from_col"] as? Int,
              let tr = msg["to_row"] as? Int,   let tc = msg["to_col"] as? Int else { return }
        guard let piece = board.grid[fr][fc] else { return }
        if !isSpectator {
            // Validate the piece belongs to the opponent
            let remoteTeam = localTeamKey == "r" ? teamL : teamR
            guard piece.team == remoteTeam else { return }
            // Validate legality using already-computed targets from beginTurn()
            guard piece.targets.contains(Cell(tr, tc)) else {
                moveLog.append("Invalid move from opponent — ignored")
                return
            }
        }
        executeMove(piece: piece, to: Cell(tr, tc))
    }
}
