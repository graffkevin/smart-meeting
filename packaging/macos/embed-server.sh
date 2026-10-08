#!/bin/bash
# Xcode build phase: copies the server built by PyInstaller (build.sh) into the app,
# Contents/Resources/smart-meeting-backend, and signs its native code with the identity of the app,
# before Xcode signs the app itself. Without it (development), the app uses a server started by
# hand: ./smart-meeting --no-window
set -euo pipefail

SERVER="${SMART_MEETING_SERVER:-$SRCROOT/../build/macos/dist/smart-meeting-backend}"
TARGET="$TARGET_BUILD_DIR/$UNLOCALIZED_RESOURCES_FOLDER_PATH/smart-meeting-backend"

if [ ! -x "$SERVER/smart-meeting-backend" ]; then
  if [ "$CONFIGURATION" = "Release" ]; then
    echo "error: server not built ($SERVER): run packaging/macos/build.sh"
    exit 1
  fi
  echo "warning: no server to embed ($SERVER): start it by hand, ./smart-meeting --no-window"
  rm -rf "$TARGET"
  exit 0
fi

rsync -a --delete "$SERVER/" "$TARGET/"

IDENTITY="${EXPANDED_CODE_SIGN_IDENTITY:-}"
[ -n "$IDENTITY" ] || IDENTITY="-"
options=(--force --sign "$IDENTITY")
# Hardened runtime with a Developer ID only: its library validation needs a Team ID, which an ad hoc
# signature (local build) does not have
[ "$IDENTITY" = "-" ] || options+=(--options runtime --timestamp)

# Every native library and binary (some have no extension, like the Python library), then the
# server itself with the entitlements: it is the process that captures the audio.
find "$TARGET" -type f ! -path "$TARGET/smart-meeting-backend" -print0 \
  | xargs -0 file --mime-type \
  | sed -n 's/: *application\/x-mach-binary$//p' \
  | while IFS= read -r binary; do codesign "${options[@]}" "$binary"; done
codesign "${options[@]}" --entitlements "$SRCROOT/$CODE_SIGN_ENTITLEMENTS" "$TARGET/smart-meeting-backend"
