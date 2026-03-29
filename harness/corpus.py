"""Corpus file management for fuzzer-discovered disagreements.

A corpus file is a self-contained JSON document that captures the complete
move sequence leading to a disagreement, independent of fuzzer RNG state.
Corpus files can be replayed as regression tests or loaded into the
interactive simulator for human investigation.

File format: ``*.corpus.json`` — see ``save_corpus`` for the schema.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

CORPUS_VERSION = 1


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
        "version": CORPUS_VERSION,
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
    """Load and validate a corpus file. Raises ``ValueError`` on problems."""
    data = json.loads(path.read_text())

    if not isinstance(data, dict):
        raise ValueError(f"{path}: root is not an object")
    if "version" not in data:
        raise ValueError(
            f"{path}: not a corpus file (no 'version' field). "
            f"Use a .corpus.json file, not a plain crash .json file."
        )
    if data["version"] != CORPUS_VERSION:
        raise ValueError(
            f"{path}: unsupported version {data['version']} "
            f"(expected {CORPUS_VERSION})"
        )
    if data.get("type") not in ("chess", "networked"):
        raise ValueError(f"{path}: unknown type {data.get('type')!r}")
    if not isinstance(data.get("moves"), list):
        raise ValueError(f"{path}: 'moves' must be a list")
    if not isinstance(data.get("failure"), dict):
        raise ValueError(f"{path}: 'failure' must be an object")

    return data


def discover_corpus(
    directory: Path, corpus_type: str | None = None,
) -> list[Path]:
    """Find all ``.corpus.json`` files under *directory*.

    Optionally filter by corpus type (``"chess"`` or ``"networked"``).
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
