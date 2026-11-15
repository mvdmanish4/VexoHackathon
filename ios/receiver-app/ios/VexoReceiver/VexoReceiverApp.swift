import AVFoundation
import CoreHaptics
import SwiftUI
import UIKit

@MainActor
final class MorsePlayer: ObservableObject {
    @Published var dotMilliseconds = 120.0
    @Published private(set) var paused = false
    @Published private(set) var waiting = 0
    @Published private(set) var currentText: String?
    @Published private(set) var issue: String?

    let supportsHaptics = CHHapticEngine.capabilitiesForHardware().supportsHaptics

    private struct Job {
        let message: MorseMessage
        var index = 0
    }

    private var queue: [Job] = []
    private var active: Job?
    private var playback: Task<Void, Never>?
    private var engine: CHHapticEngine?
    private var player: CHHapticPatternPlayer?

    func enqueue(_ message: MorseMessage, replay: Bool = false) {
        guard !message.steps.isEmpty else { return }
        let job = Job(message: message)
        if replay {
            stopPlayback()
            if let active { queue.insert(active, at: 0) }
            active = job
        } else {
            queue.append(job)
        }
        waiting = queue.count
        startPlayback()
    }

    func pause() {
        paused = true
        stopPlayback()
    }

    func resume() {
        issue = nil
        paused = false
        startPlayback()
    }

    private func stopPlayback() {
        playback?.cancel()
        playback = nil
        try? player?.stop(atTime: CHHapticTimeImmediate)
        player = nil
    }

    private func startPlayback() {
        guard !paused, playback == nil else { return }
        playback = Task { [weak self] in
            guard let self else { return }
            await self.play()
        }
    }

    private func play() async {
        while !Task.isCancelled {
            if active == nil, !queue.isEmpty { active = queue.removeFirst() }
            waiting = queue.count
            guard let job = active else {
                currentText = nil
                playback = nil
                return
            }
            currentText = job.message.text
            let step = job.message.steps[job.index]
            let dot = dotMilliseconds / 1000
            do {
                let duration = try playLetter(step, dot: dot)
                let gap = step.gap == 0 ? 7 : step.gap
                try await Task.sleep(nanoseconds: UInt64((duration + Double(gap) * dot) * 1_000_000_000))
            } catch is CancellationError {
                return
            } catch {
                issue = "Haptics stopped. Tap Resume to retry this letter."
                engine = nil
                pause()
                return
            }
            guard !Task.isCancelled else { return }
            player = nil
            active = job.index + 1 == job.message.steps.count
                ? nil : Job(message: job.message, index: job.index + 1)
        }
    }

    private func playLetter(_ step: MorseStep, dot: Double) throws -> Double {
        var duration = 0.0
        var events: [CHHapticEvent] = []
        for (index, units) in step.pattern.enumerated() {
            let length = Double(units) * dot
            if index.isMultiple(of: 2) {
                events.append(CHHapticEvent(
                    eventType: .hapticContinuous,
                    parameters: [
                        CHHapticEventParameter(parameterID: .hapticIntensity, value: 1),
                        CHHapticEventParameter(parameterID: .hapticSharpness, value: 0.65),
                    ],
                    relativeTime: duration,
                    duration: length
                ))
            }
            duration += length
        }
        if supportsHaptics {
            if engine == nil {
                let newEngine = try CHHapticEngine()
                newEngine.playsHapticsOnly = true
                newEngine.resetHandler = { [weak self] in
                    Task { @MainActor in
                        self?.engine = nil
                        self?.issue = "Haptics reset. Tap Resume to retry this letter."
                        self?.pause()
                    }
                }
                engine = newEngine
            }
            try engine?.start()
            let pattern = try CHHapticPattern(events: events, parameters: [])
            player = try engine?.makePlayer(with: pattern)
            try player?.start(atTime: CHHapticTimeImmediate)
        }
        return duration
    }
}

@main
@MainActor
struct VexoReceiverApp: App {
    var body: some Scene {
        WindowGroup { ReceiverView() }
    }
}

@MainActor
struct ReceiverView: View {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var player = MorsePlayer()
    @State private var address = Bundle.main.object(forInfoDictionaryKey: "VexoReceiverAddress") as? String
        ?? "http://MacBook-Pro.local:8765"
    @State private var code = Bundle.main.object(forInfoDictionaryKey: "VexoReceiverCode") as? String ?? ""
    @State private var showSetup = false
    @State private var connection: Task<Void, Never>?
    @State private var status = "Disconnected"
    @State private var feedID = ""
    @State private var after = 0
    @State private var turns: [Turn] = []
    @State private var reply = ""
    @State private var replySymbols = ""
    @State private var replyIssue: String?
    @State private var speech = AVSpeechSynthesizer()
    @State private var lastBandReply: String?

    private static let replyAlphabet = Dictionary(uniqueKeysWithValues: zip(
        (".- -... -.-. -.. . ..-. --. .... .. .--- -.- .-.. -- -. --- " +
         ".--. --.- .-. ... - ..- ...- .-- -..- -.-- --.. " +
         "----- .---- ..--- ...-- ....- ..... -.... --... ---.. ----.").split(separator: " "),
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    ))

    var body: some View {
        NavigationStack {
            List {
                Section("Connect") {
                    Button(connection == nil ? "Connect to Vexo" : "Disconnect") { toggleConnection() }
                    Text(status).foregroundStyle(.secondary)
                        .accessibilityLabel("Connection: \(status)")
                    Text("Keep this app open and your iPhone on the same Wi-Fi as the Mac. If iOS asks for local network access, tap Allow.")
                        .foregroundStyle(.secondary)
                    DisclosureGroup("Connection settings", isExpanded: $showSetup) {
                        TextField("Receiver address", text: $address)
                            .textContentType(.URL)
                            .keyboardType(.URL)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)
                            .disabled(connection != nil)
                        SecureField("Receiver code", text: $code)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)
                            .disabled(connection != nil)
                    }
                }
                Section("Test a band reply") {
                    Text("Once Vexo says Connected and your band is ready, tap the band once. Wait five seconds. Your iPhone should say “E.”")
                    Text("One tap is a dot. A quick double-tap is a dash. Pause about two seconds for the next letter, three seconds for a space, or five seconds to speak your reply.")
                        .foregroundStyle(.secondary)
                    if let lastBandReply {
                        Text("Last band reply: \(lastBandReply)")
                        Button("Speak last band reply again") { speak(lastBandReply) }
                    }
                    Button("Test iPhone speaker") { speak("E") }
                }
                Section("Playback") {
                    if !player.supportsHaptics {
                        Text("Visual preview. Use a supported physical iPhone to feel the pattern.")
                            .foregroundStyle(.secondary)
                    }
                    Button("Test Morse for S") {
                        player.enqueue(MorseMessage(text: "S", steps: [MorseStep(pattern: [1, 1, 1, 1, 1], gap: 0)]), replay: true)
                        player.resume()
                    }
                    Button(player.paused ? "Resume" : "Pause") {
                        if player.paused { player.resume() } else { player.pause() }
                    }
                    Slider(value: $player.dotMilliseconds, in: 60...300, step: 10) {
                        Text("Dot duration")
                    }
                    .accessibilityValue("\(Int(player.dotMilliseconds)) milliseconds")
                    Text("Dot duration: \(Int(player.dotMilliseconds)) ms")
                    if let issue = player.issue { Text(issue).foregroundStyle(.secondary) }
                    if let current = player.currentText {
                        Text("\(player.paused ? "Paused" : "Playing"): \(current)")
                    }
                    Text("\(player.waiting) turns waiting")
                }
                Section("Reply on iPhone") {
                    TextField("Reply text", text: $reply)
                    HStack {
                        Button("Dot") { replySymbols += "." }.disabled(replySymbols.count >= 5)
                        Button("Dash") { replySymbols += "-" }.disabled(replySymbols.count >= 5)
                        Button("Delete pulse") { if !replySymbols.isEmpty { replySymbols.removeLast() } }
                    }
                    .buttonStyle(.borderless)
                    if !replySymbols.isEmpty {
                        Text(replySymbols.map { $0 == "." ? "dot" : "dash" }.joined(separator: " "))
                    }
                    HStack {
                        Button("Add letter") { _ = appendReplyLetter() }
                        Button("Space") {
                            if appendReplyLetter(), !reply.isEmpty, !reply.hasSuffix(" ") {
                                reply += " "
                            }
                        }
                        Button("Clear pulses") {
                            replySymbols = ""
                            replyIssue = nil
                        }
                    }
                    .buttonStyle(.borderless)
                    if let replyIssue { Text(replyIssue).foregroundStyle(.secondary) }
                    Button("Speak reply") {
                        guard appendReplyLetter() else { return }
                        let message = reply.trimmingCharacters(in: .whitespacesAndNewlines)
                        guard !message.isEmpty else { return }
                        player.pause()
                        speak(message, interrupt: true)
                    }
                    .disabled(reply.isEmpty && replySymbols.isEmpty)
                }
                Section("Transcript") {
                    if turns.isEmpty { Text("Band and simulated turns appear here.") }
                    ForEach(turns.reversed().filter { $0.kind != "reply" }) { turn in
                        VStack(alignment: .leading, spacing: 8) {
                            Text(turn.selected.text)
                            if turn.status == "compacted" {
                                Text("\(turn.savedPercent)% shorter playback")
                                    .foregroundStyle(.secondary)
                                Text(turn.original.text)
                                    .foregroundStyle(.secondary)
                                    .accessibilityLabel("Original: " + turn.original.text)
                            } else if turn.status.hasPrefix("openai_") || turn.status == "no_key" {
                                Text("Compaction unavailable. Original retained.")
                                    .foregroundStyle(.secondary)
                            }
                            Button("Replay") { player.enqueue(turn.selected, replay: true) }
                            if turn.status == "compacted" {
                                Button("Replay full message") { player.enqueue(turn.original, replay: true) }
                            }
                        }
                        .buttonStyle(.borderless)
                    }
                }
            }
            .navigationTitle("Vexo")
        }
        .onChange(of: scenePhase) { phase in
            UIApplication.shared.isIdleTimerDisabled = phase == .active && connection != nil
            if phase != .active { player.pause() }
        }
    }

    private func appendReplyLetter() -> Bool {
        replyIssue = nil
        guard !replySymbols.isEmpty else { return true }
        guard let letter = Self.replyAlphabet[replySymbols[...]] else {
            replyIssue = "Unknown Morse letter. Delete a pulse or clear the entry."
            return false
        }
        reply.append(letter)
        replySymbols = ""
        return true
    }

    private func speak(_ text: String, interrupt: Bool = false) {
        if interrupt { speech.stopSpeaking(at: .immediate) }
        try? AVAudioSession.sharedInstance().setCategory(.playback, options: .mixWithOthers)
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        speech.speak(utterance)
    }

    private func toggleConnection() {
        if let running = connection {
            running.cancel()
            connection = nil
            UIApplication.shared.isIdleTimerDisabled = false
            status = "Disconnected"
            return
        }
        do {
            let endpoint = try ReceiverEndpoint(address: address, code: code)
            status = "Connecting…"
            UIApplication.shared.isIdleTimerDisabled = true
            connection = Task {
                while !Task.isCancelled {
                    do {
                        let feed = try await endpoint.fetch(after: after, session: feedID)
                        guard !Task.isCancelled else { return }
                        if feedID.isEmpty {
                            // Start at the current head so a fresh phone does not play old demo turns.
                            after = feed.latest
                            feedID = feed.session
                        } else {
                            if feedID != feed.session {
                                turns.removeAll()
                                after = 0
                                feedID = feed.session
                            }
                            for turn in feed.messages {
                                if turn.kind == "reply" {
                                    lastBandReply = turn.selected.text
                                    speak(turn.selected.text)
                                } else {
                                    turns.append(turn)
                                    player.enqueue(turn.selected)
                                }
                                after = turn.id
                            }
                        }
                        status = feed.missed ? "Some older turns expired." : "Connected"
                    } catch FeedError.wrongCode {
                        guard !Task.isCancelled else { return }
                        status = FeedError.wrongCode.localizedDescription
                        showSetup = true
                        connection = nil
                        UIApplication.shared.isIdleTimerDisabled = false
                        return
                    } catch {
                        guard !Task.isCancelled else { return }
                        status = "Connection interrupted. Retrying…"
                    }
                    try? await Task.sleep(nanoseconds: 450_000_000)
                }
            }
        } catch {
            status = error.localizedDescription
            showSetup = true
        }
    }
}
