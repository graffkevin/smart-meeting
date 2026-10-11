import Foundation
#if !APP_STORE
import Sparkle
#endif

/// Updates of the downloaded app (Sparkle): checked every few hours against the appcast of the
/// latest release, downloaded, checked against the app's public key and installed after asking.
/// The App Store build has none: the store updates it.
@MainActor
final class AppUpdater {
    #if !APP_STORE
    private let controller = SPUStandardUpdaterController(
        startingUpdater: true, updaterDelegate: nil, userDriverDelegate: nil)
    #endif

    /// This build updates itself (false in the App Store build)
    var available: Bool {
        #if APP_STORE
        false
        #else
        true
        #endif
    }

    /// Looks for a new version now and shows Sparkle's window: notes, then install and relaunch
    func checkForUpdates() {
        #if !APP_STORE
        controller.checkForUpdates(nil)
        #endif
    }
}
