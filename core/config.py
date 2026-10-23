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
NOTES = WORKSPACE / "notes"
LOG_HOOKS = []  # Nova forwards every log entry to its open app window
KEEP_LOG_DAYS = 30
NO_WINDOW = 0 if os.name != "nt" else 0x08000000  # creationflags for child processes: no console window flashes


def memory_text():
    """The end of Nova's long-term memory (notes/memory.md), as both brains see it."""
    try:
        return (NOTES / "memory.md").read_text(encoding="utf-8").strip()[-4000:] or "(nothing yet)"
    except OSError:
        return "(nothing yet)"


def write_private(path, text):
    """Write a key or token file only this user can read (macOS; shortcut: Windows relies on the folder's ACL)."""
    path.write_text(text, encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)


def log(event, **fields):
    entry = {"t": time.time(), "event": event, **fields}
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LOGS / time.strftime("nova-%Y-%m-%d.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    for hook in LOG_HOOKS:
        hook(entry)


def read_history(kinds, limit=600):
    """The newest log entries of these kinds, newest first."""
    items = []
    for f in sorted(LOGS.glob("nova-*.jsonl"), reverse=True):
        for line in reversed(f.read_text(encoding="utf-8", errors="replace").splitlines()):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("event") in kinds:
                items.append(entry)
                if len(items) >= limit:
                    return items
    return items


def prune_logs():
    cutoff = time.time() - KEEP_LOG_DAYS * 86400
    for f in LOGS.glob("nova-*.jsonl"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


def merged(base, override):
    out = dict(base)
    for k, v in override.items():
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
    return json.loads(_busy(lambda: CONFIG.read_text(encoding="utf-8-sig"))) if CONFIG.exists() else {}


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
