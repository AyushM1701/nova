"""Open Nova's real window with nobody at it, show it each page, and save a screenshot of each: a way to look at how the
window renders on a Mac (WKWebView) from a machine that isn't yours. The macOS job in .github/workflows/macos.yml runs this and
keeps the pictures as a download. It talks to the window the way Nova does (the same control pipe), so the pages are the real
ones; Nova itself isn't started, so the numbers on them are what the window shows when Nova isn't running.

    .venv/bin/python helpers/mac_screenshots.py out            # on a Mac: saves out/home.png and so on
    .venv/bin/python helpers/mac_screenshots.py out --no-capture   # anywhere: opens the window and goes through the pages

Not a permission check: macOS may ask the first time something is captured, and on a runner that was set up to allow it, it
doesn't. If a picture comes out black, that is the answer, not a bug in the window."""
import argparse
import os
import platform
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from multiprocessing.connection import Listener
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ["home", "chat", "history", "meetings", "dictionary", "skills", "memory", "settings:general", "settings:ai", "settings:cursor"]
STATE = {"event": "state", "phase": "idle", "brain": "Claude Code", "jobs": 0, "mode": "assistant"}


def address():
    tag = f"nova-shots-{secrets.token_hex(6)}"
    return rf"\\.\pipe\{tag}" if os.name == "nt" else os.path.join(tempfile.gettempdir(), f"{tag}.sock")


class Window:
    """The Nova window (core/app.py) in its own process, driven through the control pipe it would get from Nova."""

    def __init__(self, page="home", env=None):
        self.addr, self.key, self.conn = address(), secrets.token_bytes(32), None
        self.listener = Listener(self.addr, authkey=self.key)
        threading.Thread(target=self._accept, daemon=True).start()
        self.proc = subprocess.Popen([sys.executable, "-m", "core.app"], cwd=ROOT,
                                     env=dict(os.environ, **(env or {}), NOVA_CTRL=self.addr, NOVA_CTRL_KEY=self.key.hex(), NOVA_PAGE=page))

    def _accept(self):
        self.conn = self.listener.accept()

    def wait(self, seconds=90):
        """The page has loaded and said hello (that is when the window connects to the pipe)."""
        deadline = time.time() + seconds
        while self.conn is None and time.time() < deadline and self.proc.poll() is None:
            time.sleep(0.2)
        if self.conn is None:
            raise RuntimeError(f"the Nova window didn't connect (it exited with {self.proc.poll()})")
        self.conn.send(STATE)  # so the window looks alive instead of "Nova isn't running"
        return self

    def show(self, page):
        self.conn.send({"event": "focus", "page": page})  # the window's own handler for "open this page" (core/app.html)

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(10)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()
        self.listener.close()
        if os.name != "nt":
            Path(self.addr).unlink(missing_ok=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def facts():
    lines = [f"python {platform.python_version()}", f"platform {platform.platform()}"]
    if sys.platform == "darwin":
        for label, cmd in (("macOS", ["sw_vers", "-productVersion"]),
                           ("Safari", ["defaults", "read", "/Applications/Safari.app/Contents/Info", "CFBundleShortVersionString"])):
            try:
                lines.append(f"{label} " + subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip())
            except (OSError, subprocess.TimeoutExpired):
                pass
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--no-capture", action="store_true", help="open the window and go through the pages, take no pictures")
    ap.add_argument("--pages", default=",".join(PAGES))
    ap.add_argument("--settle", type=float, default=3.0, help="seconds to let a page draw before the picture")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "facts.txt").write_text(facts(), encoding="utf-8")
    taken = []
    with Window() as win:
        win.wait()
        time.sleep(args.settle + 3)  # the first paint, the deck's first read
        for page in args.pages.split(","):
            win.show(page)
            time.sleep(args.settle)
            if not args.no_capture:
                shot = args.out / f"{page.replace(':', '-')}.png"
                subprocess.run(["screencapture", "-x", str(shot)], check=False, timeout=60)
                if shot.exists() and shot.stat().st_size > 2000:
                    taken.append(shot.name)
    print(f"{len(taken)} pictures in {args.out}: {', '.join(taken) or 'none (no capture)'}")
    return 0 if args.no_capture or taken else 1


if __name__ == "__main__":
    sys.exit(main())
