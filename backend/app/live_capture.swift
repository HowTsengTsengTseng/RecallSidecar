import AppKit
import CoreImage
import CoreMedia
import ScreenCaptureKit
import Vision

final class CaptureAgent: NSObject, SCContentSharingPickerObserver, SCStreamOutput, SCStreamDelegate {
    private var stream: SCStream?
    private let outputQueue = DispatchQueue(label: "recall.capture.frames")
    private let ciContext = CIContext(options: [.cacheIntermediates: false])
    private var paused = false
    private var stopped = false
    private var previousFrame = Set<String>()
    private var windowLabel = "selected window"
    private var appLabel = ""

    func begin() {
        let picker = SCContentSharingPicker.shared
        var config = SCContentSharingPickerConfiguration()
        config.allowedPickerModes = .singleWindow
        config.allowsChangingSelectedContent = true
        picker.configuration = config
        picker.add(self)
        NSApp.activate(ignoringOtherApps: true)
        picker.present(using: .window)
        emit(["type": "state", "state": "selecting_window"])
    }

    func contentSharingPicker(_ picker: SCContentSharingPicker, didUpdateWith filter: SCContentFilter, for stream: SCStream?) {
        if #available(macOS 15.2, *), let window = filter.includedWindows.first {
            windowLabel = window.title ?? "selected window"
            appLabel = window.owningApplication?.applicationName ?? ""
        }
        emit(["type": "state", "state": "starting_capture", "window_label": windowLabel, "app_label": appLabel])
        let config = SCStreamConfiguration()
        config.width = 1280
        config.height = 900
        config.minimumFrameInterval = CMTime(value: 1, timescale: 2)
        config.queueDepth = 2
        config.capturesAudio = false
        let capture = SCStream(filter: filter, configuration: config, delegate: self)
        do {
            try capture.addStreamOutput(self, type: .screen, sampleHandlerQueue: outputQueue)
            self.stream = capture
            capture.startCapture { [weak self] error in
                if let error { self?.emit(["type": "error", "message": String(describing: error)]); self?.stop() }
                else { self?.emit(["type": "state", "state": "capturing"]) }
            }
        } catch { emit(["type": "error", "message": String(describing: error)]) }
    }

    func contentSharingPicker(_ picker: SCContentSharingPicker, didCancelFor stream: SCStream?) {
        emit(["type": "state", "state": "cancelled"])
        stop()
    }

    func contentSharingPickerStartDidFailWithError(_ error: Error) {
        emit(["type": "error", "message": String(describing: error)])
        stop()
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen, !paused, !stopped, CMSampleBufferIsValid(sampleBuffer),
              let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let started = DispatchTime.now().uptimeNanoseconds
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = false
        request.recognitionLanguages = ["zh-Hant", "en-US"]
        do {
            try VNImageRequestHandler(cvPixelBuffer: pixelBuffer).perform([request])
            var currentFrame = Set<String>()
            var duplicates = 0
            let changeStarted = DispatchTime.now().uptimeNanoseconds
            for observation in request.results ?? [] {
                guard let candidate = observation.topCandidates(1).first else { continue }
                let text = candidate.string.trimmingCharacters(in: .whitespacesAndNewlines)
                guard text.count >= 2, candidate.confidence >= 0.35 else { continue }
                let key = text.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current)
                currentFrame.insert(key)
                guard !previousFrame.contains(key) else { duplicates += 1; continue }
                emit(["type": "message", "text": text, "confidence": candidate.confidence,
                      "window_label": windowLabel, "app_label": appLabel,
                      "timestamp": ISO8601DateFormatter().string(from: Date())])
            }
            let changeMs = Double(DispatchTime.now().uptimeNanoseconds - changeStarted) / 1_000_000
            previousFrame = currentFrame
            let elapsed = Double(DispatchTime.now().uptimeNanoseconds - started) / 1_000_000
            emit(["type": "frame", "ocr_ms": elapsed, "change_detection_ms": changeMs, "duplicates": duplicates])
        } catch { emit(["type": "error", "message": "vision_ocr_failed"]) }
    }

    func pause() { paused = true; emit(["type": "state", "state": "paused"]) }
    func resume() { paused = false; emit(["type": "state", "state": "capturing"]) }
    func stop() {
        guard !stopped else { return }
        stopped = true
        guard let stream else {
            emit(["type": "state", "state": "stopped"])
            DispatchQueue.main.async { NSApp.terminate(nil) }
            return
        }
        stream.stopCapture { [weak self] _ in
            self?.emit(["type": "state", "state": "stopped"])
            DispatchQueue.main.async { NSApp.terminate(nil) }
        }
    }

    private func emit(_ object: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: object), let line = String(data: data, encoding: .utf8) else { return }
        print(line); fflush(stdout)
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let agent = CaptureAgent()
agent.begin()
DispatchQueue.global(qos: .userInitiated).async {
    while let line = readLine() {
        switch line { case "pause": agent.pause(); case "resume": agent.resume(); case "stop": agent.stop(); return; default: break }
    }
}
app.run()
