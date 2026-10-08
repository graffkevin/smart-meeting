import SwiftUI
import UniformTypeIdentifiers

/// Home: server status, recording, and file import
struct HomeView: View {
    @Environment(AppModel.self) private var app

    var body: some View {
        ScrollView {
            VStack(spacing: 20) {
                HealthStatusView()
                if let id = app.activeMeetingId {
                    InProgressPanel(meetingId: id)
                } else {
                    RecordForm()
                }
                ImportPanel()
            }
            .padding(24)
            .frame(maxWidth: 720)
            .frame(maxWidth: .infinity)
        }
        .navigationTitle("Smart Meeting")
    }
}

/// First-run installs with their progress, models, problems
struct HealthStatusView: View {
    @Environment(AppModel.self) private var app

    var body: some View {
        if app.unreachable {
            banner("Smart Meeting ne répond pas", detail: String(localized: "Relancez l'application."), systemImage: "exclamationmark.octagon.fill", color: .red)
        } else if let health = app.health {
            let setup = health.setup ?? []
            VStack(spacing: 12) {
                if health.whisper == "loading" {
                    banner("Préparation de la transcription", detail: String(localized: "Chargement du modèle (1,6 Go à télécharger au premier lancement)…"), systemImage: "waveform", color: .blue)
                }
                if health.whisper == "error" {
                    banner("La transcription ne fonctionne pas", detail: health.whisperDetail ?? "", systemImage: "exclamationmark.triangle.fill", color: .red)
                }
                if !setup.isEmpty {
                    GroupBox {
                        VStack(alignment: .leading, spacing: 10) {
                            ForEach(setup, id: \.label) { step in
                                if let error = step.error {
                                    Text("\(step.label) : échec. \(error)").foregroundStyle(.red)
                                } else if let progress = step.progress {
                                    ProgressView(value: progress) {
                                        Text("\(step.label) : \(Int(progress * 100)) %")
                                    }
                                } else {
                                    ProgressView { Text("\(step.label)…") }
                                        .progressViewStyle(.linear)
                                }
                            }
                            Text("Comptez 10 à 30 minutes selon votre connexion (environ 6 Go). Vous pouvez déjà enregistrer : le compte rendu sera disponible à la fin.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(6)
                    } label: {
                        Label("Premier lancement : installation de l'IA locale", systemImage: "arrow.down.circle")
                            .font(.headline)
                    }
                } else if !health.ollama {
                    banner("L'IA locale ne répond pas", detail: String(localized: "Le compte rendu automatique est indisponible."), systemImage: "exclamationmark.triangle.fill", color: .orange)
                } else if !health.ollamaModelAvailable {
                    banner("Le modèle d'IA \(health.ollamaModel) est absent.", detail: "", systemImage: "exclamationmark.triangle.fill", color: .orange)
                }
            }
        }
    }

    private func banner(_ title: LocalizedStringKey, detail: String, systemImage: String, color: Color) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: systemImage)
                .foregroundStyle(color)
                .font(.title3)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                if !detail.isEmpty {
                    Text(detail).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(color.opacity(0.1), in: RoundedRectangle(cornerRadius: 10))
    }
}

/// A meeting is being recorded: join it
struct InProgressPanel: View {
    @Environment(AppModel.self) private var app
    let meetingId: Int

    var body: some View {
        GroupBox {
            VStack(spacing: 14) {
                Label("Enregistrement", systemImage: "record.circle.fill")
                    .foregroundStyle(.red)
                    .symbolEffect(.pulse)
                Text("Une réunion est en cours").font(.title2.bold())
                Button("Reprendre la réunion", systemImage: "mic.fill") { app.open(meetingId) }
                    .controlSize(.large)
                    .keyboardShortcut(.defaultAction)
            }
            .frame(maxWidth: .infinity)
            .padding(20)
        }
    }
}

/// The main call to action: name the meeting, check its language, start recording
struct RecordForm: View {
    @Environment(AppModel.self) private var app
    @Environment(\.openSettings) private var openSettings
    @State private var title = ""
    @State private var tags: [String] = []
    @State private var language: TranscriptionLanguage?
    @State private var starting = false
    @State private var error: String?

    var body: some View {
        GroupBox {
            VStack(spacing: 18) {
                VStack(spacing: 6) {
                    Text("Prêt pour votre prochaine réunion ?")
                        .font(.largeTitle.bold())
                        .multilineTextAlignment(.center)
                    Text("Smart Meeting transcrit votre réunion en direct. Demandez-lui ce que vous voulez, pendant ou après : un résumé, vos actions, qui a dit quoi… et récupérez le compte rendu. Tout reste sur votre ordinateur.")
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.secondary)
                }

                Form {
                    TextField("Nom de la réunion", text: $title, prompt: Text("Ex. : Ma super réunion"))
                    LabeledContent("Tags") {
                        TagEditor(tags: $tags, suggestions: app.tags.map(\.name))
                    }
                    Picker("Langue parlée", selection: languageBinding) {
                        ForEach(TranscriptionLanguage.allCases) { Text($0.label).tag($0) }
                    }
                }
                .formStyle(.columns)

                Button {
                    Task { await start() }
                } label: {
                    Label(starting ? "Démarrage…" : "Démarrer l'enregistrement", systemImage: "record.circle")
                        .padding(.horizontal, 12)
                }
                .buttonStyle(.borderedProminent)
                .tint(.red)
                .controlSize(.extraLarge)
                .keyboardShortcut(.defaultAction)
                .disabled(starting || app.preferences == nil)

                HStack(spacing: 6) {
                    Text("Micro : \(micDescription) · Son des participants : \(outputDescription)")
                    Button("Modifier") { openSettings() }
                        .buttonStyle(.link)
                }
                .font(.caption)
                .foregroundStyle(.secondary)

                VStack(spacing: 6) {
                    Text("Lancez ensuite votre visio (Teams, Meet, Zoom…) : Smart Meeting s’adapte.")
                    Text("Rien de ce qui se dit n'est perdu : le son est enregistré sur votre ordinateur pendant la réunion, au cas où. Si la transcription décroche, elle reprend toute seule et rattrape ce qui manque, puis ce son est effacé (sauf si vous choisissez de le garder).")
                }
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

                if let error {
                    Label("Impossible de démarrer : \(error)", systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(20)
        }
    }

    /// The language of the settings until another is picked
    private var languageBinding: Binding<TranscriptionLanguage> {
        Binding(
            get: { language ?? TranscriptionLanguage(rawValue: app.preferences?.language ?? "auto") ?? .auto },
            set: { language = $0 }
        )
    }

    private var micDescription: String {
        let devices = app.devices
        return app.describe(app.preferences?.micDevice ?? devices?.inUseSource, in: devices?.sources ?? [])
            ?? String(localized: "aucun")
    }

    private var outputDescription: String {
        let devices = app.devices
        // macOS captures everything the Mac plays, whatever the output (AirPods, speakers…)
        if (devices?.sinks.count ?? 0) <= 1 { return String(localized: "tout le son du Mac") }
        return app.describe(app.preferences?.outputDevice ?? devices?.inUseSink, in: devices?.sinks ?? [])
            ?? String(localized: "aucun")
    }

    private func start() async {
        starting = true
        defer { starting = false }
        do {
            try await app.startMeeting(title: title, tags: tags, language: languageBinding.wrappedValue)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// Transcribes a video or audio file: a replay, a webinar, a voice note
struct ImportPanel: View {
    @Environment(AppModel.self) private var app
    @State private var choosing = false
    @State private var title = ""
    @State private var language: TranscriptionLanguage = .auto
    @State private var sending = false
    @State private var error: String?

    var body: some View {
        let busy = app.activeMeetingId != nil
        GroupBox {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Vous avez déjà un enregistrement ?").font(.headline)
                        Text("Replay de visio, webinaire, note vocale… Importez la vidéo ou le fichier audio, ou déposez-le sur la fenêtre : la transcription va plus vite que la lecture.")
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer()
                    Button(app.fileToImport == nil ? "Choisir un fichier" : "Choisir un autre fichier", systemImage: "square.and.arrow.down") {
                        choosing = true
                    }
                    .disabled(busy)
                }
                if let file = app.fileToImport {
                    HStack(alignment: .firstTextBaseline) {
                        TextField("Nom", text: $title)
                        Picker("Langue parlée", selection: $language) {
                            ForEach(TranscriptionLanguage.allCases) { Text($0.label).tag($0) }
                        }
                        .fixedSize()
                        Button {
                            Task { await send(file) }
                        } label: {
                            Label(sending ? "Envoi…" : "Transcrire « \(file.lastPathComponent) »", systemImage: "sparkles")
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(busy || sending)
                    }
                }
                if busy {
                    Text("Disponible une fois la réunion en cours terminée.").font(.caption).foregroundStyle(.secondary)
                }
                if let error {
                    Label("Import impossible : \(error)", systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red)
                }
            }
            .padding(6)
        }
        .fileImporter(isPresented: $choosing, allowedContentTypes: [.audiovisualContent]) { result in
            if case let .success(url) = result { app.fileToImport = url }
        }
        .onChange(of: app.fileToImport, initial: true) { _, file in
            if let file { title = file.deletingPathExtension().lastPathComponent }
        }
    }

    private func send(_ file: URL) async {
        sending = true
        defer { sending = false }
        do {
            try await app.importFile(file, title: title, language: language)
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}
