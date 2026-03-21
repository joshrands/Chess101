# Chess101 Multiplayer — UX Design

## Guiding Principles

1. **Zero configuration on LAN.** On the same network, finding and joining a game should require no IP addresses, no ports, no setup. Click "Host", share nothing, and the guest finds the game automatically.
2. **The physical board is always primary.** When a Pi is involved, it dictates piece positions. The simulator renders what the board says, not the other way around.
3. **Familiar phases.** The existing COLOR_PICK → WAR_GAMES → PLAYING → GAME_OVER flow is preserved. Networked games interleave the two players' selections through the same screens.
4. **Fail gracefully.** A disconnect during a game shows a clear message and offers to wait for reconnection or resign. No crash.

---

## Simulator Entry Point

On launch, `run_simulator.py` accepts optional CLI flags. If none are given, a new **Lobby screen** is shown before COLOR_PICK.

```
.venv/bin/python run_simulator.py            # → Lobby screen
.venv/bin/python run_simulator.py --local    # → skip Lobby, go straight to COLOR_PICK (original behavior)
.venv/bin/python run_simulator.py --host     # → Host immediately, skip Lobby
.venv/bin/python run_simulator.py --join 192.168.1.42  # → Join immediately
.venv/bin/python run_simulator.py --spectate 192.168.1.42
```

---

## Phase: LOBBY

Replaces the immediate COLOR_PICK start for networked games. The board area shows a 4-option menu; the side panel shows network status.

### Board display

```
┌────────────────────────────────────────────────────────────┐
│                                                            │
│                                                            │
│          ████████  Play Locally                            │
│                                                            │
│          ████████  Host a Game                             │
│                                                            │
│          ████████  Join a Game                             │
│                                                            │
│          ████████  Watch a Game                            │
│                                                            │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

Each option occupies two full rows of LED cells, lit in a muted color. The selected option pulses brighter (same checker animation as other phases). Keyboard: arrow keys or mouse click to navigate, Enter/click to select.

### Side panel — Lobby

```
Chess 101
─────────────────────
Phase   LOBBY

[ Play Locally  ]   ← selected option highlighted

Discovered games:
  Seth's Mac  ●●●○   lobby
  Alex's Pi   ●●●●   playing (spectators ok)

─────────────────────
LOG
```

Discovered games auto-populate as beacons are received. A signal-strength indicator (●●●○ = 3/4 bars based on beacon latency) shows link quality. Games in "playing" state are greyed out unless spectators are allowed.

---

## Flow: Host a Game

1. Player selects **Host a Game** in Lobby.
2. Simulator starts the WebSocket server and UDP beacon immediately.
3. Board shows a waiting animation (pulsing "waiting for opponent" pattern in neutral white/grey). Side panel shows:
   ```
   Phase   HOSTING

   Your address:
   192.168.1.42 : 65101

   Room code:
   (none in Phase 1)

   Waiting for opponent...
   ```
4. When a guest connects, the host sees the guest's name in the panel and the game advances to COLOR_PICK.
5. Host can press **Esc** to cancel hosting and return to Lobby.

---

## Flow: Join a Game

1. Player selects **Join a Game** in Lobby.
2. Board shows the list of discovered games (one row of cells per game, lit in that game's host color if known, neutral white otherwise). Side panel shows the list in text.
3. Player clicks the row for the game they want to join. If no games are discovered, a "No games found" message is shown and the player can type an IP manually (panel text input, future feature).
4. Simulator connects as WebSocket client. On success, board shows "Connected — waiting for host..." and both sides advance to COLOR_PICK.
5. Player can press **Esc** to cancel and return to Lobby.

---

## Flow: Watch a Game

1. Player selects **Watch a Game** in Lobby.
2. Same game list as Join, but includes games already in "playing" state (if `spectators_allowed`).
3. On connection, spectator receives the current board state via `board_sync` and enters a read-only PLAYING view.
4. No input is accepted (clicks are ignored). Board renders exactly as the live game. Side panel shows both player names, move count, whose turn it is, and the log feed.
5. Multiple spectators can connect to the same game.

---

## Phase: COLOR_PICK (networked)

The existing COLOR_PICK rendering is reused. In networked mode:

- **Host** clicks row 2 to choose their color (team_r). Their choice is sent to the guest via `color_chosen`. The host's chosen color is immediately visible on the guest's board too.
- **Guest** clicks row 5 to choose their color (team_l). Same propagation.
- Neither player can choose the same color as the other (the chosen color's column is greyed out for the other player).
- Once both have chosen, host sends `game_start` and both sides advance to WAR_GAMES.

Side panel additions (networked):
```
Waiting for opponent's color...   ← shown while opponent hasn't chosen yet
```

---

## Phase: WAR_GAMES (networked)

In a networked game, there is no AI selection in the traditional sense: each player IS a human controlling their side. The WAR_GAMES screen is simplified:

- Row 3 (team_r, host): Host clicks "Human" (left half) to confirm they'll play manually, or "AI" (right half) to have the local AI play for them.
- Row 4 (team_l, guest): Guest makes the same choice.
- The AI choice means "let the local alpha-beta engine play for me on this machine" — it is transparent to the opponent (they just see moves arrive).

The WAR_GAMES screen is the same visually. The side panel notes:
```
You are:  Right team (Blue)
Opponent: Left  team (Orange)
```

---

## Phase: PLAYING (networked)

### Local player's turn

Exactly as today: click to select a piece, click a target to move. Selected piece blinks; legal targets light in team color.

After making a move:
- The move is sent to the opponent
- The side panel shows "Waiting for opponent..." with an animated dot
- Input is blocked (same as AI thinking today)

### Opponent's turn

While waiting for the opponent's move:
- The board shows the current position (no selection highlight)
- The side panel shows "Opponent is thinking..." and, if the opponent is an AI, "AI thinking..." with the AI search animation (if the opponent opts to share this information — Phase 2 feature)
- The log panel shows moves as they are received

When the opponent's move arrives:
- The piece slides to its destination (simple animation: the piece lights up at source, then at destination; no interpolated movement in Phase 1)
- The move is validated locally
- `_begin_turn` is called for the local player

### Disconnection during play

If the WebSocket closes unexpectedly:
- Board dims (half-brightness overlay on all cells)
- Side panel shows: `"Opponent disconnected. Waiting 60s to reconnect..."`
- A countdown timer is shown
- If reconnection succeeds within the timeout, the game resumes from the last confirmed board state
- If not, the player is offered: "Claim victory" (if they believe they were winning) or "Return to Lobby"

---

## Phase: GAME_OVER (networked)

Both sides display the same win/draw animation. The winner sees their color flash; the loser sees the winner's color. The panel shows:

```
GAME OVER
Blue wins!

N — Play again (same teams)
R — Rematch (swap sides)
L — Return to Lobby
```

If the opponent disconnects during GAME_OVER, the local result is preserved and the same options are shown.

---

## Physical Board UX (Phase 2)

The Pi has no Pygame window. Setup happens one of two ways:

### Option A: Pi as host, Sim as UI
The connecting simulator drives the COLOR_PICK and WAR_GAMES UI. The Pi displays minimal info on any attached LCD (if present) or just via logging. Once the game starts, the Pi detects lift-off/landing via reed switches and sends moves.

Workflow:
1. Pi starts: `sudo python3 GameManager.py --host`
2. Player on the Pi sees terminal: `Hosting on 192.168.1.50:65101 — waiting for opponent...`
3. Opponent opens simulator, selects Join, sees "Pi Board (192.168.1.50)" in the game list
4. Opponent connects — now acts as the UI host: drives COLOR_PICK and WAR_GAMES
5. Once game starts, Pi waits for physical pieces to be placed and plays normally
6. Physical moves are detected → sent as `move` messages → simulator updates display

### Option B: Headless Pi-vs-Pi
Two Pis on the same network. One is `--host`, one is `--join <IP>`. No simulator involved. Each Pi detects its own moves and sends them. Optional: a spectator sim can connect to watch.

### Piece setup over network
For `interactive_setup` (placing pieces on the board), each Pi independently detects when all 16 of its pieces are placed and signals ready. The host Pi waits for the guest's `setup_complete` message before starting.

---

## Side Panel — All Network States

The right-hand panel shows network status at all times when in networked mode:

```
Chess 101
─────────────────────
Phase   PLAYING
Mode    Network (Host)
Peer    Alex's Mac  ●●●●

Turn    Blue's move
Move    #14
Peace   7 / 50   [========  ]

!! KING IN CHECK
Opponent thinking...

─────────────────────
LOG
I[sim] Running game...
I[sim] Player: Blue's move.
D[sim] KING IS IN CHECK
I[sim] Human moves 1,4 → 3,4
I[sim] Player: Orange's move.
```

New panel fields:
- **Mode** — Local / Network (Host) / Network (Guest) / Spectator
- **Peer** — opponent name and signal quality indicator
- Signal quality: derived from ping round-trip time (●●●● < 50ms, ●●●○ < 100ms, ●●○○ < 200ms, ●○○○ > 200ms)
