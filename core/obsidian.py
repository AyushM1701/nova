"""Obsidian, the optional home for Nova's notes (Settings -> General -> Notes folder): find it, say how to install it, and set up
a vault with a folder inside it for Nova. Nova never reaches into a vault beyond that one folder (core/config.py refuses a
vault's top), and it installs nothing on its own: the window runs the installer only when the user presses Install."""
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

WINGET_ID = "Obsidian.Obsidian"
BREW_CASK = "obsidian"
DOWNLOAD = "https://obsidian.md/download"
VAULT_NAME = "Nova vault"


def installed():
    """Where Obsidian is on this computer, or None."""
    if sys.platform == "darwin":
        paths = [Path("/Applications/Obsidian.app"), Path.home() / "Applications" / "Obsidian.app"]
    elif os.name == "nt":
        roots = [os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
        paths = [Path(r) / sub / "Obsidian.exe" for r in roots if r for sub in ("Programs/Obsidian", "Obsidian")]
    else:
        paths = []
    found = next((p for p in paths if p.exists()), None)
    return found or (Path(w) if (w := shutil.which("obsidian")) else None)


def install_command():
    """The command that installs Obsidian with the computer's package manager, or None (then the download page is the way)."""
    if sys.platform == "darwin":
        return ["brew", "install", "--cask", BREW_CASK] if shutil.which("brew") else None
    if os.name == "nt":
        return ["winget", "install", "-e", "--id", WINGET_ID, "--accept-source-agreements", "--accept-package-agreements"] if shutil.which("winget") else None
    return None


def config_file():
    """Obsidian's list of known vaults."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "obsidian" / "obsidian.json"
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "obsidian" / "obsidian.json"
    return Path.home() / ".config" / "obsidian" / "obsidian.json"


def running():
    """Obsidian is open now (it rewrites its vault list when it closes, so Nova doesn't edit the list then)."""
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Obsidian.exe", "/NH"], capture_output=True, text=True, timeout=10,
                                 creationflags=0x08000000).stdout
            return "obsidian.exe" in out.lower()
        return subprocess.run(["pgrep", "-xi", "obsidian"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def default_vault():
    return Path.home() / "Documents" / VAULT_NAME


def register(vault, config=None):
    """Add `vault` to Obsidian's list so it opens as a vault, keeping every other entry. Returns True if the list was changed
    (False: it was there already or the file isn't one Nova can read; nothing is overwritten then)."""
    config = config or config_file()
    try:
        data = json.loads(config.read_text(encoding="utf-8")) if config.exists() else {}
        if not isinstance(data, dict) or not isinstance(data.get("vaults", {}), dict):
            return False
    except (OSError, ValueError):
        return False
    here = os.path.normcase(os.path.realpath(vault))
    if any(isinstance(v, dict) and os.path.normcase(os.path.realpath(v.get("path", ""))) == here for v in data.get("vaults", {}).values()):
        return False
    data.setdefault("vaults", {})[secrets.token_hex(8)] = {"path": str(vault), "ts": int(time.time() * 1000)}
    config.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.with_name(config.name + ".nova.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, config)
    return True


def setup_vault(vault=None, config=None, is_running=None):
    """Make a vault folder with a `Nova` folder inside it (the notes folder to give Nova) and, when Obsidian is closed, add
    the vault to Obsidian's list. Nothing existing is changed. Returns {"vault", "notes", "registered", "running"}."""
    vault = Path(vault or default_vault())
    notes = vault / "Nova"
    (vault / ".obsidian").mkdir(parents=True, exist_ok=True)  # what makes a folder a vault
    notes.mkdir(parents=True, exist_ok=True)
    busy = running() if is_running is None else is_running
    return {"vault": str(vault), "notes": str(notes), "running": busy, "registered": False if busy else register(vault, config)}


def open_uri(vault):
    """The link that opens this vault in Obsidian."""
    return "obsidian://open?vault=" + urllib.parse.quote(Path(vault).name, safe="")
