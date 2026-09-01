"""handmouse_gui.py — Settings & control GUI for handmouse_win.py"""

import json
import os
import re
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox

FFMPEG = r"C:\Users\TylerMass\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffmpeg.exe"
PYTHON  = os.path.join(os.path.dirname(__file__), "venv-win", "Scripts", "pythonw.exe")
SCRIPT  = os.path.join(os.path.dirname(__file__), "handmouse_win.py")
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")

RESOLUTIONS = [
    ("640 × 480  (VGA)",       "640",  "480"),
    ("1280 × 720  (HD)",       "1280", "720"),
    ("1920 × 1080  (Full HD)", "1920", "1080"),
    ("2560 × 1440  (2K)",      "2560", "1440"),
    ("3840 × 2160  (4K)",      "3840", "2160"),
]
FPS_OPTIONS  = ["15", "24", "30", "60"]
HAND_OPTIONS = ["any", "left", "right"]
MODE_OPTIONS = ["relative  (trackpad, all monitors)", "absolute  (maps hand to monitor)"]

DEFAULTS = {
    "camera":       None,   # None = first detected
    "monitor":      None,   # None = first detected
    "resolution":   RESOLUTIONS[0][0],
    "fps":          "30",
    "hand":         "any",
    "sensitivity":  1.0,
    "scroll_speed": 2.0,
    "mirror":       True,
    "show":         False,
    "gpu":          False,
    "mode":         MODE_OPTIONS[0],
}

DARK   = "#1e1e2e"
PANEL  = "#2a2a3e"
ACCENT = "#7c5cfc"
TEXT   = "#cdd6f4"
MUTED  = "#6c7086"
GREEN  = "#a6e3a1"
RED    = "#f38ba8"
YELLOW = "#f9e2af"


# ── settings persistence ──────────────────────────────────────────────────────

def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        # merge with defaults so new keys are always present
        return {**DEFAULTS, **saved}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULTS)


def save_settings(d: dict):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    except Exception:
        pass


# ── data fetchers ─────────────────────────────────────────────────────────────

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
        mons = sorted(get_monitors(), key=lambda m: (not m.is_primary, m.x))
        labels = []
        for i, m in enumerate(mons):
            tag = "  ★ primary" if m.is_primary else ""
            labels.append(f"{i}:  {m.width}×{m.height}  @({m.x},{m.y}){tag}")
        return labels if labels else ["0:  (primary)"]
    except Exception:
        return ["0:  (primary)"]


def detect_gpu():
    try:
        r = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get", "Name"],
            capture_output=True, text=True, timeout=5
        )
        text = r.stdout.upper()
        if "NVIDIA" in text: return "NVIDIA"
        if "AMD"    in text or "RADEON" in text: return "AMD"
        if "INTEL"  in text: return "Intel"
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
        self._proc       = None
        self._saving     = False   # guard against recursive trace callbacks
        self._settings   = load_settings()
        self._setup_styles()
        self._build_ui()
        self._apply_settings(self._settings)
        self._attach_save_traces()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── styles ────────────────────────────────────────────────────────────────

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TScale", background=PANEL, troughcolor=DARK,
                        sliderlength=18, sliderrelief="flat")

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        tk.Frame(self, bg=ACCENT, height=4).pack(fill="x")

        tk.Label(self, text="✋  handmouse", font=("Segoe UI", 18, "bold"),
                 bg=DARK, fg=TEXT).pack(pady=(16, 2))
        tk.Label(self, text="Hand-tracking mouse controller",
                 font=("Segoe UI", 10), bg=DARK, fg=MUTED).pack(pady=(0, 12))

        card = tk.Frame(self, bg=PANEL)
        card.pack(fill="x", padx=20, pady=4)
        card.columnconfigure(1, weight=1)

        def lbl(text, row):
            tk.Label(card, text=text, font=("Segoe UI", 10),
                     bg=PANEL, fg=TEXT, anchor="w", width=17
                     ).grid(row=row, column=0, sticky="w", padx=14, pady=5)

        def menu(parent, values, var, row):
            if values:
                var.set(values[0])
            btn = tk.Menubutton(parent, textvariable=var,
                                font=("Segoe UI", 10),
                                bg="#3a3a5c", fg=TEXT,
                                activebackground=ACCENT, activeforeground="#ffffff",
                                relief="groove", bd=1, highlightthickness=0,
                                anchor="w", padx=10, pady=5, width=30)
            m = tk.Menu(btn, tearoff=False,
                        bg="#2e2e50", fg=TEXT,
                        activebackground=ACCENT, activeforeground="#ffffff",
                        font=("Segoe UI", 10), bd=0)
            for v in values:
                m.add_command(label=v, command=lambda val=v: var.set(val))
            btn["menu"] = m
            btn.grid(row=row, column=1, sticky="ew", padx=14, pady=5)
            return btn, m

        # Camera
        self._cameras  = list_cameras()
        self._cam_var  = tk.StringVar()
        lbl("Camera", 0)
        self._cam_btn, self._cam_menu = menu(card, self._cameras, self._cam_var, 0)

        # Monitor
        self._monitors = list_monitors()
        self._mon_var  = tk.StringVar()
        lbl("Control monitor", 1)
        self._mon_btn, self._mon_menu = menu(card, self._monitors, self._mon_var, 1)

        # Resolution
        self._res_var  = tk.StringVar()
        lbl("Resolution", 2)
        menu(card, [r[0] for r in RESOLUTIONS], self._res_var, 2)

        # FPS
        self._fps_var  = tk.StringVar()
        lbl("FPS", 3)
        menu(card, FPS_OPTIONS, self._fps_var, 3)

        # Hand
        self._hand_var = tk.StringVar()
        lbl("Track hand", 4)
        menu(card, HAND_OPTIONS, self._hand_var, 4)

        # Tracking mode
        self._mode_var = tk.StringVar()
        lbl("Tracking mode", 5)
        menu(card, MODE_OPTIONS, self._mode_var, 5)

        # Sensitivity
        self._sens_var       = tk.DoubleVar(value=1.0)
        self._sens_entry_var = tk.StringVar(value="1.0")
        lbl("Sensitivity", 6)
        sf = tk.Frame(card, bg=PANEL)
        sf.grid(row=6, column=1, sticky="ew", padx=14, pady=5)

        def _slider_moved(v):
            if not self._saving:
                self._sens_entry_var.set(f"{float(v):.1f}")

        def _entry_changed(*_):
            if self._saving:
                return
            try:
                val = max(0.1, min(20.0, float(self._sens_entry_var.get())))
                self._sens_var.set(val)
            except ValueError:
                pass

        self._sens_entry_var.trace_add("write", _entry_changed)
        ttk.Scale(sf, from_=0.1, to=20.0, orient="horizontal",
                  variable=self._sens_var, command=_slider_moved
                  ).pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Entry(sf, textvariable=self._sens_entry_var, width=5,
                 font=("Segoe UI", 10), bg="#3a3a5c", fg=TEXT,
                 insertbackground=TEXT, relief="groove", bd=1, justify="center"
                 ).pack(side="right")
        tk.Label(sf, text="×", font=("Segoe UI", 10),
                 bg=PANEL, fg=MUTED).pack(side="right")

        # Scroll speed
        self._scroll_var       = tk.DoubleVar(value=2.0)
        self._scroll_entry_var = tk.StringVar(value="2.0")
        lbl("Scroll speed", 7)
        scf = tk.Frame(card, bg=PANEL)
        scf.grid(row=7, column=1, sticky="ew", padx=14, pady=5)

        def _scroll_slider_moved(v):
            if not self._saving:
                self._scroll_entry_var.set(f"{float(v):.1f}")

        def _scroll_entry_changed(*_):
            if self._saving:
                return
            try:
                val = max(0.5, min(10.0, float(self._scroll_entry_var.get())))
                self._scroll_var.set(val)
            except ValueError:
                pass

        self._scroll_entry_var.trace_add("write", _scroll_entry_changed)
        ttk.Scale(scf, from_=0.5, to=10.0, orient="horizontal",
                  variable=self._scroll_var, command=_scroll_slider_moved
                  ).pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Entry(scf, textvariable=self._scroll_entry_var, width=5,
                 font=("Segoe UI", 10), bg="#3a3a5c", fg=TEXT,
                 insertbackground=TEXT, relief="groove", bd=1, justify="center"
                 ).pack(side="right")
        tk.Label(scf, text="×", font=("Segoe UI", 10),
                 bg=PANEL, fg=MUTED).pack(side="right")

        # Toggles
        tog = tk.Frame(card, bg=PANEL)
        tog.grid(row=8, column=0, columnspan=2, sticky="ew", padx=10, pady=(4, 10))

        def toggle(parent, text, var):
            return tk.Checkbutton(parent, text=text, variable=var,
                                  bg=PANEL, activebackground=PANEL,
                                  selectcolor=PANEL, fg=TEXT,
                                  font=("Segoe UI", 10))

        self._mirror_var = tk.BooleanVar()
        self._show_var   = tk.BooleanVar()
        self._gpu_var    = tk.BooleanVar()

        toggle(tog, "Mirror",         self._mirror_var).pack(side="left", padx=8)
        toggle(tog, "Preview window", self._show_var  ).pack(side="left", padx=8)
        self._gpu_cb = toggle(tog, "GPU accel", self._gpu_var)
        self._gpu_cb.pack(side="left", padx=8)
        self._gpu_badge = tk.Label(tog, text="(unavailable — pip mediapipe is CPU-only on Windows)",
                                   font=("Segoe UI", 8), bg=PANEL, fg=MUTED)
        self._gpu_badge.pack(side="left")

        # Refresh + Reset row
        btn_row = tk.Frame(self, bg=DARK)
        btn_row.pack(pady=(6, 2))
        tk.Button(btn_row, text="↻  Refresh cameras & monitors",
                  font=("Segoe UI", 9), bg=PANEL, fg=MUTED,
                  relief="flat", bd=0, activebackground=PANEL,
                  cursor="hand2", command=self._refresh).pack(side="left", padx=(0, 12))
        tk.Button(btn_row, text="⟳  Reset to defaults",
                  font=("Segoe UI", 9), bg=PANEL, fg=MUTED,
                  relief="flat", bd=0, activebackground=PANEL,
                  cursor="hand2", command=self._reset_defaults).pack(side="left")

        # Status
        self._dot = tk.Label(self, text="●", font=("Segoe UI", 13), bg=DARK, fg=RED)
        self._dot.pack()
        self._status_var = tk.StringVar(value="Stopped")
        tk.Label(self, textvariable=self._status_var,
                 font=("Segoe UI", 10), bg=DARK, fg=MUTED).pack(pady=(0, 6))

        # Start/stop
        self._btn = tk.Button(self, text="▶  Start tracking",
                              font=("Segoe UI", 12, "bold"),
                              bg=ACCENT, fg="#ffffff", relief="flat", bd=0,
                              activebackground="#6a4de0", padx=28, pady=10,
                              cursor="hand2", command=self._toggle)
        self._btn.pack(pady=(4, 16))

        # Log
        lf = tk.Frame(self, bg=DARK)
        lf.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        self._log = tk.Text(lf, height=7, bg="#12121c", fg=MUTED,
                             font=("Cascadia Mono", 9), relief="flat",
                             bd=0, state="disabled", wrap="word")
        sb = ttk.Scrollbar(lf, command=self._log.yview)
        self._log.configure(yscrollcommand=sb.set)
        self._log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # ── settings load / save ──────────────────────────────────────────────────

    def _apply_settings(self, s: dict):
        """Push a settings dict into all the UI variables."""
        self._saving = True
        try:
            # camera — fall back to first detected if saved value not present
            cam = s.get("camera")
            self._cam_var.set(cam if cam in self._cameras else self._cameras[0])

            mon = s.get("monitor")
            self._mon_var.set(mon if mon in self._monitors else self._monitors[0])

            res = s.get("resolution", DEFAULTS["resolution"])
            valid_res = [r[0] for r in RESOLUTIONS]
            self._res_var.set(res if res in valid_res else DEFAULTS["resolution"])

            fps = s.get("fps", DEFAULTS["fps"])
            self._fps_var.set(fps if fps in FPS_OPTIONS else DEFAULTS["fps"])

            hand = s.get("hand", DEFAULTS["hand"])
            self._hand_var.set(hand if hand in HAND_OPTIONS else DEFAULTS["hand"])

            sens = float(s.get("sensitivity", DEFAULTS["sensitivity"]))
            sens = max(0.1, min(20.0, sens))
            self._sens_var.set(sens)
            self._sens_entry_var.set(f"{sens:.1f}")

            scroll = float(s.get("scroll_speed", DEFAULTS["scroll_speed"]))
            scroll = max(0.5, min(10.0, scroll))
            self._scroll_var.set(scroll)
            self._scroll_entry_var.set(f"{scroll:.1f}")

            mode = s.get("mode", DEFAULTS["mode"])
            self._mode_var.set(mode if mode in MODE_OPTIONS else DEFAULTS["mode"])

            self._mirror_var.set(bool(s.get("mirror", DEFAULTS["mirror"])))
            self._show_var.set(bool(s.get("show",   DEFAULTS["show"])))
            self._gpu_var.set(bool(s.get("gpu",     DEFAULTS["gpu"])))
        finally:
            self._saving = False

    def _collect_settings(self) -> dict:
        """Read all UI variables into a plain dict."""
        return {
            "camera":       self._cam_var.get(),
            "monitor":      self._mon_var.get(),
            "resolution":   self._res_var.get(),
            "fps":          self._fps_var.get(),
            "hand":         self._hand_var.get(),
            "sensitivity":  round(self._sens_var.get(), 2),
            "scroll_speed": round(self._scroll_var.get(), 2),
            "mode":         self._mode_var.get(),
            "mirror":       self._mirror_var.get(),
            "show":         self._show_var.get(),
            "gpu":          self._gpu_var.get(),
        }

    def _save(self, *_):
        if self._saving:
            return
        save_settings(self._collect_settings())

    def _attach_save_traces(self):
        """Watch every variable and write settings.json on any change."""
        for var in (self._cam_var, self._mon_var, self._res_var,
                    self._fps_var, self._hand_var, self._mode_var,
                    self._sens_var, self._scroll_var,
                    self._mirror_var, self._show_var, self._gpu_var):
            var.trace_add("write", self._save)

    def _reset_defaults(self):
        self._apply_settings(dict(DEFAULTS))
        save_settings(self._collect_settings())
        self._log_append("Settings reset to defaults.\n")

    # ── GPU probe ─────────────────────────────────────────────────────────────

    def _probe_gpu(self):
        gpu = detect_gpu()
        def _apply():
            if gpu:
                self._gpu_badge.config(text=f"({gpu} detected)")
                # only override saved setting if this is a fresh run (no saved file)
                if not os.path.exists(SETTINGS_FILE):
                    self._gpu_var.set(True)
            else:
                self._gpu_badge.config(text="(no GPU found)")
        self.after(0, _apply)

    # ── refresh ───────────────────────────────────────────────────────────────

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
        self._cam_menu.delete(0, "end")
        for v in cams:
            self._cam_menu.add_command(label=v, command=lambda val=v: self._cam_var.set(val))
        self._cam_var.set(cams[0] if cams else "")
        self._mon_menu.delete(0, "end")
        for v in mons:
            self._mon_menu.add_command(label=v, command=lambda val=v: self._mon_var.set(val))
        self._mon_var.set(mons[0] if mons else "")
        self._log_append(f"Found {len(cams)} camera(s), {len(mons)} monitor(s)\n")

    # ── start / stop ──────────────────────────────────────────────────────────

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

    def _tracking_mode(self):
        """Extract 'relative' or 'absolute' from the display label."""
        label = self._mode_var.get()
        return "absolute" if label.startswith("absolute") else "relative"

    def _mon_index(self):
        try:
            return int(self._mon_var.get().split(":")[0].strip())
        except Exception:
            return 0

    def _start(self):
        w, h = self._res_wh()
        py = PYTHON.replace("pythonw.exe", "python.exe")
        cmd = [
            py, SCRIPT,
            "--camera",      self._cam_var.get(),
            "--width",       w,
            "--height",      h,
            "--fps",         self._fps_var.get(),
            "--hand",        self._hand_var.get(),
            "--monitor",     str(self._mon_index()),
            "--sensitivity",  f"{self._sens_var.get():.2f}",
            "--scroll-speed", f"{self._scroll_var.get():.2f}",
            "--mode",         self._tracking_mode(),
        ]
        if self._mirror_var.get(): cmd.append("--mirror")
        if self._show_var.get():   cmd.append("--show")
        if self._gpu_var.get():    cmd.append("--gpu")

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
