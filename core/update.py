"""Updates from GitHub: is a newer Nova out, and install it (fetch the new files, then rerun setup, which runs
the self-checks and restarts Nova). Settings, history, notes and models aren't part of the download, so they stay.

Bump VERSION when you publish a change people should get.
"""
import io
import os
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from core.config import ROOT
from core.system import NO_WINDOW

REPO = "AyushM1701/nova"
VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/main/VERSION"
ZIP_URL = f"https://github.com/{REPO}/archive/refs/heads/main.zip"
KEEP = {".git", ".venv", "data", "logs", "workspace", "config.json"}  # this computer's own; never replaced


def parse(version):
    return tuple(int(n) for n in re.findall(r"\d+", version)[:3])


def current():
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0"


def newer():
    """The version on GitHub if it's newer than this one, '' if not, None if GitHub couldn't be asked."""
    try:
        with urllib.request.urlopen(VERSION_URL, timeout=10) as r:
            latest = r.read(64).decode("utf-8").strip()
        return latest if parse(latest) > parse(current()) else ""
    except (OSError, ValueError):
        return None


def unpack(archive, root=ROOT):
    """Write GitHub's main.zip over Nova's folder, skipping this computer's own files. Returns the file count."""
    count = 0
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        for info in z.infolist():
            parts = Path(info.filename).parts[1:]  # drop the "nova-main/" folder
            if info.is_dir() or not parts or parts[0] in KEEP:
                continue
            if ".." in parts or Path(info.filename).is_absolute():
                raise ValueError(f"unexpected path in the update: {info.filename}")
            dest = root.joinpath(*parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(info))
            if os.name != "nt" and (info.external_attr >> 16) & 0o111:
                dest.chmod(0o755)  # setup.sh and friends stay runnable
            count += 1
    return count


def install():
    """Fetch the new version and start setup in its own process (it stops and restarts Nova)."""
    if (ROOT / ".git").exists():  # a git clone: pull, so the checkout stays clean
        r = subprocess.run(["git", "-C", str(ROOT), "pull", "--ff-only"], capture_output=True, text=True,
                           creationflags=NO_WINDOW)
        if r.returncode:
            raise RuntimeError(f"git pull didn't work: {(r.stderr or r.stdout).strip()[-300:]}")
    else:
        with urllib.request.urlopen(ZIP_URL, timeout=60) as r:
            unpack(r.read())
    if os.name == "nt":
        subprocess.Popen(["cmd", "/c", str(ROOT / "setup.cmd")], cwd=ROOT, creationflags=NO_WINDOW)
    else:  # the venv already exists, so its Python can run the setup window
        subprocess.Popen([sys.executable, str(ROOT / "helpers" / "setup_window.py")], cwd=ROOT,
                         start_new_session=True)
