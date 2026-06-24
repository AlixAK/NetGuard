# NetGuard

A GTK3 GUI application for limiting per-process internet bandwidth on Linux. Uses `tc` (traffic control) and cgroups for upload limiting, and `tc` u32 policing for download limiting.

## Features

- **Per-process bandwidth control** — set independent upload and download limits
- **Real-time monitoring** — see live download/upload speed per process, sorted by traffic
- **Process discovery** — finds all child processes (e.g., browser tabs, game clients)
- **Clean exit** — all tc rules and cgroups are removed when the app closes
- **Quick presets** — one-click 100 KB/s, 500 KB/s, 1 MB/s, 5 MB/s buttons
- **KB/s units** — displays speeds in kilobytes, not kilobits

## Screenshot

<!-- TODO: Add screenshot -->

```
NetGuard - Bandwidth Limiter
+------------------------------------------+----------------------------------+
| Running Processes                        | Set Bandwidth Limit              |
| [Search process...]           [Refresh]  | Select a process from the list   |
| PID  Name            CPU    Mem    Net   | Download limit (KB/s): [0]       |
| 1234 firefox-bin     5.4%  513 MB  0.2KB | Upload limit (KB/s):   [0]       |
| 3313 Discord        16.9%  579 MB  0.4KB | [100 KB/s][500 KB/s][1 MB/s]     |
| 4829 unityhub-bin    2.3%  288 MB  519KB | [Apply Limit]  [Remove Limit]   |
| ...                                      |                                  |
|                                          | Active Limits                    |
|                                          | No active limits                 |
+------------------------------------------+----------------------------------+
| 540.0 KB/s  22.0 KB/s | Active limits: 0 | Interface: enp10s0              |
+-----------------------------------------------------------------------------+
```

## Requirements

- Python 3.8+
- GTK 3 (`python3-gi`, `gir1.2-gtk-3.0`)
- `iproute-tc` (provides `tc`)
- `iproute2` (provides `ss`, `ip`)
- `sudo` access (for `tc` and cgroup operations)

### Fedora / Bazzite / Fedora Atomic

```bash
sudo rpm-ostree install iproute-tc python3-gtk
```

Then reboot.

### Ubuntu / Debian

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 iproute2
```

### Arch / Manjaro

```bash
sudo pacman -S python-gobject gtk3 iproute2
```

## Installation

### Quick install (recommended)

```bash
git clone https://github.com/AlixAK/NetGuard.git
cd NetGuard
chmod +x install.sh
./install.sh
```

### Manual install

```bash
sudo make install
```

This installs:
- `netguard` to `/usr/local/bin/`
- Icon to `/usr/local/share/icons/hicolor/`
- Desktop entry to `/usr/local/share/applications/`

### Uninstall

```bash
sudo make uninstall
```

### AppImage (portable, no install needed)

Build a portable AppImage that runs anywhere without installing:

```bash
# Install appimagetool
# Fedora/Bazzite:
sudo rpm-ostree install appimagetool
# Ubuntu/Debian:
sudo apt install appimagetool
# Arch:
sudo pacman -S appimagetool
# Or download from: https://github.com/AppImage/AppImageKit/releases

# Build the AppImage
chmod +x build-appimage.sh
./build-appimage.sh
```

This creates `NetGuard-x86_64.AppImage`. Run it directly:

```bash
chmod +x NetGuard-x86_64.AppImage
./NetGuard-x86_64.AppImage
```

The AppImage still requires Python 3, GTK 3, and `iproute-tc` to be installed on the system — it bundles only the app itself, not system libraries.

## Usage

### Run from terminal

```bash
netguard
```

### Run directly

```bash
python3 /usr/local/bin/netguard
```

### How it works

1. Select a process from the list
2. Set a download and/or upload limit in KB/s
3. Click **Apply Limit**
4. All limits are automatically removed when you close the app

The app uses:
- **Upload limiting**: `tc` htb qdisc + cgroup `net_cls` classifier
- **Download limiting**: `tc` u32 police filters matching `(local_ip, local_port)`
- **Speed monitoring**: `ss -tni` socket byte counters, sampled every 2 seconds

## Configuration

The app detects your default network interface automatically. Config is stored in `~/.config/netguard/limits.json` but is cleared on exit — all tc rules and cgroups are removed when the app closes.

## License

GPL v3 — see [LICENSE](LICENSE).

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request
