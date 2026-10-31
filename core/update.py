"""Updates from GitHub: is a newer Nova out, and install it (fetch the new files, then rerun setup, which runs
the self-checks and restarts Nova). Settings, history, notes and models aren't part of the download, so they stay.

Only tagged releases ship, never whatever is on main: bump VERSION, then push a tag `v<VERSION>`, and
.github/workflows/release.yml builds nova-main.zip with its SHA256SUMS. A download that doesn't match is refused.
"""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from core import ed25519
from core.config import ROOT
from core.system import NO_WINDOW

REPO = "AyushM1701/nova"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET, SUMS, SIG = "nova-main.zip", "SHA256SUMS", "SHA256SUMS.sig"
# The Ed25519 public key that signs releases (helpers/release_key.py makes the pair). Empty: releases aren't signed
# yet and the checksum alone is trusted. Once it is set, an update or walkthrough download whose SHA256SUMS lacks
# this key's signature is refused: whoever took over the release could rewrite the zip and its checksum, not this.
RELEASE_KEY = ""
KEEP = {".git", ".venv", "data", "logs", "workspace", "config.json", ".update-files", ".update-staging"}  # this computer's own
FILES = ".update-files"  # what the last update wrote, so the next one can remove what a new version dropped
STAGING = ".update-staging"  # the new files land here first, then move into place, so a failed write changes nothing


def parse(version):
    return tuple(int(n) for n in re.findall(r"\d+", version)[:3])


def current():
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0"


def latest():
    """GitHub's latest release: its version and its files' download links."""
    req = urllib.request.Request(LATEST_URL, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        release = json.load(r)
    return release["tag_name"].lstrip("v"), {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}


def newer():
    """The latest release's version if it's newer than this one, '' if not, None if GitHub couldn't be asked."""
    try:
        version, _ = latest()
        return version if parse(version) > parse(current()) else ""
    except (OSError, ValueError, KeyError):
        return None


def verified(archive, sums, name=ASSET):
    """The archive, if SHA256SUMS lists exactly its hash under `name`; else ValueError."""
    want = next((line.split()[0].lower() for line in sums.splitlines()
                 if len(line.split()) == 2 and line.split()[1].lstrip("*") == name), None)
    if not want or hashlib.sha256(archive).hexdigest() != want:
        raise ValueError("The update didn't match its published checksum, so Nova didn't install it.")
    return archive


def unpack(archive, root=ROOT):
    """Write the release zip over Nova's folder, skipping this computer's own files, and remove the files an
    earlier update wrote that this version no longer has. Everything is unpacked into a staging folder first, so a
    bad zip or a full disk leaves Nova as it was. Returns the file count."""
    stage = root / STAGING
    shutil.rmtree(stage, ignore_errors=True)  # a leftover from an update that stopped partway
    written = []
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            for info in z.infolist():
                parts = Path(info.filename).parts[1:]  # drop the "nova-main/" folder
                if info.is_dir() or not parts or parts[0] in KEEP:
                    continue
                if ".." in parts or Path(info.filename).is_absolute() or any(":" in p or "\\" in p for p in parts):
                    raise ValueError(f"unexpected path in the update: {info.filename}")  # "C:x" is a drive on Windows
                dest = stage.joinpath(*parts)
                if not dest.resolve().is_relative_to(stage.resolve()):
                    raise ValueError(f"unexpected path in the update: {info.filename}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(info))
                if os.name != "nt" and (info.external_attr >> 16) & 0o111:
                    dest.chmod(0o755)  # setup.sh and friends stay runnable
                written.append("/".join(parts))
        for name in written:  # same disk, so each move is instant and whole
            dest = root.joinpath(*name.split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage.joinpath(*name.split("/")), dest)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    try:  # only files an update wrote: models, your own files and anything from before this list stay
        dropped = set((root / FILES).read_text(encoding="utf-8").splitlines()) - set(written)
    except OSError:
        dropped = set()
    for name in dropped:
        parts = name.split("/")
        if name and parts[0] not in KEEP and ".." not in parts:
            root.joinpath(*parts).unlink(missing_ok=True)
    (root / FILES).write_text("\n".join(written), encoding="utf-8")
    return len(written)


def fetch(url, timeout=60):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def signed_sums(sums_url, sig_url, get=None):
    """The release's SHA256SUMS text, signed by the pinned release key when there is one."""
    get = get or fetch
    raw = get(sums_url, 10)
    if RELEASE_KEY:
        try:
            signature = get(sig_url, 10) if sig_url else b""
        except OSError:
            signature = b""
        if not ed25519.verify(bytes.fromhex(RELEASE_KEY), raw, signature):
            raise ValueError("The update isn't signed by Nova's release key, so Nova didn't install it.")
    return raw.decode("utf-8", "replace")


def install():
    """Fetch the latest release, check it, and start setup in its own process (it stops and restarts Nova)."""
    version, assets = latest()
    if (ROOT / ".git").exists():  # a git clone: move main to the release's tag, so the checkout stays clean
        git = lambda *args: subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,  # noqa: E731
                                           creationflags=NO_WINDOW)
        branch = git("symbolic-ref", "--short", "-q", "HEAD").stdout.strip()  # "" when detached
        if branch != "main":  # a working branch is the developer's to update, never merged into by a button
            where = f"the git branch {branch}" if branch else "no git branch (a detached checkout)"
            raise RuntimeError(f"This copy of Nova is on {where}. Switch to main, or pull Nova {version} into your "
                               "branch yourself.")
        for args in (["fetch", "--tags", "origin"], ["merge", "--ff-only", f"v{version}"]):
            r = git(*args)
            if r.returncode:
                raise RuntimeError(f"git {args[0]} didn't work: {(r.stderr or r.stdout).strip()[-300:]}")
    else:
        if ASSET not in assets or SUMS not in assets:
            raise RuntimeError(f"Nova {version} on GitHub is missing its download or checksum. Try again later.")
        unpack(verified(fetch(assets[ASSET]), signed_sums(assets[SUMS], assets.get(SIG, ""))))
    if os.name == "nt":
        subprocess.Popen(["cmd", "/c", str(ROOT / "setup.cmd")], cwd=ROOT, creationflags=NO_WINDOW)
    else:  # the venv already exists, so its Python can run the setup window
        subprocess.Popen([sys.executable, str(ROOT / "helpers" / "setup_window.py")], cwd=ROOT,
                         start_new_session=True)
