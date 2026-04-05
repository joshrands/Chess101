#!/usr/bin/env python3
"""Convert binary STL chess pieces to OBJ with centered XZ and smooth normals.

Usage:
    python3 tools/stl_to_obj.py

Outputs OBJ files to Chess101iOS/Sources/Chess101iOS/Models/.
"""

import struct
import os
import math
from collections import defaultdict

STL_DIR = os.path.join(os.path.dirname(__file__), "..", "Chess Pieces", "STL")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "Chess101iOS",
                       "Sources", "Chess101iOS", "Models")

# Map piece name -> STL filename (pick the best version)
PIECES = {
    "pawn":   "pawn.STL",
    "rook":   "rook.STL",
    "knight": "knight top.STL",
    "bishop": "bishop.STL",
    "queen":  "queen.STL",
    "king":   "king 2.STL",
}

PIECE_WIDTH_MM = 31.7  # all pieces share this XZ footprint


def normalize(v):
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if n < 1e-10:
        return (0.0, 1.0, 0.0)
    return (v[0] / n, v[1] / n, v[2] / n)


def read_binary_stl(path):
    """Return list of (face_normal, v0, v1, v2) tuples (all as (x,y,z) floats)."""
    with open(path, "rb") as f:
        data = f.read()
    num_tri = struct.unpack("<I", data[80:84])[0]
    triangles = []
    off = 84
    for _ in range(num_tri):
        n = struct.unpack("<fff", data[off: off + 12])
        v0 = struct.unpack("<fff", data[off + 12: off + 24])
        v1 = struct.unpack("<fff", data[off + 24: off + 36])
        v2 = struct.unpack("<fff", data[off + 36: off + 48])
        off += 50
        triangles.append((n, v0, v1, v2))
    return triangles


def convert(stl_path, obj_path):
    triangles = read_binary_stl(stl_path)

    # Center XZ (pieces run 0..31.7 on both axes)
    cx = PIECE_WIDTH_MM / 2.0
    cz = PIECE_WIDTH_MM / 2.0

    def center(v):
        return (v[0] - cx, v[1], v[2] - cz)

    # Deduplicate vertices (round to 3 decimal places for matching)
    vert_map = {}   # rounded_key -> 1-based index
    verts = []      # list of (x, y, z) centered
    faces = []      # list of [i0, i1, i2] 1-based
    vert_normals = defaultdict(lambda: [0.0, 0.0, 0.0])

    for _, rv0, rv1, rv2 in triangles:
        v0, v1, v2 = center(rv0), center(rv1), center(rv2)

        # Compute face normal from vertices
        ux = v1[0] - v0[0]; uy = v1[1] - v0[1]; uz = v1[2] - v0[2]
        wx = v2[0] - v0[0]; wy = v2[1] - v0[1]; wz = v2[2] - v0[2]
        fn = normalize((uy * wz - uz * wy,
                        uz * wx - ux * wz,
                        ux * wy - uy * wx))

        fi = []
        for v in (v0, v1, v2):
            key = (round(v[0], 3), round(v[1], 3), round(v[2], 3))
            if key not in vert_map:
                vert_map[key] = len(verts) + 1
                verts.append(v)
            idx = vert_map[key]
            fi.append(idx)
            vert_normals[idx][0] += fn[0]
            vert_normals[idx][1] += fn[1]
            vert_normals[idx][2] += fn[2]

        faces.append(fi)

    # Normalize accumulated normals
    smooth_normals = {idx: normalize(tuple(n)) for idx, n in vert_normals.items()}

    with open(obj_path, "w") as f:
        f.write(f"# Chess piece OBJ — converted from {os.path.basename(stl_path)}\n")
        f.write(f"# {len(triangles)} triangles, {len(verts)} unique vertices\n\n")
        for v in verts:
            f.write(f"v {v[0]:.5f} {v[1]:.5f} {v[2]:.5f}\n")
        f.write("\n")
        for i in range(1, len(verts) + 1):
            n = smooth_normals.get(i, (0.0, 1.0, 0.0))
            f.write(f"vn {n[0]:.5f} {n[1]:.5f} {n[2]:.5f}\n")
        f.write("\n")
        for fi in faces:
            a, b, c = fi
            f.write(f"f {a}//{a} {b}//{b} {c}//{c}\n")

    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    print(f"  {os.path.basename(stl_path):20s} -> {os.path.basename(obj_path)}"
          f"  tris={len(triangles):5d}  verts={len(verts):5d}"
          f"  height={max(ys):.1f}mm  xrange=[{min(xs):.1f},{max(xs):.1f}]")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Output: {OUT_DIR}\n")
    for piece, stl_name in PIECES.items():
        stl_path = os.path.join(STL_DIR, stl_name)
        obj_path = os.path.join(OUT_DIR, f"{piece}.obj")
        convert(stl_path, obj_path)
    print("\nDone.")


if __name__ == "__main__":
    main()
