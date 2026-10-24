"""Checks of Nova's macOS-only code that run without anyone at the Mac: the GitHub Actions job in
.github/workflows/macos.yml runs this after installing Nova and passing tests.py. Nothing here asks macOS for a
permission (no one could click Allow), so the prompts themselves still need a person on a real Mac.

    .venv/bin/python helpers/check_mac.py
"""
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
assert sys.platform == "darwin", "these checks are for macOS"

# every Mac-only module, and every macOS name Nova's code reaches for, can be loaded
from core import bar, loopback, overlay, pointer, screen_text, system  # noqa: E402,F401
from ApplicationServices import AXIsProcessTrusted, AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt  # noqa
from AppKit import NSRunningApplication  # noqa: E402
from AVFoundation import AVCaptureDevice, AVMediaTypeAudio  # noqa: E402,F401
from Quartz import (CGPreflightListenEventAccess, CGPreflightScreenCaptureAccess, CGRequestListenEventAccess,  # noqa
                    CGRequestScreenCaptureAccess, CGWindowListCopyWindowInfo)
import core.app  # noqa: E402,F401  (the Nova window: pywebview on Cocoa)
print("ok: Mac-only modules load")

# the pynput patch is in place: a listener macOS switches off is switched back on
import pynput._util.darwin as pk_util  # noqa: E402
from pynput import keyboard  # noqa: E402
assert pk_util.ListenerMixin._handler is system._revive_tap, "pynput's handler isn't Nova's"
assert pk_util.ListenerMixin._create_event_tap is system._keep_tap, "pynput's tap maker isn't Nova's"
listener = keyboard.Listener(on_press=lambda key: None)
listener.start()
listener.wait()
time.sleep(0.5)
listener.stop()
listener.join(5)
# without Input Monitoring macOS gives no tap (None), but the patched maker still ran and kept what it got
assert hasattr(listener, "_nova_tap"), "the patched tap maker didn't run"
print(f"ok: pynput patch active (tap {'created' if listener._nova_tap is not None else 'refused: no Input Monitoring'})")

# hold to talk on a Mac: Cmd is offered and is the default, as the triple tap uses Cmd; pynput's keys get the
# names the hold keys match
from core.config import defaults  # noqa: E402
assert defaults()["hold_key"] == "left cmd", defaults()["hold_key"]
assert {"left cmd", "right cmd", "cmd"} <= set(system.HOLD_KEYS), system.HOLD_KEYS
names = {k: system.MAC_HOLD[k] for k in (keyboard.Key.cmd_r, keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.ctrl_r,
                                         keyboard.Key.ctrl, keyboard.Key.alt_r, keyboard.Key.shift_r)}
assert names[keyboard.Key.cmd_r] == "right cmd" and names[keyboard.Key.cmd] == "left cmd", names
assert system.hold_match("right cmd", names[keyboard.Key.cmd_r]) and not system.hold_match("right cmd", names[keyboard.Key.cmd])
assert system.hold_match("cmd", names[keyboard.Key.cmd]) and system.hold_match("ctrl", names[keyboard.Key.ctrl])
hold = system.HoldKey("right cmd", lambda: None, lambda: None)  # a real pynput listener starts and stops
hold.stop()
print("ok: hold keys use Cmd on a Mac")

# the permission check answers for all four, without asking
perms = system.mac_permissions()
assert set(perms) == set(system.MAC_NAMES) and all(isinstance(v, bool) for v in perms.values()), perms
print(f"ok: permissions read {perms}")

# the front window's bounds, for window-only screenshots (no permission needed)
subprocess.run(["open", str(Path.home())], check=True)  # a Finder window
finder = None
for _ in range(40):
    apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.apple.finder")
    finder = system.window_rect(apps[0]) if apps else None
    if finder:
        break
    time.sleep(0.25)
assert finder and all(isinstance(v, int) for v in finder) and finder[2] - finder[0] >= 50 and finder[3] > finder[1], finder
print(f"ok: Finder's window is at {finder}")

# Nova.app: built and signed under its fixed name, then left exactly as it was when nothing changed
sys.path.insert(0, str(ROOT / "helpers"))
import setup_window  # noqa: E402


def run(*args):
    return subprocess.run([str(a) for a in args]).returncode


def signature():
    out = subprocess.run(["codesign", "-dv", "--verbose=4", str(setup_window.APP)], capture_output=True, text=True)
    return out.stderr  # codesign prints its details on stderr


setup_window.make_app(run)
first = signature()
assert "Identifier=com.nova.assistant" in first, first
assert run("codesign", "--verify", "--strict", setup_window.APP) == 0, "Nova.app's signature doesn't verify"
cdhash = re.search(r"CDHash=(\w+)", first).group(1)
files = sorted(p for p in setup_window.APP.rglob("*") if p.is_file())
stamps = [p.stat().st_mtime for p in files]
assert setup_window.make_app(run) is False, "a second build with nothing new rewrote Nova.app"
assert re.search(r"CDHash=(\w+)", signature()).group(1) == cdhash, "Nova.app's identity changed"
assert [p.stat().st_mtime for p in files] == stamps, "files in Nova.app were rewritten"
print(f"ok: Nova.app signed as com.nova.assistant (CDHash {cdhash}), untouched by a second build")

print("OK: all macOS checks passed")
