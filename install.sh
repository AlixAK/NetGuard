#!/bin/bash
set -e

echo "=== NetGuard Installer ==="
echo ""

# Check Python 3
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found. Please install Python 3."
    exit 1
fi

# Check GTK
if ! python3 -c "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk" 2>/dev/null; then
    echo "Error: GTK3 Python bindings not found."
    echo "Install with:"
    echo "  Fedora/Bazzite: sudo rpm-ostree install python3-gtk && reboot"
    echo "  Ubuntu/Debian:  sudo apt install python3-gi gir1.2-gtk-3.0"
    echo "  Arch:           sudo pacman -S python-gobject gtk3"
    exit 1
fi

# Check tc
if ! command -v tc &>/dev/null; then
    echo "Error: tc (traffic control) not found."
    echo "Install with:"
    echo "  Fedora/Bazzite: sudo rpm-ostree install iproute-tc && reboot"
    echo "  Ubuntu/Debian:  sudo apt install iproute2"
    echo "  Arch:           sudo pacman -S iproute2"
    exit 1
fi

# Check ss
if ! command -v ss &>/dev/null; then
    echo "Error: ss not found. Install iproute2."
    exit 1
fi

echo "All dependencies found."
echo ""
echo "Installing NetGuard..."
sudo make install
echo ""
echo "Done! Run 'netguard' to start."
