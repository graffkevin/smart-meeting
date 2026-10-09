import SwiftUI

/// Settings window (⌘,): applied at once, for the next sentences and the next meetings
struct SettingsView: View {
    @Environment(AppModel.self) private var app
    @State private var draft = Preferences()
    @State private var loaded = false
    @State private var saveTask: Task<Void, Never>?

    var body: some View {
        Form {
            Section {
                TextField("Votre nom", text: bind(\.userName, ""))
                Text("Vos phrases sont signées de ce nom, et l'IA sait que « je », c'est vous.")
                    .font(.caption).foregroundStyle(.secondary)
                LabeledContent("Vocabulaire") {
                    TagEditor(tags: bind(\.glossary, []))
                }
                Text("Noms, sigles et termes techniques à bien reconnaître (Entrée après chaque mot).")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section {
                Picker("Langue parlée par défaut", selection: bind(\.language, "auto")) {
                    ForEach(TranscriptionLanguage.allCases) { Text($0.label).tag($0.rawValue) }
                }
                Text("En automatique, la langue du début est gardée : quelques mots d'anglais ne la changent pas, un long passage dans une autre langue, si.")
                    .font(.caption).foregroundStyle(.secondary)
                Picker("Langue des réponses et des comptes rendus", selection: bind(\.uiLanguage, "fr")) {
                    Text("Français").tag("fr")
                    Text("Anglais").tag("en")
                }
            }
            Section("IA") {
                Picker("Modèle d'IA", selection: bind(\.aiMode, "fast")) {
                    Text("Rapide (par défaut)").tag("fast")
                    Text("Précis, plus lent").tag("precise")
                }
                Text("Pour les questions et le compte rendu. Le modèle précis est plus long ; il est téléchargé la première fois.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Audio") {
                devicePicker(String(localized: "Micro"), help: String(localized: "Ce que vous dites."), selection: \.micDevice,
                             devices: app.devices?.sources ?? [], inUse: app.devices?.inUseSource)
                if (app.devices?.sinks.count ?? 0) > 1 {
                    devicePicker(String(localized: "Casque"), help: String(localized: "Ce que vous entendez : la voix des autres participants."), selection: \.outputDevice,
                                 devices: app.devices?.sinks ?? [], inUse: app.devices?.inUseSink)
                } else {
                    LabeledContent {
                        Text("Tout le son du Mac")
                    } label: {
                        Text("Son des participants")
                        Text("Ce que le Mac joue est capté, quelle que soit la sortie : AirPods, casque, haut-parleurs…")
                    }
                }
                Toggle(isOn: bind(\.room, false)) {
                    Text("Réunion en salle")
                    Text("Plusieurs personnes parlent dans mon micro : elles sont distinguées par leur voix, comme les participants à distance, au lieu d'être toutes « moi ».")
                }
                Toggle(isOn: bind(\.keepAudio, false)) {
                    Text("Garder l'enregistrement audio")
                    Text("Sinon, le son n'est gardé que pendant la réunion, au cas où, puis effacé une fois tout transcrit : seule la transcription est conservée.")
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 540)
        .frame(minHeight: 680)
        .disabled(!loaded)
        .task { await app.reloadSettings() }
        // Filled once the settings arrive (the server may still be starting when the window opens)
        .onChange(of: app.preferences, initial: true) { _, preferences in
            if !loaded, let preferences {
                draft = preferences
                loaded = true
            }
        }
    }

    /// A binding to a setting, saved shortly after each change
    private func bind<Value: Equatable>(_ key: WritableKeyPath<Preferences, Value?>, _ fallback: Value) -> Binding<Value> {
        Binding(
            get: { draft[keyPath: key] ?? fallback },
            set: { value in
                guard draft[keyPath: key] != value else { return }
                draft[keyPath: key] = value
                scheduleSave()
            }
        )
    }

    private func scheduleSave() {
        saveTask?.cancel()
        let preferences = draft
        saveTask = Task {
            try? await Task.sleep(for: .milliseconds(400))
            guard !Task.isCancelled else { return }
            await app.savePreferences(preferences)
        }
    }

    /// "Automatique (device in use)" first, then the devices
    private func devicePicker(
        _ title: String, help: String, selection: WritableKeyPath<Preferences, String?>,
        devices: [AudioDevice], inUse: String?
    ) -> some View {
        let binding = Binding<String?>(
            get: { draft[keyPath: selection] },
            set: { value in
                draft[keyPath: selection] = value
                scheduleSave()
            }
        )
        let automatic = app.describe(inUse, in: devices) ?? ""
        return Picker(selection: binding) {
            Text("Automatique (\(automatic))").tag(String?.none)
            ForEach(devices, id: \.name) { Text($0.description).tag(String?.some($0.name)) }
        } label: {
            Text(title)
            Text(help)
        }
    }
}
