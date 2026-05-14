#!/usr/bin/env python3
"""Networked HIL fuzzer — drives the full lobby→host→game flow.

Connects to the HIL container via both:
  1. The control server (port 8766) — to inject reed switches
  2. A GameClient (port 65101) — to play as the remote guest

This exercises the REAL code path: Board.run() → lobby → _transition_host →
_run_networked → color_pick → war_games → setup → gameplay.

Usage:
    # Start HIL container first (with port 65101 exposed):
    docker-compose -f docker-compose.hil.yml up -d

    # Run:
    .venv/bin/python harness/fuzz_hil_networked.py
    .venv/bin/python harness/fuzz_hil_networked.py --iterations 5
    .venv/bin/python harness/fuzz_hil_networked.py --mode join
"""
from __future__ import annotations

import argparse
import collections
import json
import logging
import random
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hil.client import HilBridge
from network.client import GameClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fuzz_hil_networked")


class TestPeer:
    """Accumulates messages from the GameClient for inspection."""

    def __init__(self):
        self._msgs: collections.deque = collections.deque()
        self._new = threading.Event()

    def on_message(self, msg: dict) -> None:
        self._msgs.append(msg)
        self._new.set()

    def recv(self, timeout: float = 10.0, msg_type: str | None = None) -> dict | None:
        deadline = time.time() + timeout
        while True:
            while self._msgs:
                m = self._msgs.popleft()
                if msg_type is None or m.get("type") == msg_type:
                    return m
                # stash non-matching messages back
                self._msgs.appendleft(m)
                if msg_type:
                    # pop and discard non-matching to avoid infinite loop
                    self._msgs.popleft()
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            self._new.clear()
            self._new.wait(timeout=min(remaining, 0.2))

    def drain(self, msg_type: str, timeout: float = 1.0) -> list[dict]:
        """Collect all messages of a given type within timeout."""
        result = []
        deadline = time.time() + timeout
        while True:
            while self._msgs:
                m = self._msgs.popleft()
                if m.get("type") == msg_type:
                    result.append(m)
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            self._new.clear()
            self._new.wait(timeout=min(remaining, 0.1))
        return result

    def clear(self):
        self._msgs.clear()
        self._new.clear()


def wait_for_game_server(host: str, port: int, timeout: float = 30.0) -> bool:
    """Poll until the GameServer on the HIL container is accepting connections."""
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.socket()
            s.settimeout(1.0)
            s.connect((host, port))
            s.close()
            return True
        except (ConnectionRefusedError, OSError, socket.timeout):
            time.sleep(0.5)
    return False


def run_host_test(
    hil_url: str,
    game_host: str,
    game_port: int,
    seed: int,
) -> tuple[bool, str]:
    """Drive the HIL through lobby→host and connect as guest.

    Returns (success, message).
    """
    rng = random.Random(seed)
    bridge = HilBridge(url=hil_url, timeout=10.0)
    bridge.connect(retries=5, delay=1.0)

    if not bridge.ping():
        return False, "HIL not responding"

    logger.info("=== Lobby: selecting Network → Host ===")

    # Give the lobby time to render
    time.sleep(2.0)

    # Place piece on rain side (network) — row 3, col 5
    bridge.place_piece(3, 5)
    logger.info("Placed piece on rain side (3,5)")

    # Wait for L1 spread animation (3 seconds + margin)
    time.sleep(4.0)

    # Place piece on host position (2,0)
    bridge.place_piece(2, 0)
    logger.info("Placed piece on Host (2,0)")

    # Wait for L2 spread animation
    time.sleep(4.0)

    # Remove both pieces (blink-and-remove)
    bridge.lift_piece(2, 0)
    bridge.lift_piece(3, 5)
    logger.info("Removed lobby pieces")

    # Wait for transition to networked mode — GameServer should start
    time.sleep(2.0)

    # Wait for the GameServer to come up on port 65101
    logger.info("Waiting for GameServer on %s:%d...", game_host, game_port)
    if not wait_for_game_server(game_host, game_port, timeout=30.0):
        bridge.close()
        return False, "GameServer never started on port 65101"

    logger.info("GameServer is up — connecting GameClient")

    # Connect as guest
    peer = TestPeer()
    client = GameClient(host_ip=game_host, port=game_port)
    client.set_message_handler(peer.on_message)

    def _on_connected():
        logger.info("GameClient connected — sending hello")
        client.send({
            "type": "hello",
            "version": "1",
            "player_name": "FuzzGuest",
        })

    client._on_connected = _on_connected

    if not client.connect(timeout=10.0):
        bridge.close()
        return False, "GameClient failed to connect"

    # Wait for game_setup from host
    msg = peer.recv(timeout=10.0, msg_type="game_setup")
    if msg is None:
        client.stop()
        bridge.close()
        return False, "Never received game_setup"

    mode = msg.get("mode")
    logger.info("Received game_setup (mode=%s)", mode)
    if mode != "physical_host":
        client.stop()
        bridge.close()
        return False, f"Expected physical_host mode, got {mode}"

    # === COLOR PICK ===
    # Host (HIL) picks color via reed switch
    logger.info("=== Color pick phase ===")
    time.sleep(1.0)  # Wait for color picker to render on HIL

    # Wait for host's color_chosen
    msg = peer.recv(timeout=15.0, msg_type="color_chosen")
    if msg is None:
        # Host hasn't picked yet — inject reed switch for color pick
        logger.info("Injecting color pick for host (row 2, col 0)")
        bridge.place_piece(2, 0)
        time.sleep(0.5)
        bridge.lift_piece(2, 0)
        msg = peer.recv(timeout=10.0, msg_type="color_chosen")

    if msg is None:
        client.stop()
        bridge.close()
        return False, "Never received host's color_chosen"

    logger.info("Host chose color: team=%s idx=%s", msg.get("team_key"), msg.get("color_idx"))
    client.send({"type": "color_chosen_ack", "team_key": msg.get("team_key")})

    # Guest sends color_chosen for team_l
    guest_color = rng.randint(0, 5)
    client.send({
        "type": "color_chosen",
        "team_key": "l",
        "color_idx": guest_color,
    })
    logger.info("Guest sent color_chosen (team_l, idx=%d)", guest_color)

    # Wait for ACK
    ack = peer.recv(timeout=5.0, msg_type="color_chosen_ack")
    if ack is None:
        logger.warning("No color_chosen_ack received (continuing)")

    # === WAR GAMES ===
    logger.info("=== War games phase ===")
    time.sleep(1.0)

    # Wait for host's war_games_choice
    msg = peer.recv(timeout=15.0, msg_type="war_games_choice")
    if msg is None:
        # Inject reed switch for war games (human = row 3, col 0)
        logger.info("Injecting war games for host (row 3, col 0)")
        bridge.place_piece(3, 0)
        time.sleep(0.5)
        bridge.lift_piece(3, 0)
        msg = peer.recv(timeout=10.0, msg_type="war_games_choice")

    if msg is None:
        client.stop()
        bridge.close()
        return False, "Never received host's war_games_choice"

    logger.info("Host war games: team=%s ai=%s", msg.get("team_key"), msg.get("is_ai"))
    client.send({"type": "war_games_choice_ack", "team_key": msg.get("team_key")})

    # Guest sends war_games_choice for team_l
    client.send({
        "type": "war_games_choice",
        "team_key": "l",
        "is_ai": True,
        "player_type": "ai",
    })
    logger.info("Guest sent war_games_choice (team_l, ai=True)")

    ack = peer.recv(timeout=5.0, msg_type="war_games_choice_ack")
    if ack is None:
        logger.warning("No war_games_choice_ack received (continuing)")

    # === GAME START ===
    logger.info("=== Waiting for game_start ===")
    msg = peer.recv(timeout=15.0, msg_type="game_start")
    if msg is None:
        client.stop()
        bridge.close()
        return False, "Never received game_start"

    logger.info("Received game_start!")

    # Guest sends setup_complete
    client.send({"type": "setup_complete", "team_key": "l"})
    logger.info("Guest sent setup_complete")

    # === GAMEPLAY ===
    # Wait for setup_complete from host or first move
    logger.info("=== Waiting for gameplay to begin ===")

    # The host side does interactive_setup (reed switch piece placement).
    # In HIL, set_starting_position puts all pieces down.
    time.sleep(1.0)
    bridge.set_starting_position()
    logger.info("Set starting position on HIL")

    # Wait for setup_status or a move — anything that indicates the game loop is running
    deadline = time.time() + 30.0
    got_gameplay = False
    while time.time() < deadline:
        msg = peer.recv(timeout=1.0)
        if msg is None:
            continue
        msg_type = msg.get("type", "")
        logger.info("Received: %s", msg_type)
        if msg_type in ("move", "setup_status", "setup_complete", "board_sync_request"):
            got_gameplay = True
            break

    client.stop()
    bridge.close()

    if got_gameplay:
        return True, f"Successfully reached gameplay (last msg: {msg_type})"
    else:
        return False, "Timed out waiting for gameplay messages"


def main() -> int:
    parser = argparse.ArgumentParser(description="Networked HIL fuzzer")
    parser.add_argument("--iterations", "-n", type=int, default=1)
    parser.add_argument("--seed", "-s", type=int, default=42)
    parser.add_argument("--hil-url", default="ws://localhost:8766")
    parser.add_argument("--game-host", default="localhost")
    parser.add_argument("--game-port", type=int, default=65101)
    parser.add_argument("--mode", choices=["host", "join"], default="host")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    total, ok, failed = 0, 0, 0

    for i in range(args.iterations):
        game_seed = rng.randint(0, 2**32)
        logger.info("\n========== Iteration %d (seed=%d) ==========", i + 1, game_seed)

        if args.mode == "host":
            success, message = run_host_test(
                args.hil_url, args.game_host, args.game_port, game_seed
            )
        else:
            success, message = False, "join mode not yet implemented"

        total += 1
        if success:
            ok += 1
            logger.info("PASS: %s", message)
        else:
            failed += 1
            logger.error("FAIL: %s", message)

    print(f"\nDone. total={total} ok={ok} failed={failed}")
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
