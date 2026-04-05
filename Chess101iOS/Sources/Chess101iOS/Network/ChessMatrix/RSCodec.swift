/// RS(8,4) Reed-Solomon codec over GF(2^8).
/// Matches the JS implementation in web/chessmatrix-scanner.js exactly.
public enum RSCodec {

    // MARK: - GF(2^8) tables  (primitive polynomial 0x11D)

    private static let EXP: [UInt8] = {
        var t = [UInt8](repeating: 0, count: 512)
        var x: UInt8 = 1
        for i in 0..<255 {
            t[i] = x; t[i + 255] = x
            let hi = x & 0x80
            x = x &<< 1
            if hi != 0 { x ^= 0x1D }
        }
        return t
    }()

    private static let LOG: [UInt8] = {
        var t = [UInt8](repeating: 0, count: 256)
        var x: UInt8 = 1
        for i in 0..<255 {
            t[Int(x)] = UInt8(i)
            let hi = x & 0x80
            x = x &<< 1
            if hi != 0 { x ^= 0x1D }
        }
        return t
    }()

    static func gfMul(_ a: UInt8, _ b: UInt8) -> UInt8 {
        guard a != 0 && b != 0 else { return 0 }
        return EXP[Int(LOG[Int(a)]) + Int(LOG[Int(b)])]
    }

    private static func gfPow(_ x: UInt8, _ n: Int) -> UInt8 {
        guard x != 0 else { return 0 }
        return EXP[(Int(LOG[Int(x)]) * n) % 255]
    }

    private static func gfInv(_ x: UInt8) -> UInt8 { EXP[255 - Int(LOG[Int(x)])] }

    // MARK: - Polynomial helpers (high-degree coefficient first)

    private static func polyEval(_ poly: [UInt8], _ x: UInt8) -> UInt8 {
        var y: UInt8 = 0
        for c in poly { y = gfMul(y, x) ^ c }
        return y
    }

    private static func polyMul(_ p: [UInt8], _ q: [UInt8]) -> [UInt8] {
        var r = [UInt8](repeating: 0, count: p.count + q.count - 1)
        for i in 0..<p.count { for j in 0..<q.count { r[i+j] ^= gfMul(p[i], q[j]) } }
        return r
    }

    // Generator polynomial: (x + 2^0)(x + 2^1)(x + 2^2)(x + 2^3)
    private static let GEN: [UInt8] = {
        var g: [UInt8] = [1]
        for i in 0..<4 { g = polyMul(g, [1, gfPow(2, i)]) }
        return g
    }()

    // MARK: - Encode

    /// Appends 4 parity bytes to `data` (must be 4 bytes). Returns 8-byte codeword.
    public static func encode(_ data: [UInt8]) -> [UInt8] {
        assert(data.count == 4)
        var msg = data + [UInt8](repeating: 0, count: 4)
        for i in 0..<4 {
            let coeff = msg[i]
            if coeff != 0 {
                for j in 1..<GEN.count { msg[i+j] ^= gfMul(coeff, GEN[j]) }
            }
        }
        return data + Array(msg[4...])
    }

    // MARK: - Decode

    /// Attempts to decode an 8-byte codeword. Returns 4 data bytes, or nil if uncorrectable.
    public static func decode(_ codeword: [UInt8]) -> [UInt8]? {
        assert(codeword.count == 8)
        var msg = [UInt8](codeword)

        // 1. Syndromes S[i] = poly(2^i) for i = 0..3
        let synd: [UInt8] = (0..<4).map { i in polyEval(msg, gfPow(2, i)) }
        if synd.allSatisfy({ $0 == 0 }) { return Array(msg[0..<4]) }

        // 2. Berlekamp-Massey → error locator polynomial
        let loc = berlekampMassey(synd)
        guard loc.count - 1 <= 2 else { return nil }

        // 3. Chien search → error positions
        guard let errPos = chienSearch(loc, n: 8) else { return nil }

        // 4. Forney → error magnitudes
        let mags = forney(synd: synd, loc: loc, errPos: errPos)
        for (k, pos) in errPos.enumerated() { msg[pos] ^= mags[k] }

        // 5. Verify correction
        let check: [UInt8] = (0..<4).map { i in polyEval(msg, gfPow(2, i)) }
        guard check.allSatisfy({ $0 == 0 }) else { return nil }

        return Array(msg[0..<4])
    }

    // MARK: - BM / Chien / Forney (matching chessmatrix-scanner.js)

    private static func berlekampMassey(_ S: [UInt8]) -> [UInt8] {
        var C: [UInt8] = [1], B: [UInt8] = [1]
        var L = 0, m = 1
        var b: UInt8 = 1
        for i in 0..<S.count {
            var d = S[i]
            for j in 1...max(L, 1) {
                if j < C.count { d ^= gfMul(C[j], S[i - j]) }
            }
            let Bs = [UInt8](repeating: 0, count: m) + B
            if d == 0 { m += 1; continue }
            let fac = gfMul(d, gfInv(b))
            if 2 * L <= i {
                let T = C
                var newC = C
                while newC.count < Bs.count { newC.append(0) }
                for j in 0..<Bs.count { newC[j] ^= gfMul(fac, Bs[j]) }
                C = newC
                L = i + 1 - L; B = T; b = d; m = 1
            } else {
                var newC = C
                while newC.count < Bs.count { newC.append(0) }
                for j in 0..<Bs.count { newC[j] ^= gfMul(fac, Bs[j]) }
                C = newC
                m += 1
            }
        }
        return C
    }

    private static func chienSearch(_ loc: [UInt8], n: Int) -> [Int]? {
        let nErrs = loc.count - 1
        let rev = Array(loc.reversed())
        var pos: [Int] = []
        for i in 0..<n {
            if polyEval(rev, gfPow(2, 255 - i)) == 0 {
                pos.append(n - 1 - i)
            }
        }
        return pos.count == nErrs ? pos : nil
    }

    private static func forney(synd: [UInt8], loc: [UInt8], errPos: [Int]) -> [UInt8] {
        let omega = Array(polyMul(synd, loc).prefix(4))
        // Formal derivative: zero out even-index (from 1) coefficients
        var lp: [UInt8] = []
        for (i, v) in loc.dropFirst().enumerated() { lp.append(i % 2 == 0 ? v : 0) }
        let lpoly: [UInt8] = lp.isEmpty ? [1] : lp
        return errPos.map { pos -> UInt8 in
            let xi = gfPow(2, 8 - 1 - pos)
            let xiInv = gfInv(xi)
            let ov = polyEval(Array(omega.reversed()), xiInv)
            let lv = polyEval(Array(lpoly.reversed()), xiInv)
            return lv != 0 ? gfMul(xi, gfMul(ov, gfInv(lv))) : 0
        }
    }
}
