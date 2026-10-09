#!/usr/bin/env bash
# Builds the Windows installer, build/windows/Smart-Meeting-Setup-<version>.exe: the web interface,
# the app (PyInstaller: server, interface and window in one folder), then the installer (Inno
# Setup). On Windows with Git Bash, uv, Bun and Inno Setup 6 (GitHub: .github/workflows/release.yml).
#
#   packaging/windows/build.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BUILD="$ROOT/build/windows"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/backend/pyproject.toml" | head -1)"
ISCC="${ISCC:-/c/Program Files (x86)/Inno Setup 6/ISCC.exe}"

echo "› Interface web"
(cd "$ROOT/frontend" && bun install --frozen-lockfile && bun run build)

echo "› Icône"
mkdir -p "$BUILD"
ICONS="$ROOT/macos/SmartMeeting/Assets.xcassets/AppIcon.appiconset"
(cd "$ROOT/backend" && uv run --quiet --with pillow python -c "
import sys
from PIL import Image
Image.open(sys.argv[1]).save(sys.argv[2], sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
" "$ICONS/icon_256.png" "$BUILD/app.ico")

echo "› App (PyInstaller)"
(cd "$ROOT/backend" && uv run --quiet --extra windows-app --with pyinstaller==6.22.3 \
  pyinstaller --noconfirm --log-level WARN --distpath "$BUILD/dist" --workpath "$BUILD/work" \
  "$ROOT/packaging/windows/smart-meeting.spec")

echo "› Installeur (Inno Setup)"
"$ISCC" //Q "//DAppVersion=$VERSION" "$ROOT/packaging/windows/smart-meeting.iss"
echo "✓ $BUILD/Smart-Meeting-Setup-$VERSION.exe"
