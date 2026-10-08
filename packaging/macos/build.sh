#!/bin/bash
# Builds Smart Meeting.app and its disk image (build/macos/Smart-Meeting-<version>.dmg): the server
# (PyInstaller), the app (Xcode), then with a Developer ID the signature and the notarization.
#
#   packaging/macos/build.sh        local build, ad hoc signature (this Mac only)
#
#   DEVELOPER_ID="Developer ID Application: Name (TEAMID)" NOTARY_PROFILE=smart-meeting \
#     packaging/macos/build.sh      signed and notarized: opens on every Mac without warning
#
# NOTARY_PROFILE: credentials stored once in the keychain with
#   xcrun notarytool store-credentials smart-meeting --apple-id <email> --team-id <TEAMID>
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BUILD="$ROOT/build/macos"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/backend/pyproject.toml")"
BUILD_NUMBER="$(git -C "$ROOT" rev-list --count HEAD)"

echo "› Serveur (PyInstaller)"
(cd "$ROOT/backend" && uv run --quiet --with pyinstaller==6.22.3 pyinstaller --noconfirm --log-level WARN \
  --distpath "$BUILD/dist" --workpath "$BUILD/work" "$ROOT/packaging/macos/backend.spec")

echo "› App (Xcode)"
(cd "$ROOT/macos" && xcodegen --quiet)
signing=(CODE_SIGN_IDENTITY="${DEVELOPER_ID:--}")
[ -z "${DEVELOPER_ID:-}" ] || signing+=(OTHER_CODE_SIGN_FLAGS=--timestamp)
xcodebuild -quiet -project "$ROOT/macos/SmartMeeting.xcodeproj" -scheme SmartMeeting -configuration Release \
  -derivedDataPath "$BUILD/xcode" MARKETING_VERSION="$VERSION" CURRENT_PROJECT_VERSION="$BUILD_NUMBER" \
  "${signing[@]}" build
APP="$BUILD/xcode/Build/Products/Release/Smart Meeting.app"
codesign --verify --deep --strict "$APP"

echo "› Image disque"
DMG="$BUILD/Smart-Meeting-$VERSION.dmg"
STAGING="$BUILD/dmg"
rm -rf "$STAGING" "$DMG"
mkdir -p "$STAGING"
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
hdiutil create -quiet -volname "Smart Meeting" -srcfolder "$STAGING" -format UDZO "$DMG"
rm -rf "$STAGING"

if [ -n "${DEVELOPER_ID:-}" ]; then
  codesign --sign "$DEVELOPER_ID" --timestamp "$DMG"
  if [ -n "${NOTARY_PROFILE:-}" ]; then
    echo "› Notarisation (quelques minutes)"
    xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
  fi
fi
echo "✓ $DMG"
