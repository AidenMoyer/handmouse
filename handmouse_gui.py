"""handmouse_gui.py — Settings & control GUI for handmouse_win.py

Lets you pick camera, resolution, FPS, sensitivity, and mirror mode,
then start/stop the tracker — all without touching the command line.
"""

import os
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

FFMPEG = r"C:\Users\TylerMass\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffmpeg.exe"
PYTHON = os.path.join(os.path.dirname(__file__), "venv-win", "Scripts", "python.exe")
SCRIPT = os.path.join(os.path.dirname(__file__), "handmouse_win.py")

RESOLUTIONS = [
    ("640 × 480  (VGA)", "640", "480"),
    ("1280 × 720  (HD)", "1280", "720"),
    ("1920 × 1080  (Full HD)", "1920", "1080"),
    ("2560 × 1440  (2K)", "2560", "1440"),
    ("3840 × 2160  (4K)", "3840", "2160"),
]

FPS_OPTIONS = ["15", "24", "30", "60"]

DARK  = "#1e1e2e"
PANEL = "#2a2a3e"
ACCENT= "#7c5cfc"
TEXT  = "#cdd6f4"
MUTED = "#6c7086"
GREEN = "#a6e3a1"
RED   = "#f38ba8"


def list_cameras() -> list[str]:
    """Run ffmpeg -list_devices and return video device names."""
    try:
        r = subprocess.run(
            [FFMPEG, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True, text=True, timeout=8
        )
        combined = r.stderr + r.stdout
        names = re.findall(r'"([^"]+)"\s+\(video\)', combined)
        return names if names else ["1080P Pro Stream"]
    except Exception:
        return ["1080P Pro Stream"]


class HandmouseGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("handmouse")
        self.resizable(False, False)
        self.configure(bg=DARK)
        self._proc: subprocess.Popen | None = None
        self._log_thread: threading.Thread | None = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        pad = {"padx": 18, "pady": 8}

        # ── header ──
        hdr = tk.Frame(self, bg=ACCENT, height=4)
        hdr.pack(fill="x")

        title = tk.Label(self, text="✋  handmouse", font=("Segoe UI", 18, "bold"),
                         bg=DARK, fg=TEXT)
        title.pack(pady=(16, 4))

        sub = tk.Label(self, text="Hand-tracking mouse controller",
                       font=("Segoe UI", 10), bg=DARK, fg=MUTED)
        sub.pack(pady=(0, 14))

        # ── settings card ──
        card = tk.Frame(self, bg=PANEL, bd=0, relief="flat")
        card.pack(fill="x", padx=20, pady=4)

        def row(parent, label, widget_fn, r):
            tk.Label(parent, text=label, font=("Segoe UI", 10),
                     bg=PANEL, fg=TEXT, anchor="w", width=16).grid(
                row=r, column=0, sticky="w", padx=14, pady=6)
            w = widget_fn(parent)
            w.grid(row=r, column=1, sticky="ew", padx=14, pady=6)
            return w

        card.columnconfigure(1, weight=1)

        # Camera
        self._cameras = list_cameras()
        self._camera_var = tk.StringVar(value=self._cameras[0] if self._cameras else "")
        row(card, "Camera", lambda p: self._combo(p, self._cameras, self._camera_var), 0)

        # Resolution
        self._res_var = tk.StringVar(value=RESOLUTIONS[0][0])
        row(card, "Resolution", lambda p: self._combo(p, [r[0] for r in RESOLUTIONS], self._res_var), 1)

        # FPS
        self._fps_var = tk.StringVar(value="30")
        row(card, "FPS", lambda p: self._combo(p, FPS_OPTIONS, self._fps_var), 2)

        # Sensitivity (DPI multiplier)
        self._sens_var = tk.DoubleVar(value=1.0)
        def sens_widget(parent):
            f = tk.Frame(parent, bg=PANEL)
            self._sens_label = tk.Label(f, text="1.0×", font=("Segoe UI", 10),
                                        bg=PANEL, fg=ACCENT, width=5)
            self._sens_label.pack(side="right")
            s = ttk.Scale(f, from_=0.3, to=3.0, orient="horizontal",
                          variable=self._sens_var,
                          command=lambda v: self._sens_label.config(
                              text=f"{float(v):.1f}×"))
            s.pack(side="left", fill="x", expand=True)
            return f
        row(card, "Sensitivity", sens_widget, 3)

        # Mirror
        self._mirror_var = tk.BooleanVar(value=True)
        row(card, "Mirror", lambda p: tk.Checkbutton(
            p, variable=self._mirror_var, bg=PANEL,
            activebackground=PANEL, selectcolor=PANEL,
            fg=TEXT, text="Flip horizontally"), 4)

        # Show preview
        self._show_var = tk.BooleanVar(value=False)
        row(card, "Preview window", lambda p: tk.Checkbutton(
            p, variable=self._show_var, bg=PANEL,
            activebackground=PANEL, selectcolor=PANEL,
            fg=TEXT, text="Show camera overlay"), 5)

        # ── refresh cameras button ──
        tk.Button(self, text="↻  Refresh cameras", font=("Segoe UI", 9),
                  bg=PANEL, fg=MUTED, relief="flat", bd=0,
                  activebackground=PANEL, cursor="hand2",
                  command=self._refresh_cameras).pack(pady=(6, 2))

        # ── status indicator ──
        self._status_var = tk.StringVar(value="Stopped")
        self._status_dot = tk.Label(self, text="●", font=("Segoe UI", 12),
                                    bg=DARK, fg=RED)
        self._status_dot.pack()
        self._status_lbl = tk.Label(self, textvariable=self._status_var,
                                    font=("Segoe UI", 10), bg=DARK, fg=MUTED)
        self._status_lbl.pack(pady=(0, 6))

        # ── start / stop button ──
        self._btn = tk.Button(self, text="▶  Start tracking",
                              font=("Segoe UI", 12, "bold"),
                              bg=ACCENT, fg="#ffffff", relief="flat", bd=0,
                              activebackground="#6a4de0",
                              padx=28, pady=10, cursor="hand2",
                              command=self._toggle)
        self._btn.pack(pady=(4, 16))

        # ── log box ──
        log_frame = tk.Frame(self, bg=DARK)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        self._log = tk.Text(log_frame, height=7, bg="#12121c", fg=MUTED,
                             font=("Cascadia Mono", 9), relief="flat",
                             bd=0, state="disabled", wrap="word")
        sb = ttk.Scrollbar(log_frame, command=self._log.yview)
        self._log.configure(yscrollcommand=sb.set)
        self._log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _combo(self, parent, values, var):
        cb = ttk.Combobox(parent, values=values, textvariable=var,
                          state="readonly", font=("Segoe UI", 10))
        self._style_combo(cb)
        return cb

    def _style_combo(self, cb):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox",
                         fieldbackground=DARK, background=PANEL,
                         foreground=TEXT, selectforeground=TEXT,
                         selectbackground=ACCENT,
                         arrowcolor=ACCENT)

    # ── actions ─────────────────────────────────────────────────────────────

    def _refresh_cameras(self):
        self._log_append("Scanning for cameras…\n")
        def _scan():
            cams = list_cameras()
            self.after(0, lambda: self._apply_cameras(cams))
        threading.Thread(target=_scan, daemon=True).start()

    def _apply_cameras(self, cams):
        self._cameras = cams
        # find combo widget by traversal — simpler than storing a ref
        for w in self.winfo_children():
            if isinstance(w, tk.Frame):
                for c in w.winfo_children():
                    if isinstance(c, ttk.Combobox) and self._camera_var.get() in (list(c["values"]) or []):
                        c["values"] = cams
        self._camera_var.set(cams[0] if cams else "")
        self._log_append(f"Found {len(cams)} camera(s): {', '.join(cams)}\n")

    def _toggle(self):
        if self._proc and self._proc.poll() is None:
            self._stop()
        else:
            self._start()

    def _res_wh(self):
        label = self._res_var.get()
        for r in RESOLUTIONS:
            if r[0] == label:
                return r[1], r[2]
        return "640", "480"

    def _start(self):
        w, h = self._res_wh()
        args = [
            PYTHON, SCRIPT,
            "--camera", self._camera_var.get(),
            "--width", w,
            "--height", h,
            "--fps", self._fps_var.get(),
            "--sensitivity", f"{self._sens_var.get():.2f}",
        ]
        if self._mirror_var.get():
            args.append("--mirror")
        if self._show_var.get():
            args.append("--show")

        self._log_append(f"$ {' '.join(args[2:])}\n")
        try:
            self._proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=os.path.dirname(SCRIPT)
            )
        except Exception as e:
            messagebox.showerror("Launch failed", str(e))
            return

        self._set_running(True)
        self._log_thread = threading.Thread(target=self._tail_log, daemon=True)
        self._log_thread.start()
        self.after(500, self._check_alive)

    def _stop(self):
        if self._proc:
            self._proc.terminate()
            self._proc = None
        self._set_running(False)

    def _set_running(self, running: bool):
        if running:
            self._btn.config(text="■  Stop tracking", bg=RED, activebackground="#d07080")
            self._status_var.set("Running")
            self._status_dot.config(fg=GREEN)
        else:
            self._btn.config(text="▶  Start tracking", bg=ACCENT, activebackground="#6a4de0")
            self._status_var.set("Stopped")
            self._status_dot.config(fg=RED)

    def _check_alive(self):
        if self._proc and self._proc.poll() is not None:
            rc = self._proc.returncode
            self._proc = None
            self._set_running(False)
            self._log_append(f"[process exited: code {rc}]\n")
        elif self._proc:
            self.after(1000, self._check_alive)

    def _tail_log(self):
        if not self._proc:
            return
        for line in self._proc.stdout:
            self.after(0, self._log_append, line)

    def _log_append(self, text: str):
        self._log.config(state="normal")
        self._log.insert("end", text)
        self._log.see("end")
        self._log.config(state="disabled")

    def _on_close(self):
        self._stop()
        self.destroy()


if __name__ == "__main__":
    app = HandmouseGUI()
    app.mainloop()
