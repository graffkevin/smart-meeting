#!/bin/bash
# Xcode build phase, after Sparkle.framework is embedded and before Xcode signs the app: its
# helpers (installer, updater, XPC services) signed with the identity of the app and the hardened
# runtime, as notarization requires. App Store build: Sparkle removed, the store updates the app
# (its Swift code is compiled out there: APP_STORE condition, see build.sh).
set -euo pipefail

FRAMEWORK="$TARGET_BUILD_DIR/$FRAMEWORKS_FOLDER_PATH/Sparkle.framework"
[ -d "$FRAMEWORK" ] || exit 0
if [ "${SMART_MEETING_STORE:-NO}" = "YES" ]; then
  rm -rf "$FRAMEWORK"
  exit 0
fi

IDENTITY="${EXPANDED_CODE_SIGN_IDENTITY:-}"
[ -n "$IDENTITY" ] || IDENTITY="-"
options=(--force --sign "$IDENTITY" --options runtime)
[ "$IDENTITY" = "-" ] || options+=(--timestamp)

# Inside out, as Sparkle documents it (the Downloader keeps its network entitlement)
VERSION="$FRAMEWORK/Versions/B"
codesign "${options[@]}" "$VERSION/XPCServices/Installer.xpc"
codesign "${options[@]}" --preserve-metadata=entitlements "$VERSION/XPCServices/Downloader.xpc"
codesign "${options[@]}" "$VERSION/Autoupdate"
codesign "${options[@]}" "$VERSION/Updater.app"
codesign "${options[@]}" "$FRAMEWORK"
