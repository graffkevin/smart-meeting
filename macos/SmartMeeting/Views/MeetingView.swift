import SwiftUI

/// A meeting: live recording, questions to the AI and its report; the transcript in the inspector
struct MeetingView: View {
    @Environment(AppModel.self) private var app
    let model: MeetingModel
    @State private var deleting = false

    var body: some View {
        @Bindable var app = app
        Group {
            if let detail = model.detail {
                content(detail)
            } else if let error = model.loadError {
                ContentUnavailableView("Réunion introuvable", systemImage: "exclamationmark.triangle", description: Text(error))
            } else {
                ProgressView()
            }
        }
        .task { await model.reload() }
        .onDisappear { model.close() }
        .inspector(isPresented: $app.showTranscript) {
            TranscriptView(model: model)
                .inspectorColumnWidth(min: 300, ideal: 400, max: 640)
        }
        .toolbar { toolbar }
        .navigationTitle(model.meeting?.title ?? "")
        .navigationSubtitle(model.meeting.map { $0.startedAt.formatted(date: .abbreviated, time: .shortened) } ?? "")
        .confirmationDialog("Supprimer cette réunion ?", isPresented: $deleting) {
            Button("Supprimer", role: .destructive) {
                Task { try? await app.delete(model.id) }
            }
        } message: {
            Text("« \(model.meeting?.title ?? "") », sa transcription et son compte rendu seront définitivement supprimés.")
        }
    }

    @ToolbarContentBuilder
    private var toolbar: some ToolbarContent {
        let status = model.meeting?.status
        if status == .recording {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await model.stop() }
                } label: {
                    Label("Arrêter l'enregistrement", systemImage: "stop.circle.fill")
                }
                .tint(.red)
                .disabled(model.stopping)
                .help("Arrêter l'enregistrement (⌘.)")
            }
        }
        if status == .transcribed || status == .done {
            ToolbarItem {
                if let report = model.report {
                    ShareLink(item: report, subject: Text(model.meeting?.title ?? "")) {
                        Label("Partager le compte rendu", systemImage: "square.and.arrow.up")
                    }
                }
            }
            ToolbarItem {
                Menu {
                    if let report = model.report {
                        Button("Copier le compte rendu", systemImage: "doc.on.doc") { NSPasteboard.copy(report) }
                    }
                    if !model.segments.isEmpty {
                        Button(model.detail?.analysis == nil ? "Générer le compte rendu" : "Régénérer le compte rendu", systemImage: "sparkles") {
                            Task { await model.analyze() }
                        }
                    }
                    if model.detail?.hasAudio == true {
                        Button("Supprimer l'audio", systemImage: "speaker.slash") {
                            Task { await model.deleteAudio() }
                        }
                    }
                    Divider()
                    Button("Supprimer la réunion…", systemImage: "trash", role: .destructive) { deleting = true }
                } label: {
                    Label("Actions", systemImage: "ellipsis.circle")
                }
            }
        }
        ToolbarItem {
            Button {
                app.showTranscript.toggle()
            } label: {
                Label("Transcription", systemImage: "sidebar.right")
            }
            .help("Afficher ou masquer la transcription (⌥⌘T)")
        }
    }

    private func content(_ detail: MeetingDetail) -> some View {
        let meeting = detail.meeting
        let errors = [meeting.error, model.actionError].compactMap { $0 }
        return ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                MeetingHeader(model: model, meeting: meeting)

                if meeting.status == .recording {
                    LivePanel(model: model, startedAt: meeting.startedAt, captured: model.devices ?? detail.captured)
                }
                if meeting.status == .transcribing {
                    if let progress = model.progress {
                        let label = String(localized: "Transcription du fichier · \(Format.duration(progress.done))")
                            + (progress.total.map { " / \(Format.duration($0))" } ?? "")
                        ProgressView(value: progress.total.map { progress.done / max($0, 1) }) { Text(label) }
                    } else {
                        ProgressView { Text("Transcription des dernières phrases…") }
                            .progressViewStyle(.linear)
                    }
                }
                if meeting.status == .analyzing {
                    EstimatedProgress(
                        label: String(localized: "L'IA locale rédige le compte rendu…"),
                        estimate: detail.estimates?.analysisS ?? 30,
                        startedAt: model.loadedAt.addingTimeInterval(-(detail.analysisElapsedS ?? 0))
                    )
                }
                ForEach(errors, id: \.self) { message in
                    Label(message, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                }
                if meeting.status == .transcribed, detail.analysis == nil, !detail.segments.isEmpty {
                    Button("Générer le compte rendu", systemImage: "sparkles") {
                        Task { await model.analyze() }
                    }
                    .buttonStyle(.borderedProminent)
                }

                AskPanel(model: model, detail: detail)

                if let analysis = detail.analysis {
                    ReportView(analysis: analysis)
                }

                if [.transcribed, .done].contains(meeting.status), let storage = detail.storage {
                    StoragePaths(storage: storage)
                }
            }
            .padding(24)
            .frame(maxWidth: 900, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
    }
}

/// Title (renamed in place), tags, language, status and source file of a meeting
struct MeetingHeader: View {
    @Environment(AppModel.self) private var app
    let model: MeetingModel
    let meeting: Meeting
    @State private var title = ""
    @State private var tags: [String] = []
    @FocusState private var editingTitle: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                TextField("Nom de la réunion", text: $title)
                    .textFieldStyle(.plain)
                    .font(.largeTitle.bold())
                    .focused($editingTitle)
                    .onSubmit { Task { await app.rename(meeting.id, to: title) } }
                    .onChange(of: editingTitle) { _, editing in
                        if !editing, title != meeting.title { Task { await app.rename(meeting.id, to: title) } }
                    }
                    .help("Cliquez pour renommer")
                Spacer()
                if let language = meeting.language, language != "auto" {
                    Chip(text: language.uppercased())
                }
                if meeting.status != .recording {
                    StatusBadge(status: meeting.status)
                }
            }
            TagEditor(tags: $tags, suggestions: app.tags.map(\.name))
                .onChange(of: tags) { _, new in
                    if new != (meeting.tags ?? []) { Task { await model.setTags(new) } }
                }
            if let file = meeting.sourceFile {
                Label("Fichier : \(file)", systemImage: "doc")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .onChange(of: meeting, initial: true) { _, meeting in
            if !editingTitle { title = meeting.title }
            tags = meeting.tags ?? []
        }
    }
}

/// Duration, audio levels and captured devices of a meeting being recorded, and its stop button
struct LivePanel: View {
    @Environment(AppModel.self) private var app
    let model: MeetingModel
    let startedAt: Date
    let captured: [String: CapturedDevice]?

    var body: some View {
        GroupBox {
            VStack(spacing: 14) {
                Label("Enregistrement", systemImage: "record.circle.fill")
                    .foregroundStyle(.red)
                    .symbolEffect(.pulse)
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    Text(Format.duration(context.date.timeIntervalSince(startedAt)))
                        .font(.system(size: 44, weight: .semibold, design: .rounded).monospacedDigit())
                }
                if let levels = model.levels {
                    HStack(spacing: 24) {
                        LevelMeter(label: String(localized: "Vous"), db: levels["mic"] ?? -60, color: .accentColor)
                        LevelMeter(label: String(localized: "Participants"), db: levels["remote"] ?? -60, color: .purple)
                    }
                }
                Button {
                    Task { await model.stop() }
                } label: {
                    Label("Arrêter l'enregistrement", systemImage: "stop.fill")
                        .padding(.horizontal, 12)
                }
                .buttonStyle(.borderedProminent)
                .tint(.red)
                .controlSize(.extraLarge)
                .disabled(model.stopping)

                if app.health?.whisper == "loading" {
                    Label("Le modèle de transcription se télécharge (la première fois seulement). Tout ce qui se dit est enregistré et sera transcrit dès qu'il sera prêt : rien n'est perdu.", systemImage: "arrow.down.circle")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
                if model.queue > 0 {
                    Text("\(model.queue) phrase(s) en attente de transcription")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let captured {
                    Text("Micro : \(device(captured["mic"])) · Son : \(device(captured["remote"]))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    if let error = captured["mic"]?.error {
                        Label("Votre micro n'est pas capté : \(error)", systemImage: "mic.slash.fill")
                            .foregroundStyle(.orange)
                    }
                    if let remote = captured["remote"], let error = remote.error {
                        PermissionHelp(error: error, permissionNeeded: remote.permissionNeeded == true)
                    }
                }
            }
            .frame(maxWidth: .infinity)
            .padding(16)
        }
    }

    private func device(_ source: CapturedDevice?) -> String {
        guard let source, let name = source.device else { return String(localized: "par défaut") }
        let devices = app.devices
        let description = app.describe(name, in: (devices?.sources ?? []) + (devices?.sinks ?? [])) ?? name
        return source.auto ? String(localized: "\(description) (auto)") : description
    }
}

/// The sound of the participants is not captured: why, and the way to allow it
struct PermissionHelp: View {
    /// System Settings > Privacy & Security > Screen & System Audio Recording
    private static let permissionSettings =
        URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!

    let error: String
    let permissionNeeded: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Le son des participants n'est pas capté : \(error)", systemImage: "speaker.slash.fill")
            if permissionNeeded {
                Text("Cliquez ci-dessous, activez « Smart Meeting », puis choisissez « Quitter et rouvrir ».")
                    .foregroundStyle(.secondary)
                Button("Ouvrir les réglages", systemImage: "gear") {
                    NSWorkspace.shared.open(Self.permissionSettings)
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.orange.opacity(0.1), in: RoundedRectangle(cornerRadius: 10))
    }
}

/// Audio level of a source, from silence to 0 dBFS
struct LevelMeter: View {
    let label: String
    let db: Double
    let color: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            ProgressView(value: Format.level(db))
                .tint(color)
                .animation(.easeOut(duration: 0.15), value: db)
        }
        .frame(maxWidth: 220)
    }
}

/// Where a finished meeting is kept: the database file, and the folder of its audio when kept
struct StoragePaths: View {
    let storage: MeetingStorage

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            path(String(localized: "Enregistrée dans"), storage.database)
            if let audio = storage.audio {
                path(String(localized: "Audio dans"), audio)
            }
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }

    private func path(_ label: String, _ path: String) -> some View {
        HStack(spacing: 6) {
            Text(label)
            Text(path).font(.caption.monospaced()).textSelection(.enabled).lineLimit(1).truncationMode(.middle)
            Button("Afficher dans le Finder") {
                NSWorkspace.shared.activateFileViewerSelecting([URL(filePath: path)])
            }
            .buttonStyle(.link)
        }
    }
}

/// Questions about the meeting, answered by the local AI from the transcript, during or after it
struct AskPanel: View {
    @Environment(AppModel.self) private var app
    let model: MeetingModel
    let detail: MeetingDetail
    @State private var question = ""

    private static let quickQuestions: [(label: LocalizedStringKey, icon: String, question: String)] = [
        ("Résumer", "list.bullet.rectangle", String(localized: "Fais un résumé de la réunion jusqu'ici.")),
        ("Mes actions", "checklist", String(localized: "Qu'est-ce que je dois faire ?")),
        ("Décisions", "checkmark.seal", String(localized: "Quelles décisions ont été prises ?")),
    ]

    var body: some View {
        let empty = detail.segments.isEmpty
        let unavailable = empty || app.aiState.tone != .ready || model.pendingQuestion != nil
        Panel(title: String(localized: "Interroger la réunion"), systemImage: "bubble.left.and.text.bubble.right") {
            HStack {
                Text(empty
                    ? "Les questions deviendront possibles dès les premières phrases transcrites."
                    : "Posez une question : l'IA locale répond à partir de la transcription, même pendant la réunion.")
                    .foregroundStyle(.secondary)
                Spacer()
                AIStatusView(ai: app.aiState, model: app.health?.ollamaModel)
                    .font(.caption)
            }
            HStack {
                ForEach(Self.quickQuestions, id: \.question) { quick in
                    Button(quick.label, systemImage: quick.icon) {
                        Task { await model.ask(quick.question) }
                    }
                }
            }
            .disabled(unavailable)
            HStack {
                TextField("Votre question", text: $question, prompt: Text("Ex. : Qu’a-t-on décidé pour l’hébergement ?"))
                    .textFieldStyle(.roundedBorder)
                    .onSubmit(submit)
                    .disabled(empty)
                if !app.recentQuestions.isEmpty {
                    Menu {
                        ForEach(app.recentQuestions, id: \.self) { recent in
                            Button(recent) { question = recent }
                        }
                    } label: {
                        Image(systemName: "clock.arrow.circlepath")
                    }
                    .menuStyle(.borderlessButton)
                    .menuIndicator(.hidden)
                    .fixedSize()
                    .help("Questions récentes")
                    .disabled(empty)
                }
                Button("Demander", systemImage: "paperplane.fill", action: submit)
                    .disabled(unavailable || question.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            ForEach(Array((detail.questions ?? []).enumerated()), id: \.offset) { _, answer in
                VStack(alignment: .leading, spacing: 6) {
                    Text(answer.question).font(.subheadline.bold())
                    AIText(text: answer.answer)
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
            }
            if let pending = model.pendingQuestion {
                VStack(alignment: .leading, spacing: 6) {
                    Text(pending.question).font(.subheadline.bold())
                    EstimatedProgress(
                        label: String(localized: "L'IA locale réfléchit…"),
                        estimate: detail.estimates?.askS ?? 30,
                        startedAt: pending.startedAt
                    )
                }
                .padding(12)
                .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
            }
            if let error = model.askError {
                Label("Pas de réponse : \(error)", systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
            }
        }
    }

    private func submit() {
        let text = question
        question = ""
        Task { await model.ask(text) }
    }
}
