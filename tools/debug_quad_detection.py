"""Visual debug tool for ChessMatrix quad detection.

Each pipeline stage is numbered.  Pass --step N to output images frozen at
that stage so you can see exactly what the detector is doing at each point.

Pipeline stages
---------------
  1  grayscale  – simple channel-average float image
  2  normalize  – stretched to full [0,255] range
  3  blur       – adaptive Gaussian blur
  4  binarize   – local mean–variance threshold  T = max(m - k1·s², k2)
 11  orient     – rotate rectified image so the white L finder is at bottom-left

Usage
-----
    .venv/bin/python tools/debug_quad_detection.py --step 4          # binarized images
    .venv/bin/python tools/debug_quad_detection.py --step 4 --synth  # include synthetics
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
import numpy as np
import cv2

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES_DIR = ROOT / "tests" / "fixtures" / "chessmatrix"
OUT_DIR      = ROOT / "tests" / "fixtures" / "chessmatrix_debug"


# ── Per-step renderers ────────────────────────────────────────────────────────

def _render_grayscale(frame, pipeline):
    gray_u8 = np.clip(pipeline["gray_f"], 0, 255).astype(np.uint8)
    return cv2.cvtColor(gray_u8, cv2.COLOR_GRAY2BGR)

def _render_normalize(frame, pipeline):
    return cv2.cvtColor(pipeline["norm"], cv2.COLOR_GRAY2BGR)

def _render_blur(frame, pipeline):
    return cv2.cvtColor(pipeline["blurred"], cv2.COLOR_GRAY2BGR)

def _render_binarize(frame, pipeline):
    return cv2.cvtColor(pipeline["binary"], cv2.COLOR_GRAY2BGR)


def _render_centroid(frame, pipeline):
    out    = cv2.cvtColor(pipeline["binary"], cv2.COLOR_GRAY2BGR)
    binary = pipeline["binary"]
    white  = np.argwhere(binary > 0)   # (N, 2) array of [row, col]
    if len(white) == 0:
        cv2.putText(out, "no white pixels", (6, out.shape[0] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 220), 1)
        return out
    cy, cx = white.mean(axis=0)
    cx, cy = int(round(cx)), int(round(cy))
    cv2.drawMarker(out, (cx, cy), (0, 0, 255),
                   markerType=cv2.MARKER_CROSS, markerSize=20, thickness=2)
    cv2.circle(out, (cx, cy), 6, (0, 0, 255), -1)
    cv2.putText(out, f"centroid ({cx},{cy})", (6, out.shape[0] - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    return out


def _hough_axes(binary):
    """Find the two dominant perpendicular orientations via Hough lines.

    Runs probabilistic Hough on the binary image edges, buckets each line
    segment's angle into 1° bins, folds the histogram to [0°,90°) (since
    0° and 180° are the same line direction), then picks the peak bin as
    axis1 and the bin 90° away as axis2.

    Returns (angle1_deg, angle2_deg) or None if no lines found.
    """
    edges = cv2.Canny(binary, 30, 100)
    lines = cv2.HoughLinesP(edges, rho=1, theta=np.pi/180,
                             threshold=20, minLineLength=10, maxLineGap=5)
    if lines is None:
        return None

    # Accumulate angles into 1° bins over [0, 180)
    hist = np.zeros(180, dtype=np.float32)
    for x1, y1, x2, y2 in lines[:, 0]:
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180
        hist[int(angle)] += np.hypot(x2 - x1, y2 - y1)   # weight by length

    # Fold to [0, 90): bin b and bin b+90 are the same axis family
    folded = hist[:90] + hist[90:]
    a1 = int(np.argmax(folded))
    a2 = (a1 + 90) % 180
    return float(a1), float(a2)


def _render_hough(frame, pipeline):
    out   = cv2.cvtColor(pipeline["binary"], cv2.COLOR_GRAY2BGR)
    h_img, w_img = out.shape[:2]
    c     = pipeline["centroid"]
    if c is None:
        cv2.putText(out, "no centroid", (6, h_img - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 220), 1)
        return out

    axes = _hough_axes(pipeline["binary"])
    if axes is None:
        cv2.putText(out, "no lines found", (6, h_img - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 220), 1)
        return out

    cx, cy   = float(c[0]), float(c[1])
    scale    = min(h_img, w_img) * 0.3
    a1, a2   = axes
    for angle, color in [(a1, (0, 0, 255)), (a2, (255, 80, 0))]:
        rad = np.radians(angle)
        dx, dy = np.cos(rad) * scale, np.sin(rad) * scale
        p1 = (int(cx - dx), int(cy - dy))
        p2 = (int(cx + dx), int(cy + dy))
        cv2.arrowedLine(out, p1, p2, color, 2, tipLength=0.08)

    cv2.circle(out, (int(cx), int(cy)), 4, (0, 255, 0), -1)
    cv2.putText(out, f"axes {a1:.0f}deg / {a2:.0f}deg", (6, h_img - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 1)
    return out


def _inflate_rect_tolerant(binary, cx, cy, tolerance=0.08):
    """Grow an axis-aligned rectangle from (cx,cy), stopping a side when the
    fraction of white pixels on that edge exceeds *tolerance*."""
    h, w  = binary.shape
    top   = bottom = int(cy)
    left  = right  = int(cx)

    def _white_frac_h(row, l, r):
        strip = binary[row, l:r+1]
        return strip.mean() / 255.0

    def _white_frac_v(col, t, b):
        strip = binary[t:b+1, col]
        return strip.mean() / 255.0

    changed = True
    while changed:
        changed = False
        if top > 0 and _white_frac_h(top-1, left, right) < tolerance:
            top -= 1;    changed = True
        if bottom < h-1 and _white_frac_h(bottom+1, left, right) < tolerance:
            bottom += 1; changed = True
        if left > 0 and _white_frac_v(left-1, top, bottom) < tolerance:
            left -= 1;   changed = True
        if right < w-1 and _white_frac_v(right+1, top, bottom) < tolerance:
            right += 1;  changed = True

    return left, top, right, bottom


def _render_oriented_inflate(frame, pipeline):
    out   = cv2.cvtColor(pipeline["binary"], cv2.COLOR_GRAY2BGR)
    h_img, w_img = out.shape[:2]
    c     = pipeline["centroid"]
    if c is None:
        cv2.putText(out, "no centroid", (6, h_img - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 220), 1)
        return out

    axes = _hough_axes(pipeline["binary"])
    if axes is None:
        cv2.putText(out, "no hough lines", (6, h_img - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 220), 1)
        return out

    cx, cy = float(c[0]), float(c[1])
    a1, _  = axes

    # Rotate binary so the code axes are horizontal/vertical.
    # a1 is the angle of the dominant Hough lines; rotating by -(a1-90)
    # aligns those lines with the vertical axis.
    align = a1 - 90
    M     = cv2.getRotationMatrix2D((cx, cy), align, 1.0)
    rot   = cv2.warpAffine(pipeline["binary"], M, (w_img, h_img),
                           flags=cv2.INTER_NEAREST)

    l, t, r, b = _inflate_rect_tolerant(rot, cx, cy)

    # Transform the 4 corners back to original image space
    M_inv = cv2.getRotationMatrix2D((cx, cy), -align, 1.0)
    corners_rot = np.float32([[l, t], [r, t], [r, b], [l, b]])
    ones        = np.ones((4, 1), dtype=np.float32)
    corners_h   = np.hstack([corners_rot, ones])
    corners_orig = (M_inv @ corners_h.T).T.astype(np.int32)  # (4,2)

    cv2.polylines(out, [corners_orig.reshape(-1, 1, 2)],
                  isClosed=True, color=(0, 255, 0), thickness=2)
    for pt in corners_orig:
        cv2.circle(out, tuple(pt), 4, (0, 0, 255), -1)
    cv2.circle(out, (int(cx), int(cy)), 4, (0, 0, 255), -1)
    cv2.putText(out, f"oriented rect  angle={a1:.0f}deg", (6, h_img - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 1)
    return out


def _get_oriented_corners(pipeline):
    """Shared helper — returns (corners (4,2) int32, cx, cy) or None."""
    c = pipeline["centroid"]
    if c is None:
        return None
    axes = _hough_axes(pipeline["binary"])
    if axes is None:
        return None

    cx, cy   = float(c[0]), float(c[1])
    a1, _    = axes
    align    = a1 - 90
    h_img, w_img = pipeline["binary"].shape

    M     = cv2.getRotationMatrix2D((cx, cy), align, 1.0)
    rot   = cv2.warpAffine(pipeline["binary"], M, (w_img, h_img),
                           flags=cv2.INTER_NEAREST)
    l, t, r, b = _inflate_rect_tolerant(rot, cx, cy)

    M_inv       = cv2.getRotationMatrix2D((cx, cy), -align, 1.0)
    corners_rot = np.float32([[l, t], [r, t], [r, b], [l, b]])
    ones        = np.ones((4, 1), dtype=np.float32)
    corners_h   = np.hstack([corners_rot, ones])
    corners     = (M_inv @ corners_h.T).T.astype(np.int32)
    return corners, int(cx), int(cy)


def _render_outer_rect(frame, pipeline):
    out   = cv2.cvtColor(pipeline["binary"], cv2.COLOR_GRAY2BGR)
    h_img = out.shape[0]
    result = _get_oriented_corners(pipeline)
    if result is None:
        cv2.putText(out, "no rect", (6, h_img - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 220), 1)
        return out

    corners, _, _ = result
    # Centroid of the inner rectangle corners
    center = corners.astype(np.float32).mean(axis=0)
    icx, icy = int(round(center[0])), int(round(center[1]))

    # Inner rect (green)
    cv2.polylines(out, [corners.reshape(-1, 1, 2)],
                  isClosed=True, color=(0, 255, 0), thickness=1)

    # Outer rect scaled 4/3 from inner centroid (red)
    outer = ((corners.astype(np.float32) - center) * (4.0 / 3.0) + center).astype(np.int32)
    cv2.polylines(out, [outer.reshape(-1, 1, 2)],
                  isClosed=True, color=(0, 0, 255), thickness=2)
    for pt in outer:
        cv2.circle(out, tuple(pt), 4, (0, 0, 255), -1)
    cv2.circle(out, (icx, icy), 5, (0, 255, 255), -1)   # inner rect centroid
    cv2.putText(out, "inner (green)  outer 4/3 (red)", (6, h_img - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 0), 1)
    return out


_WARP_SIZE = 256   # output square side length for rectification


def _get_outer_corners(pipeline):
    """Returns (outer (4,2) float32 ordered TL/TR/BR/BL, H 3×3) or None.
    H is the perspective transform from outer corners → _WARP_SIZE square."""
    result = _get_oriented_corners(pipeline)
    if result is None:
        return None
    corners, _, _ = result
    center = corners.astype(np.float32).mean(axis=0)
    outer  = ((corners.astype(np.float32) - center) * (4.0 / 3.0) + center)

    # Order: TL has smallest x+y, BR largest; TR smallest y-x, BL largest
    s   = outer.sum(axis=1)
    d   = np.diff(outer, axis=1).flatten()
    ordered = np.zeros((4, 2), dtype=np.float32)
    ordered[0] = outer[np.argmin(s)]   # TL
    ordered[2] = outer[np.argmax(s)]   # BR
    ordered[1] = outer[np.argmin(d)]   # TR
    ordered[3] = outer[np.argmax(d)]   # BL

    n = float(_WARP_SIZE)
    dst = np.float32([[0, 0], [n-1, 0], [n-1, n-1], [0, n-1]])
    H   = cv2.getPerspectiveTransform(ordered, dst)
    return ordered, H


def _render_rectify_binary(frame, pipeline):
    out   = cv2.cvtColor(pipeline["binary"], cv2.COLOR_GRAY2BGR)
    h_img = out.shape[0]
    r = _get_outer_corners(pipeline)
    if r is None:
        cv2.putText(out, "no rect", (6, h_img - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 220), 1)
        return out
    ordered, H = r
    warped = cv2.warpPerspective(pipeline["binary"], H, (_WARP_SIZE, _WARP_SIZE))
    return cv2.cvtColor(warped, cv2.COLOR_GRAY2BGR)


def _render_rectify_color(frame, pipeline):
    h_img = frame.shape[0]
    r = _get_outer_corners(pipeline)
    if r is None:
        out = frame.copy()
        cv2.putText(out, "no rect", (6, h_img - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 220), 1)
        return out
    _, H = r
    return cv2.warpPerspective(frame, H, (_WARP_SIZE, _WARP_SIZE))


def _get_oriented_color(frame, pipeline):
    """Shared helper: returns the oriented rectified color image, or None on failure.

    Warps the color frame using the outer-rect homography, recomputes the
    white-pixel centroid in the rectified binary (no outside-rectangle noise),
    and rotates with np.rot90 so the L finder corner ends up at bottom-left.
    """
    r = _get_outer_corners(pipeline)
    if r is None:
        return None
    _, H = r
    rect_color  = cv2.warpPerspective(frame, H, (_WARP_SIZE, _WARP_SIZE))
    rect_binary = cv2.warpPerspective(pipeline["binary"], H, (_WARP_SIZE, _WARP_SIZE),
                                      flags=cv2.INTER_NEAREST)
    white = np.argwhere(rect_binary > 0)
    if len(white) == 0:
        return None   # can't determine orientation
    ry, rx = white.mean(axis=0)
    n = float(_WARP_SIZE)
    corners = {'TL': (0, 0), 'TR': (n, 0), 'BL': (0, n), 'BR': (n, n)}
    l_corner = min(corners, key=lambda name: (rx - corners[name][0])**2
                                           + (ry - corners[name][1])**2)
    k = {'TL': 1, 'TR': 2, 'BL': 0, 'BR': 3}[l_corner]
    return np.ascontiguousarray(np.rot90(rect_color, k=k)), l_corner, rx, ry


def _render_orient(frame, pipeline):
    """Step 11: Rotate rectified image so the white L finder sits at bottom-left."""
    h_img = frame.shape[0]
    result = _get_oriented_color(frame, pipeline)
    if result is None:
        out = frame.copy()
        cv2.putText(out, "no rect", (6, h_img - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 220), 1)
        return out
    oriented, l_corner, rx, ry = result
    k = {'TL': 1, 'TR': 2, 'BL': 0, 'BR': 3}[l_corner]
    cv2.putText(oriented, f"L@{l_corner} k={k}  centroid=({rx:.0f},{ry:.0f})",
                (4, _WARP_SIZE - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 220, 0), 1)
    return oriented


def _channel_normed(frame, pipeline):
    """Shared helper: per-channel normalized oriented image, or None."""
    result = _get_oriented_color(frame, pipeline)
    if result is None:
        return None
    oriented, *_ = result
    b, g, r = cv2.split(oriented)
    return cv2.merge([
        cv2.normalize(b, None, 0, 255, cv2.NORM_MINMAX),
        cv2.normalize(g, None, 0, 255, cv2.NORM_MINMAX),
        cv2.normalize(r, None, 0, 255, cv2.NORM_MINMAX),
    ])


def _render_channel_norm(frame, pipeline):
    """Step 12: Normalize each BGR channel independently to [0, 255]."""
    out = _channel_normed(frame, pipeline)
    if out is None:
        err = frame.copy()
        cv2.putText(err, "no rect", (6, frame.shape[0] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 220), 1)
        return err
    return out


# Calibration anchor cells: (grid_row, grid_col, canonical_BGR)
# (7,0) is the L-finder corner, always white in canonical orientation.
# (1,1),(1,6),(6,1),(6,6) are the fixed color anchors from the chessmatrix spec.
_CAL_CELLS = [
    (7, 0, (255, 255, 255)),   # WHITE  – L corner
    (1, 1, (0,   0,   0)),     # BLACK  – anchor K
    (1, 6, (0,   0,   255)),   # RED    – anchor R  (BGR order)
    (6, 1, (0,   255, 0)),     # GREEN  – anchor G
    (6, 6, (255, 0,   0)),     # BLUE   – anchor B
]


def _sample_cell_bgr(img, grid_row, grid_col, patch=5):
    """Return the mean BGR float of a small patch at the centre of a grid cell."""
    cx, cy = _cell_center_px(grid_row, grid_col)
    r = patch // 2
    return img[cy - r:cy + r + 1, cx - r:cx + r + 1].astype(np.float32).mean(axis=(0, 1))


def _cell_center_px(grid_row, grid_col):
    """Return (cx, cy) pixel centre of a grid cell in the warped image.

    The outer corners are warped to fill the full _WARP_SIZE square, so the
    8×8 grid spans the entire image: cell_px = _WARP_SIZE // 8.
    """
    cell_px = _WARP_SIZE // 8
    cx = grid_col * cell_px + cell_px // 2
    cy = grid_row * cell_px + cell_px // 2
    return cx, cy


def _render_cal_debug(frame, pipeline):
    """Step 13: Draw a dot at each calibration cell, colored by what we sample there."""
    result = _get_oriented_color(frame, pipeline)
    if result is None:
        err = frame.copy()
        cv2.putText(err, "no rect", (6, frame.shape[0] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 220), 1)
        return err
    oriented, *_ = result
    out = oriented.copy()

    labels = ["W", "K", "R", "G", "B"]
    for (grid_row, grid_col, _), label in zip(_CAL_CELLS, labels):
        cx, cy = _cell_center_px(grid_row, grid_col)
        sampled = _sample_cell_bgr(oriented, grid_row, grid_col)
        color   = tuple(int(v) for v in sampled)
        cv2.circle(out, (cx, cy), 8, color, -1)
        cv2.circle(out, (cx, cy), 8, (200, 200, 200), 1)   # white outline
        cv2.putText(out, label, (cx - 4, cy + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (200, 200, 200), 1)
    return out


# Chessmatrix color values aligned with _CAL_CELLS order: white=-1, K=0, R=1, G=2, B=3
_CAL_CM_VALUES = [-1, 0, 1, 2, 3]

# Fast lookup: canonical BGR tuple → chessmatrix color value
_BGR_TO_CM: dict[tuple, int] = {
    bgr: cm for (_, _, bgr), cm in zip(_CAL_CELLS, _CAL_CM_VALUES)
}


def _color_calibrate_image(oriented):
    """Shared helper: map every pixel of *oriented* to its nearest canonical color.

    Returns the calibrated uint8 image.
    """
    sampled = np.array(
        [_sample_cell_bgr(oriented, r, c) for r, c, _ in _CAL_CELLS],
        dtype=np.float32,
    )  # (5, 3)
    canonical = np.array(
        [list(bgr) for _, _, bgr in _CAL_CELLS],
        dtype=np.float32,
    )  # (5, 3)
    img_f = oriented.astype(np.float32)
    diff  = img_f[:, :, np.newaxis, :] - sampled     # (H, W, 5, 3)
    dist2 = (diff ** 2).sum(axis=-1)                 # (H, W, 5)
    nearest = dist2.argmin(axis=-1)                  # (H, W)
    return canonical[nearest].astype(np.uint8)


def decode_oriented(oriented):
    """Color-calibrate *oriented*, build an 8×8 grid, and decode to a room code.

    Returns ``(code, grid, cal_img)`` where *code* is a 6-letter string on
    success or an error description string on failure.
    """
    import chessmatrix as _cm
    from network.chessmatrix import bytes_to_room_code

    cal_img = _color_calibrate_image(oriented)

    grid = []
    for row in range(8):
        grid_row = []
        for col in range(8):
            cx, cy = _cell_center_px(row, col)
            bgr = tuple(int(v) for v in cal_img[cy, cx])
            grid_row.append(_BGR_TO_CM.get(bgr, 0))
        grid.append(grid_row)

    try:
        code = bytes_to_room_code(_cm.decode(grid))
    except Exception as exc:
        code = f"ERR:{exc}"

    return code, grid, cal_img


def _render_color_calibrate(frame, pipeline):
    """Step 14: Map every pixel to its nearest calibration color via L2 norm."""
    result = _get_oriented_color(frame, pipeline)
    if result is None:
        err = frame.copy()
        cv2.putText(err, "no rect", (6, frame.shape[0] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 220), 1)
        return err
    oriented, *_ = result
    return _color_calibrate_image(oriented)


def _render_decode(frame, pipeline):
    """Step 15: Full decode → overlay room code on calibrated image."""
    result = _get_oriented_color(frame, pipeline)
    if result is None:
        err = frame.copy()
        cv2.putText(err, "no rect", (6, frame.shape[0] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 220), 1)
        return err
    oriented, *_ = result
    code, _, cal_img = decode_oriented(oriented)
    out = cal_img.copy()
    ok = len(code) == 6 and code.isalpha()
    cv2.putText(out, code,
                (8, _WARP_SIZE // 2 + 8),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                (0, 220, 0) if ok else (0, 0, 220), 2)
    return out


def decode_frame_live(frame: "np.ndarray") -> dict:
    """Run the full pipeline on one frame and return a display dict.

    Returns:
        code   – 6-letter room code string, or None
        outer  – (4,2) float32 outer-rect corners (TL/TR/BR/BL), or None
        cal_img – _WARP_SIZE square calibrated BGR image, or None
    """
    pipeline      = _run_pipeline(frame)
    code          = None
    outer_corners = None
    cal_img       = None

    r = _get_outer_corners(pipeline)
    if r is not None:
        outer_corners, _ = r
        result = _get_oriented_color(frame, pipeline)
        if result is not None:
            oriented, *_ = result
            decoded, _, cal_img = decode_oriented(oriented)
            if len(decoded) == 6 and decoded.isalpha():
                code = decoded

    return {"code": code, "outer": outer_corners, "cal_img": cal_img}


STEPS = {i+1: name for i, name in enumerate([
    "grayscale",         # 1
    "normalize",         # 2
    "blur",              # 3
    "binarize",          # 4
    "centroid",          # 5
    "hough",             # 6  dominant line angles → code orientation
    "orient-inflate",    # 7  inscribed rect aligned to hough axes, noise-tolerant
    "outer-rect",        # 8  outer rect scaled 4/3 from inner centroid
    "rectify-binary",    # 9  perspective-warp binary into _WARP_SIZE square
    "rectify-color",     # 10 same transform applied to original color frame
    "orient",            # 11 rotate rectified image so white L finder is at BL
    "channel-norm",      # 12 normalize each BGR channel independently to [0, 255]
    "cal-debug",         # 13 dot at each calibration cell, colored by sampled value
    "color-calibrate",   # 14 nearest-calibration-color via L2 norm on 5 anchor cells
    "decode",            # 15 build 8×8 grid from calibrated image → room code
])}

_RENDERERS = {i+1: fn for i, fn in enumerate([
    _render_grayscale,
    _render_normalize,
    _render_blur,
    _render_binarize,
    _render_centroid,
    _render_hough,
    _render_oriented_inflate,
    _render_outer_rect,
    _render_rectify_binary,
    _render_rectify_color,
    _render_orient,
    _render_channel_norm,
    _render_cal_debug,
    _render_color_calibrate,
    _render_decode,
])}


# ── Pipeline runner ───────────────────────────────────────────────────────────

def _run_pipeline(frame) -> dict:
    from network.chessmatrix import _local_threshold

    gray_f  = np.mean(frame.astype(np.float32), axis=2)   # simple average, not luminance
    norm    = cv2.normalize(gray_f, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
    h, w    = norm.shape
    k       = max(3, int(min(h, w) * 0.015)) | 1           # adaptive kernel, must be odd
    blurred = cv2.GaussianBlur(norm, (k, k), 0)
    binary  = _local_threshold(blurred)

    white = np.argwhere(binary > 0)
    centroid = tuple(white.mean(axis=0)[::-1].astype(int)) if len(white) > 0 else None  # (cx, cy)

    return {
        "gray_f":   gray_f,
        "norm":     norm,
        "blurred":  blurred,
        "binary":   binary,
        "centroid": centroid,
    }


def _process(name: str, frame, step: int) -> None:
    pipeline  = _run_pipeline(frame)
    out       = _RENDERERS[step](frame, pipeline)
    cv2.imwrite(str(OUT_DIR / f"{name}.png"), out)
    print(f"  {name}")


# ── Synthetic frame factory ───────────────────────────────────────────────────

def _make_synthetic_frames():
    from network.chessmatrix import encode

    def _barcode(cell_px=20):
        grid = encode("ABCDEF")
        size = 8 * cell_px
        img  = np.zeros((size, size, 3), dtype=np.uint8)
        for r in range(8):
            for c in range(8):
                rv, gv, bv = grid[r][c]
                img[r*cell_px:(r+1)*cell_px, c*cell_px:(c+1)*cell_px] = (bv, gv, rv)
        return img

    def _padded(cell_px=20, pad=40, bg=220):
        bc = _barcode(cell_px)
        h, w = bc.shape[:2]
        canvas = np.full((h + 2*pad, w + 2*pad, 3), bg, dtype=np.uint8)
        canvas[pad:pad+h, pad:pad+w] = bc
        return canvas

    yield "synth_clean_lightbg", _padded()
    yield "synth_clean_darkbg",  _padded(bg=20)

    src = _padded()
    h, w = src.shape[:2]
    M = cv2.getRotationMatrix2D((w/2, h/2), 30.0, 1.0)
    yield "synth_rot30", cv2.warpAffine(src, M, (w, h),
        borderMode=cv2.BORDER_CONSTANT, borderValue=(220, 220, 220))

    yield "synth_no_padding", _barcode()

    src = _padded(pad=60)
    h, w = src.shape[:2]
    d = int(min(h, w) * 0.08)
    src_pts = np.float32([[0,0],[w,0],[w,h],[0,h]])
    dst_pts = np.float32([[d,0],[w-d,d],[w,h],[0,h-d]])
    H = cv2.getPerspectiveTransform(src_pts, dst_pts)
    yield "synth_perspective", cv2.warpPerspective(src, H, (w, h),
        borderMode=cv2.BORDER_CONSTANT, borderValue=(220, 220, 220))


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--step", type=int, choices=STEPS, default=max(STEPS),
        help="Pipeline stage to render: " + "  ".join(f"{k}={v}" for k, v in STEPS.items()),
    )
    ap.add_argument("--synth", action="store_true",
                    help="Also include synthetic test frames")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\nStep {args.step}: {STEPS[args.step]}")
    print(f"Output → {OUT_DIR.relative_to(ROOT)}\n")

    fixture_paths = sorted(FIXTURES_DIR.glob("*.png"))
    if fixture_paths:
        print(f"Fixture images ({len(fixture_paths)} files)")
        for p in fixture_paths:
            frame = cv2.imread(str(p))
            if frame is None:
                print(f"  ?  {p.stem}  [could not read]")
                continue
            _process(p.stem, frame, args.step)

    if args.synth:
        print("\nSynthetic frames")
        for name, frame in _make_synthetic_frames():
            _process(name, frame, args.step)


if __name__ == "__main__":
    main()
