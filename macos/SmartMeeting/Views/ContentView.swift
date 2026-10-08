import SwiftUI

/// Main window: the history in the sidebar, the home page or a meeting on the right
struct ContentView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        @Bindable var app = app
        NavigationSplitView {
            SidebarView()
                .navigationSplitViewColumnWidth(min: 240, ideal: 290, max: 400)
        } detail: {
            if app.serverMissing {
                ContentUnavailableView {
                    Label("Smart Meeting ne répond pas", systemImage: "exclamationmark.triangle")
                } description: {
                    Text("Le serveur n'est pas inclus dans cette version de développement. Lancez-le depuis le dossier du projet : ./smart-meeting --no-window")
                }
            } else if app.health == nil {
                ProgressView("Démarrage de Smart Meeting…")
            } else {
                switch app.screen {
                case .home:
                    HomeView()
                case let .meeting(id):
                    MeetingView(model: app.model(for: id))
                        .id(id)
                }
            }
        }
        // App Store screenshots: SM_SCREEN=settings opens the settings at launch
        .task {
            if ProcessInfo.processInfo.environment["SM_SCREEN"] == "settings" { openSettings() }
        }
        // A file dropped on the window is offered for import
        .dropDestination(for: URL.self) { urls, _ in
            guard let url = urls.first else { return false }
            app.fileToImport = url
            app.screen = .home
            return true
        }
    }
}

/// History of the meetings: by day or by tag, searchable in titles, tags, summaries and transcripts
struct SidebarView: View {
    @Environment(AppModel.self) private var app
    @State private var toDelete: Meeting?
    @State private var toRename: Meeting?
    @State private var newTitle = ""

    var body: some View {
        @Bindable var app = app
        let selection = Binding<Screen?>(get: { app.screen }, set: { if let screen = $0 { app.screen = screen } })
        List(selection: selection) {
            Label("Nouvelle réunion", systemImage: "plus.circle")
                .tag(Screen.home)

            switch app.historyView {
            case .byDate:
                ForEach(History.byDate(app.meetings), id: \.day) { group in
                    Section(History.label(of: group.day)) {
                        ForEach(group.meetings) { row($0) }
                    }
                }
            case .byTag:
                ForEach(History.byTag(app.meetings), id: \.tag) { group in
                    Section("\(group.tag) (\(group.meetings.count))") {
                        ForEach(group.meetings) { row($0) }
                    }
                }
            }
        }
        .overlay {
            if let error = app.historyError {
                ContentUnavailableView("Historique indisponible", systemImage: "exclamationmark.triangle", description: Text(error))
            } else if app.meetings.isEmpty, app.health != nil {
                if app.search.isEmpty {
                    ContentUnavailableView("Aucune réunion", systemImage: "waveform",
                                           description: Text("Vos réunions apparaîtront ici après votre premier enregistrement."))
                } else {
                    ContentUnavailableView.search(text: app.search)
                }
            }
        }
        .searchable(text: $app.search, placement: .sidebar, prompt: Text("Un mot, un nom, un sujet…"))
        .safeAreaInset(edge: .bottom) { SidebarFooter() }
        .toolbar {
            ToolbarItem {
                SettingsLink {
                    Label("Réglages", systemImage: "gearshape")
                }
                .help("Réglages (⌘,)")
            }
            ToolbarItem {
                Picker("Affichage", selection: $app.historyView) {
                    ForEach(HistoryView.allCases) { Text($0.label).tag($0) }
                }
                .pickerStyle(.menu)
                .help("Grouper les réunions par date ou par tag")
            }
        }
        .confirmationDialog(
            "Supprimer cette réunion ?",
            isPresented: Binding(get: { toDelete != nil }, set: { if !$0 { toDelete = nil } }),
            presenting: toDelete
        ) { meeting in
            Button("Supprimer", role: .destructive) {
                Task { try? await app.delete(meeting.id) }
            }
        } message: { meeting in
            Text("« \(meeting.title) », sa transcription et son compte rendu seront définitivement supprimés.")
        }
        .alert(
            "Renommer la réunion",
            isPresented: Binding(get: { toRename != nil }, set: { if !$0 { toRename = nil } }),
            presenting: toRename
        ) { meeting in
            TextField("Nom de la réunion", text: $newTitle)
            Button("Renommer") { Task { await app.rename(meeting.id, to: newTitle) } }
            Button("Annuler", role: .cancel) {}
        }
    }

    private func row(_ meeting: Meeting) -> some View {
        MeetingRow(meeting: meeting, recording: meeting.id == app.activeMeetingId)
            .tag(Screen.meeting(meeting.id))
            .contextMenu {
                Button("Renommer…") {
                    newTitle = meeting.title
                    toRename = meeting
                }
                Divider()
                Button("Supprimer…", role: .destructive) { toDelete = meeting }
                    .disabled(meeting.status == .recording)
            }
    }
}

/// A meeting of the history: title, time and duration, status, number of actions
struct MeetingRow: View {
    let meeting: Meeting
    let recording: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 6) {
                if recording {
                    Image(systemName: "record.circle.fill")
                        .foregroundStyle(.red)
                        .symbolEffect(.pulse)
                }
                Text(meeting.title).lineLimit(1)
            }
            HStack(spacing: 4) {
                Text(meeting.startedAt, style: .time)
                if let end = meeting.endedAt {
                    Text("· \(Format.duration(end.timeIntervalSince(meeting.startedAt)))")
                }
                if !recording, meeting.status != .done {
                    Text("· \(meeting.status.label)")
                }
                if let count = meeting.actionCount, count > 0 {
                    Text(count == 1 ? "· 1 action" : "· \(count) actions")
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            .lineLimit(1)
        }
        .padding(.vertical, 2)
    }
}

/// Bottom of the sidebar: everything stays on this computer; state of the local AI
struct SidebarFooter: View {
    @Environment(AppModel.self) private var app

    var body: some View {
        let ai = app.aiState
        HStack(spacing: 8) {
            Label("100 % local", systemImage: "lock.shield.fill")
                .foregroundStyle(.green)
                .help("Aucune donnée n'est envoyée ailleurs : le son, la transcription, vos questions et les réponses de l'IA restent sur votre ordinateur.")
            Spacer()
            AIStatusView(ai: ai, model: app.health?.ollamaModel)
            if app.aiRestartable {
                Button {
                    Task { await app.restartAI() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.borderless)
                .help("Redémarrer l'IA locale")
            }
        }
        .font(.caption)
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }
}

/// Groups of the history
enum History {
    struct DateGroup {
        var day: Date
        var meetings: [Meeting]
    }

    struct TagGroup {
        var tag: String
        var meetings: [Meeting]
    }

    /// Groups of meetings by day, in the order of the list (newest first)
    static func byDate(_ meetings: [Meeting]) -> [DateGroup] {
        var groups: [DateGroup] = []
        for meeting in meetings {
            let day = Calendar.current.startOfDay(for: meeting.startedAt)
            if let index = groups.firstIndex(where: { $0.day == day }) {
                groups[index].meetings.append(meeting)
            } else {
                groups.append(DateGroup(day: day, meetings: [meeting]))
            }
        }
        return groups
    }

    /// Groups of meetings by tag, alphabetically, meetings without tag last
    static func byTag(_ meetings: [Meeting]) -> [TagGroup] {
        let tags = Set(meetings.flatMap { $0.tags ?? [] }).sorted { $0.localizedCompare($1) == .orderedAscending }
        var groups = tags.map { tag in TagGroup(tag: tag, meetings: meetings.filter { $0.tags?.contains(tag) == true }) }
        let untagged = meetings.filter { ($0.tags ?? []).isEmpty }
        if !untagged.isEmpty { groups.append(TagGroup(tag: String(localized: "Sans tag"), meetings: untagged)) }
        return groups
    }

    /// "Aujourd'hui", "Hier", or the day ("Lundi 5 octobre", with its year when not this year)
    static func label(of day: Date) -> String {
        let calendar = Calendar.current
        if calendar.isDateInToday(day) { return String(localized: "Aujourd’hui") }
        if calendar.isDateInYesterday(day) { return String(localized: "Hier") }
        let sameYear = calendar.component(.year, from: day) == calendar.component(.year, from: .now)
        let text = day.formatted(sameYear
            ? .dateTime.weekday(.wide).day().month(.wide)
            : .dateTime.weekday(.wide).day().month(.wide).year())
        return text.prefix(1).uppercased() + text.dropFirst()
    }
}
