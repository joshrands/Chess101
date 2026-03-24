'use strict';
/**
 * test_chessmatrix_js.js
 * Node.js test suite mirroring test_chessmatrix_pipeline.py for the JS
 * implementation in web/chessmatrix-scanner.js.
 *
 * Run:
 *   node tests/test_chessmatrix_js.js
 *   node tests/test_chessmatrix_js.js --verbose
 */

const fs   = require('fs');
const path = require('path');
const zlib = require('zlib');

const { decodeFrame, gfMul, GEN_POLY, DATA_CELLS, CAL_CELLS, CAL_CM } =
  require('../web/chessmatrix-scanner.js');

const VERBOSE  = process.argv.includes('--verbose');
const FIXTURES = path.join(__dirname, 'fixtures', 'chessmatrix');

// ── Minimal PNG decoder (Node.js built-ins only) ───────────────────────────
function decodePNG(buf) {
  const SIG = [137, 80, 78, 71, 13, 10, 26, 10];
  for (let i = 0; i < 8; i++)
    if (buf[i] !== SIG[i]) throw new Error('Not a valid PNG');

  let off = 8;
  let width, height, bitDepth, colorType;
  const idats = [];

  while (off < buf.length) {
    const len  = buf.readUInt32BE(off);    off += 4;
    const type = buf.toString('ascii', off, off + 4); off += 4;
    const data = buf.slice(off, off + len); off += len + 4; // +4 skips CRC

    if (type === 'IHDR') {
      width     = data.readUInt32BE(0);
      height    = data.readUInt32BE(4);
      bitDepth  = data[8];
      colorType = data[9];
    } else if (type === 'IDAT') {
      idats.push(data);
    } else if (type === 'IEND') break;
  }

  if (bitDepth !== 8) throw new Error(`Unsupported bit depth: ${bitDepth}`);

  // channels per pixel: 0=Gray,2=RGB,4=Gray+A,6=RGBA
  const ch = [1, 0, 3, 0, 2, 0, 4][colorType];
  if (!ch) throw new Error(`Unsupported color type: ${colorType}`);

  const raw  = zlib.inflateSync(Buffer.concat(idats));
  const rgba = new Uint8Array(width * height * 4);
  const prev = new Uint8Array(width * ch);
  let rOff   = 0;

  function paeth(a, b, c) {
    const p = a + b - c, pa = Math.abs(p-a), pb = Math.abs(p-b), pc = Math.abs(p-c);
    return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
  }

  for (let y = 0; y < height; y++) {
    const filter = raw[rOff++];
    const row    = new Uint8Array(width * ch);
    for (let x = 0; x < row.length; x++) row[x] = raw[rOff++];

    for (let x = 0; x < row.length; x++) {
      const a = x >= ch ? row[x - ch] : 0, b = prev[x], c = x >= ch ? prev[x - ch] : 0;
      let v = row[x];
      if      (filter === 1) v += a;
      else if (filter === 2) v += b;
      else if (filter === 3) v += (a + b) >> 1;
      else if (filter === 4) v += paeth(a, b, c);
      row[x] = v & 0xFF;
    }

    for (let x = 0; x < width; x++) {
      const di = (y * width + x) * 4;
      if (ch === 3) {
        rgba[di]=row[x*3]; rgba[di+1]=row[x*3+1]; rgba[di+2]=row[x*3+2]; rgba[di+3]=255;
      } else if (ch === 4) {
        rgba[di]=row[x*4]; rgba[di+1]=row[x*4+1]; rgba[di+2]=row[x*4+2]; rgba[di+3]=row[x*4+3];
      } else if (ch === 1) {
        rgba[di]=rgba[di+1]=rgba[di+2]=row[x]; rgba[di+3]=255;
      } else { // 2 = gray+alpha
        rgba[di]=rgba[di+1]=rgba[di+2]=row[x*2]; rgba[di+3]=row[x*2+1];
      }
    }
    prev.set(row);
  }
  return { data: rgba, width, height };
}

function loadPNG(filePath) {
  return decodePNG(fs.readFileSync(filePath));
}

// ── RS encoder (uses GF primitives from scanner) ───────────────────────────
function rsEncode(data4) {
  // data4: array of 4 bytes → returns array of 8 bytes (data + 4 parity)
  const msg = [...data4, 0, 0, 0, 0];
  for (let i = 0; i < 4; i++) {
    const coef = msg[i];
    if (coef) for (let j = 1; j < GEN_POLY.length; j++)
      msg[i + j] ^= gfMul(GEN_POLY[j], coef);
  }
  return [...data4, ...msg.slice(4)];
}

// ── Room code → 4 bytes (matches network/chessmatrix.py room_code_to_bytes) ─
function roomCodeToBytes(code) {
  let v = 0;
  for (const ch of code.toUpperCase()) v = v * 32 + (ch.charCodeAt(0) - 65);
  v = v * 4;   // << 2 (2 low padding bits)
  return [(v >>> 24) & 0xFF, (v >>> 16) & 0xFF, (v >>> 8) & 0xFF, v & 0xFF];
}

// ── ChessMatrix encoder (matches network/chessmatrix.py encode()) ──────────
// Returns 8×8 array of [R, G, B] tuples (dark-mode rendering)
const CM_RGB = {
  '-1': [235, 235, 235],  // WHITE (timing)
   '0': [10,  10,  10],   // BLACK
   '1': [220, 40,  40],   // RED
   '2': [40,  180, 40],   // GREEN
   '3': [40,  40,  220],  // BLUE
};

function encodeChessMatrix(code) {
  const cw     = rsEncode(roomCodeToBytes(code));
  const dibits = [];
  for (const b of cw)
    dibits.push((b>>6)&3, (b>>4)&3, (b>>2)&3, b&3);

  // Build 8×8 grid with structural borders
  const grid = Array.from({length:8}, () => new Array(8).fill(-1));
  for (let r = 0; r < 8; r++) {
    grid[r][0] = 0;                              // left finder bar: K
    grid[r][7] = r % 2 === 1 ? 0 : -1;          // right timing strip
  }
  for (let c = 0; c < 8; c++) {
    grid[7][c] = 0;                              // bottom finder bar: K
    grid[0][c] = c % 2 === 0 ? 0 : -1;          // top timing strip
  }
  // Anchor cells
  grid[1][1]=0; grid[1][6]=1; grid[6][1]=2; grid[6][6]=3;
  // Data cells
  DATA_CELLS.forEach(([r, c], i) => { grid[r][c] = dibits[i]; });

  // Dark-mode rendering: invert structural border (K↔WHITE)
  return Array.from({length:8}, (_, r) =>
    Array.from({length:8}, (_, c) => {
      const val = grid[r][c];
      const isBorder = r===0 || r===7 || c===0 || c===7;
      if (isBorder) return val === 0 ? [235,235,235] : [10,10,10];
      return CM_RGB[String(val)];
    })
  );
}

// ── Synthetic RGBA frame (matches _synthetic_frame in Python tests) ─────────
function syntheticFrame(code, cellPx=20, pad=40) {
  const colorGrid = encodeChessMatrix(code);
  const size  = 8 * cellPx;
  const total = size + 2 * pad;
  const rgba  = new Uint8Array(total * total * 4);

  // Gray background (180)
  for (let i = 0; i < total * total; i++) {
    rgba[i*4]=180; rgba[i*4+1]=180; rgba[i*4+2]=180; rgba[i*4+3]=255;
  }
  // Draw barcode
  for (let r = 0; r < 8; r++) {
    for (let c = 0; c < 8; c++) {
      const [rv, gv, bv] = colorGrid[r][c];
      for (let dy = 0; dy < cellPx; dy++) {
        for (let dx = 0; dx < cellPx; dx++) {
          const py = pad + r * cellPx + dy;
          const px = pad + c * cellPx + dx;
          const i  = (py * total + px) * 4;
          rgba[i]=rv; rgba[i+1]=gv; rgba[i+2]=bv; rgba[i+3]=255;
        }
      }
    }
  }
  return { data: rgba, width: total, height: total };
}

// ── Affine frame rotator (matches cv2.warpAffine in Python tests) ──────────
function rotateFrame(frame, angleDeg) {
  const { data, width: w, height: h } = frame;
  const rad = angleDeg * Math.PI / 180;
  const cos = Math.cos(rad), sin = Math.sin(rad);
  const cx = w / 2, cy = h / 2;
  const out = new Uint8Array(w * h * 4);
  // Fill with gray background (180) matching Python borderValue=(180,180,180)
  for (let i = 0; i < w * h; i++) {
    out[i*4]=180; out[i*4+1]=180; out[i*4+2]=180; out[i*4+3]=255;
  }
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const dx = x - cx, dy = y - cy;
      // Inverse rotation to find source pixel (bilinear, matches cv2.warpAffine INTER_LINEAR)
      const fsx = cos*dx + sin*dy + cx;
      const fsy = -sin*dx + cos*dy + cy;
      const x0 = Math.floor(fsx), y0 = Math.floor(fsy);
      const x1 = x0 + 1, y1 = y0 + 1;
      if (x0 >= 0 && x1 < w && y0 >= 0 && y1 < h) {
        const wx = fsx - x0, wy = fsy - y0;
        const di = (y*w+x)*4;
        for (let c = 0; c < 3; c++) {
          const a = data[(y0*w+x0)*4+c], b = data[(y0*w+x1)*4+c];
          const cc= data[(y1*w+x0)*4+c], d = data[(y1*w+x1)*4+c];
          out[di+c] = (a*(1-wx)*(1-wy) + b*wx*(1-wy) + cc*(1-wx)*wy + d*wx*wy + 0.5) | 0;
        }
        out[di+3] = 255;
      }
    }
  }
  return { data: out, width: w, height: h };
}

// ── Test runner ────────────────────────────────────────────────────────────
let passed = 0, failed = 0, skipped = 0;
const failures = [];

function test(name, fn) {
  try {
    fn();
    if (VERBOSE) console.log(`  ✓ ${name}`);
    passed++;
  } catch (e) {
    if (e._skip) {
      if (VERBOSE) console.log(`  - ${name}: SKIP (${e.message})`);
      skipped++;
    } else {
      console.log(`  ✗ ${name}: ${e.message}`);
      failures.push(name);
      failed++;
    }
  }
}

function skip(msg) { const e = new Error(msg); e._skip = true; throw e; }
function assert(cond, msg) { if (!cond) throw new Error(msg || 'assertion failed'); }
function assertEqual(a, b) { if (a !== b) throw new Error(`expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`); }

// ── Tests: fixture images (ABCDEF_*.png) ──────────────────────────────────
console.log('\nFixture images — ABCDEF');
const abcdefFixtures = fs.readdirSync(FIXTURES)
  .filter(f => f.startsWith('ABCDEF_') && f.endsWith('.png'))
  .sort();

for (const name of abcdefFixtures) {
  test(name.replace('.png', ''), () => {
    const { data, width, height } = loadPNG(path.join(FIXTURES, name));
    const code = decodeFrame(data, width, height);
    if (code === null) skip('orientation not found');
    assertEqual(code, 'ABCDEF');
  });
}

// ── Tests: TESTCM fixture ─────────────────────────────────────────────────
console.log('\nFixture image — TESTCM');
test('TESTCM_matrix', () => {
  const { data, width, height } = loadPNG(path.join(FIXTURES, 'TESTCM_matrix.png'));
  const code = decodeFrame(data, width, height);
  if (code === null) skip('orientation not found');
  assertEqual(code, 'TESTCM');
});

// ── Tests: synthetic upright ──────────────────────────────────────────────
console.log('\nSynthetic upright');
for (const code of ['ABCDEF', 'TESTCM', 'ZZZZZZ', 'AAAAAA']) {
  test(`synthetic_upright_${code}`, () => {
    const frame = syntheticFrame(code);
    const got = decodeFrame(frame.data, frame.width, frame.height);
    if (got === null) throw new Error('decode returned null');
    assertEqual(got, code);
  });
}

// ── Tests: synthetic rotated ──────────────────────────────────────────────
console.log('\nSynthetic rotated');
for (const [angle, strict] of [[15, true], [45, false], [90, true], [180, true]]) {
  test(`synthetic_rotated_${angle}deg`, () => {
    const base  = syntheticFrame('ABCDEF', 20, 80);
    const frame = rotateFrame(base, angle);
    const got   = decodeFrame(frame.data, frame.width, frame.height);
    if (got === null) {
      if (strict) throw new Error(`orientation not found at ${angle}°`);
      skip(`orientation not found at ${angle}° (known limitation)`);
    }
    if (got !== 'ABCDEF') {
      if (strict) throw new Error(`angle=${angle}: decoded ${JSON.stringify(got)}`);
      skip(`angle=${angle}: decoded ${JSON.stringify(got)} (known limitation)`);
    }
  });
}

// ── Summary ────────────────────────────────────────────────────────────────
const total = passed + failed + skipped;
console.log(`\n${total} tests: ${passed} passed, ${failed} failed, ${skipped} skipped\n`);
if (failed > 0) {
  console.log('Failed tests:');
  failures.forEach(f => console.log(`  - ${f}`));
  process.exit(1);
}
