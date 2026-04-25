"""Corpus file management for fuzzer-discovered disagreements.

A corpus file is a self-contained JSON document that captures the complete
move sequence leading to a disagreement, independent of fuzzer RNG state.
Corpus files can be replayed as regression tests or loaded into the
interactive simulator for human investigation.

File format: ``*.corpus.json`` — see ``save_corpus`` for the schema.

Version 1: Move-based corpus (moves list, single seed)
Version 2: Chaos corpus (timeline events, multiple seeds, chaos profile)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any

CORPUS_VERSION_LEGACY = 1
CORPUS_VERSION_CHAOS = 2


class TimelineEventType(Enum):
    """Types of events in a chaos corpus timeline."""
    PHASE = auto()       # Game phase transition
    SEND = auto()        # Message sent
    RECV = auto()        # Message received
    FAULT = auto()       # Fault injected
    SCENARIO = auto()    # Scenario triggered
    MOVE = auto()        # Chess move applied
    CONNECT = auto()     # Peer connected
    DISCONNECT = auto()  # Peer disconnected
    RECONNECT = auto()   # Peer reconnected


@dataclass
class TimelineEvent:
    """Single event in the chaos timeline."""
    seq: int
    ts: float  # Seconds since timeline start
    event_type: str  # TimelineEventType.name
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"seq": self.seq, "ts": self.ts, "type": self.event_type, **self.data}

    @classmethod
    def from_dict(cls, d: dict) -> "TimelineEvent":
        seq = d.pop("seq")
        ts = d.pop("ts")
        event_type = d.pop("type")
        return cls(seq=seq, ts=ts, event_type=event_type, data=d)


class TimelineRecorder:
    """Records timeline events for chaos corpus generation."""

    def __init__(self):
        self._events: list[TimelineEvent] = []
        self._start_time = time.time()
        self._seq = 0

    def _next_seq(self) -> int:
        seq = self._seq
        self._seq += 1
        return seq

    def _ts(self) -> float:
        return round(time.time() - self._start_time, 3)

    def record_phase(self, phase: str) -> None:
        self._events.append(TimelineEvent(
            seq=self._next_seq(), ts=self._ts(),
            event_type="phase", data={"phase": phase}
        ))

    def record_send(self, peer: str, msg: dict) -> None:
        self._events.append(TimelineEvent(
            seq=self._next_seq(), ts=self._ts(),
            event_type="send", data={"peer": peer, "msg": msg}
        ))

    def record_recv(self, peer: str, msg: dict) -> None:
        self._events.append(TimelineEvent(
            seq=self._next_seq(), ts=self._ts(),
            event_type="recv", data={"peer": peer, "msg": msg}
        ))

    def record_fault(self, kind: str, peer: str, before: dict | None = None,
                     after: dict | None = None) -> None:
        data = {"kind": kind, "peer": peer}
        if before is not None:
            data["before"] = before
        if after is not None:
            data["after"] = after
        self._events.append(TimelineEvent(
            seq=self._next_seq(), ts=self._ts(),
            event_type="fault", data=data
        ))

    def record_scenario(self, name: str, details: dict | None = None) -> None:
        data = {"name": name}
        if details:
            data.update(details)
        self._events.append(TimelineEvent(
            seq=self._next_seq(), ts=self._ts(),
            event_type="scenario", data=data
        ))

    def record_move(self, fr: int, fc: int, tr: int, tc: int,
                    team_key: str, flags: dict | None = None) -> None:
        self._events.append(TimelineEvent(
            seq=self._next_seq(), ts=self._ts(),
            event_type="move", data={
                "fr": fr, "fc": fc, "tr": tr, "tc": tc,
                "team": team_key, "flags": flags or {}
            }
        ))

    def record_connect(self, peer: str) -> None:
        self._events.append(TimelineEvent(
            seq=self._next_seq(), ts=self._ts(),
            event_type="connect", data={"peer": peer}
        ))

    def record_disconnect(self, peer: str, reason: str = "") -> None:
        data = {"peer": peer}
        if reason:
            data["reason"] = reason
        self._events.append(TimelineEvent(
            seq=self._next_seq(), ts=self._ts(),
            event_type="disconnect", data=data
        ))

    def record_reconnect(self, peer: str, success: bool) -> None:
        self._events.append(TimelineEvent(
            seq=self._next_seq(), ts=self._ts(),
            event_type="reconnect", data={"peer": peer, "success": success}
        ))

    def record_event(self, event_type: str, details: dict) -> None:
        """Record a generic event (fault_injected, recovery_success, etc.)."""
        self._events.append(TimelineEvent(
            seq=self._next_seq(), ts=self._ts(),
            event_type=event_type, data=details
        ))

    def record_reconnect(self, peer: str, success: bool) -> None:
        self._events.append(TimelineEvent(
            seq=self._next_seq(), ts=self._ts(),
            event_type="reconnect", data={"peer": peer, "success": success}
        ))

    @property
    def events(self) -> list[TimelineEvent]:
        return self._events[:]

    def to_timeline(self) -> list[dict]:
        return [e.to_dict() for e in self._events]

    def clear(self) -> None:
        self._events.clear()
        self._start_time = time.time()
        self._seq = 0


def save_chaos_corpus(
    crashes_dir: Path,
    source: str,
    seeds: dict[str, int],
    chaos_profile: str,
    timeline: list[dict],
    failure: dict,
    team_r_rgb: tuple[int, int, int] | None = None,
    team_l_rgb: tuple[int, int, int] | None = None,
    mode: str | None = None,
) -> Path:
    """Write a chaos corpus file (v2) and return its path.

    Parameters
    ----------
    crashes_dir:
        Directory to write the file into (created if needed).
    source:
        Fuzzer that produced this corpus (e.g. ``"grand_e2e"``).
    seeds:
        Dict of seeds: ``{"game": int, "fault": int, "timing": int}``.
    chaos_profile:
        Name of chaos profile used (e.g. ``"standard"``).
    timeline:
        List of timeline event dicts from TimelineRecorder.to_timeline().
    failure:
        Dict with ``seq`` (int), ``kind`` (str), ``detail`` (str), etc.
    team_r_rgb, team_l_rgb:
        Optional team colours for board reconstruction.
    mode:
        Slave mode used (e.g. ``"lan_host"``, ``"online_host"``).
    """
    crashes_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%S")
    kind = failure.get("kind", "unknown")
    seq = failure.get("seq", 0)
    fname = f"chaos_{ts}_{kind}_seq{seq}.corpus.json"

    corpus: dict[str, Any] = {
        "version": CORPUS_VERSION_CHAOS,
        "type": "chaos",
        "created": now.isoformat(),
        "source": source,
        "seeds": seeds,
        "chaos_profile": chaos_profile,
        "timeline": timeline,
        "failure": failure,
    }
    if team_r_rgb:
        corpus["team_r_rgb"] = list(team_r_rgb)
    if team_l_rgb:
        corpus["team_l_rgb"] = list(team_l_rgb)
    if mode:
        corpus["mode"] = mode

    path = crashes_dir / fname
    path.write_text(json.dumps(corpus, indent=2))
    return path


def save_corpus(
    crashes_dir: Path,
    corpus_type: str,
    source: str,
    team_r_rgb: tuple[int, int, int],
    team_l_rgb: tuple[int, int, int],
    moves: list[dict],
    failure: dict,
    seed: int,
) -> Path:
    """Write a ``.corpus.json`` file and return its path.

    Parameters
    ----------
    crashes_dir:
        Directory to write the file into (created if needed).
    corpus_type:
        ``"chess"`` or ``"networked"``.
    source:
        Fuzzer that produced this corpus (e.g. ``"fuzz_chess"``).
    team_r_rgb, team_l_rgb:
        Team colours as (r, g, b) tuples.
    moves:
        List of move dicts, each with ``fr, fc, tr, tc, team_key, flags``.
    failure:
        Dict with at least ``ply`` (int) and ``kind`` (str).  May also have
        ``detail``, ``py_hash``, ``js_hash``, etc.
    seed:
        Original game seed (kept for reference, not required for replay).
    """
    crashes_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%S")
    kind = failure.get("kind", "unknown")
    ply = failure.get("ply", 0)
    fname = f"{corpus_type}_{ts}_{kind}_ply{ply}.corpus.json"

    corpus = {
        "version": CORPUS_VERSION_LEGACY,
        "type": corpus_type,
        "created": now.isoformat(),
        "source": source,
        "team_r_rgb": list(team_r_rgb),
        "team_l_rgb": list(team_l_rgb),
        "moves": moves,
        "failure": failure,
        "seed": seed,
    }

    path = crashes_dir / fname
    path.write_text(json.dumps(corpus, indent=2))
    return path


def load_corpus(path: Path) -> dict:
    """Load and validate a corpus file. Raises ``ValueError`` on problems.

    Supports both v1 (legacy move-based) and v2 (chaos timeline) formats.
    """
    data = json.loads(path.read_text())

    if not isinstance(data, dict):
        raise ValueError(f"{path}: root is not an object")
    if "version" not in data:
        raise ValueError(
            f"{path}: not a corpus file (no 'version' field). "
            f"Use a .corpus.json file, not a plain crash .json file."
        )

    version = data["version"]

    if version == CORPUS_VERSION_LEGACY:
        # V1: move-based corpus
        if data.get("type") not in ("chess", "networked"):
            raise ValueError(f"{path}: unknown type {data.get('type')!r}")
        if not isinstance(data.get("moves"), list):
            raise ValueError(f"{path}: 'moves' must be a list")
        if not isinstance(data.get("failure"), dict):
            raise ValueError(f"{path}: 'failure' must be an object")

    elif version == CORPUS_VERSION_CHAOS:
        # V2: chaos timeline corpus
        if data.get("type") != "chaos":
            raise ValueError(f"{path}: v2 corpus must have type 'chaos'")
        if not isinstance(data.get("seeds"), dict):
            raise ValueError(f"{path}: 'seeds' must be an object")
        if not isinstance(data.get("timeline"), list):
            raise ValueError(f"{path}: 'timeline' must be a list")
        if not isinstance(data.get("failure"), dict):
            raise ValueError(f"{path}: 'failure' must be an object")

    else:
        raise ValueError(
            f"{path}: unsupported version {version} "
            f"(expected {CORPUS_VERSION_LEGACY} or {CORPUS_VERSION_CHAOS})"
        )

    return data


def is_chaos_corpus(corpus: dict) -> bool:
    """Check if a loaded corpus is a chaos corpus (v2)."""
    return corpus.get("version") == CORPUS_VERSION_CHAOS


def discover_corpus(
    directory: Path, corpus_type: str | None = None,
) -> list[Path]:
    """Find all ``.corpus.json`` files under *directory*.

    Optionally filter by corpus type (``"chess"``, ``"networked"``, or ``"chaos"``).
    Returns paths sorted by name for deterministic test ordering.
    """
    if not directory.is_dir():
        return []

    files = sorted(directory.rglob("*.corpus.json"))

    if corpus_type is not None:
        filtered = []
        for f in files:
            try:
                data = json.loads(f.read_text())
                if data.get("type") == corpus_type:
                    filtered.append(f)
            except (json.JSONDecodeError, OSError):
                continue
        return filtered

    return files


def extract_moves_from_timeline(timeline: list[dict]) -> list[dict]:
    """Extract move events from a chaos timeline for legacy replay."""
    moves = []
    for event in timeline:
        if event.get("type") == "move":
            moves.append({
                "fr": event["fr"],
                "fc": event["fc"],
                "tr": event["tr"],
                "tc": event["tc"],
                "team_key": event["team"],
                "flags": event.get("flags", {}),
            })
    return moves
