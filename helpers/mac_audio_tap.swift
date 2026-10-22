// Nova's computer-audio capture on macOS (13 or later): ScreenCaptureKit hands over what the Mac is playing
// (a call, a video), and this writes it to stdout as 16 kHz mono 32-bit float samples, little-endian, until
// Nova closes the pipe. Nova's own sound is left out. macOS asks for Screen Recording permission the first
// time; no picture is captured beyond a 2x2 pixel frame the API requires.
// Nova builds it on first use: swiftc -O helpers/mac_audio_tap.swift -o data/bin/mac-audio-tap
import CoreMedia
import Foundation
import ScreenCaptureKit

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(1)
}

@available(macOS 13.0, *)
final class Tap: NSObject, SCStreamOutput, SCStreamDelegate {
    private var stream: SCStream?
    private let out = FileHandle.standardOutput

    func start() async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let display = content.displays.first else { fail("no display to capture audio from") }
        let config = SCStreamConfiguration()
        config.capturesAudio = true
        config.excludesCurrentProcessAudio = true
        config.sampleRate = 16000
        config.channelCount = 1
        config.width = 2
        config.height = 2
        config.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        let stream = SCStream(filter: SCContentFilter(display: display, excludingWindows: []),
                              configuration: config, delegate: self)
        try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: DispatchQueue(label: "nova.audio"))
        try await stream.startCapture()
        self.stream = stream
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer buffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, buffer.isValid else { return }
        var list = AudioBufferList()
        var block: CMBlockBuffer?
        let status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            buffer, bufferListSizeNeededOut: nil, bufferListOut: &list,
            bufferListSize: MemoryLayout<AudioBufferList>.size, blockBufferAllocator: nil,
            blockBufferMemoryAllocator: nil, flags: 0, blockBufferOut: &block)
        guard status == noErr, let data = list.mBuffers.mData else { return }
        out.write(Data(bytes: data, count: Int(list.mBuffers.mDataByteSize)))  // Nova closing the pipe ends us
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        fail("capture stopped: \(error.localizedDescription)")
    }
}

guard #available(macOS 13.0, *) else { fail("capturing the computer's audio needs macOS 13 or later") }
let tap = Tap()
Task {
    do { try await tap.start() } catch { fail("couldn't capture audio: \(error.localizedDescription)") }
}
dispatchMain()
