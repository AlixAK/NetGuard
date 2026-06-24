#!/usr/bin/env python3
"""NetGuard - Process Internet Bandwidth Limiter"""

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Gdk, Pango
import subprocess
import os
import signal
import json
import time
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "netguard"
CONFIG_FILE = CONFIG_DIR / "limits.json"
IFACE = None
REFRESH_INTERVAL = 2000


def detect_interface():
    global IFACE
    try:
        out = subprocess.check_output(
            ["ip", "route", "show", "default"], text=True
        ).strip()
        IFACE = out.split("dev")[1].strip().split()[0]
    except Exception:
        IFACE = "enp10s0"


def run_cmd(cmd, sudo=False):
    try:
        if sudo:
            cmd = ["sudo"] + cmd
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip(), result.returncode
    except Exception as e:
        return str(e), 1


def get_processes():
    procs = []
    try:
        out = subprocess.check_output(
            ["ps", "-eo", "pid=,comm=,%cpu=,rss=", "--sort=-rss"],
            text=True, timeout=5,
        )
        for line in out.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                pid = int(parts[0])
                cpu = float(parts[-2])
                rss = int(parts[-1])
                name = " ".join(parts[1:-2])
                procs.append({
                    "pid": pid,
                    "name": name,
                    "cpu": cpu,
                    "rss_kb": rss,
                })
            except (ValueError, IndexError):
                continue
    except Exception:
        pass
    return procs


def get_net_usage():
    usage = {"rx": 0, "tx": 0}
    try:
        out = subprocess.check_output(
            ["cat", "/proc/net/dev"], text=True, timeout=5
        )
        for line in out.strip().split("\n")[2:]:
            parts = line.split()
            if parts and ":" in parts[0]:
                if parts[0].rstrip(":") == IFACE:
                    usage["rx"] = int(parts[1])
                    usage["tx"] = int(parts[9])
                    break
    except Exception:
        pass
    return usage


def get_process_net_bytes():
    result = {}
    try:
        out = subprocess.check_output(
            ["ss", "-tniH", "-p"], text=True, timeout=5
        )
        current_pid = None
        for line in out.strip().split("\n"):
            line = line.strip()
            if not line:
                current_pid = None
                continue
            import re
            if current_pid is None:
                pid_match = re.search(r"pid=(\d+)", line)
                if pid_match:
                    current_pid = int(pid_match.group(1))
            else:
                rx_match = re.search(r"bytes_received:(\d+)", line)
                tx_match = re.search(r"bytes_sent:(\d+)", line)
                if current_pid not in result:
                    result[current_pid] = {"rx": 0, "tx": 0}
                if rx_match:
                    result[current_pid]["rx"] += int(rx_match.group(1))
                if tx_match:
                    result[current_pid]["tx"] += int(tx_match.group(1))
                current_pid = None
    except Exception:
        pass
    return result


class SpeedTracker:
    def __init__(self):
        self.prev_snapshot = {}
        self.prev_time = time.time()
        self._initialized = False

    def update(self):
        now = time.time()
        dt = now - self.prev_time
        if dt < 0.1:
            dt = 0.1
        current = get_process_net_bytes()
        speeds = {}
        if self._initialized:
            for pid, cur in current.items():
                prev = self.prev_snapshot.get(pid, {"rx": 0, "tx": 0})
                rx_delta = max(0, cur["rx"] - prev["rx"])
                tx_delta = max(0, cur["tx"] - prev["tx"])
                speeds[pid] = {
                    "rx_speed": rx_delta / dt,
                    "tx_speed": tx_delta / dt,
                }
        self.prev_snapshot = current
        self.prev_time = now
        self._initialized = True
        return speeds


class Backend:
    NETCLS_BASE = "/sys/fs/cgroup/net_cls"
    NETCLS_PREFIX = "netguard_"
    _next_cid = 300
    _dl_prio_counter = 10

    def __init__(self):
        self.active_limits = {}
        self._load_config()
        self._ensure_netcls_mounted()
        self._ensure_base_setup()
        self._restore_limits()

    def _ensure_netcls_mounted(self):
        if not os.path.exists(f"{self.NETCLS_BASE}/tasks"):
            run_cmd(["mkdir", "-p", self.NETCLS_BASE], sudo=True)
            run_cmd([
                "mount", "-t", "cgroup", "-o", "net_cls",
                "cgroup", self.NETCLS_BASE
            ], sudo=True)

    def _ensure_base_setup(self):
        out, rc = run_cmd(["tc", "qdisc", "show", "dev", IFACE], sudo=True)
        if "htb" not in out:
            run_cmd(["tc", "qdisc", "add", "dev", IFACE,
                      "root", "handle", "1:", "htb", "default", "99"], sudo=True)
            run_cmd(["tc", "class", "add", "dev", IFACE,
                      "parent", "1:", "classid", "1:1",
                      "htb", "rate", "100gbit", "burst", "15k"], sudo=True)
            run_cmd(["tc", "class", "add", "dev", IFACE,
                      "parent", "1:1", "classid", "1:99",
                      "htb", "rate", "100gbit", "burst", "15k"], sudo=True)
            run_cmd(["tc", "filter", "add", "dev", IFACE,
                      "protocol", "ip", "parent", "1:0",
                      "prio", "1", "handle", "1:", "cgroup"], sudo=True)

        out, rc = run_cmd(["tc", "qdisc", "show", "dev", IFACE, "ingress"], sudo=True)
        if "ingress" not in out:
            run_cmd(["tc", "qdisc", "add", "dev", IFACE, "ingress"], sudo=True)

    def _alloc_cid(self):
        cid = Backend._next_cid
        Backend._next_cid += 1
        return cid

    def _netcls_classid_value(self, cid):
        return (1 << 16) | cid

    def _cgroup_path(self, pid):
        return f"{self.NETCLS_BASE}/{self.NETCLS_PREFIX}{pid}"

    def _get_local_ip(self):
        try:
            out = subprocess.check_output(
                ["ip", "route", "get", "1.1.1.1"], text=True, timeout=5
            )
            for part in out.split():
                if part.startswith("src"):
                    return out.split("src")[1].split()[0]
        except Exception:
            pass
        return "192.168.0.7"

    def _get_pid_connections(self, pid):
        conns = []
        try:
            pids = set()
            pids.add(pid)
            out = subprocess.check_output(
                ["ps", "-eo", "pid,ppid"], text=True, timeout=5
            )
            parent_map = {}
            for line in out.strip().split("\n")[1:]:
                p = line.split()
                if len(p) == 2:
                    parent_map[int(p[0])] = int(p[1])
            queue = [pid]
            while queue:
                cur = queue.pop(0)
                for child, parent in parent_map.items():
                    if parent == cur and child not in pids:
                        pids.add(child)
                        queue.append(child)

            ss_out = subprocess.check_output(
                ["ss", "-tnH", "-p"], text=True, timeout=5,
            )
            for line in ss_out.strip().split("\n"):
                for p in pids:
                    if f"pid={p}" in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            local = parts[3]
                            remote = parts[4]
                            local_port = int(local.rsplit(":", 1)[-1])
                            remote_ip = remote.rsplit(":", 1)[0]
                            remote_port = int(remote.rsplit(":", 1)[-1])
                            conns.append({
                                "local_port": local_port,
                                "remote_ip": remote_ip,
                                "remote_port": remote_port,
                            })
                        break
        except Exception:
            pass
        return conns

    def _add_dl_filter(self, pid, local_ip, local_port, rate_kbps):
        prio = Backend._dl_prio_counter
        Backend._dl_prio_counter += 1
        run_cmd([
            "tc", "filter", "add", "dev", IFACE,
            "protocol", "ip", "parent", "ffff:",
            "prio", str(prio),
            "u32", "match", "ip", "dst", f"{local_ip}/32",
            "match", "ip", "dport", str(local_port), "0xffff",
            "police", "rate", f"{rate_kbps}kbit",
            "burst", "15k", "drop"
        ], sudo=True)
        return prio

    def _remove_dl_filters(self, prio_list):
        for prio in prio_list:
            run_cmd([
                "tc", "filter", "del", "dev", IFACE,
                "protocol", "ip", "parent", "ffff:",
                "prio", str(prio)
            ], sudo=True)

    def apply_limit(self, pid, name, download_kbps, upload_kbps):
        if pid in self.active_limits:
            self.remove_limit(pid)

        ul_cid = 0
        dl_prios = []

        if upload_kbps and upload_kbps > 0:
            ul_cid = self._alloc_cid()
            ul_value = self._netcls_classid_value(ul_cid)
            ul_classid = f"1:{ul_cid}"
            cgroup = self._cgroup_path(pid)
            run_cmd(["mkdir", "-p", cgroup], sudo=True)
            run_cmd(["bash", "-c", f"echo {ul_value} > {cgroup}/net_cls.classid"], sudo=True)
            run_cmd(["bash", "-c", f"echo {pid} > {cgroup}/cgroup.procs"], sudo=True)
            run_cmd(["tc", "class", "add", "dev", IFACE,
                      "parent", "1:1", "classid", ul_classid,
                      "htb", "rate", f"{upload_kbps}kbit",
                      "ceil", f"{upload_kbps}kbit", "burst", "15k"], sudo=True)
        else:
            cgroup = self._cgroup_path(pid)

        if download_kbps and download_kbps > 0:
            local_ip = self._get_local_ip()
            conns = self._get_pid_connections(pid)
            for conn in conns:
                prio = self._add_dl_filter(pid, local_ip, conn["local_port"], download_kbps)
                dl_prios.append(prio)

        self.active_limits[pid] = {
            "name": name,
            "download": download_kbps,
            "upload": upload_kbps,
            "cgroup": cgroup,
            "ul_cid": ul_cid,
            "dl_prios": dl_prios,
            "local_ip": local_ip if download_kbps else "",
        }
        self._save_config()

    def refresh_download_filters(self, pid):
        info = self.active_limits.get(pid)
        if not info or not info.get("download"):
            return
        self._remove_dl_filters(info.get("dl_prios", []))
        local_ip = info.get("local_ip", self._get_local_ip())
        conns = self._get_pid_connections(pid)
        new_prios = []
        for conn in conns:
            prio = self._add_dl_filter(pid, local_ip, conn["local_port"], info["download"])
            new_prios.append(prio)
        info["dl_prios"] = new_prios

    def remove_limit(self, pid):
        info = self.active_limits.get(pid)
        if not info:
            return

        if info.get("ul_cid"):
            ul_classid = f"1:{info['ul_cid']}"
            run_cmd(["tc", "class", "del", "dev", IFACE,
                      "parent", "1:1", "classid", ul_classid], sudo=True)
            cgroup = info.get("cgroup", self._cgroup_path(pid))
            run_cmd(["bash", "-c", f"echo {pid} > {self.NETCLS_BASE}/cgroup.procs"], sudo=True)
            run_cmd(["rmdir", cgroup], sudo=True)

        if info.get("dl_prios"):
            self._remove_dl_filters(info["dl_prios"])

        self.active_limits.pop(pid, None)
        self._save_config()

    def remove_all_limits(self):
        for pid in list(self.active_limits.keys()):
            self.remove_limit(pid)

    def cleanup_all(self):
        self.remove_all_limits()
        run_cmd(["tc", "qdisc", "del", "dev", IFACE, "root"], sudo=True)
        run_cmd(["tc", "qdisc", "del", "dev", IFACE, "ingress"], sudo=True)

    def _restore_limits(self):
        saved = dict(self.active_limits)
        self.active_limits.clear()
        for pid, info in saved.items():
            if os.path.exists(f"/proc/{pid}"):
                try:
                    self.apply_limit(
                        pid, info["name"],
                        info.get("download", 0),
                        info.get("upload", 0),
                    )
                except Exception:
                    pass

    def _save_config(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {}
        for pid, info in self.active_limits.items():
            data[str(pid)] = {
                "name": info["name"],
                "download": info.get("download", 0),
                "upload": info.get("upload", 0),
            }
        CONFIG_FILE.write_text(json.dumps(data, indent=2))

    def _load_config(self):
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text())
                self.active_limits = {int(k): v for k, v in data.items()}
            except Exception:
                self.active_limits = {}


class ProcessRow(Gtk.ListBoxRow):
    def __init__(self, proc):
        super().__init__()
        self.proc = proc
        self.speed_bytes = 0  # total rx+tx bytes, used for sorting
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        hbox.set_margin_top(1)
        hbox.set_margin_bottom(1)
        hbox.set_margin_start(10)
        hbox.set_margin_end(10)

        pid_label = Gtk.Label(label=str(proc["pid"]))
        pid_label.set_width_chars(7)
        pid_label.set_xalign(0)
        pid_label.get_style_context().add_class("dim-label")

        name_label = Gtk.Label(label=proc["name"])
        name_label.set_xalign(0)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        name_label.set_max_width_chars(30)

        cpu_label = Gtk.Label(label=f"{proc['cpu']:.1f}%")
        cpu_label.set_width_chars(6)
        cpu_label.set_xalign(1)

        rss = proc["rss_kb"]
        if rss > 1024 * 1024:
            rss_str = f"{rss / 1024 / 1024:.1f} GB"
        elif rss > 1024:
            rss_str = f"{rss / 1024:.1f} MB"
        else:
            rss_str = f"{rss} KB"
        mem_label = Gtk.Label(label=rss_str)
        mem_label.set_width_chars(8)
        mem_label.set_xalign(1)

        self.net_label = Gtk.Label(label="-")
        self.net_label.set_width_chars(10)
        self.net_label.set_xalign(1)
        self.net_label.get_style_context().add_class("dim-label")

        hbox.pack_start(pid_label, False, False, 0)
        hbox.pack_start(name_label, True, True, 0)
        hbox.pack_start(cpu_label, False, False, 0)
        hbox.pack_start(mem_label, False, False, 0)
        hbox.pack_start(self.net_label, False, False, 0)
        self.add(hbox)


class LimitRow(Gtk.ListBoxRow):
    def __init__(self, pid, info, on_remove):
        super().__init__()
        self.pid = pid
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        hbox.set_margin_top(6)
        hbox.set_margin_bottom(6)
        hbox.set_margin_start(10)
        hbox.set_margin_end(10)

        name_label = Gtk.Label(label=f"{info['name']} (PID: {pid})")
        name_label.set_xalign(0)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)

        dl = info.get("download", 0) or "Unlimited"
        ul = info.get("upload", 0) or "Unlimited"
        if isinstance(dl, (int, float)) and dl > 0:
            dl = f"{dl // 8} KB/s"
        if isinstance(ul, (int, float)) and ul > 0:
            ul = f"{ul // 8} KB/s"

        limit_label = Gtk.Label(label=f"  {dl}    {ul}")
        limit_label.set_xalign(1)

        remove_btn = Gtk.Button(label="Remove")
        remove_btn.get_style_context().add_class("destructive-action")
        remove_btn.set_size_request(80, -1)
        remove_btn.connect("clicked", lambda b: on_remove(pid))

        hbox.pack_start(name_label, True, True, 0)
        hbox.pack_start(limit_label, False, False, 0)
        hbox.pack_start(remove_btn, False, False, 0)
        self.add(hbox)


class NetGuardWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="NetGuard - Bandwidth Limiter")
        self.set_wmclass("netguard", "NetGuard")
        self.set_default_size(800, 600)
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "netguard.svg")
        if os.path.exists(icon_path):
            self.set_icon_from_file(icon_path)
        else:
            self.set_icon_name("netguard")

        self.backend = Backend()
        self.all_procs = []
        self.last_net = {"rx": 0, "tx": 0}
        self._tick_count = 0
        self.speed_tracker = SpeedTracker()
        self._proc_rows = {}  # pid -> (row, net_label, speed_bytes)

        self._build_ui()
        self._refresh_processes()
        GLib.timeout_add(REFRESH_INTERVAL, self._tick)

    def _build_ui(self):
        css = Gtk.CssProvider()
        css.load_from_data(b"""
            .title-label { font-weight: bold; }
            .section-label { font-weight: bold; margin: 6px 0; }
            .status-bar { padding: 4px 10px; }
            row:selected { background-color: rgba(52, 152, 219, 0.25); }
        """)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(main_vbox)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_margin_top(12)
        header.set_margin_bottom(8)
        header.set_margin_start(12)
        header.set_margin_end(12)
        title = Gtk.Label(label="NetGuard")
        title.get_style_context().add_class("title-label")
        header.pack_start(title, False, False, 0)
        main_vbox.pack_start(header, False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)
        main_vbox.pack_start(paned, True, True, 0)

        paned.pack1(self._build_process_panel(), True, True)
        paned.pack2(self._build_control_panel(), False, False)
        paned.set_position(480)

        self.status_bar = Gtk.Label(
            label="Ready  |  Interface: " + (IFACE or "?")
        )
        self.status_bar.get_style_context().add_class("status-bar")
        self.status_bar.set_xalign(0)
        main_vbox.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
        main_vbox.pack_start(self.status_bar, False, False, 0)

    def _build_process_panel(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        vbox.set_margin_top(6)
        vbox.set_margin_bottom(6)
        vbox.set_margin_start(6)

        lbl = Gtk.Label(label="Running Processes")
        lbl.set_xalign(0)
        lbl.get_style_context().add_class("section-label")
        vbox.pack_start(lbl, False, False, 0)

        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.search_entry = Gtk.SearchEntry(placeholder_text="Search process...")
        self.search_entry.connect("search-changed", lambda e: self.proc_listbox.invalidate_filter())
        self.search_entry.set_hexpand(True)
        search_box.pack_start(self.search_entry, True, True, 0)
        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.connect("clicked", lambda b: self._refresh_processes())
        search_box.pack_start(refresh_btn, False, False, 0)
        vbox.pack_start(search_box, False, False, 0)

        col_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        col_header.set_margin_start(10)
        col_header.set_margin_end(10)
        for text, w, align in [("PID", 7, 0), ("Name", 0, 0),
                                ("CPU", 6, 1), ("Memory", 8, 1),
                                ("Net", 10, 1)]:
            l = Gtk.Label(label=text)
            l.set_xalign(align)
            if w:
                l.set_width_chars(w)
            l.get_style_context().add_class("dim-label")
            col_header.pack_start(l, False, False, 0)
        vbox.pack_start(col_header, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.proc_listbox = Gtk.ListBox()
        self.proc_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.proc_listbox.set_filter_func(self._filter_func)
        scroll.add(self.proc_listbox)
        vbox.pack_start(scroll, True, True, 0)

        return vbox

    def _build_control_panel(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox.set_margin_top(6)
        vbox.set_margin_bottom(6)
        vbox.set_margin_start(6)
        vbox.set_margin_end(6)
        vbox.set_size_request(320, -1)

        lbl = Gtk.Label(label="Set Bandwidth Limit")
        lbl.set_xalign(0)
        lbl.get_style_context().add_class("section-label")
        vbox.pack_start(lbl, False, False, 0)

        form = Gtk.Grid(column_spacing=10, row_spacing=8)
        form.set_margin_start(4)
        form.set_margin_end(4)

        self.sel_label = Gtk.Label(label="Select a process from the list")
        self.sel_label.set_xalign(0)
        self.sel_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.sel_label.set_max_width_chars(38)
        form.attach(self.sel_label, 0, 0, 2, 1)

        dl_label = Gtk.Label(label="Download limit (KB/s):")
        dl_label.set_xalign(0)
        form.attach(dl_label, 0, 1, 1, 1)
        self.dl_spin = Gtk.SpinButton.new_with_range(0, 12500, 10)
        self.dl_spin.set_value(0)
        self.dl_spin.set_tooltip_text("0 = unlimited (KB/s, 1 MB/s = 1024 KB/s)")
        form.attach(self.dl_spin, 1, 1, 1, 1)

        ul_label = Gtk.Label(label="Upload limit (KB/s):")
        ul_label.set_xalign(0)
        form.attach(ul_label, 0, 2, 1, 1)
        self.ul_spin = Gtk.SpinButton.new_with_range(0, 12500, 10)
        self.ul_spin.set_value(0)
        self.ul_spin.set_tooltip_text("0 = unlimited (KB/s, 1 MB/s = 1024 KB/s)")
        form.attach(self.ul_spin, 1, 2, 1, 1)

        presets = Gtk.Box(spacing=6)
        for label_text, dl, ul in [
            ("100 KB/s", 100, 0), ("500 KB/s", 500, 0),
            ("1 MB/s", 1024, 0), ("5 MB/s", 5120, 0),
        ]:
            b = Gtk.Button(label=label_text)
            b.set_size_request(70, -1)
            b.connect("clicked", lambda btn, d, u: (self.dl_spin.set_value(d), self.ul_spin.set_value(u)), dl, ul)
            presets.pack_start(b, False, False, 0)
        form.attach(presets, 0, 3, 2, 1)

        btn_box = Gtk.Box(spacing=8)
        self.apply_btn = Gtk.Button(label="Apply Limit")
        self.apply_btn.get_style_context().add_class("suggested-action")
        self.apply_btn.set_size_request(120, -1)
        self.apply_btn.connect("clicked", self._on_apply)
        btn_box.pack_start(self.apply_btn, False, False, 0)

        self.remove_btn = Gtk.Button(label="Remove Limit")
        self.remove_btn.get_style_context().add_class("destructive-action")
        self.remove_btn.set_size_request(120, -1)
        self.remove_btn.connect("clicked", self._on_remove)
        btn_box.pack_start(self.remove_btn, False, False, 0)

        form.attach(btn_box, 0, 4, 2, 1)
        vbox.pack_start(form, False, False, 0)

        vbox.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)

        lbl2 = Gtk.Label(label="Active Limits")
        lbl2.set_xalign(0)
        lbl2.get_style_context().add_class("section-label")
        vbox.pack_start(lbl2, False, False, 0)

        self.remove_all_btn = Gtk.Button(label="Remove All Limits")
        self.remove_all_btn.get_style_context().add_class("destructive-action")
        self.remove_all_btn.connect("clicked", lambda b: self._on_remove_all())
        vbox.pack_start(self.remove_all_btn, False, False, 0)

        scroll2 = Gtk.ScrolledWindow()
        scroll2.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.limits_listbox = Gtk.ListBox()
        scroll2.add(self.limits_listbox)
        vbox.pack_start(scroll2, True, True, 0)

        self._refresh_limits()
        return vbox

    def _filter_func(self, row):
        query = self.search_entry.get_text().lower()
        if not query:
            return True
        return query in row.proc["name"].lower() or query in str(row.proc["pid"])

    def _sort_by_net(self, row1, row2, user_data):
        return int(row2.speed_bytes - row1.speed_bytes)

    def _refresh_processes(self):
        self.all_procs = get_processes()
        self._proc_rows = {}
        self.proc_listbox.foreach(lambda child: self.proc_listbox.remove(child))
        for proc in self.all_procs:
            row = ProcessRow(proc)
            self.proc_listbox.add(row)
            self._proc_rows[proc["pid"]] = row
        self.proc_listbox.set_sort_func(self._sort_by_net, None)
        self.proc_listbox.show_all()

    def _refresh_limits(self):
        self.limits_listbox.foreach(lambda child: self.limits_listbox.remove(child))
        if not self.backend.active_limits:
            lbl = Gtk.Label(label="No active limits")
            lbl.get_style_context().add_class("dim-label")
            lbl.set_margin_top(10)
            self.limits_listbox.add(lbl)
        else:
            for pid, info in sorted(self.backend.active_limits.items()):
                self.limits_listbox.add(LimitRow(pid, info, self._on_remove_pid))
        self.limits_listbox.show_all()

    def _on_apply(self, btn):
        sel = self.proc_listbox.get_selected_row()
        if not sel:
            self._show_msg("Select a process first.", Gtk.MessageType.WARNING)
            return
        proc = sel.proc
        dl = int(self.dl_spin.get_value())
        ul = int(self.ul_spin.get_value())
        if dl == 0 and ul == 0:
            self._show_msg("Set at least one limit.", Gtk.MessageType.WARNING)
            return
        dl_kbit = dl * 8
        ul_kbit = ul * 8
        try:
            self.backend.apply_limit(proc["pid"], proc["name"], dl_kbit, ul_kbit)
        except Exception as e:
            self._show_msg(f"Error: {e}", Gtk.MessageType.ERROR)
            return
        self._refresh_limits()
        self.status_bar.set_text(
            f"Limit applied: {proc['name']} (PID {proc['pid']})  |  Interface: {IFACE}")

    def _on_remove(self, btn):
        sel = self.proc_listbox.get_selected_row()
        if not sel:
            self._show_msg("Select a process first.", Gtk.MessageType.WARNING)
            return
        self.backend.remove_limit(sel.proc["pid"])
        self._refresh_limits()

    def _on_remove_pid(self, pid):
        self.backend.remove_limit(pid)
        self._refresh_limits()

    def _on_remove_all(self):
        self.backend.remove_all_limits()
        self._refresh_limits()

    def _show_msg(self, msg, mtype):
        dlg = Gtk.MessageDialog(
            transient_for=self, message_type=mtype,
            buttons=Gtk.ButtonsType.OK, text=msg,
        )
        dlg.run()
        dlg.destroy()

    def _tick(self):
        self._tick_count += 1
        if self._tick_count % 5 == 0:
            for pid in list(self.backend.active_limits.keys()):
                try:
                    self.backend.refresh_download_filters(pid)
                except Exception:
                    pass
        net = get_net_usage()
        if self.last_net["rx"] > 0:
            dl_rate = (net["rx"] - self.last_net["rx"]) / REFRESH_INTERVAL * 1000
            ul_rate = (net["tx"] - self.last_net["tx"]) / REFRESH_INTERVAL * 1000
            dl_str = f"{dl_rate / 1024:.1f} KB/s"
            ul_str = f"{ul_rate / 1024:.1f} KB/s"
            limits_count = len(self.backend.active_limits)
            self.status_bar.set_text(
                f" {dl_str}   {ul_str}  |  "
                f"Active limits: {limits_count}  |  Interface: {IFACE}"
            )
        self.last_net = net

        # Per-process network speed
        speeds = self.speed_tracker.update()
        for pid, row in self._proc_rows.items():
            sp = speeds.get(pid, {"rx_speed": 0, "tx_speed": 0})
            total = sp["rx_speed"] + sp["tx_speed"]
            row.speed_bytes = total
            if total > 0:
                if total > 1024 * 1024:
                    row.net_label.set_text(f"{total / 1024 / 1024:.1f} MB/s")
                else:
                    row.net_label.set_text(f"{total / 1024:.1f} KB/s")
                row.net_label.get_style_context().remove_class("dim-label")
            else:
                row.net_label.set_text("-")
                row.net_label.get_style_context().add_class("dim-label")
        self.proc_listbox.invalidate_sort()

        return True


def main():
    detect_interface()
    win = NetGuardWindow()

    def on_destroy(widget):
        win.backend.cleanup_all()
        CONFIG_FILE.write_text("{}")
        Gtk.main_quit()

    def on_signal(signum, frame):
        win.backend.cleanup_all()
        CONFIG_FILE.write_text("{}")
        Gtk.main_quit()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    win.connect("destroy", on_destroy)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
