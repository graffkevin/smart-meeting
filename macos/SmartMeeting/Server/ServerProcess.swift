import AppKit
import Foundation
import OSLog

/// The local server (Python, bundled by PyInstaller in Contents/Resources/smart-meeting-backend):
/// started with the app, stopped when it quits. A server already answering on the port is used as
/// it is (in development: `./smart-meeting --no-window`, or a previous instance).
@MainActor
final class ServerProcess {
    static let port = 8417
    let baseURL = URL(string: "http://127.0.0.1:\(port)/")!

    private let logger = Logger(subsystem: "com.graffkevin.smartmeeting", category: "server")
    private var process: Process?
    private var quitting = false
    private var recentCrashes: [Date] = []

    /// Server bundled in the app; nil in a development build without it (see embed-server.sh)
    var executable: URL? {
        let url = Bundle.main.resourceURL?.appending(path: "smart-meeting-backend/smart-meeting-backend")
        return url.flatMap { FileManager.default.isExecutableFile(atPath: $0.path) ? $0 : nil }
    }

    /// Where the server writes its log: Help > Server log
    static let logFile = FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask)[0]
        .appending(path: "Logs/Smart Meeting/server.log")

    /// Starts the server unless one already answers. False when there is none to start.
    func start() async -> Bool {
        if await answers() {
            logger.info("Using the server already running at \(self.baseURL)")
            return true
        }
        guard let executable else {
            logger.error("No bundled server and none running")
            return false
        }
        launch(executable)
        return true
    }

    /// Stops the server it started, gracefully (the meeting being recorded is finished and its
    /// transcription saved), then for good after `timeout`.
    func stop(timeout: TimeInterval = 60) async {
        quitting = true
        guard let process, process.isRunning else { return }
        process.terminate()  // SIGTERM: uvicorn shuts down cleanly
        let deadline = Date.now.addingTimeInterval(timeout)
        while process.isRunning, Date.now < deadline {
            try? await Task.sleep(for: .milliseconds(200))
        }
        if process.isRunning {
            logger.error("Server still running after \(timeout) s: killed")
            kill(process.processIdentifier, SIGKILL)
        }
    }

    private func launch(_ executable: URL) {
        let process = Process()
        process.executableURL = executable
        process.arguments = ["--app", "--port", String(Self.port)]
        var environment = ProcessInfo.processInfo.environment
        environment["HF_HUB_DISABLE_TELEMETRY"] = "1"
        environment["PYTHONUNBUFFERED"] = "1"
        process.environment = environment
        if let log = Self.openLog() {
            process.standardOutput = log
            process.standardError = log
        }
        process.terminationHandler = { [weak self] finished in
            Task { @MainActor in self?.ended(finished) }
        }
        do {
            try process.run()
            self.process = process
            logger.info("Server started (pid \(process.processIdentifier))")
        } catch {
            logger.error("Server not started: \(error.localizedDescription)")
        }
    }

    /// The server stopped by itself: started again, unless it keeps crashing (then the interface
    /// shows that it does not answer)
    private func ended(_ finished: Process) {
        guard !quitting, finished === process else { return }
        logger.error("Server stopped (status \(finished.terminationStatus))")
        recentCrashes = recentCrashes.filter { $0.timeIntervalSinceNow > -60 } + [.now]
        if recentCrashes.count <= 3, let executable {
            launch(executable)
        }
    }

    private func answers() async -> Bool {
        (try? await APIClient(baseURL: baseURL).health()) != nil
    }

    private static func openLog() -> FileHandle? {
        let folder = logFile.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: logFile.path) {
            FileManager.default.createFile(atPath: logFile.path, contents: nil)
        }
        let handle = try? FileHandle(forWritingTo: logFile)
        _ = try? handle?.seekToEnd()
        return handle
    }
}
