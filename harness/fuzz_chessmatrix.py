#!/usr/bin/env python3
"""ChessMatrix lockstep fuzzer.

Generates random synthetic barcode images with mutations (rotation, noise,
perspective, brightness) and checks that the Python and JS decoders agree.

Disagreements and crashes are saved to harness/crashes/chessmatrix/.

Usage::

    .venv/bin/python harness/fuzz_chessmatrix.py --iterations 10000
    .venv/bin/python harness/fuzz_chessmatrix.py --iterations 0  # run forever
"""

from __future__ import annotations

import argparse
import string
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# Allow imports from the project root and harness directory
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "harness"))

from python_bridge import JsBridge  # noqa: E402


# ── synthetic frame helpers ─────────────────────────────────────────────────

def random_room_code(rng: np.random.Generator) -> str:
    return "".join(rng.choice(list(string.ascii_uppercase), size=6))


def make_frame(room_code: str, cell_px: int = 20) -> np.ndarray:
    from network.chessmatrix import encode
    grid = encode(room_code)
    size = 8 * cell_px
    img = np.zeros((size, size, 3), dtype=np.uint8)
    for r in range(8):
        for c in range(8):
            rv, gv, bv = grid[r][c]
            y0, x0 = r * cell_px, c * cell_px
            img[y0:y0 + cell_px, x0:x0 + cell_px] = (bv, gv, rv)
    return img


def pad_frame(img: np.ndarray, pad: int = 60) -> np.ndarray:
    h, w = img.shape[:2]
    canvas = np.full((h + 2 * pad, w + 2 * pad, 3), 220, dtype=np.uint8)
    canvas[pad:pad + h, pad:pad + w] = img
    return canvas


# ── mutations ───────────────────────────────────────────────────────────────

def mutate_rotate(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    angle = rng.uniform(-180, 180)
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, M, (w, h),
                          borderMode=cv2.BORDER_CONSTANT,
                          borderValue=(220, 220, 220))


def mutate_noise(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    sigma = rng.uniform(5, 40)
    noise = rng.normal(0, sigma, img.shape).astype(np.float32)
    return np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def mutate_brightness(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    factor = rng.uniform(0.3, 2.0)
    return np.clip(img.astype(np.float32) * factor, 0, 255).astype(np.uint8)


def mutate_perspective(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    h, w = img.shape[:2]
    skew = rng.uniform(0.02, 0.15)
    dx, dy = w * skew, h * skew
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([
        [rng.uniform(0, dx), rng.uniform(0, dy)],
        [w - rng.uniform(0, dx), rng.uniform(0, dy)],
        [w - rng.uniform(0, dx), h - rng.uniform(0, dy)],
        [rng.uniform(0, dx), h - rng.uniform(0, dy)],
    ])
    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, M, (w, h),
                               borderMode=cv2.BORDER_CONSTANT,
                               borderValue=(220, 220, 220))


def mutate_salt_pepper(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    prob = rng.uniform(0.005, 0.03)
    out = img.copy()
    mask = rng.random(img.shape[:2])
    out[mask < prob / 2] = 0
    out[mask > 1 - prob / 2] = 255
    return out


MUTATIONS = [
    mutate_rotate,
    mutate_noise,
    mutate_brightness,
    mutate_perspective,
    mutate_salt_pepper,
]


# ── frame conversion ───────────────────────────────────────────────────────

def bgr_to_rgba(bgr: np.ndarray) -> bytes:
    rgb = bgr[:, :, ::-1]
    alpha = np.full((*rgb.shape[:2], 1), 255, dtype=np.uint8)
    return np.concatenate([rgb, alpha], axis=2).tobytes()


# ── main loop ──────────────────────────────────────────────────────────────

def run_fuzzer(iterations: int, seed: int) -> None:
    from network.chessmatrix import decode_frame as py_decode

    rng = np.random.default_rng(seed)
    crashes_dir = ROOT / "harness" / "crashes" / "chessmatrix"
    crashes_dir.mkdir(parents=True, exist_ok=True)

    bridge = JsBridge()
    assert bridge.ping() == "pong", "JS bridge failed to start"

    total = 0
    agree = 0
    disagree = 0
    errors = 0
    t0 = time.time()

    try:
        i = 0
        while iterations == 0 or i < iterations:
            code = random_room_code(rng)
            cell_px = int(rng.choice([14, 16, 18, 20, 24, 30]))
            pad = int(rng.integers(30, 100))

            frame = pad_frame(make_frame(code, cell_px=cell_px), pad=pad)

            # Apply 1-3 random mutations
            n_muts = int(rng.integers(1, 4))
            mutations_applied = []
            for _ in range(n_muts):
                mut = rng.choice(MUTATIONS)
                frame = mut(frame, rng)
                mutations_applied.append(mut.__name__)

            # Python decode
            try:
                py_result = py_decode(frame)
            except Exception as e:
                py_result = f"__ERROR__: {e}"

            # JS decode
            h, w = frame.shape[:2]
            try:
                js_result = bridge.decode_frame(bgr_to_rgba(frame), w, h)
            except Exception as e:
                js_result = f"__ERROR__: {e}"

            total += 1

            py_err = isinstance(py_result, str) and py_result.startswith("__ERROR__")
            js_err = isinstance(js_result, str) and js_result.startswith("__ERROR__")

            if py_err or js_err:
                errors += 1
                tag = "error"
            elif py_result == js_result:
                agree += 1
                tag = None
            else:
                disagree += 1
                tag = "disagree"

            if tag:
                fname = f"{tag}_{total:06d}_{code}.png"
                cv2.imwrite(str(crashes_dir / fname), frame)
                print(f"[{tag.upper()}] iter={total} code={code} "
                      f"muts={mutations_applied} py={py_result!r} js={js_result!r} "
                      f"→ {fname}")

            if total % 100 == 0:
                elapsed = time.time() - t0
                rate = total / elapsed if elapsed > 0 else 0
                print(f"  [{total}] agree={agree} disagree={disagree} "
                      f"errors={errors} ({rate:.0f} iter/s)")

            i += 1

    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        bridge.close()

    elapsed = time.time() - t0
    print(f"\nDone. {total} iterations in {elapsed:.1f}s")
    print(f"  agree={agree}  disagree={disagree}  errors={errors}")
    if disagree > 0:
        print(f"  Crash files in {crashes_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="ChessMatrix lockstep fuzzer")
    parser.add_argument("--iterations", type=int, default=1000,
                        help="Number of iterations (0 = infinite)")
    parser.add_argument("--seed", type=int, default=42,
                        help="RNG seed for reproducibility")
    args = parser.parse_args()
    run_fuzzer(args.iterations, args.seed)


if __name__ == "__main__":
    main()
