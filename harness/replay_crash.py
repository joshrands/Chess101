#!/usr/bin/env python3
"""Replay a fuzzer crash image through both Python and JS decoders.

Loads a crash PNG, runs it through both pipelines, prints a comparison,
and dumps Python debug stage images for visual inspection.

Usage::

    .venv/bin/python harness/replay_crash.py harness/crashes/chessmatrix/disagree_000042_ABCDEF.png
    .venv/bin/python harness/replay_crash.py some_image.png --stages        # dump all 15 pipeline stages
    .venv/bin/python harness/replay_crash.py some_image.png --stages --js   # also open JS pipeline debugger hint
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "harness"))


# ── helpers ──────────────────────────────────────────────────────────────────

def bgr_to_rgba(bgr: np.ndarray) -> bytes:
    rgb = bgr[:, :, ::-1]
    alpha = np.full((*rgb.shape[:2], 1), 255, dtype=np.uint8)
    return np.concatenate([rgb, alpha], axis=2).tobytes()


def extract_expected_code(filepath: Path) -> str | None:
    """Try to pull the room code from the crash filename convention."""
    # e.g. disagree_000042_ABCDEF.png → ABCDEF
    stem = filepath.stem
    parts = stem.split("_")
    if len(parts) >= 3:
        candidate = parts[-1]
        if len(candidate) == 6 and candidate.isalpha() and candidate.isupper():
            return candidate
    return None


# ── decode helpers ───────────────────────────────────────────────────────────

def run_python_decode(frame: np.ndarray) -> tuple[str | None, dict]:
    """Run Python decode_frame_debug, return (code, debug_dict)."""
    from network.chessmatrix import decode_frame_debug
    debug = decode_frame_debug(frame)
    return debug.get("code"), debug


def run_js_decode(frame: np.ndarray) -> str | None:
    """Run JS decode via the bridge, return room code or None."""
    from python_bridge import JsBridge
    with JsBridge() as bridge:
        assert bridge.ping() == "pong", "JS bridge failed to start"
        h, w = frame.shape[:2]
        return bridge.decode_frame(bgr_to_rgba(frame), w, h)


# ── stage dump ───────────────────────────────────────────────────────────────

def dump_stages(frame: np.ndarray, out_dir: Path) -> None:
    """Run all 15 debug_quad_detection stages and save PNGs."""
    # Import the debug tool's internals
    sys.path.insert(0, str(ROOT / "tools"))
    import debug_quad_detection as dqd

    out_dir.mkdir(parents=True, exist_ok=True)
    pipeline = dqd._run_pipeline(frame)

    for step_num in sorted(dqd._RENDERERS):
        name = dqd.STEPS[step_num]
        try:
            img = dqd._RENDERERS[step_num](frame, pipeline)
            fname = f"{step_num:02d}_{name}.png"
            cv2.imwrite(str(out_dir / fname), img)
            print(f"  {fname}")
        except Exception as e:
            print(f"  {step_num:02d}_{name}: FAILED ({e})")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", type=Path, help="Path to crash PNG")
    parser.add_argument("--stages", action="store_true",
                        help="Dump all 15 Python pipeline stage images")
    parser.add_argument("--js", action="store_true",
                        help="Print hint for opening JS pipeline debugger")
    args = parser.parse_args()

    if not args.image.exists():
        print(f"Error: {args.image} not found")
        sys.exit(1)

    frame = cv2.imread(str(args.image))
    if frame is None:
        print(f"Error: could not read image {args.image}")
        sys.exit(1)

    h, w = frame.shape[:2]
    print(f"Image: {args.image} ({w}x{h})")

    expected = extract_expected_code(args.image)
    if expected:
        print(f"Expected code (from filename): {expected}")
    print()

    # ── Python decode ────────────────────────────────────────────────────
    print("Python decode_frame_debug:")
    try:
        py_code, debug = run_python_decode(frame)
        print(f"  code:    {py_code!r}")
        print(f"  quad:    {'found' if debug.get('quad') is not None else 'None'}")
        print(f"  warped:  {'found' if debug.get('warped') is not None else 'None'}")
        print(f"  cal:     {debug.get('cal')!r}")
        print(f"  grid:    {'found' if debug.get('grid') is not None else 'None'}")
    except Exception as e:
        py_code = None
        print(f"  ERROR: {e}")
    print()

    # ── JS decode ────────────────────────────────────────────────────────
    print("JS decodeFrame:")
    try:
        js_code = run_js_decode(frame)
        print(f"  code:    {js_code!r}")
    except Exception as e:
        js_code = None
        print(f"  ERROR: {e}")
    print()

    # ── Comparison ───────────────────────────────────────────────────────
    if py_code == js_code:
        print(f"AGREE: both returned {py_code!r}")
        if expected and py_code != expected:
            print(f"  (but expected {expected!r} from filename)")
    else:
        print(f"DISAGREE: py={py_code!r}  js={js_code!r}")
        if expected:
            py_ok = py_code == expected
            js_ok = js_code == expected
            if py_ok:
                print(f"  Python is correct (matches expected {expected!r})")
            elif js_ok:
                print(f"  JS is correct (matches expected {expected!r})")
            else:
                print(f"  Neither matches expected {expected!r}")

    # ── Stage dump ───────────────────────────────────────────────────────
    if args.stages:
        out_dir = args.image.parent / f"{args.image.stem}_stages"
        print(f"\nDumping pipeline stages to {out_dir}/")
        dump_stages(frame, out_dir)

    # ── JS hint ──────────────────────────────────────────────────────────
    if args.js:
        debugger_path = ROOT / "tools" / "pipeline_debug.html"
        print(f"\nTo debug the JS side, open in a browser:")
        print(f"  {debugger_path}")
        print(f"  Then load: {args.image.resolve()}")


if __name__ == "__main__":
    main()
