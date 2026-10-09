#!/usr/bin/env bash
# Builds build/linux/smart-meeting_<version>_all.deb: the GNOME app (linux/, GTK 4 + libadwaita)
# with the project in /opt/smart-meeting. The Python dependencies, the AI and the models are
# installed for each user on first launch, like with ./smart-meeting (nothing to compile here).
#
#   packaging/linux/build-deb.sh        (or: make deb)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/backend/pyproject.toml" | head -1)"
APP_ID="io.github.graffkevin.SmartMeeting"
OUT="$ROOT/build/linux"
STAGE="$OUT/smart-meeting_${VERSION}_all"
OPT="$STAGE/opt/smart-meeting"
export PATH="$HOME/.bun/bin:$HOME/.local/bin:$PATH"

echo "Smart Meeting $VERSION : interface web"
(cd "$ROOT/frontend" && bun install --frozen-lockfile >/dev/null && bun run build >/dev/null)

rm -rf "$STAGE"
mkdir -p "$OPT/backend" "$OPT/frontend" "$OPT/linux" "$STAGE/DEBIAN" "$STAGE/usr/bin" \
  "$STAGE/usr/share/applications" "$STAGE/usr/share/icons/hicolor/scalable/apps"

# The project: launcher, server sources and lock (the environment goes to each user's folder),
# the built web interface (newer than its sources: never rebuilt there), the GNOME app
cp -p "$ROOT/smart-meeting" "$ROOT/LICENSE" "$ROOT/README.md" "$OPT/"
cp -p "$ROOT/backend/pyproject.toml" "$ROOT/backend/uv.lock" "$OPT/backend/"
cp -rp "$ROOT/backend/src" "$OPT/backend/"
for item in package.json bun.lock index.html src public; do
  cp -rp "$ROOT/frontend/$item" "$OPT/frontend/"
done
cp -rp "$ROOT/frontend/dist" "$OPT/frontend/"
find "$OPT/frontend/dist" -exec touch {} +
cp -p "$ROOT/linux/smart-meeting-app" "$OPT/linux/"
cp -rp "$ROOT/linux/smart_meeting_gtk" "$OPT/linux/"
find "$OPT" -name __pycache__ -type d -prune -exec rm -rf {} +

ln -s /opt/smart-meeting/linux/smart-meeting-app "$STAGE/usr/bin/smart-meeting-app"
cp "$ROOT/macos/app-icon.svg" "$STAGE/usr/share/icons/hicolor/scalable/apps/$APP_ID.svg"
cat > "$STAGE/usr/share/applications/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Smart Meeting
Comment=Transcription et compte rendu de réunions, 100 % local
Exec=smart-meeting-app
Icon=$APP_ID
Terminal=false
StartupNotify=true
Categories=Office;
Keywords=réunion;meeting;transcription;compte rendu;minutes;
EOF

cat > "$STAGE/DEBIAN/control" <<EOF
Package: smart-meeting
Version: $VERSION
Section: sound
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.5), gir1.2-soup-3.0, pipewire-bin, curl
Installed-Size: $(du -sk "$STAGE/opt" | cut -f1)
Maintainer: Kevin Graff <kevin.graff1@gmail.com>
Homepage: https://github.com/graffkevin/smart-meeting
Description: Transcription et compte rendu de réunions, 100 % local
 Smart Meeting écoute le micro et le casque pendant une visio, transcrit qui dit
 quoi en direct, répond aux questions sur la réunion et rédige le compte rendu.
 Tout reste sur l'ordinateur. Au premier lancement, l'application installe
 pour l'utilisateur ses dépendances, l'IA locale et les modèles (environ 8 Go).
EOF
cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
gtk-update-icon-cache -q /usr/share/icons/hicolor 2>/dev/null || true
update-desktop-database -q /usr/share/applications 2>/dev/null || true
EOF
chmod 755 "$STAGE/DEBIAN/postinst"

dpkg-deb --root-owner-group --build "$STAGE" "$OUT/smart-meeting_${VERSION}_all.deb" >/dev/null
echo "Paquet : $OUT/smart-meeting_${VERSION}_all.deb"
echo "Installer : sudo apt install $OUT/smart-meeting_${VERSION}_all.deb"
