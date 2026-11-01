"""Paths, settings and the activity log, shared by Nova and its app window.

config.json holds only what the user changed; everything else comes from config.default.json,
so new settings from an update appear automatically.
"""
import contextlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG, DEFAULTS = ROOT / "config.json", ROOT / "config.default.json"
LOGS, DATA, WORKSPACE = ROOT / "logs", ROOT / "data", ROOT / "workspace"
DEFAULT_NOTES = WORKSPACE / "notes"
LOG_HOOKS = []  # Nova forwards every log entry to its open app window
KEEP_LOG_DAYS = 30
CAP_BYTES = 4 << 20  # crash.txt and setup.log grow without a day boundary: past this only the newest quarter stays
NO_WINDOW = 0 if os.name != "nt" else 0x08000000  # creationflags for child processes: no console window flashes


def memory_text():
    """The end of Nova's long-term memory (notes/memory.md), as both brains see it."""
    try:
        return (NOTES / "memory.md").read_text(encoding="utf-8").strip()[-4000:] or "(nothing yet)"
    except OSError:
        return "(nothing yet)"


def write_atomic(path, text, private=False):
    """Write a file whole or not at all: a power cut or a crash leaves the old one, never half of the new one.
    `private`: only this user can read it (macOS; shortcut: Windows relies on the folder's ACL)."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    if private and os.name != "nt":
        tmp.chmod(0o600)
    _busy(lambda: os.replace(tmp, path))


def write_private(path, text):
    write_atomic(path, text, private=True)


def log(event, **fields):
    entry = {"t": time.time(), "event": event, **fields}
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LOGS / time.strftime("nova-%Y-%m-%d.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    for hook in LOG_HOOKS:
        hook(entry)


def read_history(kinds, limit=None):
    """The newest log entries of these kinds, newest first (all of them when `limit` is None)."""
    items = []
    for f in sorted(LOGS.glob("nova-*.jsonl"), reverse=True):
        for line in reversed(f.read_text(encoding="utf-8", errors="replace").splitlines()):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("event") in kinds:
                items.append(entry)
                if limit and len(items) >= limit:
                    return items
    return items


def prune_logs():
    cutoff = time.time() - KEEP_LOG_DAYS * 86400
    for f in LOGS.glob("nova-*.jsonl"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
    for f in (LOGS / "crash.txt", DATA / "setup.log"):  # never rotated: keep the newest tail of a big one
        try:
            if f.stat().st_size > CAP_BYTES:
                f.write_bytes(f.read_bytes()[-CAP_BYTES // 4:])
        except OSError:
            pass


def merged(base, override):
    out = dict(base)
    for k, v in override.items():
        if isinstance(base.get(k), dict) and not isinstance(v, dict):
            continue  # "voice": null or "fast" from a hand edit would turn a whole section into a string
        out[k] = merged(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def overrides(cfg, base):
    """Only the values that differ from the defaults."""
    out = {}
    for k, v in cfg.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            sub = overrides(v, base[k])
            if sub:
                out[k] = sub
        elif k not in base or base[k] != v:
            out[k] = v
    return out


def defaults():
    d = json.loads(DEFAULTS.read_text(encoding="utf-8"))
    if sys.platform == "darwin":  # a Mac holds Cmd where Windows holds Ctrl, as the triple tap does
        d["hold_key"] = d["hold_key"].replace("ctrl", "cmd")
    return d


def user_config():
    """The user's own overrides; raises ValueError if config.json isn't valid JSON."""
    data = json.loads(_busy(lambda: CONFIG.read_text(encoding="utf-8-sig"))) if CONFIG.exists() else {}
    if not isinstance(data, dict):
        raise ValueError("it must be one JSON object, { ... }")
    return data


def notes_folder_problem(path):
    """Why `path` can't be Nova's notes folder, or "" if it can. Checked where the setting is made: the AI works in this
    folder without asking, so it must be one only Nova's notes live in."""
    try:
        path = Path(path).expanduser()
        if not path.is_absolute():
            return "Pick a full folder path."
        if not path.is_dir():
            return "That folder doesn't exist."
        real = Path(os.path.realpath(path))
        if (real / ".obsidian").exists():  # the top of a vault: plugins in there run code, and every other note is in reach
            return ("That is the top of an Obsidian vault. Pick a folder inside it instead, for example <your vault>/Nova, "
                    "so Nova can only change its own notes and never Obsidian's plugins or your other notes.")
        if real.parent == real:
            return "That is a whole drive. Pick a folder on it."
        if real == Path.home():
            return "Pick a folder inside your home folder, not the home folder itself."
        workspace, install = Path(os.path.realpath(WORKSPACE)), Path(os.path.realpath(ROOT))
        if not (real == workspace or workspace in real.parents) and (real == install or install in real.parents or real in install.parents):
            return "That is Nova's own folder, or one that holds it."
        system = ([os.environ.get(v, "") for v in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData")] if os.name == "nt"
                  else ["/System", "/Library", "/Applications", "/usr", "/bin", "/sbin", "/etc", "/var", "/private"])
        if any(d and (real == Path(d) or Path(d) in real.parents) for d in system):
            return "That is a system folder."
        probe = real / f".nova-write-test-{os.getpid()}"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
    except OSError:
        return "Nova can't write to that folder."
    return ""


def notes_dir(cfg=None):
    """(folder, problem): the notes folder the settings ask for (`notes.folder`), or the default one and, if a folder was
    asked for but can't be used, why. NOTES below is this at start-up, so a change applies after Nova restarts."""
    try:
        want = str(((cfg if cfg is not None else user_config()).get("notes") or {}).get("folder") or "").strip()
    except (ValueError, OSError, AttributeError):
        want = ""
    if not want:
        return DEFAULT_NOTES, ""
    problem = notes_folder_problem(want)
    return (DEFAULT_NOTES, f"Using the default notes folder: {problem}") if problem else (Path(want).expanduser(), "")


def copy_notes(src, dst):
    """Copy the notes in `src` into `dst`, skipping files already there and never deleting anything (links, and an
    Obsidian settings folder, are not copied). Returns how many files were copied."""
    src, dst, count = Path(src), Path(dst), 0
    if not src.is_dir() or os.path.realpath(src) == os.path.realpath(dst):
        return 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != ".obsidian" and not os.path.islink(os.path.join(root, d))]
        target = dst / Path(root).relative_to(src)
        for name in files:
            from_file, to_file = Path(root) / name, target / name
            if os.path.islink(from_file) or to_file.exists():
                continue
            try:
                target.mkdir(parents=True, exist_ok=True)
                to_file.write_bytes(from_file.read_bytes())
                count += 1
            except OSError:
                continue
    return count


def _busy(action, tries=50):
    """Windows refuses to read or replace a file another program is replacing or reading this instant: retry."""
    for attempt in range(tries):
        try:
            return action()
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.02)


@contextlib.contextmanager
def _saving():
    """One save at a time across Nova, its window and the AI: each reads, changes and writes config.json, and two
    at once would undo each other's change. A lock file older than 10 s was left by a crash and is taken over."""
    lock = CONFIG.with_suffix(".lock")
    for _ in range(500):  # up to about 10 s
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except (FileExistsError, PermissionError):  # Windows says PermissionError while it's being deleted
            try:
                if time.time() - lock.stat().st_mtime > 10:
                    lock.unlink()
            except OSError:  # released meanwhile
                pass
            time.sleep(0.02)
    else:
        raise TimeoutError("Another program kept Nova's settings locked.")
    try:
        yield
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)


NOTES, NOTES_PROBLEM = notes_dir()  # the notes folder for this run of Nova


def load_config():
    """(settings, error). A broken config.json falls back to the defaults instead of stopping Nova."""
    try:
        return merged(defaults(), user_config()), None
    except ValueError as e:
        return defaults(), f"config.json has a mistake ({e}); using the default settings until it is fixed."


def set_path(cfg, path, value):
    """cfg["a"]["b"] = value for the path "a.b"."""
    *parents, last = path.split(".")
    for key in parents:
        cfg = cfg.setdefault(key, {})
    cfg[last] = value


def update_config(changes):
    """Apply {"dotted.path": value} on top of the settings on disk now, so changes Nova, the window or the AI
    made since this caller read them survive. Raises ValueError if config.json is broken."""
    with _saving():
        cfg, error = load_config()
        if error:
            raise ValueError(error)
        for path, value in changes.items():
            set_path(cfg, path, value)
        _save(cfg)


def save_config(cfg):
    with _saving():
        _save(cfg)


def _save(cfg):
    try:
        user_config()
    except ValueError:  # keep the hand-edited file the user may still want
        CONFIG.replace(CONFIG.with_suffix(".broken.json"))
    tmp = CONFIG.with_suffix(f".{os.getpid()}.tmp")  # each program its own: a shared name collided
    tmp.write_text(json.dumps(overrides(cfg, defaults()), indent=2, ensure_ascii=False), encoding="utf-8")
    _busy(lambda: tmp.replace(CONFIG))  # atomic: Nova's settings watcher never reads half a file
