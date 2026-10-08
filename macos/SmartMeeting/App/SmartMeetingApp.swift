import SwiftUI
import UniformTypeIdentifiers

@main
struct SmartMeetingApp: App {
    @NSApplicationDelegateAdaptor private var delegate: AppDelegate

    var body: some Scene {
        // A single window: closing it keeps the app (and a recording) running, the Dock icon reopens it
        Window("Smart Meeting", id: "main") {
            ContentView()
                .environment(delegate.app)
                .frame(minWidth: 900, minHeight: 600)
                .task { await delegate.app.start() }
        }
        .defaultSize(width: 1280, height: 820)
        .commands { AppCommands(app: delegate.app) }

        Settings {
            SettingsView()
                .environment(delegate.app)
        }

        // While recording: a red dot in the menu bar, to get back to the meeting or stop it
        MenuBarExtra(isInserted: .constant(delegate.app.activeMeetingId != nil)) {
            RecordingMenu()
                .environment(delegate.app)
        } label: {
            Label("Enregistrement en cours", systemImage: "record.circle.fill")
        }
    }
}

/// Starts and stops the server with the app; asks before quitting during a recording
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let app = AppModel()

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if app.activeMeetingId != nil {
            let alert = NSAlert()
            alert.messageText = String(localized: "Quitter Smart Meeting ?")
            alert.informativeText = String(localized: "Une réunion est en cours : elle sera arrêtée et sa transcription terminée. Le compte rendu pourra être généré plus tard.")
            alert.addButton(withTitle: String(localized: "Quitter"))
            alert.addButton(withTitle: String(localized: "Annuler"))
            guard alert.runModal() == .alertFirstButtonReturn else { return .terminateCancel }
        }
        Task {
            await app.server.stop()
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
}

/// Menus: new meeting, import, stop the recording, transcript panel, server log
struct AppCommands: Commands {
    let app: AppModel
    @Environment(\.openWindow) private var openWindow

    var body: some Commands {
        CommandGroup(replacing: .newItem) {
            Button("Nouvelle réunion") {
                openWindow(id: "main")
                app.screen = .home
            }
            .keyboardShortcut("n")
            Button("Importer un enregistrement…") {
                openWindow(id: "main")
                chooseFileToImport()
            }
            .keyboardShortcut("o")
        }
        CommandMenu("Réunion") {
            Button("Arrêter l'enregistrement") {
                Task { await app.stopActiveMeeting() }
            }
            .keyboardShortcut(".")
            .disabled(app.activeMeetingId == nil)
            Divider()
            Toggle("Afficher la transcription", isOn: Binding(get: { app.showTranscript }, set: { app.showTranscript = $0 }))
                .keyboardShortcut("t", modifiers: [.command, .option])
        }
        CommandGroup(after: .help) {
            Button("Afficher le journal du serveur") {
                NSWorkspace.shared.activateFileViewerSelecting([ServerProcess.logFile])
            }
        }
    }

    private func chooseFileToImport() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.audiovisualContent]
        panel.message = String(localized: "Replay de visio, webinaire, note vocale…")
        guard panel.runModal() == .OK, let url = panel.url else { return }
        app.fileToImport = url
        app.screen = .home
    }
}

/// Menu of the menu bar icon shown while recording
struct RecordingMenu: View {
    @Environment(AppModel.self) private var app
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        if let id = app.activeMeetingId {
            let title = app.meetings.first { $0.id == id }?.title
            Text(title ?? String(localized: "Réunion en cours"))
            Button("Afficher la réunion") {
                openWindow(id: "main")
                NSApp.activate()
                app.open(id)
            }
            Button("Arrêter l'enregistrement") {
                Task { await app.stopActiveMeeting() }
            }
        }
    }
}
