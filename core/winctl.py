"""Close and arrange windows by spoken name, with no AI. Windows only; on macOS these return False (the AI handles them)."""
import atexit
import contextlib
import ctypes
import os
import sys
import threading
from pathlib import Path

from core.system import IS_MAC

if not IS_MAC:
    import ctypes.wintypes as wt
    user32 = ctypes.windll.user32
    WM_CLOSE = 0x0010
    SW_RESTORE, SW_MAXIMIZE = 9, 3
    # what people say -> the program's name, which is all a window is matched by (its title is the page or document
    # open in it: "close YouTube" must never close the browser window that happens to be showing a YouTube tab)
    PROGRAMS = {"chrome": "chrome", "google chrome": "chrome", "vs code": "code", "vscode": "code", "visual studio code": "code",
                "code": "code", "edge": "msedge", "microsoft edge": "msedge", "terminal": "windowsterminal",
                "windows terminal": "windowsterminal", "explorer": "explorer", "file explorer": "explorer",
                "files": "explorer", "opera": "opera", "opera gx": "opera", "calculator": "calculatorapp",
                "settings": "systemsettings", "word": "winword", "powerpoint": "powerpnt"}


def _image(pid):
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    path, size = ctypes.create_unicode_buffer(520), wt.DWORD(520)
    ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size))
    ctypes.windll.kernel32.CloseHandle(handle)
    return path.value if ok else ""


def _process_name(pid):
    return os.path.basename(_image(pid)).lower().removesuffix(".exe")


ROOT = Path(__file__).resolve().parents[1]


class _Entry(ctypes.Structure):  # PROCESSENTRY32W
    _fields_ = [("size", wt.DWORD), ("usage", wt.DWORD), ("pid", wt.DWORD), ("heap", ctypes.c_void_p), ("module", wt.DWORD),
                ("threads", wt.DWORD), ("parent", wt.DWORD), ("priority", ctypes.c_long), ("flags", wt.DWORD),
                ("exe", ctypes.c_wchar * 260)]


def _parents():
    """{pid: parent pid} of every running process."""
    kernel = ctypes.windll.kernel32
    kernel.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    snapshot = kernel.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    entry, parents = _Entry(size=ctypes.sizeof(_Entry)), {}
    more = kernel.Process32FirstW(ctypes.c_void_p(snapshot), ctypes.byref(entry))
    while more:
        parents[entry.pid] = entry.parent
        more = kernel.Process32NextW(ctypes.c_void_p(snapshot), ctypes.byref(entry))
    kernel.CloseHandle(ctypes.c_void_p(snapshot))
    return parents


def is_nova(pid):
    """Nova itself: this process, or a Python process it started (the companion window is a child process, `python -m core.app`,
    whose Settings change the safety mode: nothing the AI drives may reach it), or a program from Nova's own folder.
    By ancestry, because a venv's python.exe is a launcher and the window belongs to the interpreter behind it."""
    if IS_MAC:
        return pid == os.getpid()
    if pid == os.getpid():
        return True
    image = os.path.normcase(_image(pid))
    if image.startswith(os.path.normcase(str(ROOT)) + os.sep):
        return True
    if os.path.basename(image) not in ("python.exe", "pythonw.exe"):
        return False  # an app Nova opened (Notepad, Spotify) is the user's to drive; only Nova's own Python windows are not
    parents, here = _parents(), pid
    for _ in range(10):
        if here == os.getpid():
            return True
        here = parents.get(here, 0)
        if not here:
            return False
    return False


def _windows():
    """[(hwnd, title, process name)] for visible top-level windows with a title."""
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd):
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, 256)
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            process = _process_name(pid.value)
            if process:
                found.append((hwnd, title.value, process, pid.value))
        return True
    user32.EnumWindows(each, 0)
    return found


def owner(hwnd):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def process_of(hwnd):
    return _process_name(owner(hwnd))


def find_process(process):
    """The first visible window of a program by its exact process name (a window's title changes: Spotify's is the song)."""
    for hwnd, _, name, pid in _windows():
        if name == process and not is_nova(pid):
            return hwnd
    return None


def find(name):
    """The window hwnd for a spoken program name ("it", "this" = the front window), or None. Never by window title."""
    if IS_MAC:
        return None
    name = name.lower().strip()
    if name in ("it", "this", "that", "this window", "window"):
        front = user32.GetForegroundWindow()
        return front if front and not is_nova(owner(front)) else None  # never Nova's own window
    program = PROGRAMS.get(name, name).replace(" ", "")
    for hwnd, title, process, pid in _windows():
        if title == "Program Manager" or is_nova(pid):
            continue
        # a short word must be the whole program name ("x"), a longer one may be part of it ("spot" for spotify)
        if process == program or (len(program) >= 4 and program in process):
            return hwnd
    return None


def close(name):
    hwnd = find(name)
    if hwnd:
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)  # the app's own close, so it can still ask to save
    return bool(hwnd)


if not IS_MAC:
    class _Monitor(ctypes.Structure):
        _fields_ = [("size", wt.DWORD), ("monitor", wt.RECT), ("work", wt.RECT), ("flags", wt.DWORD)]


def place(name, where):
    """Snap an app's window to left | right | full | center of the screen it is on."""
    hwnd = find(name)
    if not hwnd:
        return False
    info = _Monitor(size=ctypes.sizeof(_Monitor))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info))
    r = info.work
    w, h = r.right - r.left, r.bottom - r.top
    user32.ShowWindow(hwnd, SW_RESTORE)
    if where == "full":
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
        return True
    x, width = {"left": (r.left, w // 2), "right": (r.left + w // 2, w // 2), "center": (r.left + w // 6, w * 2 // 3)}[where]
    user32.SetWindowPos(hwnd, 0, x, r.top, width, h, 0x0004)  # SWP_NOZORDER
    return True


_reader = {"uses": 0, "timer": None, "ours": False}  # ours: Nova raised the flag (a real screen reader's stays)
_reader_lock = threading.Lock()


def _reader_off(always=False):
    with _reader_lock:
        if _reader["ours"] and (always or not _reader["uses"]):
            user32.SystemParametersInfoW(0x47, 0, None, 2)
            _reader["ours"] = False


if not IS_MAC:  # quitting inside the linger must not leave the flag on for good
    atexit.register(lambda: _reader_off(always=True))


@contextlib.contextmanager
def screen_reader(linger=30):
    """Windows' screen-reader flag on, which makes Chromium and Electron apps (Spotify, Discord, VS Code) build their
    accessibility tree. It stays on `linger` seconds after the last use: switched off and on again within seconds, the
    app doesn't rebuild the tree in time, and a second command right after the first would find nothing."""
    set_flag = user32.SystemParametersInfoW
    with _reader_lock:
        if _reader["timer"]:
            _reader["timer"].cancel()
        _reader["uses"] += 1
        if not _reader["ours"]:
            already = ctypes.c_int(0)
            set_flag(0x46, 0, ctypes.byref(already), 0)  # SPI_GETSCREENREADER: NVDA, JAWS or Narrator may be running
            if not already.value:
                set_flag(0x47, 1, None, 2)  # SPI_SETSCREENREADER
                _reader["ours"] = True
    try:
        yield
    finally:
        with _reader_lock:
            _reader["uses"] -= 1
            if not _reader["uses"]:
                _reader["timer"] = threading.Timer(linger, _reader_off)
                _reader["timer"].daemon = True
                _reader["timer"].start()
