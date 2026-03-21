# Phase 2 — Physical Board Network Support

## Goal

Allow a Raspberry Pi physical board to participate in networked games: Pi vs Sim, Pi vs Pi, and Sim as spectator of a physical game. Physical piece movements (detected via reed switches) are transmitted as moves to the remote side.

## Prerequisite

Phase 1 (LAN Sim vs Sim) must be complete. Phase 2 layers physical board support on top of the same protocol.

---

## New Challenges vs Phase 1

| Challenge | Details |
|---|---|
| No display on Pi | Color pick and WAR_GAMES cannot use the board LED grid as a menu — the physical game pieces are what's on the board, not pixels |
| Move detection latency | Reed switches require a full lift-off + landing cycle to detect a move, taking 1–3 seconds |
| Ambiguous lift-off | A player may lift a piece and put it back (thinking, then changing their mind) |
| Physical piece setup | `interactive_setup` must complete before the network game can start |
| Setup UI | How does the Pi player choose team color with no keyboard or touchscreen? |

---

## Work Estimate

**Total: ~3–4 weeks additional**

| Task | Effort |
|---|---|
| `NetworkedBoard` — Pi game manager with network | 3 days |
| Move detection wrapping (`detect_lift_off` + `detect_landing` → network send) | 2 days |
| Physical setup sequence over network | 1.5 days |
| Pi CLI flags + headless mode | 1 day |
| Spectator mode (receive-only `NetworkedGameRunner`) | 1.5 days |
| Sim-as-setup-UI for Pi color pick | 2 days |
| mDNS discovery via Zeroconf (upgrade from UDP beacon) | 1 day |
| Pi reconnect + move re-send on disconnect | 1 day |
| Integration testing Pi ↔ Sim | 2 days |
| Integration testing Pi ↔ Pi | 1 day |

---

## Architecture: `NetworkedBoard`

A new entry point for the Pi that wraps the existing `Board` class with network hooks.

```
game/
└── networked_board.py    # NetworkedBoard: Board + network send/receive
```

```python
class NetworkedBoard(Board):
    """Board subclass that transmits moves over a network connection."""

    def __init__(self, net: GameServer | GameClient, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._net = net
        self._net.set_message_handler(self._on_network_message)

    def do_turn(self, team) -> None:
        """Override: after physical move detected, send to opponent."""
        # 1. Detect lift-off (existing logic)
        lifted_piece, old_row, old_col = self.detect_lift_off(team)
        if lifted_piece is None:
            return

        # 2. Wait for landing
        new_row, new_col = self.detect_landing(lifted_piece)

        # 3. Apply move locally (existing logic)
        self.grid[new_row][new_col] = self.grid[old_row][old_col]
        self._apply_move(old_row, old_col, new_row, new_col)

        # 4. Build and send move message
        flags = self._build_flags(lifted_piece, old_row, old_col, new_row, new_col)
        self._net.send_sync({
            "type": "move",
            "from_row": old_row, "from_col": old_col,
            "to_row":   new_row, "to_col":   new_col,
            "piece": type(lifted_piece).__name__,
            "flags": flags,
            "board_hash": board_hash(self.grid, self.peace_time, "team_r"),
        })

    def _on_network_message(self, msg: dict) -> None:
        """Receive remote moves and apply them to the physical board."""
        if msg["type"] == "move":
            # Apply to logical grid so chess logic is updated
            fr, fc = msg["from_row"], msg["from_col"]
            tr, tc = msg["to_row"],   msg["to_col"]
            self.grid[tr][tc] = self.grid[fr][fc]
            self._apply_move(fr, fc, tr, tc)
            # Light the LED matrix to show the opponent's move
            self._render_opponent_move(fr, fc, tr, tc)
```

---

## Physical Setup Sequence

### Option A: Pi-hosted setup (Pi controls everything)

1. Pi starts `--host`. No setup UI.
2. Color pick: The Pi blinks the 8 color options on its LED matrix. The physical player presses a reed-switch cell on row 2 to select their color. (This requires the player to briefly place a physical piece on that cell and remove it — awkward but functional.)
3. WAR_GAMES: Pi blinks row 3 (Human / AI). Player places piece on left half for Human, right half for AI.
4. Connecting sim acts as team_l and drives its own COLOR_PICK and WAR_GAMES via normal clicks.
5. `interactive_setup` runs on both sides: Pi waits for all 16 physical pieces to be placed; sim waits for 16 clicks confirming piece placement (the sim side must manually place pieces on the board or click "auto-setup").

### Option B: Sim-as-UI for Pi (recommended for better UX)

The connecting simulator acts as the UI host for the Pi player's setup selections. The Pi itself just waits.

1. Pi starts `--host`. Terminal shows `Hosting... waiting for setup UI to connect.`
2. Sim connects. The sim shows COLOR_PICK as normal but with a note: "You are controlling the Pi board's setup." Row 2 = Pi's team color, Row 5 = Sim's team color.
3. Sim sends `color_chosen` for the Pi's team as well as its own.
4. Same for WAR_GAMES.
5. For `interactive_setup`: Pi sends `setup_status` messages as physical pieces are detected. Sim shows a "waiting for physical board setup" screen that lights up each row as the Pi detects pieces placed. Sim's own setup is just clicking "auto-setup" (pieces are placed on the sim board automatically).
6. Once both sides signal `setup_complete`, the host sends `game_start`.

Option B is strongly preferred and is what should be implemented.

---

## Move Detection Flow (Pi Side)

The existing `detect_lift_off` / `detect_landing` loop in `Board.do_turn()` is blocking. In networked mode, the Pi must also listen for incoming moves from the opponent.

**Solution:** run incoming message handling in the network background thread (already the case with asyncio). The Pi's main thread blocks on reed-switch polling as today. When the opponent's move arrives, it is queued and applied immediately after the Pi's own turn completes (or, for the opponent's turn, applied without the Pi needing to "take a turn").

**Turn coordination:**
- The Pi only calls `detect_lift_off` when it is the local team's turn
- During the opponent's turn, the Pi calls `_wait_for_remote_move()` which blocks until the network thread delivers a move from the queue
- After applying the remote move, the Pi lights the board to show where the opponent moved (source square blinks in opponent's color, destination square stays lit)

```python
def _wait_for_remote_move(self, timeout: float = 300.0) -> None:
    """Block until a remote move arrives or timeout."""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        with self._net_lock:
            if self._pending_remote_move:
                msg = self._pending_remote_move
                self._pending_remote_move = None
        if msg:
            self._apply_remote_move(msg)
            return
        time.sleep(0.05)
    # Timeout: declare disconnect
    self.game_over = True
```

---

## Spectator Mode (Sim Side)

A spectator `NetworkedGameRunner` receives board state but does not send moves.

- Connects to host with role `SPECTATOR`
- On connect, receives current `board_sync` (full position)
- Each incoming `move` message is applied to the local board
- `_begin_turn()` is called after each move so legal moves are computed (allows the spectator to see highlighted squares if they hover)
- No `_handle_playing` input events are processed (clicks are ignored)
- Side panel shows both player names, whose turn, move count, log

The spectator renders the board identically to a playing client. The only difference is the panel label ("Spectating") and the disabled input.

---

## mDNS / Zeroconf Discovery

Upgrade from plain UDP beacons to mDNS/DNS-SD so Pi games appear automatically in the Finder / system services on Mac (and in the simulator's Join screen).

Library: `zeroconf` (pure Python, no compiled extensions)

```python
from zeroconf import Zeroconf, ServiceInfo

def advertise_game(host_name: str, port: int = 65101) -> ServiceInfo:
    info = ServiceInfo(
        "_chess101._tcp.local.",
        f"{host_name}._chess101._tcp.local.",
        addresses=[socket.inet_aton(get_local_ip())],
        port=port,
        properties={"game_state": "lobby", "version": "1"},
    )
    zc = Zeroconf()
    zc.register_service(info)
    return info  # caller holds reference to keep it registered
```

Simulators browse for `_chess101._tcp.local.` services to populate the Join list. This works across subnets if mDNS is forwarded, and also shows up in macOS Bonjour.

Add `zeroconf>=0.131` to `requirements.txt`.

---

## Pi CLI Flags

```bash
sudo python3 GameManager.py --host
sudo python3 GameManager.py --join 192.168.1.42
sudo python3 GameManager.py --spectate 192.168.1.42
sudo python3 GameManager.py --host --port 65200
```

The flags are parsed in `GameManager.py` before the main game loop. If `--host` or `--join` is given, a `NetworkedBoard` is instantiated instead of `Board`.

---

## Testing Plan

### Manual (requires hardware)

- [ ] Pi `--host`, Mac sim joins: play full game from setup to checkmate
- [ ] Mac sim `--host`, Pi joins: sim player drives color/WAR_GAMES UI for Pi
- [ ] Pi `--host`, Pi joins (two physical boards): full game without any sim
- [ ] Sim spectates a Pi vs Sim game: board state mirrors physical moves
- [ ] Pi player lifts a piece and puts it back (changes mind): no false move sent
- [ ] Pi player disconnects mid-game: sim shows countdown, Pi reconnects, game resumes

### Automated

- [ ] `NetworkedBoard.do_turn` mock test: simulate lift-off/landing, verify move message is sent
- [ ] Remote move received: mock network message → verify grid updated correctly
- [ ] `_wait_for_remote_move` timeout: verify game_over set after 5 minutes
