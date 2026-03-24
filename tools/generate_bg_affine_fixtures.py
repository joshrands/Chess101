"""Generate background × affine test fixture images for ChessMatrix scanning tests.

Writes one PNG per (background colour × affine transform) combination to
``tests/fixtures/chessmatrix/``.  Files are named::

    ABCDEF_<bg_name>-<tx_name>.png

Run from the Chess101 project root::

    .venv/bin/python tools/generate_bg_affine_fixtures.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "tests" / "fixtures" / "chessmatrix"
CODE = "ABCDEF"

BG_MATRIX = [
    ("black",      (0,   0,   0  )),
    ("white",      (255, 255, 255)),
    ("dark_gray",  (40,  40,  40 )),
    ("light_gray", (210, 210, 210)),
    ("red_bg",     (0,   0,   180)),
    ("green_bg",   (0,   180, 0  )),
    ("blue_bg",    (180, 0,   0  )),
    ("yellow_bg",  (0,   200, 200)),
    ("purple_bg",  (120, 0,   120)),
]

AFFINE_MATRIX = [
    ("upright",  0.0,   0.00),
    ("rot25sh",  25.0,  0.12),
    ("rot90sh",  90.0, -0.08),
    ("rot150sh", 150.0, 0.15),
]


def _make_barcode(code: str, cell_px: int = 20) -> "cv2.Mat":
    import numpy as np
    from network.chessmatrix import encode

    # encode() returns 8×8 (R,G,B) tuples with dark-mode inversion already applied.
    grid = encode(code)
    size = 8 * cell_px
    img = np.zeros((size, size, 3), dtype=np.uint8)
    for r in range(8):
        for c in range(8):
            rv, gv, bv = grid[r][c]
            img[r * cell_px:(r + 1) * cell_px, c * cell_px:(c + 1) * cell_px] = (bv, gv, rv)
    return img


def _make_affine_on_bg(
    code: str,
    bg_bgr: tuple[int, int, int],
    angle_deg: float,
    shear_x: float = 0.0,
    cell_px: int = 20,
    pad: int = 100,
) -> "cv2.Mat":
    import cv2
    import numpy as np

    barcode = _make_barcode(code, cell_px=cell_px)
    h, w = barcode.shape[:2]
    canvas = np.empty((h + 2 * pad, w + 2 * pad, 3), dtype=np.uint8)
    canvas[:] = bg_bgr
    canvas[pad:pad + h, pad:pad + w] = barcode

    ch, cw = canvas.shape[:2]
    R = cv2.getRotationMatrix2D((cw / 2, ch / 2), angle_deg, 1.0)
    rotated = cv2.warpAffine(canvas, R, (cw, ch),
                              borderMode=cv2.BORDER_CONSTANT,
                              borderValue=bg_bgr)
    if shear_x == 0.0:
        return rotated
    S = np.float32([[1, shear_x, 0], [0, 1, 0]])
    new_w = int(cw + abs(shear_x) * ch)
    return cv2.warpAffine(rotated, S, (new_w, ch),
                           borderMode=cv2.BORDER_CONSTANT,
                           borderValue=bg_bgr)


def main() -> None:
    try:
        import cv2
    except ImportError:
        sys.exit("opencv-python is required: pip install opencv-python")

    FIXTURES.mkdir(parents=True, exist_ok=True)
    count = 0
    for bg_name, bg_bgr in BG_MATRIX:
        for tx_name, angle, shear in AFFINE_MATRIX:
            frame = _make_affine_on_bg(CODE, bg_bgr, angle, shear)
            path = FIXTURES / f"{CODE}_{bg_name}-{tx_name}.png"
            cv2.imwrite(str(path), frame)
            count += 1
            print(f"  {path.name}")

    print(f"\nSaved {count} images to {FIXTURES}")


if __name__ == "__main__":
    main()
