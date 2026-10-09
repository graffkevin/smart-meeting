import AppKit
import Foundation
import Observation
import UserNotifications

/// What the main window shows: the home page (start or import a meeting) or a meeting
enum Screen: Hashable {
    case home
    case meeting(Int)
}

/// How the history lists the meetings
enum HistoryView: String, CaseIterable, Identifiable {
    case byDate, byTag

    var id: String { rawValue }
    var label: String {
        switch self {
        case .byDate: String(localized: "Par date")
        case .byTag: String(localized: "Par tag")
        }
    }
}

/// State of the local AI, from the polled server status: green, orange or red with an explanation
struct AIState {
    enum Tone { case ready, warning, down }

    var tone: Tone
    var hint: String
}

/// State of the whole app: the server, its status, the history, the settings, the open meetings
@MainActor
@Observable
final class AppModel {
    let server = ServerProcess()
    var api: APIClient { APIClient(baseURL: server.baseURL) }

    /// The server could not be started (no bundled server, none running)
    private(set) var serverMissing = false
    private(set) var health: Health?
    /// The server stopped answering after having answered
    private(set) var unreachable = false

    var screen: Screen = .home
    var search = "" {
        didSet { scheduleSearch() }
    }
    var historyView: HistoryView = .byDate
    private(set) var meetings: [Meeting] = []
    private(set) var historyError: String?
    private(set) var tags: [TagCount] = []
    private(set) var preferences: Preferences?
    private(set) var devices: AudioDevices?
    private(set) var recentQuestions: [String] = []
    /// Latest version published, when newer than this app (a new disk image to download)
    private(set) var newVersion: UpdateInfo?

    /// File chosen to import (menu File > Import, drop on the window), shown on the home page
    var fileToImport: URL?
    var showTranscript = true

    private var models: [Int: MeetingModel] = [:]
    private var searchTask: Task<Void, Never>?
    private var started = false

    var activeMeetingId: Int? { health?.activeMeetingId }

    // MARK: Lifecycle

    func start() async {
        guard !started else { return }
        started = true
        _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])
        serverMissing = !(await server.start())
        if serverMissing { return }
        Task { await pollHealth() }
        Task { await pollUpdate() }
    }

    /// The server reads the latest release every few hours; compared with the version of this app
    /// (its bundled server does not know its own)
    private func pollUpdate() async {
        try? await Task.sleep(for: .seconds(30))  // the start of the app comes first
        while !Task.isCancelled {
            if let update = try? await api.update(), let latest = update.latest,
               let current = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String,
               latest.compare(current, options: .numeric) == .orderedDescending {
                newVersion = update
            }
            try? await Task.sleep(for: .seconds(30 * 60))
        }
    }

    func dismissNewVersion() {
        newVersion = nil
    }

    /// Server status every 2 s (installs, models, active meeting); everything else is loaded once it
    /// answers, and again when it comes back
    private func pollHealth() async {
        var reloadNeeded = true
        while !Task.isCancelled {
            do {
                let previousActive = health?.activeMeetingId
                health = try await api.health()
                unreachable = false
                if reloadNeeded {
                    reloadNeeded = false
                    await reloadAll()
                    openRequestedScreen()
                } else if previousActive != health?.activeMeetingId {
                    await reloadHistory()
                }
            } catch {
                // Starting: the first answer can take a few seconds, it is not a failure yet
                unreachable = health != nil
                reloadNeeded = true
            }
            try? await Task.sleep(for: .seconds(2))
        }
    }

    /// Screen asked at launch, for the App Store screenshots: SM_SCREEN=meeting:<id>
    private func openRequestedScreen() {
        let requested = ProcessInfo.processInfo.environment["SM_SCREEN"] ?? ""
        if requested.hasPrefix("meeting:"), let id = Int(requested.dropFirst("meeting:".count)) {
            open(id)
        }
    }

    func reloadAll() async {
        async let history: Void = reloadHistory()
        async let settings: Void = reloadSettings()
        _ = await (history, settings)
    }

    func reloadHistory() async {
        do {
            meetings = try await api.meetings(search: search)
            historyError = nil
        } catch {
            historyError = error.localizedDescription
        }
        tags = (try? await api.tags()) ?? tags
    }

    func reloadSettings() async {
        preferences = (try? await api.preferences()) ?? preferences
        devices = (try? await api.audioDevices()) ?? devices
        recentQuestions = (try? await api.recentQuestions()) ?? recentQuestions
    }

    func reloadRecentQuestions() async {
        recentQuestions = (try? await api.recentQuestions()) ?? recentQuestions
    }

    private func scheduleSearch() {
        searchTask?.cancel()
        searchTask = Task {
            try? await Task.sleep(for: .milliseconds(250))
            guard !Task.isCancelled else { return }
            await reloadHistory()
        }
    }

    // MARK: AI status

    var aiState: AIState {
        guard let health, !unreachable else {
            return AIState(tone: .down, hint: String(localized: "Smart Meeting ne répond pas"))
        }
        let model = health.ollamaModel
        if !health.ollama {
            return installing
                ? AIState(tone: .warning, hint: String(localized: "Installation de l'IA locale en cours"))
                : AIState(tone: .down, hint: String(localized: "L'IA locale ne répond pas : relancement automatique en cours"))
        }
        return health.ollamaModelAvailable
            ? AIState(tone: .ready, hint: String(localized: "IA locale prête : \(model)"))
            : AIState(tone: .warning, hint: String(localized: "L'IA locale répond, mais le modèle \(model) est absent"))
    }

    var installing: Bool {
        (health?.setup ?? []).contains { !$0.done && $0.error == nil }
    }

    /// The local AI can be restarted: it is not green and not being installed
    var aiRestartable: Bool { health != nil && !unreachable && aiState.tone != .ready && !installing }

    func restartAI() async {
        try? await api.restartAI()
    }

    // MARK: Meetings

    func model(for id: Int) -> MeetingModel {
        if let model = models[id] { return model }
        let model = MeetingModel(id: id, app: self)
        models[id] = model
        return model
    }

    func open(_ id: Int) {
        screen = .meeting(id)
    }

    func startMeeting(title: String, tags: [String], language: TranscriptionLanguage) async throws {
        let preferences = preferences ?? Preferences()
        let meeting = try await api.startMeeting(StartMeetingRequest(
            title: title,
            micDevice: preferences.micDevice,
            remoteDevice: preferences.outputDevice,
            keepAudio: preferences.keepAudio ?? false,
            language: language.rawValue,
            tags: tags,
            room: preferences.room ?? false
        ))
        health = (try? await api.health()) ?? health
        await reloadHistory()
        open(meeting.id)
    }

    func importFile(_ file: URL, title: String, language: TranscriptionLanguage) async throws {
        let meeting = try await api.importFile(file, title: title, language: language.rawValue)
        fileToImport = nil
        await reloadHistory()
        open(meeting.id)
    }

    func stopActiveMeeting() async {
        guard let id = activeMeetingId else { return }
        await model(for: id).stop()
    }

    func rename(_ id: Int, to title: String) async {
        let title = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty else { return }
        _ = try? await api.rename(id, title: title)
        await reloadHistory()
        await models[id]?.reload()
    }

    func delete(_ id: Int) async throws {
        try await api.deleteMeeting(id)
        if screen == .meeting(id) { screen = .home }
        models[id]?.close()
        models[id] = nil
        await reloadHistory()
    }

    func savePreferences(_ preferences: Preferences) async {
        self.preferences = preferences
        self.preferences = (try? await api.savePreferences(preferences)) ?? preferences
    }

    /// Notification when a minutes report is ready while the app is in the background
    func notifyReportReady(_ meeting: Meeting) {
        guard !NSApp.isActive else { return }
        let content = UNMutableNotificationContent()
        content.title = String(localized: "Compte rendu prêt")
        content.body = meeting.title
        content.sound = .default
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: "report-\(meeting.id)", content: content, trigger: nil))
    }

    /// Description of a device by its name, or the name itself
    func describe(_ name: String?, in list: [AudioDevice]) -> String? {
        guard let name else { return nil }
        return list.first { $0.name == name }?.description ?? name
    }
}
