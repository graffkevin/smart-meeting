#!/bin/bash
# Writes the Sparkle appcast of a release on stdout: the disk image of the tag, its EdDSA signature
# (the private key of SPARKLE_PRIVATE_KEY, the public one is in Info.plist) and the version of the
# app it holds. Added to the release by .github/workflows/release.yml; the apps read the one of the
# latest published release (SUFeedURL), so a draft is offered to nobody.
#
#   SPARKLE_PRIVATE_KEY=… packaging/macos/appcast.sh build/macos/Smart-Meeting-0.2.6.dmg v0.2.6 > appcast.xml
set -euo pipefail

DMG="$1"
TAG="$2"
REPOSITORY="graffkevin/smart-meeting"
SPARKLE_VERSION="2.10.0"  # same as macos/project.yml
: "${SPARKLE_PRIVATE_KEY:?the private key of the updates (secret SPARKLE_PRIVATE_KEY)}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# The version of the app inside the image: Sparkle compares its build number with the installed one
hdiutil attach -quiet -nobrowse -readonly -mountpoint "$work/image" "$DMG"
info="$work/image/Smart Meeting.app/Contents/Info.plist"
version="$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$info")"
build="$(/usr/libexec/PlistBuddy -c "Print :CFBundleVersion" "$info")"
minimum="$(/usr/libexec/PlistBuddy -c "Print :LSMinimumSystemVersion" "$info")"
hdiutil detach -quiet "$work/image"

curl -sSfL -o "$work/sparkle.tar.xz" \
  "https://github.com/sparkle-project/Sparkle/releases/download/$SPARKLE_VERSION/Sparkle-$SPARKLE_VERSION.tar.xz"
tar -xf "$work/sparkle.tar.xz" -C "$work" ./bin/sign_update
# sparkle:edSignature="…" length="…"
signature="$(printf '%s' "$SPARKLE_PRIVATE_KEY" | "$work/bin/sign_update" --ed-key-file - "$DMG")"

cat <<EOF
<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <title>Smart Meeting</title>
    <link>https://github.com/$REPOSITORY/releases</link>
    <item>
      <title>Smart Meeting $version</title>
      <pubDate>$(LC_ALL=C date -u "+%a, %d %b %Y %H:%M:%S +0000")</pubDate>
      <sparkle:version>$build</sparkle:version>
      <sparkle:shortVersionString>$version</sparkle:shortVersionString>
      <sparkle:minimumSystemVersion>$minimum</sparkle:minimumSystemVersion>
      <sparkle:fullReleaseNotesLink>https://github.com/$REPOSITORY/releases/tag/$TAG</sparkle:fullReleaseNotesLink>
      <enclosure url="https://github.com/$REPOSITORY/releases/download/$TAG/$(basename "$DMG")"
                 type="application/octet-stream" $signature />
    </item>
  </channel>
</rss>
EOF
