#!/bin/bash
# Xcode build phase: copies into the app (Contents/Resources) the server built by PyInstaller and
# Ollama (build.sh), and signs their native code with the identity of the app, before Xcode signs
# the app itself. Without the server (development), the app uses one started by hand:
# ./smart-meeting --no-window
#
# Signature of the programs: App Store build (SMART_MEETING_STORE=YES), in the app's sandbox
# (inherit.entitlements); Developer ID, hardened runtime (the server with the app's entitlements:
# it captures the audio); ad hoc (local build), neither (library validation needs a Team ID).
set -euo pipefail

BUILD="${SMART_MEETING_BUILD:-$SRCROOT/../build/macos}"
RESOURCES="$TARGET_BUILD_DIR/$UNLOCALIZED_RESOURCES_FOLDER_PATH"

if [ ! -x "$BUILD/dist/smart-meeting-backend/smart-meeting-backend" ]; then
  if [ "$CONFIGURATION" = "Release" ]; then
    echo "error: server not built ($BUILD/dist): run packaging/macos/build.sh"
    exit 1
  fi
  echo "warning: no server to embed ($BUILD/dist): start it by hand, ./smart-meeting --no-window"
  rm -rf "$RESOURCES/smart-meeting-backend" "$RESOURCES/ollama"
  exit 0
fi
rsync -a --delete "$BUILD/dist/smart-meeting-backend/" "$RESOURCES/smart-meeting-backend/"
if [ -x "$BUILD/ollama/ollama" ]; then
  rsync -a --delete "$BUILD/ollama/" "$RESOURCES/ollama/"
fi

IDENTITY="${EXPANDED_CODE_SIGN_IDENTITY:-}"
[ -n "$IDENTITY" ] || IDENTITY="-"
options=(--force --sign "$IDENTITY")
program_options=()
if [ "${SMART_MEETING_STORE:-NO}" = "YES" ]; then
  program_options=(--entitlements "$SRCROOT/../packaging/macos/inherit.entitlements")
elif [ "$IDENTITY" != "-" ]; then
  options+=(--options runtime --timestamp)
fi

# Libraries first (some have no extension, like the Python library), programs last
binaries="$(find "$RESOURCES/smart-meeting-backend" "$RESOURCES/ollama" -type f -print0 2>/dev/null \
  | xargs -0 file --mime-type | sed -n 's/: *application\/x-mach-binary$//p')"
programs=("$RESOURCES/smart-meeting-backend/smart-meeting-backend")
[ -x "$RESOURCES/ollama/ollama" ] && programs+=("$RESOURCES/ollama/ollama" "$RESOURCES/ollama/llama-server")
while IFS= read -r binary; do
  [[ " ${programs[*]} " == *" $binary "* ]] || codesign "${options[@]}" "$binary"
done <<< "$binaries"

server_options=(${program_options[@]+"${program_options[@]}"})
if [ "${SMART_MEETING_STORE:-NO}" != "YES" ] && [ "$IDENTITY" != "-" ]; then
  server_options=(--entitlements "$SRCROOT/$CODE_SIGN_ENTITLEMENTS")
fi
for program in "${programs[@]}"; do
  if [ "$program" = "${programs[0]}" ]; then
    codesign "${options[@]}" ${server_options[@]+"${server_options[@]}"} "$program"
  else
    codesign "${options[@]}" ${program_options[@]+"${program_options[@]}"} "$program"
  fi
done
