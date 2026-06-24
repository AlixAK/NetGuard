# NetGuard

A GTK3 GUI application for limiting per-process internet bandwidth on Linux. Uses `tc` (traffic control) and cgroups for upload limiting, and `tc` u32 policing for download limiting.

## Features

- **Per-process bandwidth control** — set independent upload and download limits
- **Real-time monitoring** — see live download/upload speed per process, sorted by traffic
- **Process discovery** — finds all child processes (e.g., browser tabs, game clients)
- **Persistent limits** — saves and restores limits across restarts
- **Quick presets** — one-click 100 KB/s, 500 KB/s, 1 MB/s, 5 MB/s buttons
- **KB/s units** — displays speeds in kilobytes, not kilobits

## Screenshot

![NetGuard](assets/screenshot.png)

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
git clone https://github.com/YOUR_USERNAME/NetGuard.git
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
- Icon to `/usr/share/icons/hicolor/`
- Desktop entry to `/usr/share/applications/`

### Uninstall

```bash
sudo make uninstall
```

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
4. Limits persist across app restarts

The app uses:
- **Upload limiting**: `tc` htb qdisc + cgroup `net_cls` classifier
- **Download limiting**: `tc` u32 police filters matching `(local_ip, local_port)`
- **Speed monitoring**: `ss -tni` socket byte counters, sampled every 2 seconds

## Configuration

Active limits are saved to `~/.config/netguard/limits.json` and restored on startup.

## License

GPL v3 — see [LICENSE](LICENSE).

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request
