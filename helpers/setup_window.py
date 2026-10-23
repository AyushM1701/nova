"""Nova's macOS setup window: setup.sh finds Python, then this window does the rest with visible progress
(libraries, speech models, the voices and "Hey Nova", Nova.app, self-checks) and opens Nova, whose own screens
handle the microphone, your AI, the shortcut and macOS permissions. Stdlib + tkinter only.

    python3 helpers/setup_window.py
"""
import os
import platform
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV, PY = ROOT / ".venv", ROOT / ".venv" / "bin" / "python"
APP = Path.home() / "Applications" / "Nova.app"
MODEL_BYTES = int(2.1 * 2**30)  # approximate size of the two speech models, only used for the progress label

BG, FG, DIM, ACCENT, TRACK, BAD = "#131528", "#eef0fa", "#a4a8c2", "#7b6dff", "#262a42", "#ff7a7a"
INFO_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Nova</string>
  <key>CFBundleIdentifier</key><string>com.nova.assistant</string>
  <key>CFBundleExecutable</key><string>Nova</string>
  <key>CFBundleIconFile</key><string>Nova</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSUIElement</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>Nova listens for "Hey Nova" and your requests. Audio never leaves this Mac.</string>
  <key>NSScreenCaptureUsageDescription</key><string>Nova looks at your screen only when you ask about it.</string>
  <key>NSAppleEventsUsageDescription</key><string>Nova controls apps when you ask it to.</string>
</dict></plist>
"""


class Window:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Nova setup")
        self.root.configure(bg=BG)
        self.root.geometry("560x262")
        self.root.resizable(False, False)
        self.lines, self.cancelled, self.proc = queue.Queue(), False, None
        self.title = tk.Label(self.root, text="Installing Nova", bg=BG, fg=FG, font=("Helvetica", 20, "bold"))
        self.title.place(x=28, y=22)
        # wraps to a second line: errors and the closing message are longer than the window is wide
        self.status = tk.Label(self.root, text="Getting ready", bg=BG, fg=DIM, font=("Helvetica", 13),
                               wraplength=504, justify="left", anchor="nw")
        self.status.place(x=28, y=64, width=504, height=42)
        self.track = tk.Canvas(self.root, width=504, height=6, bg=TRACK, highlightthickness=0)
        self.track.place(x=28, y=112)
        self.fill = self.track.create_rectangle(0, 0, 0, 6, fill=ACCENT, width=0)
        self.detail = tk.Label(self.root, text="", bg=BG, fg=DIM, font=("Helvetica", 11), anchor="w", width=70)
        self.detail.place(x=28, y=128)
        self.log = tk.Text(self.root, height=6, bg="#0a0c16", fg=DIM, font=("Menlo", 10), relief="flat")
        self.button = tk.Button(self.root, text="Cancel", command=self.on_button, highlightbackground=BG)
        self.button.place(x=440, y=212)
        self.toggle = tk.Label(self.root, text="Show details", bg=BG, fg=DIM, cursor="hand2")
        self.toggle.place(x=28, y=217)
        self.toggle.bind("<Button-1>", lambda _: self.show_log(not self.log.winfo_ismapped()))
        self.root.protocol("WM_DELETE_WINDOW", self.on_button)
        self.root.bind("<Escape>", lambda _: self.on_button())
        self.done = False

    def show_log(self, on):
        if on:
            self.root.geometry("560x412")
            self.log.place(x=28, y=156, width=504, height=150)
            self.button.place(y=362)
            self.toggle.place(y=367)
            self.toggle.config(text="Hide details")
        else:
            self.log.place_forget()
            self.root.geometry("560x262")
            self.button.place(y=212)
            self.toggle.place(y=217)
            self.toggle.config(text="Show details")

    def on_button(self):
        if self.done:
            self.root.destroy()
        else:
            self.cancelled = True
            if self.proc:
                self.proc.terminate()

    def ui(self, fn):
        self.lines.put(fn)

    def pump(self):
        while not self.lines.empty():
            self.lines.get_nowait()()
        self.root.after(80, self.pump)

    def note(self, line):
        self.ui(lambda: (self.log.insert("end", line + "\n"), self.log.see("end")))

    def run(self, *args, cwd=ROOT):
        """Run one step, streaming its output into the details box. Returns the exit code."""
        if self.cancelled:
            raise RuntimeError("Setup was cancelled.")
        self.note("> " + " ".join(map(str, args)))
        self.proc = subprocess.Popen([str(a) for a in args], cwd=cwd, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, errors="replace")
        for line in self.proc.stdout:
            if line.strip():
                self.note(line.rstrip()[:300])
                if line.strip().endswith("MB"):
                    self.ui(lambda l=line.strip(): self.detail.config(text=l))
        code = self.proc.wait()
        if self.cancelled:
            raise RuntimeError("Setup was cancelled.")
        return code


def show_part(win, stop, part, label, size_mb):
    """How far one model download has got, from its .part file, once a second."""
    win.ui(lambda: win.detail.config(text=f"{label} (about {size_mb} MB)"))
    while not stop.wait(1):
        try:
            got = part.stat().st_size >> 20
        except OSError:  # not started yet, or finished and unpacked
            continue
        win.ui(lambda g=got: win.detail.config(text=f"{label}: {g} of about {size_mb} MB"))


def show_download(win, stop):
    """Counts what has arrived in the Hugging Face cache once a second (the download itself prints nothing)."""
    hub = Path.home() / ".cache" / "huggingface" / "hub"  # shortcut: ignores a custom HF_HOME, only feeds this label
    dirs = [hub / "models--Systran--faster-whisper-small", hub / "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"]
    while not stop.wait(1):
        try:
            size = sum(f.stat().st_size for d in dirs if d.exists() for f in d.rglob("*")
                       if f.is_file() and not f.is_symlink())  # snapshots/ links to blobs/: count each file once
        except OSError:  # a partial file was renamed mid-count: try again next second
            continue
        win.ui(lambda s=size: win.detail.config(text=f"{s >> 20:,} MB of about {MODEL_BYTES >> 20:,} MB"))


def make_app(run):
    """Write ~/Applications/Nova.app (run(*args) runs a command). Returns whether anything in it changed.
    helpers/check_mac.py builds it twice to check that an unchanged app is left alone."""
    (APP / "Contents" / "MacOS").mkdir(parents=True, exist_ok=True)
    (APP / "Contents" / "Resources").mkdir(parents=True, exist_ok=True)
    launcher = APP / "Contents" / "MacOS" / "Nova"  # a tiny app, so macOS asks permissions for "Nova"
    # macOS opens an app whose program is a script under Rosetta on Apple chips, where libraries installed for arm64
    # won't load: run Python as the architecture setup installed them for
    script = f'#!/bin/bash\ncd "{ROOT}" && exec /usr/bin/arch -{platform.machine()} "{PY}" "{ROOT / "nova.py"}"\n'
    drawn = ROOT / "data" / "Nova.icns"
    drawn.parent.mkdir(exist_ok=True)
    run(PY, "-m", "core.icon", drawn)
    # macOS remembers permissions for this exact app, so an update rewrites it only if something really changed:
    # an unchanged app keeps its Microphone, Accessibility... permissions, a changed one may have to ask again
    changed = False
    for path, data in ((launcher, script.encode()), (APP / "Contents" / "Info.plist", INFO_PLIST.encode()),
                       (APP / "Contents" / "Resources" / "Nova.icns", drawn.read_bytes() if drawn.exists() else b"")):
        if data and (not path.exists() or path.read_bytes() != data):
            path.write_bytes(data)
            changed = True
    launcher.chmod(0o755)
    if changed:  # signed on this Mac ("ad hoc") under a fixed name, so it's the same Nova from one update to the next
        run("codesign", "--force", "--sign", "-", "--identifier", "com.nova.assistant", APP)
    return changed


def steps(win):
    total = 6

    def step(n, text, detail=""):
        win.ui(lambda: (win.status.config(text=f"Step {n} of {total}: {text}"), win.detail.config(text=detail),
                        win.track.coords(win.fill, 0, 0, 504 * (n - 1) / total, 6)))
        win.note(f"== {text}")

    step(1, "Creating Nova's own Python environment")
    if not PY.exists() and win.run(sys.executable, "-m", "venv", VENV) != 0:
        raise RuntimeError("Couldn't create Nova's Python environment (see details).")
    step(2, "Installing libraries", "This takes a minute or two the first time.")
    if win.run(PY, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--prefer-binary",
               "-r", ROOT / "requirements.txt") != 0:
        raise RuntimeError("Installing libraries failed. Check your internet connection; the details say more.")
    os.chmod(ROOT / "helpers" / "clipboard.sh", 0o755)
    step(3, "Downloading the speech models (about 2 GB, once)")
    stop = threading.Event()
    threading.Thread(target=show_download, args=(win, stop), daemon=True).start()
    try:
        failed = win.run(PY, "-c", "from faster_whisper.utils import download_model as d; d('small'); d('large-v3-turbo')") != 0
    finally:
        stop.set()
    if failed:
        raise RuntimeError("Downloading the speech models failed. Check your internet connection and try again.")
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "models-ready").touch()
    # Piper speaks by default and Kitten is the light choice; Kokoro (330 MB) downloads only if picked in Settings
    step(4, "Downloading Nova's voices and \"Hey Nova\" (about 110 MB, once)")
    for name, label, size, folder in (("piper", "Piper voice", 64, "tts"), ("kitten", "Kitten voice", 25, "tts"),
                                      ("kws", "\"Hey Nova\"", 18, "models")):
        stop = threading.Event()
        part = ROOT / "data" / folder / f"{name}.part"  # core/models.py downloads into <name>.part first
        threading.Thread(target=show_part, args=(win, stop, part, label, size), daemon=True).start()
        try:
            failed = win.run(PY, "-m", "core.models", "download", name) != 0
        finally:
            stop.set()
        if failed:
            win.note(f"{label} didn't download. Nova uses what it has (the macOS voice at worst); Settings can retry.")
    step(5, "Adding Nova to your Applications")
    make_app(win.run)
    step(6, "Running Nova's self-checks")
    if win.run(PY, ROOT / "tests.py") != 0:
        raise RuntimeError("Nova's self-checks failed (see details). Please report this.")
    subprocess.run(["pkill", "-f", str(ROOT / "nova.py")])  # an update: start again on the new code
    time.sleep(1)  # until the old copy lets go of its single-instance port, or the new one just exits
    subprocess.Popen(["open", "-a", str(APP)])


def main():
    win = Window()

    def work():
        try:
            steps(win)
            win.ui(lambda: (win.track.coords(win.fill, 0, 0, 504, 6), win.title.config(text="Nova is installed"), win.status.config(
                text="Nova is opening. It will walk you through the microphone, your AI, the shortcut and permissions."),
                win.detail.config(text="Nova lives in the menu bar."), win.button.config(text="Close"),
                win.root.after(6000, win.root.destroy)))
        except Exception as e:
            message = str(e)
            win.note(f"ERROR: {message}")
            win.ui(lambda: (win.title.config(text="Setup cancelled" if win.cancelled else "Setup stopped"),
                            win.track.itemconfig(win.fill, fill=BAD), win.status.config(text=message, fg=BAD), win.button.config(text="Close"), win.show_log(True),
                            (ROOT / "data" / "setup.log").write_text(win.log.get("1.0", "end"), encoding="utf-8")))
            (ROOT / "data").mkdir(exist_ok=True)
        finally:
            win.done = True

    threading.Thread(target=work, daemon=True).start()
    win.root.after(80, win.pump)
    win.root.lift()
    win.root.attributes("-topmost", True)
    win.root.after(500, lambda: win.root.attributes("-topmost", False))
    win.root.mainloop()


if __name__ == "__main__":
    if shutil.which("open") is None:
        sys.exit("This setup window is for macOS. On Windows, double-click setup.cmd.")
    main()
