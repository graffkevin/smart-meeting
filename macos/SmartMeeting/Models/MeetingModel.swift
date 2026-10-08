import AppKit
import Foundation
import Observation

/// Provisional text of the sentence being spoken: shown live, replaced by its final transcription
struct PartialText: Hashable {
    var source: AudioSource
    var speaker: String
    var startS: Double
    var text: String
}

/// A question being answered by the local AI
struct PendingQuestion {
    var question: String
    var startedAt: Date
}

/// A meeting on screen: its stored state (reloaded from the server) and its live state (audio
/// levels, capture devices, import progress, sentences being spoken) from its WebSocket
@MainActor
@Observable
final class MeetingModel {
    /// A final sentence replaces a provisional text that started at most this much later (seconds)
    private static let partialTolerance = 0.5

    let id: Int
    private unowned let app: AppModel

    private(set) var detail: MeetingDetail?
    private(set) var loadError: String?
    /// Markdown report, once the meeting is finished
    private(set) var report: String?
    private(set) var loadedAt = Date.now

    // Live state, not stored
    private(set) var levels: [String: Double]?
    private(set) var queue = 0
    private(set) var devices: [String: CapturedDevice]?
    private(set) var progress: (done: Double, total: Double?)?
    private(set) var partials: [AudioSource: PartialText] = [:]

    private(set) var stopping = false
    private(set) var pendingQuestion: PendingQuestion?
    private(set) var askError: String?
    /// Last failed action (stop, analysis…)
    var actionError: String?

    private var socket: URLSessionWebSocketTask?
    private var loading = false

    init(id: Int, app: AppModel) {
        self.id = id
        self.app = app
    }

    var meeting: Meeting? { detail?.meeting }
    var segments: [Segment] { detail?.segments ?? [] }

    // MARK: Loading and live events

    func reload() async {
        guard !loading else { return }
        loading = true
        defer { loading = false }
        let previous = detail?.meeting.status
        do {
            let detail = try await app.api.meeting(id)
            self.detail = detail
            loadedAt = .now
            loadError = nil
            let status = detail.meeting.status
            if status.isLive {
                connect()
            } else {
                disconnect()
                partials = [:]
                report = try? await app.api.report(id)
            }
            if previous == .analyzing, status == .done { app.notifyReportReady(detail.meeting) }
        } catch {
            loadError = error.localizedDescription
        }
    }

    private func connect() {
        guard socket == nil else { return }
        let task = URLSession.shared.webSocketTask(with: app.api.eventsURL(id))
        socket = task
        task.resume()
        Task { await receive(from: task) }
        // Connected: reload once, for the segments transcribed before the connection
        Task { await reload() }
    }

    private func receive(from task: URLSessionWebSocketTask) async {
        while socket === task {
            guard let message = try? await task.receive() else {
                // Closed (server restarted…): connect again while the meeting is live
                if socket === task {
                    socket = nil
                    try? await Task.sleep(for: .seconds(2))
                    await reload()
                }
                return
            }
            let data: Data? = switch message {
            case let .string(text): Data(text.utf8)
            case let .data(data): data
            @unknown default: nil
            }
            if let data, let event = try? APIClient.decode(MeetingEvent.self, from: data) {
                await handle(event)
            }
        }
    }

    private func handle(_ event: MeetingEvent) async {
        switch event.type {
        case "segment":
            guard let segment = event.segment else { return }
            if var detail, !detail.segments.contains(where: { $0.id != nil && $0.id == segment.id }) {
                detail.segments.append(segment)
                detail.segments.sort { $0.startS < $1.startS }
                self.detail = detail
            }
            if let partial = partials[segment.source], segment.startS >= partial.startS - Self.partialTolerance {
                partials[segment.source] = nil
            }
        case "partial":
            guard let source = event.source, let speaker = event.speaker, let start = event.startS, let text = event.text else { return }
            partials[source] = PartialText(source: source, speaker: speaker, startS: start, text: text)
        case "levels":
            levels = event.levels
            queue = event.queue ?? 0
        case "devices":
            devices = event.devices
        case "progress":
            if let done = event.doneS { progress = (done, event.totalS) }
        case "status":
            await reload()
            await app.reloadHistory()
        case "speakers":
            await reload()
        default:
            break
        }
    }

    private func disconnect() {
        socket?.cancel(with: .goingAway, reason: nil)
        socket = nil
    }

    func close() {
        disconnect()
    }

    // MARK: Actions

    func stop() async {
        stopping = true
        defer { stopping = false }
        do {
            _ = try await app.api.stopMeeting(id)
        } catch {
            actionError = error.localizedDescription
        }
        await reload()
        await app.reloadHistory()
    }

    func analyze() async {
        do {
            try await app.api.analyze(id)
        } catch {
            actionError = error.localizedDescription
        }
        await reload()
    }

    func ask(_ question: String) async {
        let question = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !question.isEmpty, pendingQuestion == nil else { return }
        pendingQuestion = PendingQuestion(question: question, startedAt: .now)
        askError = nil
        defer { pendingQuestion = nil }
        do {
            _ = try await app.api.ask(id, question: question)
            await reload()
            await app.reloadRecentQuestions()
        } catch {
            askError = error.localizedDescription
        }
    }

    func setTags(_ tags: [String]) async {
        _ = try? await app.api.setTags(id, tags: tags)
        await reload()
        await app.reloadHistory()
    }

    func renameSpeaker(_ old: String, to new: String) async {
        let new = new.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !new.isEmpty, new != old else { return }
        try? await app.api.renameSpeaker(id, old: old, new: new)
        await reload()
    }

    func deleteAudio() async {
        try? await app.api.deleteAudio(id)
        await reload()
    }

    // MARK: Texts

    /// Time of a sentence: wall-clock time of a live meeting, position in an imported file
    func time(_ offset: Double) -> String {
        guard let meeting else { return "" }
        if meeting.sourceFile != nil { return Format.duration(offset) }
        return meeting.startedAt.addingTimeInterval(offset).formatted(date: .omitted, time: .standard)
    }

    /// Whole transcript as text, one `[time] Speaker : text` line per sentence
    var transcriptText: String {
        segments.map { "[\(time($0.startS))] \($0.speaker ?? "") : \($0.text)" }.joined(separator: "\n")
    }
}

/// Text formats of the meetings
enum Format {
    /// `hh:mm:ss` of a duration in seconds (negative values count as 0)
    static func duration(_ total: Double) -> String {
        let seconds = max(0, Int(total))
        return String(format: "%02d:%02d:%02d", seconds / 3600, seconds % 3600 / 60, seconds % 60)
    }

    /// Audio level in dBFS as 0…1, from -60 dBFS (silence) to 0 dBFS
    static func level(_ db: Double) -> Double {
        min(1, max(0, (db + 60) / 60))
    }
}
