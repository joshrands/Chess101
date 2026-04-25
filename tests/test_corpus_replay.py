"""Corpus regression tests: replay fuzzer-discovered disagreements.

Discovers ``.corpus.json`` files from two sources:

1. **Checked-in fixtures** (``tests/fixtures/corpus/``) — curated
   representative samples of known bugs.  These are permanent regression
   tests that run in CI.

2. **Local crash directory** (``harness/crashes/``) — automatically
   populated by the lockstep fuzzers.  These are only present on
   developer machines and are skipped in CI.

Fixture corpus files carry a ``status`` field in their ``failure`` dict:

- ``"fixed"`` — the bug is resolved; the replay must complete without
  any hash or grid mismatch (a regression if it fails).
- ``"open"`` — the bug is still present; disagreement is expected and
  the test is marked ``xfail``.

Local crash files (no ``status``) default to ``"open"`` behavior.

Running
-------
    bazel test //tests:test_corpus_replay
    .venv/bin/python -m pytest tests/test_corpus_replay.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))

from python_bridge import JsBridge  # noqa: E402
from corpus import load_corpus, discover_corpus, is_chaos_corpus  # noqa: E402
from replay import ReplayEngine  # noqa: E402
from chaos_replay import ChaosReplayEngine  # noqa: E402

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "corpus"
_CRASHES_DIR = Path(__file__).resolve().parent.parent / "harness" / "crashes"


# ── fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def bridge():
    b = JsBridge()
    assert b.ping() == "pong"
    yield b
    b.close()


# ── corpus discovery ─────────────────────────────────────────────────────

def _discover_all() -> list[Path]:
    """Discover corpus files from both fixtures and local crashes."""
    seen: set[str] = set()
    result: list[Path] = []

    # Checked-in fixtures first (always present in CI)
    for p in discover_corpus(_FIXTURES_DIR):
        seen.add(p.name)
        result.append(p)

    # Local crash files (developer machines only, skip duplicates)
    for p in discover_corpus(_CRASHES_DIR):
        if p.name not in seen:
            result.append(p)

    return result


_CORPUS_FILES = _discover_all()


def _corpus_ids() -> list[str]:
    return [f.stem for f in _CORPUS_FILES]


# ── tests ────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _CORPUS_FILES, reason="no corpus files found")
class TestCorpusReplay:
    """Replay each corpus file and verify parity (or expected disagreement)."""

    @pytest.mark.parametrize(
        "corpus_path",
        _CORPUS_FILES,
        ids=_corpus_ids(),
    )
    def test_replay(self, bridge, corpus_path):
        corpus = load_corpus(corpus_path)
        status = corpus["failure"].get("status", "open")
        failure_kind = corpus["failure"].get("kind", "unknown")

        # ── Chaos corpus (network resilience) ────────────────────────────
        if is_chaos_corpus(corpus):
            engine = ChaosReplayEngine(corpus)
            result = engine.replay()

            if status == "fixed":
                # Bug is fixed — replay must succeed. Failure is regression.
                assert result.success, (
                    f"REGRESSION: chaos corpus failed after fix: "
                    f"{result.error}"
                )
            else:
                # Bug is open — failure is expected.
                if not result.success:
                    pytest.xfail(
                        f"Known chaos bug ({failure_kind}): {result.error}"
                    )
            return

        # ── Lockstep corpus (chess engine parity) ────────────────────────
        engine = ReplayEngine(corpus, bridge)
        engine.init()

        failure_ply = corpus["failure"]["ply"]

        while not engine.is_complete:
            result = engine.step()

            if result.ply == failure_ply:
                if status == "fixed":
                    # Bug is fixed — full replay must succeed without
                    # disagreement.  A failure here is a regression.
                    if failure_kind == "board_hash":
                        assert result.hashes_match is not False, (
                            f"REGRESSION at ply {failure_ply}: "
                            f"py={result.py_hash[:16]} js={result.js_hash[:16]}"
                        )
                    elif failure_kind == "grid_mismatch":
                        assert result.grid_mismatch is None, (
                            f"REGRESSION at ply {failure_ply}: "
                            f"{result.grid_mismatch}"
                        )
                    elif failure_kind == "legal_moves":
                        # legal_moves corpus stops before the disputed
                        # ply — reaching it without crash is the test.
                        pass
                else:
                    # Bug is open — disagreement is expected.
                    if failure_kind == "board_hash":
                        assert result.hashes_match is not None
                        if not result.hashes_match:
                            pytest.xfail(
                                f"Known hash disagreement at ply {failure_ply}: "
                                f"py={result.py_hash[:16]} js={result.js_hash[:16]}"
                            )
                    elif failure_kind == "grid_mismatch":
                        if result.grid_mismatch is not None:
                            pytest.xfail(
                                f"Known grid mismatch at ply {failure_ply}: "
                                f"{result.grid_mismatch}"
                            )
                    elif failure_kind == "legal_moves":
                        pass
