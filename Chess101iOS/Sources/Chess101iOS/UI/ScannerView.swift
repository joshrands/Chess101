#if canImport(UIKit)
import SwiftUI
import AVFoundation

/// Live camera scanner that decodes a ChessMatrix room code.
public struct ScannerView: UIViewControllerRepresentable {
    @Binding public var detectedCode: String?

    public init(detectedCode: Binding<String?>) { self._detectedCode = detectedCode }

    public func makeUIViewController(context: Context) -> ScannerViewController {
        let vc = ScannerViewController()
        vc.onDetected = { code in
            DispatchQueue.main.async { detectedCode = code }
        }
        return vc
    }

    public func updateUIViewController(_ vc: ScannerViewController, context: Context) {}
}

/// Camera session + frame processing for ChessMatrix decoding.
public final class ScannerViewController: UIViewController, AVCaptureVideoDataOutputSampleBufferDelegate {
    var onDetected: ((String) -> Void)?
    private var captureSession: AVCaptureSession?
    private var lastDecodeTime: Date = .distantPast

    public override func viewDidLoad() {
        super.viewDidLoad()
        setupCamera()
    }

    private func setupCamera() {
        let session = AVCaptureSession()
        session.sessionPreset = .medium
        guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
              let input = try? AVCaptureDeviceInput(device: device) else { return }
        session.addInput(input)

        let output = AVCaptureVideoDataOutput()
        output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
        output.setSampleBufferDelegate(self, queue: DispatchQueue(label: "chess101.scanner"))
        session.addOutput(output)

        let preview = AVCaptureVideoPreviewLayer(session: session)
        preview.videoGravity = .resizeAspectFill
        preview.frame = view.bounds
        view.layer.insertSublayer(preview, at: 0)

        captureSession = session
        DispatchQueue.global(qos: .userInitiated).async { session.startRunning() }
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

        let w = CVPixelBufferGetWidth(pixelBuffer)
        let h = CVPixelBufferGetHeight(pixelBuffer)
        guard let base = CVPixelBufferGetBaseAddress(pixelBuffer) else { return }

        // Convert BGRA → RGBA
        let byteCount = w * h * 4
        var rgba = [UInt8](repeating: 0, count: byteCount)
        let src = base.assumingMemoryBound(to: UInt8.self)
        for i in 0..<w * h {
            rgba[i*4]   = src[i*4+2]  // R ← B
            rgba[i*4+1] = src[i*4+1]  // G
            rgba[i*4+2] = src[i*4]    // B ← R
            rgba[i*4+3] = 255
        }

        if let code = ChessMatrixDecoder.decodeFrame(pixels: rgba, width: w, height: h) {
            onDetected?(code)
        }
    }
}
#endif
