"""
generate_icon.py — Chess101 app icon generator.

Renders the knight STL as a dark piece silhouette with a rainbow glow
that follows the shape of the piece, on a near-black background.

Usage:
    .venv/bin/python tools/generate_icon.py
Output:
    Chess101iOS/icon_1024.png
"""

import struct, math, os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import scipy.ndimage as ndi

SIZE = 1024
OUT_PATH = os.path.join(os.path.dirname(__file__), "..",
                        "Chess101iOS", "icon_1024.png")

# ── 1. Parse the STL ─────────────────────────────────────────────────────────

def load_stl(path):
    with open(path, "rb") as f:
        f.seek(80)
        n = struct.unpack("<I", f.read(4))[0]
    expected = 80 + 4 + n * 50
    if abs(os.path.getsize(path) - expected) < 10:
        tris = np.zeros((n, 3, 3), dtype=np.float32)
        with open(path, "rb") as f:
            f.seek(84)
            for i in range(n):
                d = f.read(50)
                v = struct.unpack("<12fH", d)
                tris[i] = [v[3:6], v[6:9], v[9:12]]
        return tris
    # ASCII fallback
    tris, verts = [], []
    with open(path, "r", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("vertex"):
                p = line.split()
                verts.append([float(p[1]), float(p[2]), float(p[3])])
                if len(verts) == 3:
                    tris.append(verts); verts = []
    return np.array(tris, dtype=np.float32)

# ── 2. Project + rasterize ────────────────────────────────────────────────────

def project_and_rasterize(tris, img_size):
    """
    STL has Y as vertical axis. Rotate around world-Y (turn) then world-X (tilt)
    so we see the side profile with Y running up the screen.
    """
    turn = math.radians(25)   # turn left/right around vertical
    tilt = math.radians(8)    # slight look-down from above

    ct, st   = math.cos(turn), math.sin(turn)
    cx2, sx2 = math.cos(tilt), math.sin(tilt)

    Ry = np.array([[ ct, 0, st], [0, 1, 0], [-st, 0, ct]], dtype=np.float32)
    Rx = np.array([[1, 0, 0], [0, cx2, sx2], [0, -sx2, cx2]], dtype=np.float32)
    R  = Rx @ Ry

    pts = tris.reshape(-1, 3) @ R.T
    pts = pts.reshape(-1, 3, 3)

    all_xy = pts[:, :, :2].reshape(-1, 2)
    mn, mx = all_xy.min(axis=0), all_xy.max(axis=0)
    span   = (mx - mn).max()
    pad    = 0.10
    scale  = (1.0 - 2 * pad) / span
    cx_w   = (mn[0] + mx[0]) / 2
    cy_w   = (mn[1] + mx[1]) / 2

    def to_px(xy):
        x = (xy[:, 0] - cx_w) * scale + 0.5
        y = (xy[:, 1] - cy_w) * scale + 0.5
        return np.stack([x * img_size, (1.0 - y) * img_size], axis=-1)

    all_z  = pts[:, :, 2].reshape(-1)
    z_min, z_max = all_z.min(), all_z.max()
    z_range = z_max - z_min if z_max > z_min else 1.0

    depth_buf = np.full((img_size, img_size), -np.inf, dtype=np.float32)
    mask      = np.zeros((img_size, img_size), dtype=np.uint8)

    for tri in pts:
        pix   = to_px(tri[:, :2])
        z_avg = tri[:, 2].mean()

        bx0 = max(0, int(pix[:, 0].min()) - 1)
        bx1 = min(img_size - 1, int(pix[:, 0].max()) + 2)
        by0 = max(0, int(pix[:, 1].min()) - 1)
        by1 = min(img_size - 1, int(pix[:, 1].max()) + 2)
        if bx0 >= bx1 or by0 >= by1:
            continue

        xs = np.arange(bx0, bx1, dtype=np.float32) + 0.5
        ys = np.arange(by0, by1, dtype=np.float32) + 0.5
        gx, gy = np.meshgrid(xs, ys)

        p0, p1, p2 = pix[0], pix[1], pix[2]
        denom = (p1[1]-p2[1])*(p0[0]-p2[0]) + (p2[0]-p1[0])*(p0[1]-p2[1])
        if abs(denom) < 1e-6:
            continue

        w0 = ((p1[1]-p2[1])*(gx-p2[0]) + (p2[0]-p1[0])*(gy-p2[1])) / denom
        w1 = ((p2[1]-p0[1])*(gx-p2[0]) + (p0[0]-p2[0])*(gy-p2[1])) / denom
        w2 = 1.0 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue

        abs_iy = gy[inside].astype(int)
        abs_ix = gx[inside].astype(int)
        update = z_avg > depth_buf[abs_iy, abs_ix]
        upd_iy = abs_iy[update]; upd_ix = abs_ix[update]
        if len(upd_iy):
            depth_buf[upd_iy, upd_ix] = z_avg
            mask[upd_iy, upd_ix] = 1

    depth_norm = np.zeros_like(depth_buf)
    valid = mask.astype(bool)
    depth_norm[valid] = (depth_buf[valid] - z_min) / z_range
    return depth_norm, mask

# ── 3. Helpers ────────────────────────────────────────────────────────────────

def hsv_to_rgb_array(hue):
    """Vectorised HSV→RGB, S=1 V=1, hue in [0,1]."""
    h6  = hue * 6.0
    idx = h6.astype(int) % 6
    f   = h6 - np.floor(h6)
    q   = 1.0 - f
    rgb = np.zeros((*hue.shape, 3), dtype=np.float32)
    for i, (rv, gv, bv) in enumerate([
        (1, f, 0), (q, 1, 0), (0, 1, f),
        (0, q, 1), (f, 0, 1), (1, 0, q)
    ]):
        sel = idx == i
        rgb[sel, 0] = rv if np.isscalar(rv) else rv[sel]
        rgb[sel, 1] = gv if np.isscalar(gv) else gv[sel]
        rgb[sel, 2] = bv if np.isscalar(bv) else bv[sel]
    return rgb


def shape_glow(mask, size):
    """
    Rainbow glow whose shape follows the piece silhouette.

    For every pixel outside the mask:
      - alpha  = exponential falloff from the nearest mask edge
      - hue    = angle from the piece centroid (rainbow goes around the shape)
    """
    # Euclidean distance from nearest mask pixel (0 at edge, grows outward)
    dist   = ndi.distance_transform_edt(mask == 0).astype(np.float32)
    max_r  = size * 0.14
    dist_n = np.clip(dist / max_r, 0, 1)

    # Sharp falloff so the glow hugs the edge and dies quickly
    alpha = np.exp(-dist_n * 4.5) * (1.0 - dist_n)
    alpha[mask.astype(bool)] = 0   # no glow inside the piece

    # Hue from angle around the piece centroid
    ys, xs = np.mgrid[0:size, 0:size]
    cy_m   = np.average(ys, weights=mask.astype(float))
    cx_m   = np.average(xs, weights=mask.astype(float))
    hue    = (np.arctan2(ys - cy_m, xs - cx_m) / (2 * math.pi)) % 1.0

    rgb = hsv_to_rgb_array(hue)
    arr = np.zeros((size, size, 4), dtype=np.float32)
    arr[:, :, :3] = rgb
    arr[:, :, 3]  = np.clip(alpha * 1.4, 0, 1)
    return Image.fromarray((arr * 255).astype(np.uint8), "RGBA")


def shade_piece(depth_norm, mask):
    """Very dark piece with subtle depth shading."""
    arr = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
    v   = mask.astype(bool)
    spec = np.clip(depth_norm * 0.6, 0, 1)
    rim  = np.clip(1.0 - depth_norm * 1.6, 0, 1)
    arr[v, 0] = np.clip(18 + spec[v]*60 + rim[v]*35, 0, 255).astype(np.uint8)
    arr[v, 1] = np.clip(20 + spec[v]*65 + rim[v]*40, 0, 255).astype(np.uint8)
    arr[v, 2] = np.clip(28 + spec[v]*80 + rim[v]*55, 0, 255).astype(np.uint8)
    arr[v, 3] = 255
    return Image.fromarray(arr, "RGBA")

# ── 4. Compose ────────────────────────────────────────────────────────────────

def make_icon():
    stl_path = os.path.join(os.path.dirname(__file__), "..",
                            "web", "pieces", "stl", "knight.stl")
    print(f"Loading {stl_path} …")
    tris = load_stl(stl_path)
    print(f"  {len(tris):,} triangles")

    print("Rasterizing …")
    depth, mask = project_and_rasterize(tris, SIZE)

    print("Building glow …")

    # Background
    bg = Image.new("RGBA", (SIZE, SIZE), (10, 13, 18, 255))

    # Shape glow — compute once, then blur to two different radii
    glow_raw = shape_glow(mask, SIZE)

    # Soft spill — very subtle ambient bleed
    glow_wide = glow_raw.filter(ImageFilter.GaussianBlur(radius=SIZE // 18))
    wa = np.array(glow_wide).astype(np.float32)
    wa[:, :, 3] = np.clip(wa[:, :, 3] * 0.7, 0, 255)
    bg = Image.alpha_composite(bg, Image.fromarray(wa.astype(np.uint8), "RGBA"))

    # Tight halo right at the contour
    glow_tight = glow_raw.filter(ImageFilter.GaussianBlur(radius=SIZE // 60))
    ta = np.array(glow_tight).astype(np.float32)
    ta[:, :, 3] = np.clip(ta[:, :, 3] * 1.1, 0, 255)
    bg = Image.alpha_composite(bg, Image.fromarray(ta.astype(np.uint8), "RGBA"))

    # Vignette: darken corners
    v_arr = np.zeros((SIZE, SIZE, 4), dtype=np.float32)
    yc, xc = np.mgrid[0:SIZE, 0:SIZE]
    dv = np.sqrt(((xc - SIZE/2) / (SIZE/2))**2 + ((yc - SIZE/2) / (SIZE/2))**2)
    v_arr[:, :, 3] = np.clip((dv - 0.55) / 0.65, 0, 1)**1.6 * 210
    bg = Image.alpha_composite(bg, Image.fromarray(v_arr.astype(np.uint8), "RGBA"))

    # Piece itself
    piece_img   = shade_piece(depth, mask)
    piece_alpha = piece_img.split()[3].filter(ImageFilter.GaussianBlur(radius=0.8))
    piece_img.putalpha(piece_alpha)
    bg = Image.alpha_composite(bg, piece_img)

    # Rounded corners (iOS icon shape)
    corner_r = int(SIZE * 0.2237)
    corners  = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(corners).rounded_rectangle(
        [0, 0, SIZE - 1, SIZE - 1], radius=corner_r, fill=255)
    bg.putalpha(corners)

    out = os.path.abspath(OUT_PATH)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bg.convert("RGBA").save(out)
    print(f"Saved → {out}")

if __name__ == "__main__":
    make_icon()
