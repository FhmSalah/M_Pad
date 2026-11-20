#!/bin/sh
# Build the macOS app and a drag-to-install disk image.
#   cd desktop && ./build_macos.sh
# Output: dist/Macro Pad.app and dist/MacroPad-<version>-macOS.dmg
#
# Needs: macOS on Apple Silicon (the spec targets arm64), and a venv with
# requirements-build.txt installed in desktop/.venv (see README).
set -eu

cd "$(dirname "$0")"
PYTHON="${PYTHON:-.venv/bin/python}"
[ "$(uname)" = "Darwin" ] || { echo "Run this on macOS."; exit 1; }
[ -x "$PYTHON" ] || { echo "Python not found at $PYTHON (create .venv first)."; exit 1; }

VERSION="$("$PYTHON" -c 'from version import VERSION; print(VERSION)')"
APP="dist/Macro Pad.app"
DMG="dist/MacroPad-$VERSION-macOS.dmg"

rm -rf "build/macos" "$APP" "$DMG"
"$PYTHON" -m PyInstaller --noconfirm --workpath build/macos --distpath dist MacroPad-macOS.spec
[ -d "$APP" ] || { echo "PyInstaller did not produce $APP"; exit 1; }

# Ad-hoc signature: required on Apple Silicon. Not notarized (needs a paid Apple
# Developer account), so first launch needs System Settings > Privacy & Security > Open Anyway.
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

# Disk image: the app plus a shortcut to /Applications, so users drag one onto the other.
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "Macro Pad $VERSION" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$DMG"
hdiutil verify "$DMG"

echo "App: $APP"
echo "Disk image: $DMG"
