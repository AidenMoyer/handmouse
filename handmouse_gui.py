"""handmouse_gui.py — Settings & control GUI for handmouse_win.py"""

import os
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

FFMPEG = r"C:\Users\TylerMass\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffmpeg.exe"
PYTHON = os.path.join(os.path.dirname(__file__), "venv-win", "Scripts", "pythonw.exe")
SCRIPT = os.path.join(os.path.dirname(__file__), "handmouse_win.py")

RESOLUTIONS = [
    ("640 × 480  (VGA)",       "640",  "480"),
    ("1280 × 720  (HD)",       "1280", "720"),
    ("1920 × 1080  (Full HD)", "1920", "1080"),
    ("2560 × 1440  (2K)",      "2560", "1440"),
    ("3840 × 2160  (4K)",      "3840", "2160"),
]
FPS_OPTIONS  = ["15", "24", "30", "60"]
HAND_OPTIONS = ["any", "left", "right"]

DARK   = "#1e1e2e"
PANEL  = "#2a2a3e"
ACCENT = "#7c5cfc"
TEXT   = "#cdd6f4"
MUTED  = "#6c7086"
GREEN  = "#a6e3a1"
RED    = "#f38ba8"
YELLOW = "#f9e2af"


# ── data fetchers (run in threads so GUI doesn't freeze) ──────────────────────

def list_cameras():
    try:
        r = subprocess.run(
            [FFMPEG, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True, text=True, timeout=8
        )
        names = re.findall(r'"([^"]+)"\s+\(video\)', r.stderr + r.stdout)
        return names if names else ["1080P Pro Stream"]
    except Exception:
        return ["1080P Pro Stream"]


def list_monitors():
    try:
        from screeninfo import get_monitors
        mons = get_monitors()
        mons = sorted(mons, key=lambda m: (not m.is_primary, m.x))
        labels = []
        for i, m in enumerate(mons):
            tag = "  ★ primary" if m.is_primary else ""
            labels.append(f"{i}:  {m.width}×{m.height}  @({m.x},{m.y}){tag}")
        return labels if labels else ["0:  (primary)"]
    except Exception:
        return ["0:  (primary)"]


def detect_gpu():
    """Return 'NVIDIA', 'AMD', 'Intel', or None."""
    try:
        import subprocess
        r = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get", "Name"],
            capture_output=True, text=True, timeout=5
        )
        text = r.stdout.upper()
        if "NVIDIA" in text:
            return "NVIDIA"
        if "AMD" in text or "RADEON" in text:
            return "AMD"
        if "INTEL" in text:
            return "Intel"
    except Exception:
        pass
    return None


# ── main window ───────────────────────────────────────────────────────────────

class HandmouseGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("handmouse")
        self.resizable(False, False)
        self.configure(bg=DARK)
        self._proc = None
        self._setup_styles()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # async GPU probe so it doesn't block startup
        threading.Thread(target=self._probe_gpu, daemon=True).start()

    # ── styles ─────────────────────────────────────────────────────────────

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TScale", background=PANEL, troughcolor=DARK,
                        sliderlength=18, sliderrelief="flat")

    # ── UI ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # accent bar
        tk.Frame(self, bg=ACCENT, height=4).pack(fill="x")

        # title
        tk.Label(self, text="✋  handmouse", font=("Segoe UI", 18, "bold"),
                 bg=DARK, fg=TEXT).pack(pady=(16, 2))
        tk.Label(self, text="Hand-tracking mouse controller",
                 font=("Segoe UI", 10), bg=DARK, fg=MUTED).pack(pady=(0, 12))

        # ── settings card ──────────────────────────────────────────────────
        card = tk.Frame(self, bg=PANEL)
        card.pack(fill="x", padx=20, pady=4)
        card.columnconfigure(1, weight=1)

        def lbl(text, row):
            tk.Label(card, text=text, font=("Segoe UI", 10),
                     bg=PANEL, fg=TEXT, anchor="w", width=17
                     ).grid(row=row, column=0, sticky="w", padx=14, pady=5)

        def menu(parent, values, var, row):
            """Menubutton + Menu — fully Tk-styled, text always visible."""
            if values:
                var.set(values[0])
            btn = tk.Menubutton(parent, textvariable=var,
                                font=("Segoe UI", 10),
                                bg="#3a3a5c", fg=TEXT,
                                activebackground=ACCENT, activeforeground="#ffffff",
                                relief="groove", bd=1,
                                highlightthickness=0,
                                anchor="w", padx=10, pady=5, width=30)
            m = tk.Menu(btn, tearoff=False,
                        bg="#2e2e50", fg=TEXT,
                        activebackground=ACCENT, activeforeground="#ffffff",
                        font=("Segoe UI", 10), bd=0)
            for v in values:
                m.add_command(label=v, command=lambda val=v: var.set(val))
            btn["menu"] = m
            btn.grid(row=row, column=1, sticky="ew", padx=14, pady=5)
            return btn, m   # return both so caller can repopulate menu

        # Camera
        self._cameras = list_cameras()
        self._cam_var = tk.StringVar(value=self._cameras[0])
        lbl("Camera", 0)
        self._cam_btn, self._cam_menu = menu(card, self._cameras, self._cam_var, 0)

        # Monitor
        self._monitors = list_monitors()
        self._mon_var = tk.StringVar(value=self._monitors[0])
        lbl("Control monitor", 1)
        self._mon_btn, self._mon_menu = menu(card, self._monitors, self._mon_var, 1)

        # Resolution
        self._res_var = tk.StringVar(value=RESOLUTIONS[0][0])
        lbl("Resolution", 2)
        menu(card, [r[0] for r in RESOLUTIONS], self._res_var, 2)

        # FPS
        self._fps_var = tk.StringVar(value="30")
        lbl("FPS", 3)
        menu(card, FPS_OPTIONS, self._fps_var, 3)

        # Hand
        self._hand_var = tk.StringVar(value="any")
        lbl("Track hand", 4)
        menu(card, HAND_OPTIONS, self._hand_var, 4)

        # Sensitivity
        self._sens_var = tk.DoubleVar(value=1.0)
        lbl("Sensitivity", 5)
        sens_frame = tk.Frame(card, bg=PANEL)
        sens_frame.grid(row=5, column=1, sticky="ew", padx=14, pady=5)

        def _sens_slider_moved(v):
            self._sens_entry_var.set(f"{float(v):.1f}")

        def _sens_entry_changed(*_):
            try:
                val = float(self._sens_entry_var.get())
                val = max(0.1, min(20.0, val))
                self._sens_var.set(val)
            except ValueError:
                pass

        self._sens_entry_var = tk.StringVar(value="1.0")
        self._sens_entry_var.trace_add("write", _sens_entry_changed)

        ttk.Scale(sens_frame, from_=0.1, to=20.0, orient="horizontal",
                  variable=self._sens_var,
                  command=_sens_slider_moved
                  ).pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Entry(sens_frame, textvariable=self._sens_entry_var,
                 width=5, font=("Segoe UI", 10),
                 bg="#3a3a5c", fg=TEXT, insertbackground=TEXT,
                 relief="groove", bd=1, justify="center"
                 ).pack(side="right")
        tk.Label(sens_frame, text="×", font=("Segoe UI", 10),
                 bg=PANEL, fg=MUTED).pack(side="right")

        # ── toggles row ────────────────────────────────────────────────────
        tog = tk.Frame(card, bg=PANEL)
        tog.grid(row=6, column=0, columnspan=2, sticky="ew", padx=10, pady=(4, 10))

        def toggle(parent, text, var, **kw):
            return tk.Checkbutton(parent, text=text, variable=var,
                                  bg=PANEL, activebackground=PANEL,
                                  selectcolor=PANEL, fg=TEXT,
                                  font=("Segoe UI", 10), **kw)

        self._mirror_var = tk.BooleanVar(value=True)
        self._show_var   = tk.BooleanVar(value=False)
        self._gpu_var    = tk.BooleanVar(value=False)

        toggle(tog, "Mirror", self._mirror_var).pack(side="left", padx=8)
        toggle(tog, "Preview window", self._show_var).pack(side="left", padx=8)
        self._gpu_cb = toggle(tog, "GPU accel", self._gpu_var)
        self._gpu_cb.pack(side="left", padx=8)
        self._gpu_badge = tk.Label(tog, text="", font=("Segoe UI", 8),
                                    bg=PANEL, fg=YELLOW)
        self._gpu_badge.pack(side="left")

        # ── refresh button ─────────────────────────────────────────────────
        tk.Button(self, text="↻  Refresh cameras & monitors",
                  font=("Segoe UI", 9), bg=PANEL, fg=MUTED,
                  relief="flat", bd=0, activebackground=PANEL,
                  cursor="hand2", command=self._refresh).pack(pady=(6, 2))

        # ── status ─────────────────────────────────────────────────────────
        self._dot = tk.Label(self, text="●", font=("Segoe UI", 13), bg=DARK, fg=RED)
        self._dot.pack()
        self._status_var = tk.StringVar(value="Stopped")
        tk.Label(self, textvariable=self._status_var,
                 font=("Segoe UI", 10), bg=DARK, fg=MUTED).pack(pady=(0, 6))

        # ── start/stop button ──────────────────────────────────────────────
        self._btn = tk.Button(self, text="▶  Start tracking",
                              font=("Segoe UI", 12, "bold"),
                              bg=ACCENT, fg="#ffffff", relief="flat", bd=0,
                              activebackground="#6a4de0", padx=28, pady=10,
                              cursor="hand2", command=self._toggle)
        self._btn.pack(pady=(4, 16))

        # ── log ────────────────────────────────────────────────────────────
        lf = tk.Frame(self, bg=DARK)
        lf.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        self._log = tk.Text(lf, height=7, bg="#12121c", fg=MUTED,
                             font=("Cascadia Mono", 9), relief="flat",
                             bd=0, state="disabled", wrap="word")
        sb = ttk.Scrollbar(lf, command=self._log.yview)
        self._log.configure(yscrollcommand=sb.set)
        self._log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # ── GPU probe ──────────────────────────────────────────────────────────

    def _probe_gpu(self):
        gpu = detect_gpu()
        def _apply():
            if gpu:
                self._gpu_badge.config(text=f"({gpu} detected)")
                self._gpu_var.set(True)   # default on when GPU found
            else:
                self._gpu_badge.config(text="(no GPU found)")
                self._gpu_var.set(False)
        self.after(0, _apply)

    # ── refresh ────────────────────────────────────────────────────────────

    def _refresh(self):
        self._log_append("Scanning cameras & monitors…\n")
        def _scan():
            cams = list_cameras()
            mons = list_monitors()
            self.after(0, lambda: self._apply_refresh(cams, mons))
        threading.Thread(target=_scan, daemon=True).start()

    def _apply_refresh(self, cams, mons):
        self._cameras  = cams
        self._monitors = mons
        # repopulate camera menu
        self._cam_menu.delete(0, "end")
        for v in cams:
            self._cam_menu.add_command(label=v, command=lambda val=v: self._cam_var.set(val))
        self._cam_var.set(cams[0] if cams else "")
        # repopulate monitor menu
        self._mon_menu.delete(0, "end")
        for v in mons:
            self._mon_menu.add_command(label=v, command=lambda val=v: self._mon_var.set(val))
        self._mon_var.set(mons[0] if mons else "")
        self._log_append(f"Found {len(cams)} camera(s), {len(mons)} monitor(s)\n")

    # ── start / stop ───────────────────────────────────────────────────────

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

    def _mon_index(self):
        label = self._mon_var.get()
        try:
            return int(label.split(":")[0].strip())
        except Exception:
            return 0

    def _start(self):
        w, h = self._res_wh()
        # Use python.exe (not pythonw) so stdout/stderr is captured
        py = PYTHON.replace("pythonw.exe", "python.exe")
        cmd = [
            py, SCRIPT,
            "--camera",      self._cam_var.get(),
            "--width",       w,
            "--height",      h,
            "--fps",         self._fps_var.get(),
            "--hand",        self._hand_var.get(),
            "--monitor",     str(self._mon_index()),
            "--sensitivity", f"{self._sens_var.get():.2f}",   # clamped 0.1–20
        ]
        if self._mirror_var.get():
            cmd.append("--mirror")
        if self._show_var.get():
            cmd.append("--show")
        if self._gpu_var.get():
            cmd.append("--gpu")

        self._log_append("$ " + " ".join(cmd[2:]) + "\n")
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=os.path.dirname(SCRIPT)
            )
        except Exception as e:
            messagebox.showerror("Launch failed", str(e))
            return

        self._set_running(True)
        threading.Thread(target=self._tail_log, daemon=True).start()
        self.after(500, self._check_alive)

    def _stop(self):
        if self._proc:
            self._proc.terminate()
            self._proc = None
        self._set_running(False)

    def _set_running(self, running):
        if running:
            self._btn.config(text="■  Stop tracking", bg=RED, activebackground="#d07080")
            self._status_var.set("Running")
            self._dot.config(fg=GREEN)
        else:
            self._btn.config(text="▶  Start tracking", bg=ACCENT, activebackground="#6a4de0")
            self._status_var.set("Stopped")
            self._dot.config(fg=RED)

    def _check_alive(self):
        if self._proc and self._proc.poll() is not None:
            rc = self._proc.returncode
            self._proc = None
            self._set_running(False)
            self._log_append(f"[exited: code {rc}]\n")
        elif self._proc:
            self.after(1000, self._check_alive)

    def _tail_log(self):
        if not self._proc:
            return
        for line in self._proc.stdout:
            self.after(0, self._log_append, line)

    def _log_append(self, text):
        self._log.config(state="normal")
        self._log.insert("end", text)
        self._log.see("end")
        self._log.config(state="disabled")

    def _on_close(self):
        self._stop()
        self.destroy()


if __name__ == "__main__":
    HandmouseGUI().mainloop()
