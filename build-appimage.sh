#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APPDIR="$SCRIPT_DIR/NetGuard.AppDir"
OUTPUT="$SCRIPT_DIR/NetGuard-x86_64.AppImage"

echo "=== Building NetGuard AppImage ==="

# Check appimagetool
if ! command -v appimagetool &>/dev/null; then
    echo "Error: appimagetool not found."
    echo "Install it or download from: https://github.com/AppImage/AppImageKit/releases"
    exit 1
fi

# Clean previous build
rm -rf "$APPDIR" "$OUTPUT"

# Create AppDir structure
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$APPDIR/usr/share/icons/hicolor/128x128/apps"

# Copy app
cp "$SCRIPT_DIR/main.py" "$APPDIR/usr/bin/netguard"
chmod +x "$APPDIR/usr/bin/netguard"

# Copy icon
cp "$SCRIPT_DIR/assets/netguard.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/netguard.svg"
if command -v convert &>/dev/null; then
    convert -background none -density 300 -resize 128x128 \
        "$SCRIPT_DIR/assets/netguard.svg" "$APPDIR/usr/share/icons/hicolor/128x128/apps/netguard.png" 2>/dev/null
fi

# Desktop file
cat > "$APPDIR/netguard.desktop" << 'EOF'
[Desktop Entry]
Name=NetGuard
Comment=Process Internet Bandwidth Limiter
Exec=netguard
Icon=netguard
Terminal=false
Type=Application
Categories=System;
StartupNotify=true
StartupWMClass=netguard
EOF

# Icon symlink at root
ln -sf usr/share/icons/hicolor/128x128/apps/netguard.png "$APPDIR/netguard.png"

# AppRun launcher
cat > "$APPDIR/AppRun" << 'APPRUN'
#!/bin/bash
DIR="$(dirname "$(readlink -f "$0")")"
export APPDIR="$DIR"
exec python3 "$DIR/usr/bin/netguard" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# Build AppImage
arch=$(uname -m)
ARCH="$arch" appimagetool "$APPDIR" "$OUTPUT" 2>&1

# Cleanup
rm -rf "$APPDIR"

echo ""
echo "Built: $OUTPUT"
echo "Run with: chmod +x $OUTPUT && $OUTPUT"
