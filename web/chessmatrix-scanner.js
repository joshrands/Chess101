'use strict';
/**
 * chessmatrix-scanner.js
 * Full ChessMatrix image scanning pipeline ported from:
 *   tools/debug_quad_detection.py  +  network/chessmatrix.py
 *
 * Exports a single global: ChessMatrixScanner
 *
 * Usage:
 *   const scanner = new ChessMatrixScanner({ videoEl, canvasEl, onDecode, onStatus });
 *   await scanner.start();   // opens camera + starts scan loop
 *   scanner.stop();          // releases camera
 */

// ── Constants ──────────────────────────────────────────────────────────────
const WARP_SIZE = 256;

// Calibration anchor cells in the oriented image: [grid_row, grid_col, [R, G, B]]
// (7,0) = WHITE L-finder corner; (1,1)/(1,6)/(6,1)/(6,6) = colour anchors
const CAL_CELLS = [
  [7, 0, [255, 255, 255]],   // WHITE  — L corner
  [1, 1, [  0,   0,   0]],   // BLACK  — anchor K
  [1, 6, [255,   0,   0]],   // RED    — anchor R
  [6, 1, [  0, 255,   0]],   // GREEN  — anchor G
  [6, 6, [  0,   0, 255]],   // BLUE   — anchor B
];
// Chessmatrix color values aligned with CAL_CELLS: WHITE=-1, K=0, R=1, G=2, B=3
const CAL_CM = [-1, 0, 1, 2, 3];

// Data cell positions (interior 6×6 minus 4 anchors), row-major
const _ANCHORS = new Set(['1,1', '1,6', '6,1', '6,6']);
const DATA_CELLS = [];
for (let r = 1; r <= 6; r++)
  for (let c = 1; c <= 6; c++)
    if (!_ANCHORS.has(`${r},${c}`)) DATA_CELLS.push([r, c]);
// DATA_CELLS.length === 32

// ── GF(256) ────────────────────────────────────────────────────────────────
const _PRIM = 0x11D;
const _GF_EXP = new Uint8Array(512);
const _GF_LOG = new Uint8Array(256);
(function buildGF() {
  let x = 1;
  for (let i = 0; i < 255; i++) {
    _GF_EXP[i] = x; _GF_LOG[x] = i;
    x <<= 1; if (x & 0x100) x ^= _PRIM;
  }
  for (let i = 255; i < 512; i++) _GF_EXP[i] = _GF_EXP[i - 255];
})();

function gfMul(a, b) { return (a && b) ? _GF_EXP[_GF_LOG[a] + _GF_LOG[b]] : 0; }
function gfPow(x, n) { return x ? _GF_EXP[(_GF_LOG[x] * n) % 255] : 0; }
function gfInv(x)    { return _GF_EXP[255 - _GF_LOG[x]]; }

function polyEval(poly, x) { let y = 0; for (const c of poly) y = gfMul(y, x) ^ c; return y; }
function polyMul(p, q) {
  const r = new Array(p.length + q.length - 1).fill(0);
  for (let i = 0; i < p.length; i++)
    for (let j = 0; j < q.length; j++) r[i+j] ^= gfMul(p[i], q[j]);
  return r;
}

// ── Reed-Solomon RS(8,4) ───────────────────────────────────────────────────
const NSYM = 4, NRS = 8, NDATA = 4;

const GEN_POLY = (() => {
  let g = [1];
  for (let i = 0; i < NSYM; i++) g = polyMul(g, [1, gfPow(2, i)]);
  return g;
})();

function rsSyndromes(cw) {
  return Array.from({length: NSYM}, (_, i) => polyEval(cw, gfPow(2, i)));
}

function rsBerlekampMassey(S) {
  let C = [1], B = [1], L = 0, m = 1, b = 1;
  for (let i = 0; i < S.length; i++) {
    let d = S[i];
    for (let j = 1; j <= L; j++) if (j < C.length) d ^= gfMul(C[j], S[i - j]);
    const Bs = [...new Array(m).fill(0), ...B];
    if (!d) { m++; continue; }
    const fac = gfMul(d, gfInv(b));
    if (2 * L <= i) {
      const T = [...C];
      while (C.length < Bs.length) C.push(0);
      for (let j = 0; j < Bs.length; j++) C[j] ^= gfMul(fac, Bs[j]);
      L = i + 1 - L; B = T; b = d; m = 1;
    } else {
      while (C.length < Bs.length) C.push(0);
      for (let j = 0; j < Bs.length; j++) C[j] ^= gfMul(fac, Bs[j]);
      m++;
    }
  }
  return C;
}

function rsChienSearch(loc, n) {
  const errs = loc.length - 1, pos = [], rev = [...loc].reverse();
  for (let i = 0; i < n; i++)
    if (polyEval(rev, gfPow(2, 255 - i)) === 0) pos.push(n - 1 - i);
  return pos.length === errs ? pos : null;
}

function rsForney(S, loc, errPos) {
  const omega = polyMul([...S], loc).slice(0, NSYM);
  const lp = loc.slice(1).map((v, i) => i % 2 === 0 ? v : 0);
  const lpoly = lp.length ? lp : [1];
  return errPos.map(pos => {
    const xi = gfPow(2, NRS - 1 - pos), xiInv = gfInv(xi);
    const ov = polyEval([...omega].reverse(), xiInv);
    const lv = polyEval([...lpoly].reverse(), xiInv);
    return lv ? gfMul(xi, gfMul(ov, gfInv(lv))) : 0;
  });
}

function rsDecode(cw8) {
  // cw8: Uint8Array of 8 bytes → returns Uint8Array of 4 data bytes, or null
  const msg = Array.from(cw8);
  const synd = rsSyndromes(msg);
  if (synd.every(s => s === 0)) return new Uint8Array(msg.slice(0, NDATA));
  const loc = rsBerlekampMassey(synd);
  if (loc.length - 1 > NSYM / 2) return null;
  const pos = rsChienSearch(loc, NRS);
  if (!pos) return null;
  const mags = rsForney(synd, loc, pos);
  for (let k = 0; k < pos.length; k++) msg[pos[k]] ^= mags[k];
  if (rsSyndromes(msg).some(s => s)) return null;
  return new Uint8Array(msg.slice(0, NDATA));
}

// ── Room code (bytes ↔ string) ─────────────────────────────────────────────
function bytesToRoomCode(data) {
  // 5-bit packing: 6 letters × 5 bits in high 30 bits of uint32
  let v = ((data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]) >>> 0;
  v >>>= 2;
  const ch = [];
  for (let i = 0; i < 6; i++) {
    const n = v & 0x1F;
    if (n > 25) return null;
    ch.push(String.fromCharCode(65 + n));
    v >>>= 5;
  }
  return ch.reverse().join('');
}

function decodeColorGrid(grid) {
  // grid: 8×8 array of color values (0-3)
  const dibits = DATA_CELLS.map(([r, c]) => grid[r][c]);
  const cw = new Uint8Array(8);
  for (let i = 0; i < 8; i++)
    cw[i] = (dibits[i*4] << 6) | (dibits[i*4+1] << 4) |
             (dibits[i*4+2] << 2) | dibits[i*4+3];
  const data = rsDecode(cw);
  return data ? bytesToRoomCode(data) : null;
}

// ── Image pipeline helpers ─────────────────────────────────────────────────

function toGray(rgba, n) {
  const g = new Float32Array(n);
  for (let i = 0; i < n; i++)
    g[i] = (rgba[i*4] + rgba[i*4+1] + rgba[i*4+2]) / 3;
  return g;
}

function normalize(gray) {
  let mn = Infinity, mx = -Infinity;
  for (const v of gray) { if (v < mn) mn = v; if (v > mx) mx = v; }
  if (mx === mn) return new Uint8Array(gray.length);
  const scale = 255 / (mx - mn), out = new Uint8Array(gray.length);
  for (let i = 0; i < gray.length; i++) out[i] = (gray[i] - mn) * scale + 0.5;
  return out;
}

function boxFilter(src, w, h, r) {
  // Integral-image box filter — returns Float32Array
  const ii = new Float64Array((w+1) * (h+1));
  for (let y = 1; y <= h; y++)
    for (let x = 1; x <= w; x++)
      ii[y*(w+1)+x] = src[(y-1)*w+(x-1)]
        + ii[(y-1)*(w+1)+x] + ii[y*(w+1)+(x-1)] - ii[(y-1)*(w+1)+(x-1)];
  const out = new Float32Array(w * h);
  for (let y = 0; y < h; y++) {
    const y1 = Math.max(0, y-r), y2 = Math.min(h-1, y+r);
    for (let x = 0; x < w; x++) {
      const x1 = Math.max(0, x-r), x2 = Math.min(w-1, x+r);
      const area = (y2-y1+1) * (x2-x1+1);
      out[y*w+x] = (ii[(y2+1)*(w+1)+(x2+1)] - ii[y1*(w+1)+(x2+1)]
                  - ii[(y2+1)*(w+1)+x1] + ii[y1*(w+1)+x1]) / area;
    }
  }
  return out;
}

function localThreshold(norm, w, h, win=31, k1=0.15, k2=200) {
  const f = new Float32Array(norm);
  const fsq = f.map(v => v * v);
  const r = (win - 1) >> 1;
  const mean = boxFilter(f, w, h, r);
  const msq  = boxFilter(fsq, w, h, r);
  const bin  = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) {
    const T = Math.max(mean[i] - k1 * Math.max(msq[i] - mean[i]*mean[i], 0), k2);
    bin[i] = f[i] > T ? 255 : 0;
  }
  return bin;
}

function imageCentroid(bin, w, h) {
  let sx = 0, sy = 0, n = 0;
  for (let y = 0; y < h; y++)
    for (let x = 0; x < w; x++)
      if (bin[y*w+x]) { sx += x; sy += y; n++; }
  return n > 0 ? [sx / n, sy / n] : null;
}

// ── Hough angle detection (gradient on normalised gray) ────────────────────
// norm: Uint8Array of normalised [0..255] grayscale — using the smooth float
// values avoids binary staircase artefacts that defeat diagonal detection.
function houghAxes(norm, w, h) {
  const hist = new Float32Array(180);
  for (let y = 1; y < h-1; y++) {
    for (let x = 1; x < w-1; x++) {
      const gx = -norm[(y-1)*w+(x-1)] + norm[(y-1)*w+(x+1)]
                 - 2*norm[y*w+(x-1)] + 2*norm[y*w+(x+1)]
                 - norm[(y+1)*w+(x-1)] + norm[(y+1)*w+(x+1)];
      const gy =  norm[(y-1)*w+(x-1)] + 2*norm[(y-1)*w+x] + norm[(y-1)*w+(x+1)]
                - norm[(y+1)*w+(x-1)] - 2*norm[(y+1)*w+x] - norm[(y+1)*w+(x+1)];
      const mag = Math.sqrt(gx*gx + gy*gy);
      if (mag < 100) continue;
      // Gradient is perpendicular to edge; subtract 90° to get line direction
      let ang = ((Math.atan2(gy, gx) * 180 / Math.PI - 90) % 180 + 180) % 180;
      hist[Math.min(179, ang | 0)] += mag;
    }
  }
  // Fold to [0,90)
  const folded = new Float32Array(90);
  for (let i = 0; i < 90; i++) folded[i] = hist[i] + hist[(i+90) % 180];
  let a1 = 0;
  for (let i = 1; i < 90; i++) if (folded[i] > folded[a1]) a1 = i;
  return folded[a1] > 0 ? [a1, (a1 + 90) % 180] : null;
}

// ── Inflate rect (tolerant) ────────────────────────────────────────────────
function inflateRect(bin, w, h, cx, cy, tol=0.08) {
  let top = cy|0, bot = cy|0, left = cx|0, right = cx|0;
  let changed = true;
  while (changed) {
    changed = false;
    const rw = right - left + 1, rh = bot - top + 1;
    if (top > 0) {
      let cnt = 0;
      for (let x = left; x <= right; x++) cnt += bin[(top-1)*w+x] ? 1 : 0;
      if (cnt / rw < tol) { top--; changed = true; }
    }
    if (bot < h-1) {
      let cnt = 0;
      for (let x = left; x <= right; x++) cnt += bin[(bot+1)*w+x] ? 1 : 0;
      if (cnt / rw < tol) { bot++; changed = true; }
    }
    if (left > 0) {
      let cnt = 0;
      for (let y = top; y <= bot; y++) cnt += bin[y*w+(left-1)] ? 1 : 0;
      if (cnt / rh < tol) { left--; changed = true; }
    }
    if (right < w-1) {
      let cnt = 0;
      for (let y = top; y <= bot; y++) cnt += bin[y*w+(right+1)] ? 1 : 0;
      if (cnt / rh < tol) { right++; changed = true; }
    }
  }
  return [left, top, right, bot];
}

// ── Binary rotation (nearest-neighbour inverse warp) ──────────────────────
function rotateBin(bin, w, h, cx, cy, deg) {
  const rad = deg * Math.PI / 180;
  const cos = Math.cos(rad), sin = Math.sin(rad);
  const out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const dx = x - cx, dy = y - cy;
      const sx = (cos * dx + sin * dy + cx) | 0;
      const sy = (-sin * dx + cos * dy + cy) | 0;
      if (sx >= 0 && sx < w && sy >= 0 && sy < h)
        out[y*w+x] = bin[sy*w+sx];
    }
  }
  return out;
}

// ── Perspective homography (DLT, h33=1) ───────────────────────────────────
function computeH(src, dst) {
  // src, dst: 4 points each as [x, y]
  const A = [];
  for (let i = 0; i < 4; i++) {
    const [x, y] = src[i], [u, v] = dst[i];
    A.push([-x, -y, -1, 0, 0, 0, u*x, u*y, u]);
    A.push([ 0,  0,  0,-x,-y,-1, v*x, v*y, v]);
  }
  // Build 8×9 augmented system (h9=1, move to RHS)
  const M = A.slice(0, 8).map((row, i) => [...row.slice(0, 8), -A[i][8]]);
  // Gauss-Jordan with partial pivot
  for (let col = 0; col < 8; col++) {
    let mx = col;
    for (let r = col+1; r < 8; r++)
      if (Math.abs(M[r][col]) > Math.abs(M[mx][col])) mx = r;
    [M[col], M[mx]] = [M[mx], M[col]];
    const piv = M[col][col];
    if (Math.abs(piv) < 1e-10) return null;
    for (let j = col; j <= 8; j++) M[col][j] /= piv;
    for (let r = 0; r < 8; r++) {
      if (r === col) continue;
      const f = M[r][col];
      for (let j = col; j <= 8; j++) M[r][j] -= f * M[col][j];
    }
  }
  return [...M.map(row => row[8]), 1]; // 9-element row-major H
}

function inv3x3(H) {
  const [a,b,c,d,e,f,g,h,k] = H;
  const det = a*(e*k-f*h) - b*(d*k-f*g) + c*(d*h-e*g);
  if (Math.abs(det) < 1e-10) return null;
  return [
    (e*k-f*h)/det, (c*h-b*k)/det, (b*f-c*e)/det,
    (f*g-d*k)/det, (a*k-c*g)/det, (c*d-a*f)/det,
    (d*h-e*g)/det, (b*g-a*h)/det, (a*e-b*d)/det,
  ];
}

function warpRGBA(rgba, sw, sh, H, dw, dh) {
  const Hi = inv3x3(H); if (!Hi) return null;
  const out = new Uint8Array(dw * dh * 4);
  for (let dy = 0; dy < dh; dy++) {
    for (let dx = 0; dx < dw; dx++) {
      const wp = Hi[6]*dx + Hi[7]*dy + Hi[8];
      const sx = (Hi[0]*dx + Hi[1]*dy + Hi[2]) / wp;
      const sy = (Hi[3]*dx + Hi[4]*dy + Hi[5]) / wp;
      if (sx >= 0 && sx < sw && sy >= 0 && sy < sh) {
        const si = ((sy|0)*sw + (sx|0)) * 4;
        const di = (dy*dw + dx) * 4;
        out[di]=rgba[si]; out[di+1]=rgba[si+1]; out[di+2]=rgba[si+2]; out[di+3]=255;
      }
    }
  }
  return out;
}

function warpBin(bin, sw, sh, H, dw, dh) {
  const Hi = inv3x3(H); if (!Hi) return null;
  const out = new Uint8Array(dw * dh);
  for (let dy = 0; dy < dh; dy++) {
    for (let dx = 0; dx < dw; dx++) {
      const wp = Hi[6]*dx + Hi[7]*dy + Hi[8];
      const sx = (Hi[0]*dx + Hi[1]*dy + Hi[2]) / wp;
      const sy = (Hi[3]*dx + Hi[4]*dy + Hi[5]) / wp;
      if (sx >= 0 && sx < sw && sy >= 0 && sy < sh)
        out[dy*dw+dx] = bin[(sy|0)*sw+(sx|0)];
    }
  }
  return out;
}

// ── Outer corners + homography ─────────────────────────────────────────────
function getOuterCornersH(bin, w, h, norm) {
  const c = imageCentroid(bin, w, h); if (!c) return null;
  const [cx, cy] = c;
  const axes = houghAxes(norm || bin, w, h); if (!axes) return null;
  const [a1] = axes;
  const align = a1 - 90;

  // Rotate binary to axis-align the code, then inflate rect
  const rotB = rotateBin(bin, w, h, cx, cy, align);
  const [left, top, right, bot] = inflateRect(rotB, w, h, cx, cy);

  // Rotate corners back (inverse rotation = -align)
  const rad = -align * Math.PI / 180;
  const cos = Math.cos(rad), sin = Math.sin(rad);
  function back(px, py) {
    const dx = px - cx, dy = py - cy;
    return [dx*cos - dy*sin + cx, dx*sin + dy*cos + cy];
  }
  const corners = [back(left,top), back(right,top), back(right,bot), back(left,bot)];

  // Scale 4/3 from centroid to get outer rect
  const mcx = (corners[0][0]+corners[1][0]+corners[2][0]+corners[3][0]) / 4;
  const mcy = (corners[0][1]+corners[1][1]+corners[2][1]+corners[3][1]) / 4;
  const outer = corners.map(([px,py]) => [(px-mcx)*4/3+mcx, (py-mcy)*4/3+mcy]);

  // Order corners clockwise from topmost by angle from centroid.
  // Angular sort is robust for any quadrilateral, including 45° diamonds
  // where sum/difference ordering produces degenerate (duplicate) corners.
  const angles = outer.map(([px,py]) => Math.atan2(px-mcx, mcy-py)); // CW from north
  const sortedIdx = [0,1,2,3].sort((a,b) => angles[a]-angles[b]);
  const cw = sortedIdx.map(i => outer[i]); // [top, right, bottom, left] for a diamond
  // Reorder to [TL, TR, BR, BL]: find the topmost (min y) as TL start
  const topI = cw.reduce((mi,p,i) => p[1] < cw[mi][1] ? i : mi, 0);
  const ordered = [0,1,2,3].map(i => cw[(topI+i) % 4]);
  const N = WARP_SIZE - 1;

  const H = computeH(ordered, [[0,0],[N,0],[N,N],[0,N]]);
  return H ? { ordered, H } : null;
}

// ── rot90 on RGBA (same semantics as numpy.rot90) ──────────────────────────
function rot90RGBA(rgba, N, k) {
  k = ((k % 4) + 4) % 4;
  if (!k) return rgba.slice();
  const out = new Uint8Array(rgba.length);
  for (let y = 0; y < N; y++) {
    for (let x = 0; x < N; x++) {
      let sx, sy;
      if      (k === 1) { sx = y;     sy = N-1-x; }
      else if (k === 2) { sx = N-1-x; sy = N-1-y; }
      else              { sx = N-1-y; sy = x;      }
      const si = (sy*N+sx)*4, di = (y*N+x)*4;
      out[di]=rgba[si]; out[di+1]=rgba[si+1]; out[di+2]=rgba[si+2]; out[di+3]=255;
    }
  }
  return out;
}

// ── Oriented colour warp ───────────────────────────────────────────────────
function getOrientedRGBA(rgba, bin, w, h, norm) {
  const r = getOuterCornersH(bin, w, h, norm); if (!r) return null;
  const N = WARP_SIZE;
  const warpedRGBA = warpRGBA(rgba, w, h, r.H, N, N); if (!warpedRGBA) return null;
  const warpedBin  = warpBin(bin, w, h, r.H, N, N);   if (!warpedBin)  return null;

  // Recompute centroid in rectified binary (no outside-rect noise)
  let sx = 0, sy = 0, n = 0;
  for (let y = 0; y < N; y++)
    for (let x = 0; x < N; x++)
      if (warpedBin[y*N+x]) { sx += x; sy += y; n++; }
  if (!n) return null;
  const rx = sx / n, ry = sy / n;

  // Nearest corner to white centroid = L-finder position
  const CORNERS = {TL:[0,0], TR:[N,0], BL:[0,N], BR:[N,N]};
  let minD = Infinity, lc = 'BL';
  for (const [name, [cx, cy]] of Object.entries(CORNERS)) {
    const d = (rx-cx)**2 + (ry-cy)**2;
    if (d < minD) { minD = d; lc = name; }
  }
  const k = {TL:3, TR:2, BL:0, BR:1}[lc];
  return rot90RGBA(warpedRGBA, N, k);
}

// ── Cell sampling ──────────────────────────────────────────────────────────
function cellCenterPx(row, col) {
  const cell = WARP_SIZE / 8;
  return [col*cell + cell/2, row*cell + cell/2]; // [cx, cy]
}

function sampleCell(rgba, N, row, col, patch=5) {
  const [cx, cy] = cellCenterPx(row, col);
  const r = (patch / 2) | 0;
  let sr = 0, sg = 0, sb = 0, n = 0;
  for (let y = Math.round(cy)-r; y <= Math.round(cy)+r; y++)
    for (let x = Math.round(cx)-r; x <= Math.round(cx)+r; x++)
      if (x >= 0 && x < N && y >= 0 && y < N) {
        const i = (y*N+x)*4;
        sr += rgba[i]; sg += rgba[i+1]; sb += rgba[i+2]; n++;
      }
  return n ? [sr/n, sg/n, sb/n] : [0, 0, 0];
}

// ── Colour calibration + grid extraction ──────────────────────────────────
function calibrateAndDecode(oriented, N) {
  // Sample the 5 anchor cells to get per-image calibration references
  const sampled = CAL_CELLS.map(([r, c]) => sampleCell(oriented, N, r, c));

  // For every cell center: find nearest calibration sample, map to cm value
  const grid = Array.from({length: 8}, () => new Array(8).fill(0));
  for (let row = 0; row < 8; row++) {
    for (let col = 0; col < 8; col++) {
      const [cx, cy] = cellCenterPx(row, col);
      const i = (Math.round(cy)*N + Math.round(cx)) * 4;
      const pr = oriented[i], pg = oriented[i+1], pb = oriented[i+2];
      let minD = Infinity, nearest = 0;
      for (let k = 0; k < sampled.length; k++) {
        const [sr, sg, sb] = sampled[k];
        const d = (pr-sr)**2 + (pg-sg)**2 + (pb-sb)**2;
        if (d < minD) { minD = d; nearest = k; }
      }
      // Clamp to [0,3] so data cells always produce valid dibits
      grid[row][col] = Math.max(0, CAL_CM[nearest]);
    }
  }
  return decodeColorGrid(grid);
}

// ── Top-level frame decoder ────────────────────────────────────────────────
function decodeFrame(rgba, w, h) {
  const gray   = toGray(rgba, w * h);
  const norm   = normalize(gray);
  const blur1  = boxFilter(new Float32Array(norm), w, h, 1); // ~3×3 blur
  const bin    = localThreshold(blur1, w, h);
  const ori    = getOrientedRGBA(rgba, bin, w, h, norm);
  if (!ori) return null;
  const code   = calibrateAndDecode(ori, WARP_SIZE);
  return (code && code.length === 6) ? code : null;
}

// ── ChessMatrixScanner public class ───────────────────────────────────────
class ChessMatrixScanner {
  /**
   * @param {object} opts
   * @param {HTMLVideoElement}  opts.videoEl   — <video> element for preview
   * @param {HTMLCanvasElement} opts.canvasEl  — hidden <canvas> for frame capture
   * @param {function(string)}  opts.onDecode  — called once with the 6-letter code
   * @param {function(string)}  [opts.onStatus] — called with status text updates
   */
  constructor({ videoEl, canvasEl, onDecode, onStatus }) {
    this._video   = videoEl;
    this._canvas  = canvasEl;
    this._onDecode  = onDecode;
    this._onStatus  = onStatus || (() => {});
    this._stream  = null;
    this._running = false;
    this._raf     = null;
    this._ctx     = canvasEl.getContext('2d', { willReadFrequently: true });
  }

  async start() {
    this._stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' }, width: {ideal: 640}, height: {ideal: 480} },
    });
    this._video.srcObject = this._stream;
    await this._video.play();
    this._running = true;
    this._onStatus('Scanning for ChessMatrix code\u2026');
    this._scheduleNext();
  }

  stop() {
    this._running = false;
    if (this._raf) { cancelAnimationFrame(this._raf); this._raf = null; }
    if (this._stream) { this._stream.getTracks().forEach(t => t.stop()); this._stream = null; }
    this._video.srcObject = null;
  }

  _scheduleNext() {
    if (!this._running) return;
    this._raf = requestAnimationFrame(() => this._scan());
  }

  _scan() {
    if (!this._running) return;
    const { _video: v, _canvas: c, _ctx: ctx } = this;
    if (v.readyState < 2) { this._scheduleNext(); return; }

    const W = c.width, H = c.height;
    ctx.drawImage(v, 0, 0, W, H);
    const { data } = ctx.getImageData(0, 0, W, H);
    const code = decodeFrame(data, W, H);
    if (code) {
      this._running = false;
      this._onStatus(`\u2713 Decoded: ${code}`);
      this._onDecode(code);
    } else {
      this._scheduleNext();
    }
  }
}

// Node.js compatibility — expose internals needed by test_chessmatrix_js.js
if (typeof module !== 'undefined') {
  module.exports = {
    decodeFrame,
    ChessMatrixScanner,
    // GF(256) primitives (for RS encoder in tests)
    gfMul, gfPow, GEN_POLY,
    // Grid constants
    DATA_CELLS, CAL_CELLS, CAL_CM,
    // Pipeline internals (for debugging / unit tests)
    _toGray: toGray,
    _normalize: normalize,
    _boxFilter: boxFilter,
    _localThreshold: localThreshold,
    _imageCentroid: imageCentroid,
    _houghAxes: houghAxes,
    _rotateBin: rotateBin,
    _inflateRect: inflateRect,
    _getOuterCornersH: getOuterCornersH,
    _warpRGBA: warpRGBA,
    _warpBin: warpBin,
    _rot90RGBA: rot90RGBA,
    _getOrientedRGBA: getOrientedRGBA,
    _calibrateAndDecode: calibrateAndDecode,
    _sampleCell: sampleCell,
    _cellCenterPx: cellCenterPx,
    _WARP_SIZE: WARP_SIZE,
  };
}
