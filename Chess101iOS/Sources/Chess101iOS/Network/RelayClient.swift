import Foundation

// MARK: - Relay errors

public enum RelayError: Error, LocalizedError {
    case serverFull
    case roomNotFound
    case badToken
    case badHandshake
    case connectionFailed(String)
    case timeout

    public var errorDescription: String? {
        switch self {
        case .serverFull:              return "Relay server is full"
        case .roomNotFound:            return "Room not found or already full"
        case .badToken:                return "Reconnection token invalid"
        case .badHandshake:            return "Bad handshake message"
        case .connectionFailed(let s): return "Connection failed: \(s)"
        case .timeout:                 return "Operation timed out"
        }
    }
}

// MARK: - RelayClient

/// WebSocket client for the Chess101 relay server.
/// Uses `URLSessionWebSocketTask` — no external dependencies.
public final class RelayClient: NSObject, URLSessionWebSocketDelegate {

    private let url: URL
    private var socket: URLSessionWebSocketTask?
    private var urlSession: URLSession?
    private let lock = NSLock()

    // Pending one-shot waiters for handshake responses.
    private struct Waiter {
        let id: UUID
        let predicate: ([String: Any]) -> Bool
        let continuation: CheckedContinuation<[String: Any], Error>
    }
    private var waiters: [Waiter] = []

    // Signals when the WebSocket handshake has completed.
    private var openContinuation: CheckedContinuation<Void, Error>?

    /// Ongoing game messages forwarded to GameSession via this stream.
    public private(set) var messageStream: AsyncStream<[String: Any]>!
    private var messageContinuation: AsyncStream<[String: Any]>.Continuation!

    public var token: String?
    public var roomCode: String?

    public init(url: URL = URL(string: "wss://relay.chess101.net")!) {
        self.url = url
        super.init()
        messageStream = AsyncStream { [weak self] cont in
            self?.messageContinuation = cont
        }
        urlSession = URLSession(configuration: .default, delegate: self, delegateQueue: nil)
    }

    // MARK: - Connection lifecycle

    /// Establish the WebSocket and wait until the connection is open.
    private func connectAndWait() async throws {
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            lock.lock()
            openContinuation = cont
            lock.unlock()
            let request = URLRequest(url: url)
            socket = urlSession?.webSocketTask(with: request)
            socket?.resume()
            receiveLoop()
        }
    }

    public func disconnect() {
        socket?.cancel(with: .normalClosure, reason: nil)
        failAllWaiters(with: RelayError.connectionFailed("Disconnected"))
        messageContinuation.finish()
    }

    // MARK: - URLSessionWebSocketDelegate

    public func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                           didOpenWithProtocol protocol: String?) {
        lock.lock()
        let cont = openContinuation
        openContinuation = nil
        lock.unlock()
        cont?.resume(returning: ())
    }

    public func urlSession(_ session: URLSession, task: URLSessionTask,
                           didCompleteWithError error: Error?) {
        // Signal connection failure to anyone still waiting for the socket to open.
        lock.lock()
        let cont = openContinuation
        openContinuation = nil
        lock.unlock()
        if let error {
            cont?.resume(throwing: RelayError.connectionFailed(error.localizedDescription))
        }
        failAllWaiters(with: RelayError.connectionFailed("Connection closed"))
        messageContinuation.finish()
    }

    // MARK: - Room operations

    public func createRoom(playerName: String) async throws -> String {
        try await connectAndWait()
        try send(["type": "relay_create", "player_name": playerName, "version": "1"])
        let msg = try await waitForHandshake { t in t == "relay_created" || t == "relay_error" }
        guard let code = msg["room_code"] as? String,
              let tok  = msg["token"]     as? String else { throw relayError(from: msg) }
        roomCode = code; token = tok
        return code
    }

    public func joinRoom(code: String, playerName: String) async throws -> String {
        try await connectAndWait()
        try send(["type": "relay_join", "room_code": code.uppercased(),
                  "player_name": playerName, "version": "1"])
        let msg = try await waitForHandshake { t in t == "relay_created" || t == "relay_error" }
        guard let tok = msg["token"] as? String else { throw relayError(from: msg) }
        roomCode = code.uppercased(); token = tok
        return tok
    }

    public func spectate(code: String) async throws {
        try await connectAndWait()
        try send(["type": "relay_spectate", "room_code": code.uppercased()])
        let msg = try await waitForHandshake { t in t == "relay_spectating" || t == "relay_error" }
        guard msg["type"] as? String == "relay_spectating" else { throw relayError(from: msg) }
        roomCode = code.uppercased()
    }

    public func reconnect(code: String, savedToken: String) async throws {
        try await connectAndWait()
        try send(["type": "relay_reconnect", "room_code": code.uppercased(), "token": savedToken])
        let msg = try await waitForHandshake { t in t == "relay_reconnected" || t == "relay_error" }
        guard msg["type"] as? String == "relay_reconnected" else { throw relayError(from: msg) }
        roomCode = code.uppercased(); token = savedToken
    }

    // MARK: - Sending

    public func send(_ msg: [String: Any]) throws {
        let data = try JSONSerialization.data(withJSONObject: msg)
        let str  = String(data: data, encoding: .utf8)!
        socket?.send(.string(str)) { _ in }
    }

    // MARK: - Receive loop

    private func receiveLoop() {
        socket?.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let message):
                if case .string(let text) = message,
                   let data = text.data(using: .utf8),
                   let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    self.dispatch(json)
                }
                self.receiveLoop()
            case .failure(let error):
                self.failAllWaiters(with: RelayError.connectionFailed(error.localizedDescription))
                self.messageContinuation.finish()
            }
        }
    }

    /// Route an incoming message: wake any matching one-shot waiter, then
    /// forward to the game message stream for GameSession.
    private func dispatch(_ msg: [String: Any]) {
        lock.lock()
        let type = msg["type"] as? String ?? ""
        var unmatched: [Waiter] = []
        var matched: CheckedContinuation<[String: Any], Error>? = nil
        for w in waiters {
            if matched == nil && w.predicate(msg) {
                matched = w.continuation
            } else {
                unmatched.append(w)
            }
        }
        waiters = unmatched
        lock.unlock()

        matched?.resume(returning: msg)

        // Relay handshake messages are only for the one-shot waiter.
        // Game messages go to the stream for GameSession to consume.
        let isHandshake = type.hasPrefix("relay_")
        if !isHandshake || matched == nil {
            messageContinuation.yield(msg)
        }
    }

    // MARK: - Helpers

    /// Wait for the first incoming message whose `type` matches the predicate,
    /// or throw `.timeout` after `timeout` seconds.
    private func waitForHandshake(timeout: TimeInterval = 30,
                                   matching: @escaping (String) -> Bool) async throws -> [String: Any] {
        let id = UUID()
        return try await withCheckedThrowingContinuation { cont in
            lock.lock()
            waiters.append(Waiter(id: id,
                                  predicate: { (matching($0["type"] as? String ?? "")) },
                                  continuation: cont))
            lock.unlock()

            Task {
                try? await Task.sleep(nanoseconds: UInt64(timeout * 1_000_000_000))
                self.lock.lock()
                guard let idx = self.waiters.firstIndex(where: { $0.id == id }) else {
                    self.lock.unlock(); return   // already resolved
                }
                self.waiters.remove(at: idx)
                self.lock.unlock()
                cont.resume(throwing: RelayError.timeout)
            }
        }
    }

    private func failAllWaiters(with error: Error) {
        lock.lock()
        let pending = waiters
        waiters = []
        lock.unlock()
        for w in pending { w.continuation.resume(throwing: error) }
    }

    private func relayError(from msg: [String: Any]) -> RelayError {
        switch msg["code"] as? String {
        case "server_full":    return .serverFull
        case "room_not_found": return .roomNotFound
        case "bad_token":      return .badToken
        default:               return .badHandshake
        }
    }
}
