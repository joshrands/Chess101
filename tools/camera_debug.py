"""ChessMatrix live camera debug tool.

Opens a webcam (or a single image), runs the full decode pipeline on every
frame, and overlays:

  - A bounding box around the detected code:
      green  = successful 6-letter decode
      red    = code region found but decode failed
  - The decoded room code (or "???" on failure) next to the box
  - Bottom-right inset: color-calibrated 8×8 grid enlarged ×3
  - FPS counter

Usage
-----
    # Live camera (device 0 by default)
    .venv/bin/python tools/camera_debug.py

    # Different camera index
    .venv/bin/python tools/camera_debug.py --camera 1

    # Static image (processes once, waits for keypress)
    .venv/bin/python tools/camera_debug.py --image tests/fixtures/chessmatrix/ABCDEF_matrix.png

Keyboard controls
-----------------
    q / ESC  — quit
    s        — save current frame to tests/fixtures/chessmatrix/<CODE>_snapshot.png
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ChessMatrix camera debug tool")
    p.add_argument("--camera", type=int, default=0,
                   help="Camera device index (default 0)")
    p.add_argument("--image", type=str, default=None,
                   help="Path to a static image (skips live capture)")
    return p.parse_args()


def _build_display(frame, result: dict, fps: float, inset_scale: int = 3):
    import cv2
    import numpy as np

    h, w = frame.shape[:2]
    max_w = 960
    if w > max_w:
        s = max_w / w
        display = cv2.resize(frame.copy(), (int(w * s), int(h * s)))
        sx, sy = s, s
    else:
        display = frame.copy()
        sx, sy = 1.0, 1.0
    dh, dw = display.shape[:2]

    outer = result.get("outer")
    code  = result.get("code")

    # ── Bounding box ──────────────────────────────────────────────────────
    if outer is not None:
        pts   = (outer * np.array([sx, sy])).astype(int)
        color = (0, 220, 0) if code else (0, 0, 220)
        cv2.polylines(display, [pts.reshape(-1, 1, 2)], True, color, 2)

        # Label above the top-left corner
        label     = code if code else "???"
        label_pt  = (int(pts[:, 0].min()), max(int(pts[:, 1].min()) - 8, 18))
        cv2.putText(display, label, label_pt,
                    cv2.FONT_HERSHEY_DUPLEX, 0.9, color, 2)

    # ── Calibrated grid inset (bottom-right) ─────────────────────────────
    cal_img = result.get("cal_img")
    if cal_img is not None:
        inset_side = dh // inset_scale
        inset = cv2.resize(cal_img, (inset_side, inset_side),
                           interpolation=cv2.INTER_NEAREST)
        # Grid lines
        cell = inset_side // 8
        for i in range(9):
            cv2.line(inset, (i * cell, 0), (i * cell, inset_side), (60, 60, 60), 1)
            cv2.line(inset, (0, i * cell), (inset_side, i * cell), (60, 60, 60), 1)
        display[dh - inset_side:dh, dw - inset_side:dw] = inset
        cv2.rectangle(display,
                      (dw - inset_side, dh - inset_side),
                      (dw - 1, dh - 1),
                      (100, 100, 100), 1)
        cv2.putText(display, "calibrated",
                    (dw - inset_side + 4, dh - inset_side + 14),
                    cv2.FONT_HERSHEY_PLAIN, 0.9, (200, 200, 200), 1)

    # ── FPS ───────────────────────────────────────────────────────────────
    cv2.putText(display, f"FPS: {fps:.1f}", (10, 22),
                cv2.FONT_HERSHEY_PLAIN, 1.1, (180, 180, 180), 1)

    return display


def _save_snapshot(frame, code: str | None) -> None:
    import cv2
    out_dir = ROOT / "tests" / "fixtures" / "chessmatrix"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{code}_snapshot" if code else "debug_snapshot"
    path = out_dir / f"{stem}.png"
    cv2.imwrite(str(path), frame)
    print(f"Saved snapshot → {path}")


def main() -> None:
    try:
        import cv2
    except ImportError:
        sys.exit("opencv-python is required: pip install opencv-python")

    try:
        from debug_quad_detection import decode_frame_live
    except ImportError as e:
        sys.exit(f"Could not import debug_quad_detection: {e}\n"
                 "Run from the Chess101 project root.")

    args = _parse_args()

    # ── Static image mode ─────────────────────────────────────────────────
    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            sys.exit(f"Could not read image: {args.image}")
        print(f"Processing {args.image}  ({frame.shape[1]}×{frame.shape[0]})")
        result = decode_frame_live(frame)
        print(f"  code: {result['code']!r}")
        display = _build_display(frame, result, fps=0.0)
        cv2.imshow("ChessMatrix Debug", display)
        print("Press any key to quit, 's' to save snapshot.")
        while True:
            key = cv2.waitKey(0) & 0xFF
            if key in (ord('q'), 27):
                break
            elif key == ord('s'):
                _save_snapshot(frame, result.get("code"))
        cv2.destroyAllWindows()
        return

    # ── Live camera mode ──────────────────────────────────────────────────
    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        sys.exit(f"Could not open camera {args.camera}")

    print(f"Opened camera {args.camera}. Press q/ESC to quit, s to save.")

    fps         = 0.0
    frame_count = 0
    t_start     = time.monotonic()
    last_result: dict = {}

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Camera read failed — exiting.")
                break

            last_result  = decode_frame_live(frame)
            frame_count += 1
            elapsed      = time.monotonic() - t_start
            fps          = frame_count / elapsed if elapsed > 0 else 0.0

            display = _build_display(frame, last_result, fps)
            cv2.imshow("ChessMatrix Debug", display)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):
                break
            elif key == ord('s'):
                _save_snapshot(frame, last_result.get("code"))
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
