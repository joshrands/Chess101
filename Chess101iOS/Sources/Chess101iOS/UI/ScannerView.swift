#if canImport(UIKit)
import SwiftUI
import AVFoundation

/// Live camera scanner that decodes a ChessMatrix room code.
public struct ScannerView: UIViewControllerRepresentable {
    @Binding public var detectedCode: String?
    @Binding public var debugInfo: ScanDebugInfo

    public init(detectedCode: Binding<String?>, debugInfo: Binding<ScanDebugInfo>) {
        self._detectedCode = detectedCode
        self._debugInfo = debugInfo
    }

    public func makeUIViewController(context: Context) -> ScannerViewController {
        let vc = ScannerViewController()
        vc.onDetected = { code in
            DispatchQueue.main.async { detectedCode = code }
        }
        vc.onDebugUpdate = { info in
            DispatchQueue.main.async { debugInfo = info }
        }
        return vc
    }

    public func updateUIViewController(_ vc: ScannerViewController, context: Context) {}
}

/// Camera session + frame processing for ChessMatrix decoding.
public final class ScannerViewController: UIViewController, AVCaptureVideoDataOutputSampleBufferDelegate {
    var onDetected: ((String) -> Void)?
    var onDebugUpdate: ((ScanDebugInfo) -> Void)?
    private var captureSession: AVCaptureSession?
    private var lastDecodeTime: Date = .distantPast

    public override func viewDidLoad() {
        super.viewDidLoad()
        setupCamera()
    }

    private func setupCamera() {
        let status = AVCaptureDevice.authorizationStatus(for: .video)
        print("[Scanner] camera auth status: \(status.rawValue)")
        switch status {
        case .authorized:
            startSession()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { granted in
                print("[Scanner] camera permission granted: \(granted)")
                if granted { DispatchQueue.main.async { self.startSession() } }
            }
        case .denied, .restricted:
            print("[Scanner] camera permission denied/restricted — cannot scan")
        @unknown default:
            break
        }
    }

    private func startSession() {
        let session = AVCaptureSession()
        session.sessionPreset = .medium

        guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) else {
            print("[Scanner] no back camera device found")
            return
        }
        do {
            let input = try AVCaptureDeviceInput(device: device)
            session.addInput(input)
            print("[Scanner] camera input added: \(device.localizedName)")
        } catch {
            print("[Scanner] failed to create camera input: \(error)")
            return
        }

        let output = AVCaptureVideoDataOutput()
        output.alwaysDiscardsLateVideoFrames = true
        output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
        output.setSampleBufferDelegate(self, queue: DispatchQueue(label: "chess101.scanner"))

        guard session.canAddOutput(output) else {
            print("[Scanner] cannot add video output")
            return
        }
        session.addOutput(output)

        if let conn = output.connection(with: .video) {
            print("[Scanner] video connection active=\(conn.isActive) enabled=\(conn.isEnabled)")
        } else {
            print("[Scanner] WARNING: no video connection on output")
        }

        let preview = AVCaptureVideoPreviewLayer(session: session)
        preview.videoGravity = .resizeAspectFill
        preview.frame = view.bounds
        view.layer.insertSublayer(preview, at: 0)

        captureSession = session
        DispatchQueue.global(qos: .userInitiated).async {
            print("[Scanner] starting session")
            session.startRunning()
            print("[Scanner] session running: \(session.isRunning)")
        }
    }

    public override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        (view.layer.sublayers?.first as? AVCaptureVideoPreviewLayer)?.frame = view.bounds
    }

    public func captureOutput(_ output: AVCaptureOutput,
                               didOutput buffer: CMSampleBuffer,
                               from connection: AVCaptureConnection) {
        // Throttle to 4 FPS for decode
        guard Date().timeIntervalSince(lastDecodeTime) > 0.25 else { return }
        lastDecodeTime = Date()

        guard let pixelBuffer = CMSampleBufferGetImageBuffer(buffer) else { return }
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        let srcW = CVPixelBufferGetWidth(pixelBuffer)
        let srcH = CVPixelBufferGetHeight(pixelBuffer)
        guard let base = CVPixelBufferGetBaseAddress(pixelBuffer) else { return }

        // Downsample to max 320px on longest side — keeps pipeline fast in Swift
        let maxDim = 640
        let scale = min(1.0, Double(maxDim) / Double(max(srcW, srcH)))
        let w = max(1, Int(Double(srcW) * scale))
        let h = max(1, Int(Double(srcH) * scale))

        // Convert BGRA → RGBA while downsampling (nearest-neighbour)
        var rgba = [UInt8](repeating: 0, count: w * h * 4)
        let src = base.assumingMemoryBound(to: UInt8.self)
        for dy in 0..<h {
            let sy = dy * srcH / h
            for dx in 0..<w {
                let sx = dx * srcW / w
                let si = (sy * srcW + sx) * 4
                let di = (dy * w + dx) * 4
                rgba[di]   = src[si+2]   // R ← B
                rgba[di+1] = src[si+1]   // G
                rgba[di+2] = src[si]     // B ← R
                rgba[di+3] = 255
            }
        }

        let dbg = ChessMatrixDecoder.decodeFrameDebug(pixels: rgba, width: w, height: h)
        onDebugUpdate?(dbg)
        if let code = dbg.code {
            onDetected?(code)
        }
    }
}
#endif
