import Foundation
import Accelerate

/// Intermediate pipeline results from `decodeFrameDebug`.
public struct ScanDebugInfo {
    // Granular stage flags — set true as each step passes
    public var centroidFound: Bool = false   // step 5: white pixels exist in binary image
    public var axesFound: Bool = false       // step 6: two dominant Hough axes found
    public var quadFound: Bool = false       // step 7-9: bounding rect + perspective warp
    public var warpedFound: Bool = false     // step 10: L-finder orientation succeeded
    public var calFound: Bool = false        // step 11a: calibration anchor spread >= 60
    public var gridFound: Bool = false       // step 11b: 32 dibits classified
    public var code: String? = nil
    /// Calibration anchor RGB values in order K, R, G, B.
    public var calRGB: [(r: Float, g: Float, b: Float)]? = nil
    /// 128×128 RGBA downsampled binary image — shows what the binarizer sees.
    public var binaryThumb: [UInt8]? = nil
    /// Oriented warped image as 128×128 RGBA bytes (nil if pipeline failed before this stage).
    public var warpedPixels: [UInt8]? = nil
    public init() {}
}

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
        // 3. Gaussian blur (r=1 matching JS — small box to reduce noise before binarize)
        let blurred = gaussianBlur(gray, width: width, height: height, radius: 1)
        // 4. Local binarize (uses blurred, k2=200 floor)
        let binary = localBinarize(blurred, width: width, height: height)
        // 5. Centroid
        guard let centroid = whiteCentroid(binary, width: width, height: height) else { return nil }
        // 6. Hough axes (on unblurred normalized gray — matches JS which passes norm not blur1)
        guard let (angle1, angle2) = houghAxes(gray, width: width, height: height) else { return nil }
        // 7-9. Unshear + tolerant inflate + back-transform + scale + angular sort + perspective warp
        guard let outer = getOuterCorners(binary: binary, width: width, height: height,
                                          centroid: centroid, angle1: angle1, angle2: angle2) else { return nil }
        guard let warped = perspectiveWarp(pixels: pixels, width: width, height: height,
                                           corners: outer, outSize: 128) else { return nil }
        // 10. Orientation — find rotation with L-finder at bottom-left
        guard let oriented = findOrientation(warped: warped, size: 128) else { return nil }
        // 11. Timing strip structural guard (matches JS timingStripOk) — rejects non-barcode warps
        guard timingStripOk(oriented, size: 128) else { return nil }
        // 12. Calibrate and decode
        return calibrateAndDecode(oriented, size: 128)
    }

    /// Same pipeline as `decodeFrame` but returns intermediate debug info at each stage.
    public static func decodeFrameDebug(pixels: [UInt8], width: Int, height: Int) -> ScanDebugInfo {
        var info = ScanDebugInfo()
        let tag = "[ChessMatrix]"

        var gray = grayscale(pixels: pixels, width: width, height: height)
        normalize(&gray, width: width, height: height)
        let blurred = gaussianBlur(gray, width: width, height: height, radius: 1)
        let binary = localBinarize(blurred, width: width, height: height)
        info.binaryThumb = downsampleBinary(binary, srcW: width, srcH: height, dstSize: 128)

        let whiteCount = binary.filter { $0 > 0 }.count
        let whitePct = 100 * whiteCount / (width * height)
        print("\(tag) frame \(width)×\(height) whitePx=\(whiteCount) (\(whitePct)%)")

        guard let centroid = whiteCentroid(binary, width: width, height: height) else {
            print("\(tag) FAIL centroid — no white pixels in binary image")
            return info
        }
        info.centroidFound = true
        print("\(tag) centroid=(\(Int(centroid.x)),\(Int(centroid.y)))")

        guard let (angle1, angle2) = houghAxes(gray, width: width, height: height) else {
            print("\(tag) FAIL axes — could not find two dominant Hough angles")
            return info
        }
        info.axesFound = true
        let deg1 = Int(angle1 * 180 / .pi), deg2 = Int(angle2 * 180 / .pi)
        print("\(tag) axes=\(deg1)°,\(deg2)°")

        guard let outer = getOuterCorners(binary: binary, width: width, height: height,
                                          centroid: centroid, angle1: angle1, angle2: angle2) else {
            print("\(tag) FAIL inflateRect — bounding rect degenerate")
            return info
        }
        info.quadFound = true
        print("\(tag) quad found (outer corners sorted)")

        guard let warped = perspectiveWarp(pixels: pixels, width: width, height: height,
                                           corners: outer, outSize: 128) else {
            print("\(tag) FAIL perspectiveWarp")
            return info
        }

        guard let oriented = findOrientation(warped: warped, size: 128) else {
            print("\(tag) FAIL orientation — no rotation had bright bottom row (L-finder not found)")
            return info
        }
        info.warpedFound = true
        info.warpedPixels = oriented
        print("\(tag) warp+orient OK — check warped thumbnail in overlay")

        guard timingStripOk(oriented, size: 128, log: true) else {
            print("\(tag) FAIL timingStrip — row0/col7 don't alternate (not a barcode)")
            return info
        }

        info.code = calibrateAndDecodeDebug(oriented, size: 128, info: &info)
        if let code = info.code {
            print("\(tag) SUCCESS code=\(code)")
        } else {
            print("\(tag) FAIL decode — calFound=\(info.calFound) gridFound=\(info.gridFound)")
            if let cal = info.calRGB {
                let names = ["K","R","G","B"]
                for (i, c) in cal.enumerated() {
                    print("\(tag)   \(names[i]): r=\(Int(c.r)) g=\(Int(c.g)) b=\(Int(c.b))")
                }
            }
        }
        return info
    }

    private static func downsampleBinary(_ binary: [UInt8], srcW: Int, srcH: Int, dstSize: Int) -> [UInt8] {
        var out = [UInt8](repeating: 0, count: dstSize * dstSize * 4)
        for dy in 0..<dstSize {
            for dx in 0..<dstSize {
                let sy = dy * srcH / dstSize
                let sx = dx * srcW / dstSize
                let v = binary[sy * srcW + sx]
                let i = (dy * dstSize + dx) * 4
                out[i] = v; out[i+1] = v; out[i+2] = v; out[i+3] = 255
            }
        }
        return out
    }

    /// Variant of `calibrateAndDecode` that fills `info` with calibration data.
    private static func calibrateAndDecodeDebug(_ img: [UInt8], size: Int,
                                                info: inout ScanDebugInfo) -> String? {
        let cs = size / 8
        let anchorCells: [(r: Int, c: Int, label: Int)] = [(1,1,0),(1,6,1),(6,1,2),(6,6,3),(7,0,255)]
        var calibration = [(r: Float, g: Float, b: Float, label: Int)]()
        for a in anchorCells {
            let (sr, sg, sb) = sampleCell(img, size: size, cellSize: cs, row: a.r, col: a.c)
            calibration.append((sr, sg, sb, a.label))
        }
        let lums = calibration.map { ($0.r + $0.g + $0.b) / 3 }
        guard (lums.max()! - lums.min()!) >= 60 else { return nil }
        info.calFound = true
        info.calRGB = calibration.prefix(4).map { (r: $0.r, g: $0.g, b: $0.b) }
        var dibits = [UInt8]()
        for r in 0..<8 { for c in 0..<8 {
            guard ChessMatrixEncoder.isDataCell(r: r, c: c) else { continue }
            let (dr, dg, db) = sampleCell(img, size: size, cellSize: cs, row: r, col: c)
            var best = 0; var bestDist = Float.infinity
            for (i, cal) in calibration.prefix(4).enumerated() {
                let d = (dr-cal.r)*(dr-cal.r) + (dg-cal.g)*(dg-cal.g) + (db-cal.b)*(db-cal.b)
                if d < bestDist { bestDist = d; best = i }
            }
            dibits.append(UInt8(best))
        }}
        guard dibits.count == 32 else { return nil }
        info.gridFound = true
        let codeword = (0..<8).map { i -> UInt8 in
            let d = dibits[i*4..<i*4+4]
            return (d[d.startIndex] << 6) | (d[d.startIndex+1] << 4) |
                   (d[d.startIndex+2] << 2) | d[d.startIndex+3]
        }
        let tag = "[ChessMatrix]"
        print("\(tag) codeword=\(codeword.map { String(format:"%02X",$0) }.joined())")
        guard let data = RSCodec.decode(codeword) else {
            print("\(tag) RS decode failed — too many errors in codeword")
            return nil
        }
        return bytesToRoomCode(Array(data))
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
        // Matches Python _local_threshold: T = max(mean - k1*var, k2) where k1=0.15, k2=200.
        // k2=200 is the critical floor: only pixels > 200/255 (very bright) are ever white.
        // Uses two integral images (sum and sum-of-squares) for O(1) per pixel variance.
        let k: Int = 15   // half-window = 15 → 31×31 neighbourhood, same as Python window=31
        let k1: Double = 0.15
        let k2: Double = 200.0

        var iSum  = [Double](repeating: 0, count: width * height)
        var iSumSq = [Double](repeating: 0, count: width * height)
        for r in 0..<height {
            for c in 0..<width {
                let v = Double(img[r * width + c])
                let above  = r > 0 ? iSum[(r-1)*width+c]    : 0
                let left   = c > 0 ? iSum[r*width+(c-1)]    : 0
                let diag   = (r > 0 && c > 0) ? iSum[(r-1)*width+(c-1)] : 0
                iSum[r*width+c] = v + above + left - diag
                let aboveSq = r > 0 ? iSumSq[(r-1)*width+c]    : 0
                let leftSq  = c > 0 ? iSumSq[r*width+(c-1)]    : 0
                let diagSq  = (r > 0 && c > 0) ? iSumSq[(r-1)*width+(c-1)] : 0
                iSumSq[r*width+c] = v*v + aboveSq + leftSq - diagSq
            }
        }
        var out = [UInt8](repeating: 0, count: width * height)
        for r in 0..<height {
            let r1 = max(0, r-k), r2 = min(height-1, r+k)
            for c in 0..<width {
                let c1 = max(0, c-k), c2 = min(width-1, c+k)
                func boxSum(_ I: [Double]) -> Double {
                    var s = I[r2*width+c2]
                    if r1 > 0 { s -= I[(r1-1)*width+c2] }
                    if c1 > 0 { s -= I[r2*width+(c1-1)] }
                    if r1 > 0 && c1 > 0 { s += I[(r1-1)*width+(c1-1)] }
                    return s
                }
                let n = Double((r2-r1+1)*(c2-c1+1))
                let mean   = boxSum(iSum) / n
                let meanSq = boxSum(iSumSq) / n
                let variance = max(meanSq - mean * mean, 0.0)
                let threshold = max(mean - k1 * variance, k2)
                out[r*width+c] = Double(img[r*width+c]) > threshold ? 255 : 0
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

    // MARK: - Steps 6-9: Hough axes + unshear + inflate + warp corners

    /// Hough axis detection on normalized grayscale — matches JS `houghAxes`.
    /// Uses Sobel on gray (not binary) and atan2(gx,gy) for LINE direction.
    static func houghAxes(_ gray: [Float], width: Int, height: Int) -> (Float, Float)? {
        var hist = [Float](repeating: 0, count: 180)
        for r in 1..<height-1 {
            for c in 1..<width-1 {
                let gx = -gray[(r-1)*width+(c-1)] + gray[(r-1)*width+(c+1)]
                       - 2*gray[r*width+(c-1)]    + 2*gray[r*width+(c+1)]
                       - gray[(r+1)*width+(c-1)]  + gray[(r+1)*width+(c+1)]
                let gy =  gray[(r-1)*width+(c-1)] + 2*gray[(r-1)*width+c] + gray[(r-1)*width+(c+1)]
                       -  gray[(r+1)*width+(c-1)] - 2*gray[(r+1)*width+c] - gray[(r+1)*width+(c+1)]
                let mag = sqrt(gx*gx + gy*gy)
                guard mag > 100 else { continue }
                // Line direction: atan2(gx, gy) — perpendicular to gradient (matches JS)
                var angle = atan2(gx, gy) * 180 / .pi
                angle = ((angle.truncatingRemainder(dividingBy: 180)) + 180)
                            .truncatingRemainder(dividingBy: 180)
                hist[min(179, max(0, Int(angle)))] += mag
            }
        }
        let p1 = hist.enumerated().max(by: { $0.element < $1.element })!.offset
        guard hist[p1] > 0 else { return nil }
        // Find second peak: suppress ±5° around p1 (matches JS)
        var sup = hist
        for d in -5...5 { sup[((p1 + d) % 180 + 180) % 180] = 0 }
        let p2entries = sup.enumerated().max(by: { $0.element < $1.element })
        guard let p2 = p2entries, p2.element > 0 else { return nil }
        return (Float(p1) * .pi / 180, Float(p2.offset) * .pi / 180)
    }

    /// Apply 2×2 affine unshear to binary image (inverse-map each dst pixel).
    /// `m` = basis matrix A = [[u1x,u2x],[u1y,u2y]]; maps unsheared → original.
    private static func applyAffineBin(_ bin: [UInt8], width: Int, height: Int,
                                        cx: Float, cy: Float, m: [[Float]]) -> [UInt8] {
        let (a, b, c, d) = (m[0][0], m[0][1], m[1][0], m[1][1])
        var out = [UInt8](repeating: 0, count: width * height)
        for y in 0..<height {
            for x in 0..<width {
                let dx = Float(x) - cx, dy = Float(y) - cy
                let sx = Int(a * dx + b * dy + cx)
                let sy = Int(c * dx + d * dy + cy)
                if sx >= 0 && sx < width && sy >= 0 && sy < height {
                    out[y * width + x] = bin[sy * width + sx]
                }
            }
        }
        return out
    }

    /// Tolerant axis-aligned inflate rect from centroid — matches JS `inflateRect(tol=0.08)`.
    /// Expands one pixel at a time; stops when the next row/col has ≥8% white pixels.
    private static func inflateRectTolerant(_ bin: [UInt8], width: Int, height: Int,
                                             cx: Float, cy: Float) -> (l: Int, t: Int, r: Int, b: Int)? {
        var top = Int(cy), bot = Int(cy), left = Int(cx), right = Int(cx)
        var changed = true
        while changed {
            changed = false
            let rw = max(1, right - left + 1)
            let rh = max(1, bot - top + 1)
            if top > 0 {
                var cnt = 0
                for x in left...right { if bin[(top-1)*width+x] > 0 { cnt += 1 } }
                if Float(cnt) / Float(rw) < 0.08 { top -= 1; changed = true }
            }
            if bot < height-1 {
                var cnt = 0
                for x in left...right { if bin[(bot+1)*width+x] > 0 { cnt += 1 } }
                if Float(cnt) / Float(rw) < 0.08 { bot += 1; changed = true }
            }
            if left > 0 {
                var cnt = 0
                for y in top...bot { if bin[y*width+(left-1)] > 0 { cnt += 1 } }
                if Float(cnt) / Float(rh) < 0.08 { left -= 1; changed = true }
            }
            if right < width-1 {
                var cnt = 0
                for y in top...bot { if bin[y*width+(right+1)] > 0 { cnt += 1 } }
                if Float(cnt) / Float(rh) < 0.08 { right += 1; changed = true }
            }
        }
        guard right > left && bot > top else { return nil }
        return (left, top, right, bot)
    }

    /// Angular sort of 4 corners CW from north, starting at topmost = TL.
    /// Matches JS: atan2(px-mcx, mcy-py) sorts CW from north.
    private static func angularSortCorners(_ corners: [(x: Float, y: Float)]) -> [(x: Float, y: Float)] {
        let mcx = corners.reduce(0) { $0 + $1.x } / 4
        let mcy = corners.reduce(0) { $0 + $1.y } / 4
        let sorted = corners.sorted { atan2($0.x - mcx, mcy - $0.y) < atan2($1.x - mcx, mcy - $1.y) }
        let topI = sorted.enumerated().min(by: { $0.element.y < $1.element.y })!.offset
        return (0..<4).map { sorted[(topI + $0) % 4] }
    }

    /// Combined steps 7-9: unshear binary → tolerant inflate → back-transform → scale 4/3 → angular sort.
    /// Returns 4 corners in [TL, TR, BR, BL] order ready for perspective warp.
    static func getOuterCorners(binary: [UInt8], width: Int, height: Int,
                                 centroid: (x: Float, y: Float),
                                 angle1: Float, angle2: Float) -> [(x: Float, y: Float)]? {
        let u1 = (cos(angle1), sin(angle1))
        let u2 = (cos(angle2), sin(angle2))
        let A: [[Float]] = [[u1.0, u2.0], [u1.1, u2.1]]

        let unsheared = applyAffineBin(binary, width: width, height: height,
                                        cx: centroid.x, cy: centroid.y, m: A)
        guard let (left, top, right, bot) = inflateRectTolerant(
            unsheared, width: width, height: height, cx: centroid.x, cy: centroid.y) else { return nil }

        // Back-transform: original = A * (unsheared - c) + c
        func back(_ px: Float, _ py: Float) -> (x: Float, y: Float) {
            let dx = px - centroid.x, dy = py - centroid.y
            return (A[0][0]*dx + A[0][1]*dy + centroid.x,
                    A[1][0]*dx + A[1][1]*dy + centroid.y)
        }
        let corners = [back(Float(left), Float(top)), back(Float(right), Float(top)),
                       back(Float(right), Float(bot)), back(Float(left), Float(bot))]

        // Scale 4/3 from centroid of inner corners
        let mcx = corners.reduce(0) { $0 + $1.x } / 4
        let mcy = corners.reduce(0) { $0 + $1.y } / 4
        let outer = corners.map { (x: ($0.x - mcx) * 4/3 + mcx, y: ($0.y - mcy) * 4/3 + mcy) }

        return angularSortCorners(outer)
    }

    // MARK: - Step 9: Perspective warp (full homography DLT, matches JS warpRGBA)

    private static func computeHomography(src: [(x: Float, y: Float)],
                                           dst: [(x: Float, y: Float)]) -> [Double]? {
        var M = [[Double]](repeating: [Double](repeating: 0, count: 9), count: 8)
        for i in 0..<4 {
            let (x, y) = (Double(src[i].x), Double(src[i].y))
            let (u, v) = (Double(dst[i].x), Double(dst[i].y))
            M[2*i]   = [-x, -y, -1,  0,  0,  0, u*x, u*y, u]
            M[2*i+1] = [ 0,  0,  0, -x, -y, -1, v*x, v*y, v]
        }
        var A = (0..<8).map { i -> [Double] in Array(M[i][0..<8]) + [-M[i][8]] }
        for col in 0..<8 {
            var mx = col
            for r in (col+1)..<8 { if abs(A[r][col]) > abs(A[mx][col]) { mx = r } }
            if mx != col { A.swapAt(col, mx) }
            let piv = A[col][col]
            guard abs(piv) > 1e-10 else { return nil }
            for j in col..<9 { A[col][j] /= piv }
            for r in 0..<8 where r != col {
                let f = A[r][col]; for j in col..<9 { A[r][j] -= f * A[col][j] }
            }
        }
        return A.map { $0[8] } + [1.0]
    }

    private static func inv3x3(_ H: [Double]) -> [Double]? {
        let (a,b,c,d,e,f,g,h,k) = (H[0],H[1],H[2],H[3],H[4],H[5],H[6],H[7],H[8])
        let det = a*(e*k-f*h) - b*(d*k-f*g) + c*(d*h-e*g)
        guard abs(det) > 1e-10 else { return nil }
        return [(e*k-f*h)/det,(c*h-b*k)/det,(b*f-c*e)/det,
                (f*g-d*k)/det,(a*k-c*g)/det,(c*d-a*f)/det,
                (d*h-e*g)/det,(b*g-a*h)/det,(a*e-b*d)/det]
    }

    static func perspectiveWarp(pixels: [UInt8], width: Int, height: Int,
                                 corners: [(x: Float, y: Float)], outSize: Int) -> [UInt8]? {
        let N = Float(outSize - 1)
        let dst: [(x: Float, y: Float)] = [(0,0),(N,0),(N,N),(0,N)]
        guard let H = computeHomography(src: corners, dst: dst),
              let Hi = inv3x3(H) else { return nil }
        var out = [UInt8](repeating: 0, count: outSize * outSize * 4)
        for oy in 0..<outSize {
            let dy = Double(oy)
            for ox in 0..<outSize {
                let dx = Double(ox)
                let wp = Hi[6]*dx + Hi[7]*dy + Hi[8]
                guard abs(wp) > 1e-10 else { continue }
                let sx = (Hi[0]*dx + Hi[1]*dy + Hi[2]) / wp
                let sy = (Hi[3]*dx + Hi[4]*dy + Hi[5]) / wp
                let ix = min(max(Int(sx), 0), width - 1)
                let iy = min(max(Int(sy), 0), height - 1)
                let si = (iy * width + ix) * 4
                let di = (oy * outSize + ox) * 4
                out[di] = pixels[si]; out[di+1] = pixels[si+1]
                out[di+2] = pixels[si+2]; out[di+3] = 255
            }
        }
        return out
    }

    // MARK: - Old step 7 stubs (kept to avoid dead-code warnings from old call sites)
    static func inflateRect(_ bin: [UInt8], width: Int, height: Int,
                             centroid: (x: Float, y: Float),
                             angle1: Float, angle2: Float) -> [(x: Float, y: Float)]? {
        return getOuterCorners(binary: bin, width: width, height: height,
                               centroid: centroid, angle1: angle1, angle2: angle2)
    }
    static func scaleRect(_ corners: [(x: Float, y: Float)], factor: Float,
                           cx: Float, cy: Float) -> [(x: Float, y: Float)] {
        corners.map { (cx + ($0.x - cx) * factor, cy + ($0.y - cy) * factor) }
    }

    // MARK: - Step 10: Orientation

    /// Mirrors Python `_warp_to_canonical`: binarize the warped image, find the centroid
    /// of bright pixels, rotate so that centroid-corner ends up at bottom-left (L-finder).
    static func findOrientation(warped: [UInt8], size: Int) -> [UInt8]? {
        // Global mean threshold on warped luminance
        var lums = [Float](repeating: 0, count: size * size)
        for i in 0..<size * size {
            lums[i] = (Float(warped[i*4]) + Float(warped[i*4+1]) + Float(warped[i*4+2])) / 3.0
        }
        let mean = lums.reduce(0, +) / Float(size * size)

        // Centroid of above-mean pixels
        var sx: Float = 0, sy: Float = 0, cnt: Float = 0
        for r in 0..<size {
            for c in 0..<size {
                if lums[r * size + c] > mean {
                    sx += Float(c); sy += Float(r); cnt += 1
                }
            }
        }
        guard cnt > 0 else { return nil }
        let cx = sx / cnt, cy = sy / cnt
        let n = Float(size)

        // Nearest corner to centroid — that corner is the L-finder
        let corners = [("TL", Float(0), Float(0)), ("TR", n, Float(0)),
                       ("BL", Float(0), n),        ("BR", n, n)]
        let nearest = corners.min { a, b in
            (cx-a.1)*(cx-a.1)+(cy-a.2)*(cy-a.2) < (cx-b.1)*(cx-b.1)+(cy-b.2)*(cy-b.2)
        }!

        // Rotate so L-finder lands at bottom-left.
        // iOS rotate90 is CW (not CCW like numpy): TL→3, TR→2, BL→0, BR→1.
        let k = ["TL": 3, "TR": 2, "BL": 0, "BR": 1][nearest.0]!
        return k == 0 ? warped : rotate90(warped, size: size, times: k)
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

    // MARK: - Step 11a: Timing strip guard (matches JS timingStripOk)

    /// Validates that row 0 and col 7 alternate bright/dark (structural timing strips).
    /// Row 0 has 7/7 natural alternations → threshold 6. Col 7 has 5/7 → threshold 4
    /// (one imaging-noise tolerance each).
    @discardableResult
    private static func timingStripOk(_ img: [UInt8], size: Int, log: Bool = false) -> Bool {
        let cs = size / 8
        func bright(_ r: Int, _ c: Int) -> Bool {
            let (sr, sg, sb) = sampleCell(img, size: size, cellSize: cs, row: r, col: c)
            return (sr + sg + sb) / 3 > 127
        }
        func countAlternations(_ cells: [(Int, Int)]) -> Int {
            var ok = 0
            for i in 0..<(cells.count - 1) {
                if bright(cells[i].0, cells[i].1) != bright(cells[i+1].0, cells[i+1].1) { ok += 1 }
            }
            return ok
        }
        let row0 = (0..<8).map { (0, $0) }
        let col7 = (0..<8).map { ($0, 7) }
        let r0 = countAlternations(row0)
        let c7 = countAlternations(col7)
        if log { print("[ChessMatrix] timingStrip row0=\(r0)/7 col7=\(c7)/7") }
        return r0 >= 6 && c7 >= 4
    }

    // MARK: - Step 11b: Calibrate and decode

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
