#!/bin/bash
# Builds Smart Meeting.app with its server and Ollama, then packages it:
#
#   packaging/macos/build.sh                 disk image (build/macos/Smart-Meeting-<version>.dmg),
#                                            ad hoc signature: this Mac only
#
#   DEVELOPER_ID="Developer ID Application: Name (TEAMID)" NOTARY_PROFILE=smart-meeting \
#     packaging/macos/build.sh               signed and notarized disk image: opens on every Mac
#
#   packaging/macos/build.sh --store         App Store package (build/macos/Smart-Meeting-<version>.pkg),
#                                            in the sandbox, to send with Transporter
#
# NOTARY_PROFILE: credentials stored once in the keychain with
#   xcrun notarytool store-credentials smart-meeting --apple-id <email> --team-id <TEAMID>
# --store needs the "Apple Distribution" and "Mac Installer Distribution" certificates, and the
# Mac App Store provisioning profile of the app installed (STORE_PROFILE: its name).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BUILD="$ROOT/build/macos"
TEAM="${TEAM:-S9DDJTM2UJ}"
STORE_PROFILE="${STORE_PROFILE:-Smart Meeting App Store}"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/backend/pyproject.toml")"
BUILD_NUMBER="$(git -C "$ROOT" rev-list --count HEAD)"
STORE=NO
[ "${1:-}" != "--store" ] || STORE=YES

echo "› Serveur (PyInstaller)"
(cd "$ROOT/backend" && uv run --quiet --with pyinstaller==6.22.3 pyinstaller --noconfirm --log-level WARN \
  --distpath "$BUILD/dist" --workpath "$BUILD/work" "$ROOT/packaging/macos/backend.spec")

echo "› Ollama"
"$ROOT/packaging/macos/fetch-ollama.sh" "$BUILD/ollama"

echo "› App (Xcode)"
(cd "$ROOT/macos" && xcodegen --quiet)
if [ "$STORE" = YES ]; then
  signing=(SMART_MEETING_STORE=YES CODE_SIGN_ENTITLEMENTS=SmartMeeting/SmartMeeting.appstore.entitlements
    CODE_SIGN_IDENTITY="Apple Distribution" DEVELOPMENT_TEAM="$TEAM"
    PROVISIONING_PROFILE_SPECIFIER="$STORE_PROFILE"
    # No get-task-allow (debugging), which Xcode adds to a plain build: refused by the App Store
    CODE_SIGN_INJECT_BASE_ENTITLEMENTS=NO)
elif [ -n "${DEVELOPER_ID:-}" ]; then
  # Same without get-task-allow: refused by the notarization
  signing=(CODE_SIGN_IDENTITY="$DEVELOPER_ID" OTHER_CODE_SIGN_FLAGS=--timestamp
    CODE_SIGN_INJECT_BASE_ENTITLEMENTS=NO)
else
  signing=(CODE_SIGN_IDENTITY=-)
fi
DERIVED="$BUILD/xcode-$([ "$STORE" = YES ] && echo store || echo direct)"
xcodebuild -quiet -project "$ROOT/macos/SmartMeeting.xcodeproj" -scheme SmartMeeting -configuration Release \
  -derivedDataPath "$DERIVED" MARKETING_VERSION="$VERSION" CURRENT_PROJECT_VERSION="$BUILD_NUMBER" \
  "${signing[@]}" build
APP="$DERIVED/Build/Products/Release/Smart Meeting.app"
codesign --verify --deep --strict "$APP"

if [ "$STORE" = YES ]; then
  echo "› Paquet App Store"
  installer="$(security find-identity -v | grep -E "\"(3rd Party Mac Developer Installer|Mac Installer Distribution): .*\($TEAM\)\"" \
    | sed -E 's/.*"(.*)"/\1/' | head -1)"
  [ -n "$installer" ] || { echo "Certificat « Mac Installer Distribution » introuvable"; exit 1; }
  PKG="$BUILD/Smart-Meeting-$VERSION.pkg"
  productbuild --component "$APP" /Applications --sign "$installer" "$PKG"
  echo "✓ $PKG : à envoyer avec l'app Transporter"
  exit 0
fi

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
