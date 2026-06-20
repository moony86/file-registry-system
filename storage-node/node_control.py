import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import urllib.request
import webbrowser

import tkinter as tk
from tkinter import messagebox


APP_TITLE = "FSYS Node"


def runtime_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


RUNTIME_DIR = runtime_dir()
ENV_PATH = RUNTIME_DIR / ".env"
LOG_PATH = RUNTIME_DIR / "logs" / "node.log"


def parse_env(path=ENV_PATH):
    values = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def node_port():
    values = parse_env()
    try:
        return int(values.get("NODE_PORT", "5001"))
    except ValueError:
        return 5001


def node_status_url():
    return f"http://127.0.0.1:{node_port()}/api/status"


def master_url():
    values = parse_env()
    urls = values.get("MASTER_URLS") or values.get("MASTER_URL") or "http://localhost:5000"
    return urls.split(",", 1)[0].strip().rstrip("/") or "http://localhost:5000"


def node_command(extra_args=None):
    extra_args = extra_args or []
    exe = RUNTIME_DIR / "fsys-node.exe"
    if exe.exists():
        return [str(exe), *extra_args], RUNTIME_DIR
    return [sys.executable, str(RUNTIME_DIR / "app.py"), *extra_args], RUNTIME_DIR


def open_path(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")
    os.startfile(path)


class NodeControlApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("560x520")
        self.process = None
        self.last_status = None

        self.status_var = tk.StringVar(value="Node status: unknown")
        self.master_var = tk.StringVar(value="Master: unknown")
        self.node_var = tk.StringVar(value="Node: unknown")
        self.space_var = tk.StringVar(value="Shared space: unknown")
        self.libs_var = tk.StringVar(value="Local libraries: unknown")
        self.message_var = tk.StringVar(value="Ready.")

        self.build_ui()
        self.poll_status_loop()

    def build_ui(self):
        frame = tk.Frame(self.root, padx=16, pady=16)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text="FSYS Storage Node", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        tk.Label(frame, textvariable=self.status_var, font=("Segoe UI", 11)).pack(anchor="w", pady=(12, 0))
        tk.Label(frame, textvariable=self.master_var).pack(anchor="w")
        tk.Label(frame, textvariable=self.node_var).pack(anchor="w")
        tk.Label(frame, textvariable=self.space_var).pack(anchor="w")
        tk.Label(frame, textvariable=self.libs_var, wraplength=520, justify=tk.LEFT).pack(anchor="w", pady=(0, 12))

        buttons = tk.Frame(frame)
        buttons.pack(fill=tk.X, pady=8)

        for text, command in [
            ("Start Node", self.start_node),
            ("Stop Node", self.stop_node),
            ("Restart Node", self.restart_node),
            ("Open Dashboard", self.open_dashboard),
            ("Open Local Status", self.open_status),
            ("Open Logs", self.open_logs),
            ("Setup / Reconfigure", self.open_setup),
        ]:
            tk.Button(buttons, text=text, command=command, width=22).pack(anchor="w", pady=2)

        tk.Label(frame, textvariable=self.message_var, fg="#555", wraplength=520, justify=tk.LEFT).pack(anchor="w", pady=(16, 0))

    def set_message(self, message):
        self.message_var.set(message)

    def start_node(self):
        if self.process and self.process.poll() is None:
            self.set_message("Node is already running from this control window.")
            return
        cmd, cwd = node_command()
        try:
            self.process = subprocess.Popen(cmd, cwd=str(cwd))
            self.set_message("Node started. Waiting for /api/status...")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not start node:\n{exc}")

    def stop_node(self):
        if not self.process or self.process.poll() is not None:
            self.set_message("No node process started by this control window.")
            return
        self.process.terminate()
        self.set_message("Stop requested.")

    def restart_node(self):
        self.stop_node()
        self.root.after(1500, self.start_node)

    def open_dashboard(self):
        webbrowser.open(f"{master_url()}/dashboard")

    def open_status(self):
        webbrowser.open(node_status_url())

    def open_logs(self):
        open_path(LOG_PATH)

    def open_setup(self):
        cmd, cwd = node_command(["--setup"])
        try:
            if os.name == "nt":
                subprocess.Popen(["cmd", "/k", *cmd], cwd=str(cwd))
            else:
                subprocess.Popen(cmd, cwd=str(cwd))
            self.set_message("Setup opened in a separate window.")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Could not open setup:\n{exc}")

    def fetch_status(self):
        try:
            with urllib.request.urlopen(node_status_url(), timeout=2) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            return None

    def update_status(self, data):
        values = parse_env()
        libs = values.get("LOCAL_LIBRARY_DIRS", "")
        if not data:
            self.status_var.set("Node status: offline or starting")
            self.master_var.set(f"Master: waiting for {master_url()}")
            self.node_var.set(f"Node: 127.0.0.1:{node_port()}")
            self.space_var.set("Shared space: unavailable")
            self.libs_var.set(f"Local libraries: {libs or '(none configured)'}")
            return

        self.last_status = data
        registration = data.get("registration") or {}
        master_state = "connected" if registration.get("registered") else "waiting for master"
        used = int(data.get("shared_space_used_bytes") or 0)
        limit = int(data.get("shared_space_limit_bytes") or 0)
        self.status_var.set("Node status: online")
        self.master_var.set(f"Master: {master_state} | active={data.get('active_master_url') or 'unknown'}")
        self.node_var.set(f"Node: {data.get('node_id')} | {data.get('node_host')}:{data.get('node_port')}")
        self.space_var.set(f"Shared space: {used} / {limit} bytes")
        self.libs_var.set(f"Local libraries: {libs or '(none configured)'}")

    def poll_status_loop(self):
        def worker():
            data = self.fetch_status()
            self.root.after(0, lambda: self.update_status(data))
        threading.Thread(target=worker, daemon=True).start()
        self.root.after(3000, self.poll_status_loop)


def main():
    root = tk.Tk()
    NodeControlApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
