/// The game's phase state machine — mirrors Python/JS exactly.
public enum GamePhase: Equatable {
    case lobby
    case colorPick
    case warGames
    case playing
    case gameOver
}

/// Whether this game slot is human or AI.
public enum PlayerType: Equatable {
    case human
    case ai
}

/// Lobby option selection.
public enum LobbyOption: CaseIterable {
    case playLocally
    case hostOnline
    case joinOnline
    case spectate
}

