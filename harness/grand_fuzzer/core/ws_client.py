"""Deterministic WebSocket wrapper for reproducible fuzzing.

Provides seed-controlled timing for message sends, making network
timing reproducible across fuzzing runs.
"""
from __future__ import annotations

import json
import queue
import random
import threading
import time
from typing import Callable


class DeterministicWSClient:
    """WebSocket client with seed-controlled timing.

    Wraps any WebSocket-like object (GameServer, GameClient, RelayClient)
    and adds deterministic delays to sends based on the provided seed.
    """

    def __init__(self, impl, seed: int):
        """
        Args:
            impl: Underlying WebSocket implementation with send() method
            seed: RNG seed for reproducible timing
        """
        self._impl = impl
        self._rng = random.Random(seed)
        self._received: list[dict] = []
        self._lock = threading.Lock()
        self._new_msg = threading.Event()

        if hasattr(impl, "set_message_handler"):
            impl.set_message_handler(self._on_message)

    def _on_message(self, msg: dict) -> None:
        """Handle incoming message."""
        with self._lock:
            self._received.append(msg)
        self._new_msg.set()

    def send(self, msg: dict, delay_range: tuple[float, float] = (0.0, 0.0)) -> None:
        """Send message with optional deterministic delay.

        Args:
            msg: Message to send
            delay_range: (min, max) seconds to delay before send
        """
        if delay_range[1] > 0:
            delay = self._rng.uniform(*delay_range)
            time.sleep(delay)
        self._impl.send(msg)

    def send_delayed(self, msg: dict, min_delay: float, max_delay: float) -> None:
        """Send message after deterministic delay."""
        self.send(msg, (min_delay, max_delay))

    def recv(self, timeout: float = 5.0) -> dict | None:
        """Receive next message, blocking up to timeout."""
        deadline = time.time() + timeout
        while True:
            with self._lock:
                if self._received:
                    return self._received.pop(0)
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            self._new_msg.clear()
            self._new_msg.wait(timeout=min(remaining, 0.1))

    def recv_all(self) -> list[dict]:
        """Return all pending messages without blocking."""
        with self._lock:
            msgs = self._received[:]
            self._received.clear()
        return msgs

    def clear(self) -> None:
        """Clear receive buffer."""
        with self._lock:
            self._received.clear()
        self._new_msg.clear()

    def close(self) -> None:
        """Close underlying connection."""
        if hasattr(self._impl, "close"):
            self._impl.close()
        elif hasattr(self._impl, "stop"):
            self._impl.stop()

    @property
    def impl(self):
        """Access underlying implementation."""
        return self._impl


class MessageRecorder:
    """Records all messages sent/received for corpus generation."""

    def __init__(self):
        self._events: list[dict] = []
        self._lock = threading.Lock()
        self._start_time = time.time()

    def record_send(self, peer: str, msg: dict) -> None:
        """Record a sent message."""
        with self._lock:
            self._events.append({
                "type": "send",
                "peer": peer,
                "msg": msg,
                "time": time.time() - self._start_time,
            })

    def record_recv(self, peer: str, msg: dict) -> None:
        """Record a received message."""
        with self._lock:
            self._events.append({
                "type": "recv",
                "peer": peer,
                "msg": msg,
                "time": time.time() - self._start_time,
            })

    def record_event(self, event_type: str, data: dict) -> None:
        """Record arbitrary event."""
        with self._lock:
            self._events.append({
                "type": event_type,
                "data": data,
                "time": time.time() - self._start_time,
            })

    @property
    def events(self) -> list[dict]:
        """Get copy of all recorded events."""
        with self._lock:
            return self._events[:]

    def clear(self) -> None:
        """Clear recorded events."""
        with self._lock:
            self._events.clear()
        self._start_time = time.time()
