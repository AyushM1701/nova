"""Everything that differs between Windows and macOS, in one place."""
import os
import shlex
import subprocess
import sys

IS_MAC = sys.platform == "darwin"

if IS_MAC:
    from AppKit import NSApplication, NSScreen, NSWorkspace
    from pynput import keyboard as pk

    _keys = pk.Controller()
    MEDIA = {"play_pause": pk.Key.media_play_pause, "next": pk.Key.media_next, "previous": pk.Key.media_previous,
             "mute": pk.Key.media_volume_mute, "volume_up": pk.Key.media_volume_up,
             "volume_down": pk.Key.media_volume_down}
else:
    import ctypes
    import ctypes.wintypes
    import winsound

    import keyboard

    user32 = ctypes.windll.user32
    MEDIA = {"play_pause": "play/pause media", "next": "next track", "previous": "previous track",
             "mute": "volume mute", "volume_up": "volume up", "volume_down": "volume down"}

DEFAULT_HOTKEY = "cmd+shift+space" if IS_MAC else "ctrl+alt+space"
NO_WINDOW = 0 if IS_MAC else subprocess.CREATE_NO_WINDOW  # creationflags for child processes


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
    """Global shortcut plus Esc. Windows swallows the shortcut; macOS needs Input Monitoring permission."""

    def __init__(self, combo, on_hotkey, on_esc):
        if IS_MAC:
            fmt = "+".join(f"<{k}>" if len(k) > 1 else k for k in combo.lower().split("+"))
            self.listener = pk.GlobalHotKeys({fmt: on_hotkey, "<esc>": on_esc})
            self.listener.start()
        else:
            keyboard.add_hotkey(combo, on_hotkey, suppress=True)
            keyboard.add_hotkey("esc", on_esc)


def beep(start):
    if IS_MAC:
        subprocess.Popen(["afplay", "/System/Library/Sounds/" + ("Tink.aiff" if start else "Pop.aiff")])
    else:
        winsound.Beep(880 if start else 660, 60)


def foreground():
    """The app the user is in now, so dictation can be typed back into it."""
    return NSWorkspace.sharedWorkspace().frontmostApplication() if IS_MAC else user32.GetForegroundWindow()


def focus(target):
    if not target:
        return
    if IS_MAC:
        target.activateWithOptions_(2)  # NSApplicationActivateIgnoringOtherApps
    else:
        user32.SetForegroundWindow(target)


def paste():
    if IS_MAC:
        with _keys.pressed(pk.Key.cmd):
            _keys.tap("v")
    else:
        keyboard.send("ctrl+v")


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


def open_path(path):
    if IS_MAC:
        subprocess.Popen(["open", str(path)])
    else:
        os.startfile(path)


def edit_file(path):
    subprocess.Popen(["open", "-t", str(path)] if IS_MAC else ["notepad", str(path)])


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
