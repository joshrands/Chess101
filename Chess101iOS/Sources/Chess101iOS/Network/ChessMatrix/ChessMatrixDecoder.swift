import Foundation
import Accelerate

/// Decodes a ChessMatrix barcode from a raw RGBA pixel buffer.
/// Pipeline mirrors Python `decode_frame()` / JS `decodeFrame()` exactly.
public enum ChessMatrixDecoder {

    // MARK: - Public entry point

    /// Attempt to decode a room code from a camera frame.
    /// - Parameters:
    ///   - pixels: Flat RGBA bytes (width × height × 4)
    ///   - width: Frame width in pixels
    ///   - height: Frame height in pixels
    /// - Returns: 6-character room code, or `nil` if the barcode could not be decoded.
    public static func decodeFrame(pixels: [UInt8], width: Int, height: Int) -> String? {
        // 1. Grayscale
        var gray = grayscale(pixels: pixels, width: width, height: height)
        // 2. Normalize to [0, 255]
        normalize(&gray, width: width, height: height)
        // 3. Gaussian blur
        let blurred = gaussianBlur(gray, width: width, height: height, radius: max(1, min(width, height) / 80))
        // 4. Local binarize
        let binary = localBinarize(blurred, width: width, height: height)
        // 5. Centroid
        guard let centroid = whiteCentroid(binary, width: width, height: height) else { return nil }
        // 6. Hough axes
        guard let (angle1, angle2) = houghAxes(binary, width: width, height: height) else { return nil }
        // 7. Affine unshear + inflate rect
        guard let rect = inflateRect(binary, width: width, height: height,
                                     centroid: centroid, angle1: angle1, angle2: angle2) else { return nil }
        // 8. Scale outer rect outward 4/3
        let outer = scaleRect(rect, factor: 4.0 / 3.0, cx: Float(centroid.x), cy: Float(centroid.y))
        // 9. Perspective warp to 128×128
        guard let warped = perspectiveWarp(pixels: pixels, width: width, height: height,
                                           corners: outer, outSize: 128) else { return nil }
        // 10. Orientation — find rotation with L-finder (black 2×2) at bottom-left
        guard let oriented = findOrientation(warped: warped, size: 128) else { return nil }
        // 11. Calibrate and decode
        return calibrateAndDecode(oriented, size: 128)
    }

    // MARK: - Step 1: Grayscale

    static func grayscale(pixels: [UInt8], width: Int, height: Int) -> [Float] {
        var out = [Float](repeating: 0, count: width * height)
        for i in 0..<width * height {
            let r = Float(pixels[i*4]), g = Float(pixels[i*4+1]), b = Float(pixels[i*4+2])
            out[i] = (r + g + b) / 3.0
        }
        return out
    }

    // MARK: - Step 2: Normalize

    static func normalize(_ img: inout [Float], width: Int, height: Int) {
        var minV: Float = 255, maxV: Float = 0
        for v in img { minV = min(minV, v); maxV = max(maxV, v) }
        let range = maxV - minV
        guard range > 1 else { return }
        img = img.map { ($0 - minV) / range * 255 }
    }

    // MARK: - Step 3: Gaussian blur (box approximation)

    static func gaussianBlur(_ img: [Float], width: Int, height: Int, radius: Int) -> [Float] {
        guard radius > 0 else { return img }
        var out = img
        // Horizontal pass
        for r in 0..<height {
            for c in 0..<width {
                var sum: Float = 0; var cnt = 0
                for dc in -radius...radius {
                    let cc = c + dc
                    guard cc >= 0 && cc < width else { continue }
                    sum += img[r * width + cc]; cnt += 1
                }
                out[r * width + c] = sum / Float(cnt)
            }
        }
        var out2 = out
        // Vertical pass
        for r in 0..<height {
            for c in 0..<width {
                var sum: Float = 0; var cnt = 0
                for dr in -radius...radius {
                    let rr = r + dr
                    guard rr >= 0 && rr < height else { continue }
                    sum += out[rr * width + c]; cnt += 1
                }
                out2[r * width + c] = sum / Float(cnt)
            }
        }
        return out2
    }

    // MARK: - Step 4: Local binarize

    static func localBinarize(_ img: [Float], width: Int, height: Int) -> [UInt8] {
        let k = max(width, height) / 8
        var out = [UInt8](repeating: 0, count: width * height)
        for r in 0..<height {
            for c in 0..<width {
                var sum: Float = 0; var sumSq: Float = 0; var cnt = 0
                for dr in -k...k {
                    for dc in -k...k {
                        let rr = r + dr, cc = c + dc
                        guard rr >= 0 && rr < height && cc >= 0 && cc < width else { continue }
                        let v = img[rr * width + cc]
                        sum += v; sumSq += v * v; cnt += 1
                    }
                }
                let mean = sum / Float(cnt)
                let variance = sumSq / Float(cnt) - mean * mean
                let threshold = mean - 0.2 * sqrt(max(0, variance))
                out[r * width + c] = img[r * width + c] > threshold ? 255 : 0
            }
        }
        return out
    }

    // MARK: - Step 5: White centroid

    static func whiteCentroid(_ bin: [UInt8], width: Int, height: Int) -> (x: Float, y: Float)? {
        var sx: Float = 0, sy: Float = 0, cnt: Float = 0
        for r in 0..<height {
            for c in 0..<width {
                if bin[r * width + c] > 0 { sx += Float(c); sy += Float(r); cnt += 1 }
            }
        }
        guard cnt > 0 else { return nil }
        return (sx / cnt, sy / cnt)
    }

    // MARK: - Step 6: Hough axes (simplified gradient histogram)

    static func houghAxes(_ bin: [UInt8], width: Int, height: Int) -> (Float, Float)? {
        // Compute Sobel gradients and accumulate angle histogram
        var hist = [Float](repeating: 0, count: 180)
        for r in 1..<height-1 {
            for c in 1..<width-1 {
                let gx = Int(bin[r*width+(c+1)]) - Int(bin[r*width+(c-1)])
                let gy = Int(bin[(r+1)*width+c]) - Int(bin[(r-1)*width+c])
                let mag = Float(gx*gx + gy*gy)
                guard mag > 0 else { continue }
                var angle = atan2(Float(gy), Float(gx)) * 180 / .pi
                if angle < 0 { angle += 180 }
                let idx = min(179, max(0, Int(angle)))
                hist[idx] += sqrt(mag)
            }
        }
        // Find two dominant peaks separated by at least 20°
        let p1 = hist.enumerated().max(by: { $0.element < $1.element })!.offset
        var p2 = -1; var p2v: Float = -1
        for i in 0..<180 {
            let sep = min(abs(i - p1), 180 - abs(i - p1))
            if sep >= 20 && hist[i] > p2v { p2 = i; p2v = hist[i] }
        }
        guard p2 >= 0 else { return nil }
        return (Float(p1) * .pi / 180, Float(p2) * .pi / 180)
    }

    // MARK: - Step 7: Inflate rect (AABB in unsheared space)

    static func inflateRect(_ bin: [UInt8], width: Int, height: Int,
                             centroid: (x: Float, y: Float),
                             angle1: Float, angle2: Float) -> [(x: Float, y: Float)]? {
        // Build axis vectors (first-quadrant direction)
        func unit(_ a: Float) -> (Float, Float) { (cos(a), sin(a)) }
        let (u1x, u1y) = unit(angle1)
        let (u2x, u2y) = unit(angle2)
        // Project centroid into axis space and expand outward until edge
        var minA = Float(0), maxA = Float(0), minB = Float(0), maxB = Float(0)
        for r in 0..<height {
            for c in 0..<width {
                guard bin[r * width + c] > 0 else { continue }
                let dx = Float(c) - centroid.x, dy = Float(r) - centroid.y
                let a = dx * u1x + dy * u1y
                let b = dx * u2x + dy * u2y
                minA = min(minA, a); maxA = max(maxA, a)
                minB = min(minB, b); maxB = max(maxB, b)
            }
        }
        guard maxA > minA && maxB > minB else { return nil }
        // Four corners in original space
        func pt(_ a: Float, _ b: Float) -> (x: Float, y: Float) {
            (centroid.x + a * u1x + b * u2x,
             centroid.y + a * u1y + b * u2y)
        }
        return [pt(minA, minB), pt(maxA, minB), pt(maxA, maxB), pt(minA, maxB)]
    }

    // MARK: - Scale rect

    static func scaleRect(_ corners: [(x: Float, y: Float)], factor: Float,
                           cx: Float, cy: Float) -> [(x: Float, y: Float)] {
        corners.map { (cx + ($0.x - cx) * factor, cy + ($0.y - cy) * factor) }
    }

    // MARK: - Step 9: Perspective warp

    static func perspectiveWarp(pixels: [UInt8], width: Int, height: Int,
                                 corners: [(x: Float, y: Float)], outSize: Int) -> [UInt8]? {
        // Bilinear warp from source quad to outSize×outSize square
        var out = [UInt8](repeating: 128, count: outSize * outSize * 4)
        let (tl, tr, br, bl) = (corners[0], corners[1], corners[2], corners[3])
        for or_ in 0..<outSize {
            let v = Float(or_) / Float(outSize - 1)
            for oc in 0..<outSize {
                let u = Float(oc) / Float(outSize - 1)
                let sx = tl.x*(1-u)*(1-v) + tr.x*u*(1-v) + br.x*u*v + bl.x*(1-u)*v
                let sy = tl.y*(1-u)*(1-v) + tr.y*u*(1-v) + br.y*u*v + bl.y*(1-u)*v
                let ix = Int(sx), iy = Int(sy)
                guard ix >= 0 && ix < width && iy >= 0 && iy < height else { continue }
                let si = (iy * width + ix) * 4
                let di = (or_ * outSize + oc) * 4
                out[di] = pixels[si]; out[di+1] = pixels[si+1]
                out[di+2] = pixels[si+2]; out[di+3] = 255
            }
        }
        return out
    }

    // MARK: - Step 10: Orientation

    /// Try all 4 rotations; return the one where the bottom border (row 7) is all-bright.
    /// This matches the L-finder spec: row 7 and col 0 are all white in correctly-oriented images.
    static func findOrientation(warped: [UInt8], size: Int) -> [UInt8]? {
        for rot in 0..<4 {
            let img = rotate90(warped, size: size, times: rot)
            // Row 7 should be all-bright (L-finder bottom bar, 235,235,235).
            // Sample average luminance of the entire bottom row of cells.
            let cs = size / 8
            var lum: Float = 0; var cnt = 0
            let rowStart = 7 * cs
            for py in rowStart..<size {
                for px in 0..<size {
                    let i = (py * size + px) * 4
                    lum += Float(img[i]) + Float(img[i+1]) + Float(img[i+2])
                    cnt += 1
                }
            }
            let avg = lum / Float(cnt) / 3
            if avg > 150 { return img }
        }
        return nil
    }

    static func rotate90(_ img: [UInt8], size: Int, times: Int) -> [UInt8] {
        var cur = img
        for _ in 0..<times {
            var next = [UInt8](repeating: 0, count: cur.count)
            for r in 0..<size { for c in 0..<size {
                let si = (r * size + c) * 4
                let di = (c * size + (size - 1 - r)) * 4
                next[di] = cur[si]; next[di+1] = cur[si+1]
                next[di+2] = cur[si+2]; next[di+3] = cur[si+3]
            }}
            cur = next
        }
        return cur
    }

    // MARK: - Step 11: Calibrate and decode

    /// Sample a cell using four 3×3 patches at the ¼/¾ quadrant midpoints, avoiding
    /// the cell center where the physical reed switch is visible through the board surface.
    private static func sampleCell(_ img: [UInt8], size: Int, cellSize: Int,
                                   row: Int, col: Int) -> (r: Float, g: Float, b: Float) {
        let q = cellSize / 4
        var sr: Float = 0, sg: Float = 0, sb: Float = 0; var cnt = 0
        for qy in [q, 3 * q] {
            for qx in [q, 3 * q] {
                let cy = row * cellSize + qy
                let cx = col * cellSize + qx
                for dy in -1...1 { for dx in -1...1 {
                    let py = cy + dy, px = cx + dx
                    guard py >= 0 && py < size && px >= 0 && px < size else { continue }
                    let i = (py * size + px) * 4
                    sr += Float(img[i]); sg += Float(img[i+1]); sb += Float(img[i+2]); cnt += 1
                }}
            }
        }
        guard cnt > 0 else { return (0, 0, 0) }
        return (sr / Float(cnt), sg / Float(cnt), sb / Float(cnt))
    }

    static func calibrateAndDecode(_ img: [UInt8], size: Int) -> String? {
        let cs = size / 8  // cell size in pixels
        // Sample the 5 anchor cells to calibrate colors.
        // Anchors: (1,1)=black, (1,6)=red, (6,1)=green, (6,6)=blue, (7,0)=white (L-finder corner).
        let anchorCells: [(r: Int, c: Int, label: Int)] = [(1,1,0),(1,6,1),(6,1,2),(6,6,3),(7,0,255)]
        var calibration = [(r: Float, g: Float, b: Float, label: Int)]()
        for a in anchorCells {
            let (sr, sg, sb) = sampleCell(img, size: size, cellSize: cs, row: a.r, col: a.c)
            calibration.append((sr, sg, sb, a.label))
        }
        // Reject if luminance spread is < 60 (prevents all-zero false positives)
        let lums = calibration.map { ($0.r + $0.g + $0.b) / 3 }
        guard (lums.max()! - lums.min()!) >= 60 else { return nil }

        // Sample data cells and classify
        var dibits = [UInt8]()
        for r in 0..<8 { for c in 0..<8 {
            guard ChessMatrixEncoder.isDataCell(r: r, c: c) else { continue }
            let (dr, dg, db) = sampleCell(img, size: size, cellSize: cs, row: r, col: c)
            // Nearest calibration point (Euclidean in RGB)
            var best = 0; var bestDist = Float.infinity
            for (i, cal) in calibration.prefix(4).enumerated() {
                let d = (dr-cal.r)*(dr-cal.r) + (dg-cal.g)*(dg-cal.g) + (db-cal.b)*(db-cal.b)
                if d < bestDist { bestDist = d; best = i }
            }
            dibits.append(UInt8(best))
        }}
        guard dibits.count == 32 else { return nil }

        // Pack dibits → 8 bytes
        let codeword = (0..<8).map { i -> UInt8 in
            let d = dibits[i*4..<i*4+4]
            return (d[d.startIndex] << 6) | (d[d.startIndex+1] << 4) |
                   (d[d.startIndex+2] << 2) | d[d.startIndex+3]
        }
        guard let data = RSCodec.decode(codeword) else { return nil }
        return bytesToRoomCode(Array(data))
    }

    // MARK: - Grid decode (encoder round-trip path, matches JS decodeColorGrid)

    /// Decode a pre-rendered 8×8 color grid (values 0–3) into a room code.
    /// Mirrors JS `decodeColorGrid(grid)` exactly — no image pipeline needed.
    public static func decodeColorGrid(_ grid: [[Int]]) -> String? {
        var dibits = [UInt8]()
        for r in 0..<8 { for c in 0..<8 {
            guard ChessMatrixEncoder.isDataCell(r: r, c: c) else { continue }
            dibits.append(UInt8(grid[r][c]))
        }}
        guard dibits.count == 32 else { return nil }
        let codeword = (0..<8).map { i -> UInt8 in
            (dibits[i*4] << 6) | (dibits[i*4+1] << 4) | (dibits[i*4+2] << 2) | dibits[i*4+3]
        }
        guard let data = RSCodec.decode(codeword) else { return nil }
        return bytesToRoomCode(Array(data))
    }

    // MARK: - Bytes → room code

    static func bytesToRoomCode(_ bytes: [UInt8]) -> String? {
        // Unpack 30 bits (6 chars × 5 bits) from 4 bytes
        var bits = [Int]()
        for b in bytes { for i in stride(from: 7, through: 0, by: -1) { bits.append(Int((b >> i) & 1)) } }
        var code = ""
        for i in 0..<6 {
            let val = bits[i*5..<i*5+5].reduce(0) { $0 << 1 | $1 }
            guard val >= 0 && val < 26 else { return nil }
            code.append(Character(UnicodeScalar(65 + val)!))
        }
        return code
    }
}
