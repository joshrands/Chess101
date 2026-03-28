"""Corpus regression tests: replay fuzzer-discovered disagreements.

Automatically discovers all ``.corpus.json`` files in ``harness/crashes/``
and replays each through both Python and JS engines, verifying the
disagreement still reproduces.  When a bug is fixed, the corresponding
corpus test will start passing — flip it from ``xfail`` to a regular
assertion to lock in the fix.

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
from corpus import load_corpus, discover_corpus  # noqa: E402
from replay import ReplayEngine  # noqa: E402

CRASHES_DIR = Path(__file__).resolve().parent.parent / "harness" / "crashes"


# ── fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def bridge():
    b = JsBridge()
    assert b.ping() == "pong"
    yield b
    b.close()


# ── corpus discovery ─────────────────────────────────────────────────────

_CORPUS_FILES = discover_corpus(CRASHES_DIR)


def _corpus_ids() -> list[str]:
    return [f.stem for f in _CORPUS_FILES]


# ── tests ────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _CORPUS_FILES, reason="no corpus files found")
class TestCorpusReplay:
    """Replay each corpus file and verify the disagreement reproduces."""

    @pytest.mark.parametrize(
        "corpus_path",
        _CORPUS_FILES,
        ids=_corpus_ids(),
    )
    def test_replay(self, bridge, corpus_path):
        corpus = load_corpus(corpus_path)
        engine = ReplayEngine(corpus, bridge)
        engine.init()

        failure_ply = corpus["failure"]["ply"]
        failure_kind = corpus["failure"].get("kind", "unknown")

        while not engine.is_complete:
            result = engine.step()

            # At the failure ply, verify the disagreement reproduces.
            # These are expected to fail (bugs in JS engine are known);
            # when a bug is fixed, remove the xfail and keep the assertion.
            if result.ply == failure_ply:
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
                    # For legal_moves failures, the disagreement is about
                    # which moves are available, not about applying a move.
                    # The corpus stops before the disputed ply, so we just
                    # verify we can replay up to it without crashing.
                    pass
