"""Everything that differs between Windows and macOS, in one place."""
import os
import plistlib
import shlex
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np

IS_MAC = sys.platform == "darwin"

if IS_MAC:
    from AppKit import NSApplication, NSScreen, NSWorkspace
    from pynput import keyboard as pk

    _keys = pk.Controller()
    MAC_HOLD = {pk.Key.ctrl_r: "right ctrl", pk.Key.alt_r: "right alt", pk.Key.shift_r: "right shift"}
    MEDIA = {"play_pause": pk.Key.media_play_pause, "next": pk.Key.media_next, "previous": pk.Key.media_previous,
             "mute": pk.Key.media_volume_mute, "volume_up": pk.Key.media_volume_up,
             "volume_down": pk.Key.media_volume_down}
else:
    import ctypes
    import ctypes.wintypes
    import winreg

    import keyboard

    user32 = ctypes.windll.user32
    MEDIA = {"play_pause": "play/pause media", "next": "next track", "previous": "previous track",
             "mute": "volume mute", "volume_up": "volume up", "volume_down": "volume down"}

DEFAULT_HOTKEY = "cmd+shift+space" if IS_MAC else "ctrl+alt+space"
from core.config import NO_WINDOW  # noqa: E402,F401  (callers import it from here too)
# Nova runs under pythonw on Windows, which has no stdout; hooks and helpers must answer on stdout
CONSOLE_PYTHON = Path(sys.executable).with_name("python.exe") if os.name == "nt" else Path(sys.executable)


def before_tk():
    if not IS_MAC:
        try:  # crisp bar and card on scaled (125%, 150%) displays
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except OSError:
            pass


def after_tk():
    if IS_MAC:  # menu-bar app: no Dock icon, and showing the bar doesn't steal focus
        NSApplication.sharedApplication().setActivationPolicy_(1)  # NSApplicationActivationPolicyAccessory


class Hotkeys:
    """Global shortcut plus Esc. Windows swallows the shortcut; macOS needs Input Monitoring permission.
    Raises ValueError for a shortcut that can't be parsed."""

    def __init__(self, combo, on_hotkey, on_esc):
        self.combo = combo
        if IS_MAC:
            fmt = "+".join(f"<{k}>" if len(k) > 1 else k for k in combo.lower().split("+"))
            self.listener = pk.GlobalHotKeys({fmt: on_hotkey, "<esc>": on_esc})
            self.listener.start()
        else:
            self.handles = [keyboard.add_hotkey(combo, on_hotkey, suppress=True)]
            self.handles.append(keyboard.add_hotkey("esc", on_esc))

    def stop(self):
        if IS_MAC:
            self.listener.stop()
        else:
            for h in self.handles:
                keyboard.remove_hotkey(h)


HOLD_KEYS = ("right ctrl", "right alt", "right shift")
HOLD_DELAY_S = 0.25  # a quick tap, or the key used in a combo, never starts listening


class HoldKey:
    """Hold-to-talk on one modifier key on its own: hold it a moment and Nova listens, let go and it stops.
    Pressed together with another key (Right Ctrl+C) it stays an ordinary shortcut: the key is never swallowed."""

    def __init__(self, key, on_start, on_stop):
        self.key, self.on_start, self.on_stop = key.lower(), on_start, on_stop
        self.held = self.started = False
        self.timer, self.lock = None, threading.Lock()
        if IS_MAC:
            name = lambda k: MAC_HOLD.get(k, str(k))
            self.listener = pk.Listener(on_press=lambda k: self.event(name(k), True),
                                        on_release=lambda k: self.event(name(k), False))
            self.listener.start()
        else:
            self.hook = keyboard.hook(lambda e: self.event(e.name, e.event_type == "down"))

    def event(self, name, down):
        name = (name or "").lower()
        with self.lock:
            if name != self.key and not (self.key == "right alt" and name == "alt gr"):  # AltGr on many layouts
                if down and self.held and not self.started:  # a combo: leave it to the app
                    self.held = False
                    self.timer and self.timer.cancel()
                return
            if down:
                if not self.held:  # held keys repeat their key-down
                    self.held, self.started = True, False
                    self.timer = threading.Timer(HOLD_DELAY_S, self.fire)
                    self.timer.start()
                return
            self.held = False
            self.timer and self.timer.cancel()
            stop, self.started = self.started, False
        if stop:
            self.on_stop()

    def fire(self):
        with self.lock:
            if not self.held:
                return
            self.started = True
        self.on_start()

    def stop(self):
        self.timer and self.timer.cancel()
        if IS_MAC:
            self.listener.stop()
        else:
            keyboard.unhook(self.hook)


def pretty_hotkey(combo):
    """'ctrl+alt+space' -> 'Ctrl+Alt+Space', for showing the shortcut to people."""
    names = {"ctrl": "Ctrl", "alt": "Option" if IS_MAC else "Alt", "cmd": "Cmd", "shift": "Shift",
             "windows": "Win", "win": "Win", "space": "Space", "esc": "Esc", "enter": "Enter", "tab": "Tab"}
    return "+".join(names.get(k, k.upper() if len(k) <= 3 else k.title()) for k in combo.lower().split("+"))


def _chime(freqs, seconds=0.07, rate=44100):
    """A short, soft two-note chime (sine with a fade): gentler than the PC-speaker beep."""
    t = np.arange(int(seconds * rate)) / rate
    fade = np.minimum(1, np.minimum(t, seconds - t) / 0.012)
    return np.concatenate([0.18 * np.sin(2 * np.pi * f * t) * fade for f in freqs]).astype(np.float32)


CHIMES = {True: _chime((660, 990)), False: _chime((880, 587))}


def beep(start):
    import sounddevice as sd  # lazy: the app window imports this module without needing audio
    try:
        sd.play(CHIMES[start], 44100)
        if start:
            sd.wait()  # finish before recording, so the chime isn't measured as the room's noise
    except Exception:  # no speakers: the bar still shows the state
        pass


def foreground():
    """The app the user is in now, so dictation can be typed back into it."""
    return NSWorkspace.sharedWorkspace().frontmostApplication() if IS_MAC else user32.GetForegroundWindow()


def focus(target):
    if not target:
        return
    if IS_MAC:
        target.activateWithOptions_(2)  # NSApplicationActivateIgnoringOtherApps
    elif user32.GetForegroundWindow() != target:  # focus moved while Nova listened or thought
        bring_front(target)


def paste():
    if IS_MAC:
        with _keys.pressed(pk.Key.cmd):
            _keys.tap("v")
    else:
        keyboard.send("ctrl+v")


def copy():
    if IS_MAC:
        with _keys.pressed(pk.Key.cmd):
            _keys.tap("c")
    else:
        keyboard.send("ctrl+c")


def raise_app(exe):
    """Bring a running program's front window to the front, restoring it if it's minimized (Windows; e.g. the
    browser after Nova opened a page in it). False if it has no open window."""
    if IS_MAC or not exe:
        return False
    kernel32, name, found = ctypes.windll.kernel32, Path(exe).name.lower(), []

    def each(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) and not user32.GetWindow(hwnd, 4):
            pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            proc = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
            if proc:
                buf, size = ctypes.create_unicode_buffer(1024), ctypes.wintypes.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(proc, 0, buf, ctypes.byref(size)) and \
                        Path(buf.value).name.lower() == name:
                    found.append(hwnd)
                kernel32.CloseHandle(proc)
        return not found  # windows come front to back: the first match is the one used last

    user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)(each), 0)
    if not found:
        return False
    hwnd = found[0]
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    return bring_front(hwnd)


def bring_front(hwnd):
    # Windows lets only the app in front hand the front to another; sharing its input for a moment allows it
    here, front = ctypes.windll.kernel32.GetCurrentThreadId(), user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    attached = front and front != here and user32.AttachThreadInput(here, front, True)
    try:
        user32.BringWindowToTop(hwnd)
        return bool(user32.SetForegroundWindow(hwnd))
    finally:
        if attached:
            user32.AttachThreadInput(here, front, False)


def window_title(target):
    """The app (macOS) or window title (Windows) the user was in, as context for the AI."""
    if not target:
        return ""
    if IS_MAC:
        return str(target.localizedName() or "")
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(target, buf, 512)
    return buf.value


def window_rect(target):
    """(left, top, right, bottom) of the user's window on Windows, or None (macOS: the whole screen is used)."""
    if IS_MAC or not target:
        return None
    rect = ctypes.wintypes.RECT()
    if not user32.GetWindowRect(target, ctypes.byref(rect)) or rect.right - rect.left < 50:
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def screenshot(path, box=None):
    """Save every screen, or just `box` (screen pixels), as a PNG. macOS asks for Screen Recording permission
    the first time."""
    from PIL import ImageGrab
    if IS_MAC:
        img = ImageGrab.grab()  # shortcut: main display only on macOS; screencapture -D per display if asked
        k, left, top = img.width / screen_width(), 0, 0  # Retina Macs grab twice the pixels Tk reports
    else:  # all monitors, so a window on the second screen is captured too; boxes are virtual-screen pixels
        img = ImageGrab.grab(all_screens=True)
        k, left, top = 1, user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)  # SM_X/YVIRTUALSCREEN
    if box:
        img = img.crop((max(0, int((box[0] - left) * k)), max(0, int((box[1] - top) * k)),  # maximized windows
                        min(img.width, int((box[2] - left) * k)), min(img.height, int((box[3] - top) * k))))  # overhang
    img.save(path)
    return path


def screen_width():
    return int(NSScreen.mainScreen().frame().size.width) if IS_MAC else user32.GetSystemMetrics(0)


def refresh_path(env=None):
    """Re-read PATH, so a CLI or Node.js installed while Nova runs is found without a restart."""
    if IS_MAC:
        # an app opened from Finder gets a bare PATH; the login shell's has nvm, npm and Homebrew in it
        try:
            shell = subprocess.run([os.environ.get("SHELL", "/bin/zsh"), "-ilc", "echo $PATH"], capture_output=True,
                                   text=True, timeout=5, stdin=subprocess.DEVNULL).stdout.strip().splitlines()
        except (OSError, subprocess.TimeoutExpired):
            shell = []
        home = Path.home()
        extra = (shell[-1].split(os.pathsep) if shell else []) + [
            str(home / ".local" / "bin"), str(home / ".npm-global" / "bin"), "/opt/homebrew/bin", "/usr/local/bin"]
        path = os.pathsep.join(p for p in dict.fromkeys(os.environ.get("PATH", "").split(os.pathsep) + extra) if p)
    else:
        parts = []
        for hive, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                          (winreg.HKEY_CURRENT_USER, "Environment")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    parts.append(os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]))
            except OSError:
                pass
        path = os.pathsep.join(parts) or os.environ.get("PATH", "")
    os.environ["PATH"] = path
    if env is not None:
        env["PATH"] = path


def media(name, times=1):
    for _ in range(times):
        if IS_MAC:
            _keys.tap(MEDIA[name])
        else:
            keyboard.send(MEDIA[name])


def set_volume(percent):
    percent = max(0, min(100, percent))
    if IS_MAC:
        subprocess.run(["osascript", "-e", f"set volume output volume {percent}"])
    else:
        # shortcut: each key press moves Windows volume 2%; use the Core Audio API if exact levels matter
        media("volume_down", 50)
        media("volume_up", percent // 2)


# apps people name that aren't Start-menu shortcuts on Windows
WIN_APPS = {"calculator": "calc", "calc": "calc", "notepad": "notepad", "paint": "mspaint", "settings": "ms-settings:",
            "file explorer": "explorer", "explorer": "explorer", "files": "explorer", "task manager": "taskmgr",
            "terminal": "wt", "command prompt": "cmd", "control panel": "control", "snipping tool": "snippingtool",
            "camera": "microsoft.windows.camera:", "clock": "ms-clock:", "photos": "ms-photos:", "store": "ms-windows-store:",
            "microsoft store": "ms-windows-store:", "mail": "outlookmail:", "spotify": "spotify:", "whatsapp": "whatsapp:"}
ALIASES = {"vs code": "visual studio code", "vscode": "visual studio code", "code": "visual studio code",
           "chrome": "google chrome", "edge": "microsoft edge", "word": "word", "excel": "excel", "opera": "opera gx"}


def open_app(name):
    """Open an installed app by its spoken name. False if Nova can't find it (then the AI takes over)."""
    name = ALIASES.get(name.lower(), name.lower())
    if IS_MAC:
        return subprocess.run(["open", "-a", name], capture_output=True).returncode == 0
    roots = [Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
             Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"]
    links = [p for root in roots if root.exists() for p in root.rglob("*") if p.suffix.lower() in (".lnk", ".url")]
    words = lambda s: s.lower().replace("-", " ").split()
    for rank in (lambda s: s.lower() == name, lambda s: s.lower().startswith(name),
                 lambda s: all(w in words(s) for w in name.split())):
        hits = sorted((p for p in links if rank(p.stem) and "uninstall" not in p.stem.lower()), key=lambda p: len(p.stem))
        if hits:
            os.startfile(hits[0])
            return True
    if name in WIN_APPS:
        os.startfile(WIN_APPS[name]) if ":" in WIN_APPS[name] else subprocess.Popen(WIN_APPS[name], shell=True)
        return True
    return False


def open_url(url):
    subprocess.Popen(["open", url]) if IS_MAC else os.startfile(url)


def lock_screen():
    if IS_MAC:  # Ctrl+Cmd+Q, macOS's own Lock Screen shortcut (sleeping the display only locks with a setting)
        with _keys.pressed(pk.Key.ctrl, pk.Key.cmd):
            _keys.tap("q")
    else:
        user32.LockWorkStation()


def open_path(path):
    if IS_MAC:
        subprocess.Popen(["open", str(path)])
    else:
        os.startfile(path)


def edit_file(path):
    subprocess.Popen(["open", "-t", str(path)] if IS_MAC else ["notepad", str(path)])


MAC_AGENT = Path.home() / "Library" / "LaunchAgents" / "com.nova.assistant.plist"
MAC_APP = Path.home() / "Applications" / "Nova.app"


def _startup_link():
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Nova.lnk"


def autostart_enabled():
    return MAC_AGENT.exists() if IS_MAC else _startup_link().exists()


def set_autostart(on, pythonw, script, icon):
    """Start Nova at login: a Startup-folder shortcut on Windows, a LaunchAgent on macOS."""
    if IS_MAC:
        if on:
            MAC_AGENT.parent.mkdir(parents=True, exist_ok=True)
            MAC_AGENT.write_bytes(plistlib.dumps({"Label": "com.nova.assistant", "RunAtLoad": True,
                                                  "ProgramArguments": ["/usr/bin/open", "-a", str(MAC_APP)]}))
        else:
            MAC_AGENT.unlink(missing_ok=True)
        return
    link = _startup_link()
    if not on:
        link.unlink(missing_ok=True)
        return
    # the paths travel in the environment, never inside the script text
    ps = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:NOVA_LNK); $s.TargetPath = $env:NOVA_PY; "
          "$s.Arguments = [char]34 + $env:NOVA_SCRIPT + [char]34; $s.WorkingDirectory = $env:NOVA_DIR; "
          "$s.IconLocation = $env:NOVA_ICON; $s.Description = 'Nova voice assistant'; $s.Save()")
    env = dict(os.environ, NOVA_LNK=str(link), NOVA_PY=str(pythonw), NOVA_SCRIPT=str(script),
               NOVA_DIR=str(Path(script).parent), NOVA_ICON=str(icon))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, capture_output=True,
                   creationflags=NO_WINDOW, check=True)


def on_ac_power():
    """Plugged in (a desktop PC counts as plugged in)."""
    if IS_MAC:
        return "AC Power" in subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout

    class Power(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
    power = Power()
    return not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(power)) or power.ACLineStatus != 0


_caffeinate = None


def keep_awake(on):
    """Stop idle sleep (the screen may still turn off), so a paired phone can reach Nova; or allow it again.
    Windows: call it from a thread that lives as long as Nova (the setting belongs to the calling thread)."""
    global _caffeinate
    if IS_MAC:
        if on and not _caffeinate:
            _caffeinate = subprocess.Popen(["caffeinate", "-s"])  # -s: stays awake only while on AC power
        elif not on and _caffeinate:
            _caffeinate.terminate()
            _caffeinate = None
    else:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | (0x00000001 if on else 0))  # ES_CONTINUOUS|SYSTEM


def work_area():
    """(left, top, right, bottom) of the screen minus taskbar/Dock, in Tk coordinates."""
    if IS_MAC:
        screen = NSScreen.mainScreen()
        full, vis = screen.frame(), screen.visibleFrame()
        top = full.size.height - (vis.origin.y + vis.size.height)
        return (vis.origin.x, top, vis.origin.x + vis.size.width, full.size.height - vis.origin.y)
    rect = ctypes.wintypes.RECT()
    user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
    return rect.left, rect.top, rect.right, rect.bottom


def notch():
    """(width, height) in points of a MacBook's camera notch, or (0, 0) without one (and on Windows)."""
    if not IS_MAC:
        return 0, 0
    try:
        screen = NSScreen.mainScreen()
        top = screen.safeAreaInsets().top  # macOS 12+: the strip the notch takes
        if top <= 0:
            return 0, 0
        left, right = screen.auxiliaryTopLeftArea().size.width, screen.auxiliaryTopRightArea().size.width
        return int(screen.frame().size.width - left - right), int(top)
    except AttributeError:  # older macOS: no notch API, and no notch either
        return 0, 0


def screen_span():
    """(left, right) of the whole main screen, in the same coordinates as work_area()."""
    if IS_MAC:
        frame = NSScreen.mainScreen().frame()
        return frame.origin.x, frame.origin.x + frame.size.width
    return 0, user32.GetSystemMetrics(0)


def no_activate(tk_window, layered=False):
    """Make a Tk window clickable but never focused (Windows). Returns its native handle."""
    if IS_MAC:
        return None
    tk_window.update_idletasks()
    hwnd = user32.GetParent(tk_window.winfo_id())
    style = user32.GetWindowLongW(hwnd, -20) | 0x08000000 | 0x80  # WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
    user32.SetWindowLongW(hwnd, -20, style | (0x80000 if layered else 0))  # WS_EX_LAYERED
    return hwnd


def show(tk_window, hwnd):
    if hwnd:
        user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
    else:
        tk_window.deiconify()


def hide(tk_window, hwnd):
    if hwnd:
        user32.ShowWindow(hwnd, 0)
    else:
        tk_window.withdraw()


def hook_command(python, script):
    """Shell command line for a CLI hook. 8.3 short paths on Windows: no quotes, so any shell runs it."""
    if IS_MAC:
        return f"{shlex.quote(str(python))} {shlex.quote(str(script))}"
    def short(path):
        buf = ctypes.create_unicode_buffer(1024)
        p = (buf.value if ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, 1024) else str(path))
        p = p.replace("\\", "/")
        return f'"{p}"' if " " in p else p  # 8.3 names can be disabled on a drive: quote as a last resort
    return f"{short(python)} {short(script)}"
